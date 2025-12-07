import discord
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    and_,
    or_,
)
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Relationship,
    Session,
    mapped_column,
    object_mapper,
    relationship,
)
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    def __repr__(self):
        return "%s(%s)" % (
            type(self).__name__,
            ", ".join(
                f"{item[0]}={item[1]}"
                for item in vars(self).items()
                if not item[0].startswith("_")
            ),
        )


class Guild(Base):
    __tablename__ = "guild"

    id = mapped_column(Integer, primary_key=True)
    owner_id = mapped_column(Integer, ForeignKey("user.id"), nullable=True)
    created_at = mapped_column(DateTime, nullable=False)
    approx_member_count = mapped_column(Integer, nullable=True)
    member_count = mapped_column(Integer, nullable=True)
    approx_presence_count = mapped_column(Integer, nullable=True)
    banner = mapped_column(Text, nullable=True)
    icon = mapped_column(Text, nullable=True)
    description = mapped_column(Text, nullable=True)
    verification_level = mapped_column(Integer, nullable=False)

    channels = relationship("Channel", back_populates="guild", lazy="noload")


class BackfillSession(Base):
    __tablename__ = "backfill_session"

    id = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    created_at = mapped_column(DateTime, nullable=False, server_default=func.now())
    channel_id = mapped_column(Integer, ForeignKey("channel.id"), nullable=False)

    start_message_id = mapped_column(
        BigInteger, ForeignKey("message.id"), nullable=True
    )
    completed = mapped_column(Boolean, default=False, nullable=False)

    channel = relationship("Channel", lazy="noload")
    message = relationship("Message", lazy="noload")


class Channel(Base):
    __tablename__ = "channel"

    id = mapped_column(Integer, primary_key=True)
    guild_id = mapped_column(Integer, ForeignKey("guild.id"), index=True)
    name = mapped_column(Text, nullable=False)
    type = mapped_column(Integer, nullable=False)
    created_at = mapped_column(DateTime, nullable=False, index=True)
    slowmode_delay = mapped_column(Integer, nullable=False)
    topic = mapped_column(Text, nullable=True)

    guild = relationship("Guild", lazy="noload")
    messages = relationship("Message", back_populates="channel", lazy="noload")

    backfill_lowest_message_id = mapped_column(BigInteger, nullable=True)
    backfill_session: Mapped[list[BackfillSession]] = relationship(
        "BackfillSession", back_populates="channel", lazy="noload"
    )


class User(Base):
    __tablename__ = "user"

    id = mapped_column(Integer, primary_key=True)
    name = mapped_column(Text, nullable=False, index=True)
    avatar = mapped_column(Text, nullable=True)
    bot = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at = mapped_column(DateTime, nullable=False)

    messages = relationship("Message", back_populates="author", lazy="noload")


class Message(Base):
    __tablename__ = "message"

    id = mapped_column(BigInteger, primary_key=True)
    channel_id = mapped_column(
        Integer, ForeignKey("channel.id"), nullable=False, index=True
    )
    guild_id = mapped_column(Integer, ForeignKey("guild.id"), nullable=True, index=True)
    author_id = mapped_column(
        Integer, ForeignKey("user.id"), nullable=False, index=True
    )
    reply_to_id = mapped_column(Integer, nullable=True, index=True)
    content = mapped_column(Text, nullable=False)
    created_at = mapped_column(DateTime, nullable=False, index=True)
    type = mapped_column(Integer, nullable=True)
    flags = mapped_column(Integer, nullable=True)

    author = relationship("User", back_populates="messages", lazy="noload")
    channel = relationship("Channel", back_populates="messages", lazy="noload")
    guild = relationship("Guild", lazy="noload")


class MessageVersion(Base):
    __tablename__ = "message_version"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id = mapped_column(
        BigInteger, ForeignKey("message.id"), nullable=False, index=True
    )
    editor_id = mapped_column(Integer, ForeignKey("user.id"), nullable=True, index=True)
    created_at = mapped_column(DateTime, nullable=True, index=True)
    content = mapped_column(Text, nullable=False)

    message = relationship("Message", lazy="noload")


Index("ix_message_channel_created", Message.channel_id, Message.created_at)
Index("ix_message_guild_created", Message.guild_id, Message.created_at)
Index("ix_message_author_created", Message.author_id, Message.created_at)
Index("ix_msgversion_msg_created", MessageVersion.message_id, MessageVersion.created_at)


conflict_count = 0

def insert_message(session: Session, msg: discord.Message, commit: bool = True) -> None:
    global conflict_count

    try:
        session.execute(
            insert(Message).values(
                id=msg.id,
                channel_id=msg.channel.id,
                guild_id=msg.guild.id if msg.guild else None,
                author_id=msg.author.id,
                reply_to_id=msg.reference.message_id if msg.reference else None,
                content=msg.content,
                created_at=msg.created_at,
                type=msg.type.value,
                flags=msg.flags.value,
            )
        )
    except IntegrityError:
        conflict_count += 1
        print(f"Message conflict: {conflict_count}")

    if commit:
        session.commit()


def insert_backfill_session(
    session: Session, channel: discord.TextChannel, commit: bool = True
) -> None:
    session.execute(insert(BackfillSession).values(channel_id=channel.id))

    if commit:
        session.commit()


