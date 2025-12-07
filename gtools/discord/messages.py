import asyncio
import atexit
from time import sleep
from typing import cast
import discord
import sqlalchemy
from sqlalchemy.orm import contains_eager, joinedload, selectinload, sessionmaker
from sqlalchemy.sql import select

from gtools.core.discord.backfill import ChannelBackfill, ChannelBackfillManager
from gtools.core.discord.history import HistoryFetcher
from gtools.core.discord.models import Base, Channel, Message
from gtools.core.discord.writer import MessageWriter


if __name__ == "__main__":
    client = discord.Client()
    engine = sqlalchemy.create_engine(
        "sqlite:///discord_store.db", future=True, echo=False
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    w = MessageWriter(
        SessionLocal,
        [lambda m: backfill.register_channel(cast(discord.TextChannel, m.channel), m)],
    )
    history = HistoryFetcher()
    backfill = None

    # TODO: these async can cause some pretty heavy race condition, consider using a queue
    @client.event
    async def on_ready() -> None:
        global backfill
        backfill = ChannelBackfillManager(SessionLocal, history, w, client.loop)
        with SessionLocal() as session:
            for channel in session.query(Channel).all():
                ch = client.get_channel(channel.id)
                if not isinstance(ch, discord.TextChannel):
                    continue

                backfill.add(ch)

    @client.event
    async def on_message(message: discord.Message) -> None:
        if message.pinned:
            return

        w.add(message)

    @client.event
    async def on_message_edit(_before: discord.Message, after: discord.Message) -> None:
        w.add(after, edit=True)

    def cleanup() -> None:
        w.stop()
        # TODO: ensure all messages is flushed before cleaning up
        with SessionLocal() as session:
            for channel in session.query(Channel).all():
                ch = client.get_channel(channel.id)
                if not isinstance(ch, discord.TextChannel):
                    continue

                backfill.cleanup(ch)

        backfill.stop()

    client.run(token="TOKEN_HERE")

    # NOTE: about history
    # the backfill process will start for every channel on startup that is not completed yet
    # every channel will have a "backfill_complete" flag
    # backfill_complete is set when discord returns None when fetching history
    # for every channel it will track the following:
    # - start_message_id
    # - lowest_message_id: will be used for resuming the backfill later
    # - latest_message_id: will be used to catch up if the bot goes offline
    # catching up:
    # _______#######-------CCCCC
    #        ^     ^       ^
    #   LOWEST     HIGHEST START
    # _: to backfill
    # #: already saved
    # -: the messages that are sent when the bot is offline
    # C: bot tracking again
    # on startup, it will start backfill and catchup process
    # BACKFILL: from lowest to beginning
    # CATCHUP: from highest to start
    # scenario 2:
    # _______##########----CCCCC--------CCCCC
    #                  1111     22222222
    # backfill: nothing change
    # catchup became 2 job: segment 1 and 2
    # how to determine segment:
    # rather than status model, create a session model, it will hold:
    # - start_message_id: the latest message id from the realtime system
    # - lowest_message_id: will be used for resuming the backfill later
    # - latest_message_id: will be used to catch up if the bot goes offline
    # this way, we can query every session for a given channel, and figure out the segment:
    # - order the session chronogically
    # - a segment is defined as 2 id representing the boundary,
    #   the boundary shall be determined using the lowest_message_id and latest_message_id
    # - the lowest_message_id shall be determined using the latest message from the catchup process
    # - the latest_message_id shall be determined using start_message_id
    # - the start_message_id shall be determined using the highest message id in the database
    # on another note, it seems start_message_id is redundant
    # and lowest_message_id is confused with the backfill process, it should be named better such as
    # latest_message_id: lower bound
    # start_message_id: upper bound
    # fk this is getting out of hand, need to rethink about the whole flow later

    # with SessionLocal() as session:
    #     stmt = (
    #         sqlalchemy.select(Message)
    #         .join(Message.channel)
    #         .options(joinedload(Message.author))
    #         .where(Channel.name.ilike("%chat%"))
    #         .order_by(Message.id)
    #     )
    #     messages = session.scalars(stmt).all()
    #     for m in messages:
    #         print(m.id, m.author.name, m.content)

    try:
        while True:
            sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()
        asyncio.run(client.close())
