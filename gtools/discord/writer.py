from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
import threading
import time
from typing import Any, Callable, cast
import discord
from sqlalchemy.orm import Session, sessionmaker

from gtools.core.discord.models import (
    insert_channel,
    insert_guild,
    insert_message,
    insert_message_edit,
    insert_user,
    upsert_channel,
    upsert_guild,
    upsert_user,
)


class MessageWriter:
    def __init__(
        self,
        session_maker: sessionmaker[Session],
        callbacks: list[Callable[[discord.Message], Any]] | None = None,
        *,
        batch_size: int = 10000,
        flush_interval: float = 1,
        callback_workers: int = 4,
    ) -> None:
        self.session_maker = session_maker
        self._callbacks = callbacks or []

        self._queue: Queue[tuple[discord.Message | None, bool]] = Queue()
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        self.running = True
        self._callback_pool = ThreadPoolExecutor(
            max_workers=callback_workers, thread_name_prefix="msgwriter-cb"
        )
        self._worker_thread = threading.Thread(
            target=self._worker, daemon=True, name="MessageWriterWorker"
        )
        self._worker_thread.start()

    def add(self, msg: discord.Message, edit: bool = False) -> None:
        self._queue.put((msg, edit))

    def stop(self, timeout: float | None = None) -> None:
        self.running = False
        self._queue.put((None, False))
        self._worker_thread.join(timeout)
        try:
            self._callback_pool.shutdown(wait=False)
        except Exception:
            pass

    def _drain_batch(self) -> list[tuple[discord.Message, bool]]:
        items: list[tuple[discord.Message | None, bool]] = []

        while len(items) < self.batch_size:
            try:
                items.append(self._queue.get(timeout=self.flush_interval))
            except Empty:
                break

        items = [it for it in items if it[0] is not None]
        return items

    def _coalesce(
        self, items: list[tuple[discord.Message, bool]]
    ) -> list[tuple[discord.Message, bool]]:
        latest: dict[int, tuple[discord.Message, bool]] = {}
        for msg, is_edit in items:
            # skip if msg is None (shouldn't happen here)
            if msg is None:
                continue
            latest[msg.id] = (msg, is_edit)
        return list(latest.values())

    def _worker(self) -> None:
        try:
            while self.running or not self._queue.empty():
                items = self._drain_batch()
                if not items:
                    continue

                items = list(
                    filter(
                        lambda x: isinstance(
                            x[0].author, (discord.Member, discord.User)
                        )
                        and isinstance(x[0].channel, discord.TextChannel),
                        items,
                    )
                )

                if not items:
                    continue

                items = self._coalesce(items)

                print(f"Flushing {len(items)} messages")

                users: dict[int, discord.Member] = {}
                channels: dict[int, discord.TextChannel] = {}
                guilds: dict[int, discord.Guild] = {}

                for msg, _ in items:
                    if msg.author.id not in users:
                        users[msg.author.id] = cast(discord.Member, msg.author)
                    if msg.channel.id not in channels:
                        channels[msg.channel.id] = cast(
                            discord.TextChannel, msg.channel
                        )
                    if msg.guild and msg.guild.id not in guilds:
                        guilds[msg.guild.id] = msg.guild

                with self.session_maker() as session:
                    for _, user in users.items():
                        upsert_user(session, user, commit=False)
                    for _, channel in channels.items():
                        upsert_channel(session, channel, commit=False)
                    for _, guild in guilds.items():
                        upsert_guild(session, guild, commit=False)

                    for msg, is_edit in items:
                        insert = insert_message_edit if is_edit else insert_message
                        insert(session, msg, commit=False)

                    session.commit()

                for msg, _ in items:
                    for cb in self._callbacks:
                        try:
                            self._callback_pool.submit(cb, msg)
                        except Exception:
                            pass

            while not self._queue.empty():
                try:
                    itm = self._queue.get_nowait()
                except Exception:
                    break
                if itm is None:
                    continue
                msg, is_edit = itm
                if msg is None:
                    continue

                for cb in self._callbacks:
                    try:
                        self._callback_pool.submit(cb, msg)
                    except Exception:
                        pass

        finally:
            try:
                self._callback_pool.shutdown(wait=False)
            except Exception:
                pass