def update_backfill_session(
    session: Session,
    channel: discord.TextChannel,
    start_message_id: int | None = None,
    last_message_id: int | None = None,
    commit: bool = True,
) -> None:
    session.execute(
        insert(BackfillSession).values(
            channel_id=channel.id,
            start_message_id=start_message_id,
            last_message_id=last_message_id,
        )
    )

    if commit:
        session.commit()


def _col_changed(col, value):
    if value is None:
        return col.is_not(None)
    else:
        return (col != value) | col.is_(None)


def upsert_user(session: Session, user: discord.Member, commit: bool = True) -> None:
    avatar_url = user.avatar.url if user.avatar else None

    stmt = insert(User).values(
        id=user.id,
        name=user.name,
        avatar=avatar_url,
        bot=user.bot,
        created_at=user.created_at,
    )

    where_cond = or_(
        _col_changed(User.name, user.name),
        _col_changed(User.avatar, avatar_url),
        _col_changed(User.bot, user.bot),
    )

    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "name": user.name,
            "avatar": avatar_url,
            "bot": user.bot,
        },
        where=where_cond,
    )

    session.execute(stmt)

    if commit:
        session.commit()


def upsert_channel(
    session: Session, channel: discord.TextChannel, commit: bool = True
) -> None:
    topic = channel.topic
    stmt = insert(Channel).values(
        id=channel.id,
        guild_id=channel.guild.id,
        name=channel.name,
        type=channel.type.value,
        created_at=channel.created_at,
        slowmode_delay=channel.slowmode_delay,
        topic=topic,
    )

    where_cond = or_(
        _col_changed(Channel.guild_id, channel.guild.id),
        _col_changed(Channel.name, channel.name),
        _col_changed(Channel.type, channel.type.value),
        _col_changed(Channel.created_at, channel.created_at),
        _col_changed(Channel.slowmode_delay, channel.slowmode_delay),
        _col_changed(Channel.topic, topic),
    )

    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "guild_id": channel.guild.id,
            "name": channel.name,
            "type": channel.type.value,
            "created_at": channel.created_at,
            "slowmode_delay": channel.slowmode_delay,
            "topic": topic,
        },
        where=where_cond,
    )

    session.execute(stmt)

    if commit:
        session.commit()


def upsert_guild(session: Session, guild: discord.Guild, commit: bool = True) -> None:
    owner_id = guild.owner.id if guild.owner else None
    banner_url = guild.banner.url if guild.banner else None
    icon_url = guild.icon.url if guild.icon else None

    stmt = insert(Guild).values(
        id=guild.id,
        owner_id=owner_id,
        created_at=guild.created_at,
        approx_member_count=guild.approximate_member_count,
        member_count=guild.member_count,
        approx_presence_count=guild.approximate_presence_count,
        banner=banner_url,
        icon=icon_url,
        description=guild.description,
        verification_level=guild.verification_level.value,
    )

    where_cond = or_(
        _col_changed(Guild.owner_id, owner_id),
        _col_changed(Guild.created_at, guild.created_at),
        _col_changed(Guild.approx_member_count, guild.approximate_member_count),
        _col_changed(Guild.member_count, guild.member_count),
        _col_changed(Guild.approx_presence_count, guild.approximate_presence_count),
        _col_changed(Guild.banner, banner_url),
        _col_changed(Guild.icon, icon_url),
        _col_changed(Guild.description, guild.description),
        _col_changed(Guild.verification_level, guild.verification_level.value),
    )

    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "owner_id": owner_id,
            "created_at": guild.created_at,
            "approx_member_count": guild.approximate_member_count,
            "member_count": guild.member_count,
            "approx_presence_count": guild.approximate_presence_count,
            "banner": banner_url,
            "icon": icon_url,
            "description": guild.description,
            "verification_level": guild.verification_level.value,
        },
        where=where_cond,
    )

    session.execute(stmt)

    if commit:
        session.commit()


def insert_user(session: Session, user: discord.Member, commit: bool = True) -> None:
    session.execute(
        insert(User).values(
            id=user.id,
            name=user.name,
            avatar=user.avatar.url if user.avatar else None,
            bot=user.bot,
            created_at=user.created_at,
        )
    )
    if commit:
        session.commit()


def insert_channel(
    session: Session, channel: discord.TextChannel, commit: bool = True
) -> None:
    session.execute(
        insert(Channel).values(
            id=channel.id,
            guild_id=channel.guild.id,
            name=channel.name,
            type=channel.type.value,
            created_at=channel.created_at,
            slowmode_delay=channel.slowmode_delay,
            topic=channel.topic,
        )
    )

    if commit:
        session.commit()


def insert_guild(session: Session, guild: discord.Guild, commit: bool = True) -> None:
    session.execute(
        insert(Guild).values(
            id=guild.id,
            owner_id=guild.owner.id if guild.owner else None,
            created_at=guild.created_at,
            approx_member_count=guild.approximate_member_count,
            member_count=guild.member_count,
            approx_presence_count=guild.approximate_presence_count,
            banner=guild.banner.url if guild.banner else None,
            icon=guild.icon.url if guild.icon else None,
            description=guild.description,
            verification_level=guild.verification_level.value,
        )
    )

    if commit:
        session.commit()


def insert_message_edit(
    session: Session, msg: discord.Message, commit: bool = True
) -> None:
    session.execute(
        insert(MessageVersion).values(
            message_id=msg.id,
            editor_id=msg.author.id,
            created_at=msg.created_at,
            content=msg.content,
        )
    )

    if commit:
        session.commit()
