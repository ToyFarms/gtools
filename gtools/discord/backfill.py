import asyncio
import inspect
from itertools import pairwise
from pprint import pprint
import queue
import threading
import time
from typing import Any, Callable
import discord
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql import func, insert, select, update
from gtools.core.discord.history import HistoryFetcher
from gtools.core.discord.models import BackfillSession, Channel, Message
from gtools.core.discord.writer import MessageWriter
from gtools.core.utils.rate_limiter import async_rate_limiter, rate_limiter


global_limiter = rate_limiter(30)


class ChannelBackfill:
    def __init__(
        self,
        channel: discord.TextChannel,
        bound: tuple[int | None, int | None],
        session: sessionmaker[Session],
        fetcher: HistoryFetcher,
        writer: MessageWriter,
        loop: asyncio.AbstractEventLoop,
        on_complete: Callable[[], Any] = lambda: None,
        *,
        per_rate: int = 5,
        limiter_obj=None,
    ) -> None:
        if bound[0] is None and bound[1] is None:
            raise ValueError(
                "Illegal states: lower id and upper id cannot both be NULL"
            )

        self.channel = channel
        self.bound = list(bound)
        self.session = session
        self.fetcher = fetcher
        self.writer = writer
        self.on_complete = on_complete
        self.loop = loop
        self.running = True
        self.cancelled = False

        if limiter_obj is not None:
            self.limiter = limiter_obj
        else:
            per_rate = 1 if per_rate is None else per_rate
            self.limiter = rate_limiter(per_rate)

    def cancel(self) -> None:
        self.cancelled = True
        self.running = False


class BackfillWorkerManager:
    def __init__(self, num_workers: int = 2) -> None:
        self._q: queue.Queue[ChannelBackfill | None] = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._num_workers = max(1, int(num_workers))

    def start(self, num_workers: int | None = None) -> None:
        """Start worker threads. Optionally change num_workers on start."""
        with self._lock:
            if num_workers is not None:
                self._num_workers = max(1, int(num_workers))

            # if any worker alive, assume already started
            if any(w.is_alive() for w in self._workers):
                return

            self._stop_event.clear()
            self._workers = []
            for i in range(self._num_workers):
                t = threading.Thread(
                    target=self._worker_loop, daemon=True, name=f"backfill-worker-{i}"
                )
                self._workers.append(t)
                t.start()

    def submit(self, backfill: ChannelBackfill) -> None:
        self._q.put(backfill)
        self.start()

    def stop(self, wait: bool = True) -> None:
        self._stop_event.set()
        for _ in range(self._num_workers):
            self._q.put(None)  # pyright: ignore[reportArgumentType]

        if wait:
            for w in self._workers:
                if w:
                    w.join(timeout=5.0)

    def _run_coro(self, coro, loop: asyncio.AbstractEventLoop):
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result()

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            item = self._q.get()
            if item is None:
                # sentinel -> stop this worker
                self._q.task_done()
                break
            try:
                self._process_task(item)
            except Exception as exc:
                print("BackfillManager worker task exception:", exc)
            finally:
                self._q.task_done()

    def _process_task(self, task: ChannelBackfill) -> None:
        channel = task.channel
        fetcher = task.fetcher
        writer = task.writer
        loop = task.loop

        if task.bound[0] is None and task.bound[1] is None:
            raise ValueError(
                "Illegal states: lower id and upper id cannot both be NULL"
            )

        while task.running and not task.cancelled and not self._stop_event.is_set():
            with global_limiter as glimiter:
                with task.limiter as climiter:
                    try:
                        lower_obj = (
                            None
                            if task.bound[0] is None
                            else discord.Object(id=task.bound[0])
                        )
                        upper_obj = (
                            None
                            if task.bound[1] is None
                            else discord.Object(id=task.bound[1])
                        )

                        msgs = self._run_coro(
                            fetcher.fetch(
                                channel, lower_bound=lower_obj, upper_bound=upper_obj
                            ),
                            loop,
                        )

                        print(
                            f"Got {len(msgs)} message from channel "
                            f"({'BACKFILL' if task.bound[0] is None else 'FORWARDFILL' if task.bound[1] is None else 'CATCHUP'}, "
                            f"[{task.bound[0]}, {task.bound[1]}]): {channel.id}"
                        )

                        if not msgs:
                            try:
                                task.on_complete()
                            except Exception as e:
                                print("on_complete raised:", e)
                            task.running = False
                            break

                        if not task.bound[0] and task.bound[1]:
                            # backfill
                            task.bound[1] = msgs[-1].id if msgs else task.bound[1]
                        elif not task.bound[1] and task.bound[0]:
                            # forward fill
                            task.bound[0] = msgs[-1].id if msgs else task.bound[0]
                        elif task.bound[0] and task.bound[1]:
                            task.bound[0] = msgs[-1].id if msgs else task.bound[0]

                        for msg in msgs:
                            if (
                                task.bound[0]
                                and task.bound[1]
                                and msg.id >= task.bound[1]
                            ):
                                try:
                                    task.on_complete()
                                except Exception as e:
                                    print("on_complete raised:", e)
                                task.running = False
                                break
                            writer.add(msg)

                        with task.session() as session:
                            if not task.bound[1] and task.bound[0]:
                                sessions = session.scalars(
                                    select(BackfillSession).where(
                                        BackfillSession.channel_id == channel.id
                                    )
                                ).all()

                                ses = None
                                if len(sessions) % 2 == 0:
                                    ses = sessions[-2]
                                else:
                                    ses = sessions[-1]

                                session.execute(
                                    update(BackfillSession)
                                    .where(BackfillSession.id == ses.id)
                                    .values(start_message_id=task.bound[0])
                                )

                            session.commit()

                        try:
                            climiter.exp_backoff(delta=-1)
                        except Exception:
                            pass

                    except discord.HTTPException as e:
                        print("discord HTTPException in backfill:", e)
                        if getattr(e, "status", None) == 429:
                            try:
                                climiter.exp_backoff(delta=1)
                            except Exception:
                                pass
                            try:
                                glimiter.exp_backoff(delta=1)
                            except Exception:
                                pass
                    except Exception as exc:
                        task.cancel()
                        break

        if task.cancelled:
            print(f"Backfill for channel {channel.id} cancelled.")
        else:
            print(f"Backfill for channel {channel.id} completed/stopped.")


class ChannelBackfillManager:
    def __init__(
        self,
        session: sessionmaker[Session],
        fetcher: HistoryFetcher,
        writer: MessageWriter,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.session = session
        self.fetcher = fetcher
        self.writer = writer
        self.loop = loop
        self.backfills: list[ChannelBackfill] = []
        self._seen_channel: set[int] = set()
        self._session_seen_channel: set[int] = set()
        self._backfill_worker = BackfillWorkerManager()

    def add_backfill_session(self, backfill: ChannelBackfill) -> None:
        self.backfills.append(backfill)
        self._backfill_worker.submit(backfill)

    def _create_new_session(
        self, channel: discord.TextChannel, msg: discord.Message | None = None
    ) -> BackfillSession:
        with self.session() as session:
            highest_message: int = (
                msg.id
                if msg
                else session.query(func.max(Message.id))
                .filter(Message.channel_id == channel.id)
                .scalar()
            )

            s = BackfillSession(
                channel_id=channel.id,
                start_message_id=highest_message,
            )
            session.add(s)
            session.commit()

            return s

    # while running
    # NOTE: msg is used for backfill tracking
    def register_channel(
        self, channel: discord.TextChannel, msg: discord.Message | None = None
    ) -> None:
        # catchup
        if channel.id not in self._session_seen_channel:
            with self.session() as session:
                sessions = session.scalars(
                    select(BackfillSession).where(BackfillSession.channel_id == channel.id)
                ).all()

                if sessions and len(sessions) % 2 != 0:
                    self._create_new_session(channel, msg)

            self._session_seen_channel.add(channel.id)

        # actual backfill
        if channel.id in self._seen_channel:
            return

        lowest_message_id = msg.id if msg else None
        if lowest_message_id:
            with self.session() as session:
                # NOTE: this is assuming that the channel already exists, which it should
                session.execute(
                    update(Channel)
                    .where(Channel.id == channel.id)
                    .values(backfill_lowest_message_id=lowest_message_id)
                )
                session.commit()

                self.add_backfill_session(
                    ChannelBackfill(
                        channel,
                        (None, lowest_message_id),
                        self.session,
                        self.fetcher,
                        self.writer,
                        self.loop,
                        on_complete=lambda channel_id=channel.id: self._mark_session_complete(
                            None, channel_id
                        ),
                    )
                )

        self._seen_channel.add(channel.id)

    # on startup
    def add(self, channel: discord.TextChannel) -> None:
        with self.session() as session:
            # start actual backfill
            ch = session.scalars(
                select(Channel).where(
                    Channel.id == channel.id
                    and Channel.backfill_lowest_message_id != None
                    and Channel.backfill_lowest_message_id != -1
                )
            ).one_or_none()
            if ch:
                self.add_backfill_session(
                    ChannelBackfill(
                        channel,
                        (None, ch.backfill_lowest_message_id),
                        self.session,
                        self.fetcher,
                        self.writer,
                        self.loop,
                        on_complete=lambda channel_id=channel.id: self._mark_session_complete(
                            None, channel_id
                        ),
                    )
                )

            # start catchup
            sessions = session.scalars(
                select(BackfillSession).order_by(BackfillSession.id.asc())
            ).all()

            if not sessions:
                return

            # since the session is determined by the message sent for the anchor,
            # there is a possibility that no message is sent for a long time, rather
            # than waiting, we should catchup until discord returns empty--much like actual backfill.
            latest_no_end: BackfillSession | None = None
            if len(sessions) % 2 != 0:
                latest_no_end = sessions[-1]
                sessions = sessions[:-1]

            # [s][s2][s3][s4]
            #     ^^^^^^ done
            for n0, n1 in zip(sessions[::2], sessions[1::2]):
                if n0.completed and n1.completed:
                    continue

                if n0.start_message_id == n1.start_message_id:
                    self._mark_session_complete(n0.id, n1.id)
                    continue

                lower = n0.start_message_id
                upper = n1.start_message_id

                self.add_backfill_session(
                    ChannelBackfill(
                        channel,
                        (lower, upper),
                        self.session,
                        self.fetcher,
                        self.writer,
                        self.loop,
                        on_complete=lambda n0_id=n0.id, n1_id=n1.id: self._mark_session_complete(
                            n0_id, n1_id
                        ),
                    )
                )

            if latest_no_end:
                self.add_backfill_session(
                    ChannelBackfill(
                        channel,
                        (latest_no_end.start_message_id, None),
                        self.session,
                        self.fetcher,
                        self.writer,
                        self.loop,
                        on_complete=lambda latest=latest_no_end.id: self._mark_session_complete(
                            latest, None
                        ),
                    )
                )

    def cleanup(self, channel: discord.TextChannel) -> None:
        self._create_new_session(channel)

    def _mark_session_complete(
        self, lower_id: int | None, upper_id: int | None
    ) -> None:
        if lower_id is None and upper_id is None:
            raise ValueError(
                "Illegal states: lower id and upper id cannot both be NULL"
            )

        with self.session() as session:
            if lower_id is None:
                session.execute(
                    update(Channel)
                    .where(Channel.id == upper_id)
                    .values(backfill_lowest_message_id=-1)
                )
            elif upper_id is None:
                session.execute(
                    update(BackfillSession)
                    .where(BackfillSession.id == lower_id)
                    .values(completed=True)
                )
            else:
                session.execute(
                    update(BackfillSession)
                    .where(BackfillSession.id.in_((lower_id, upper_id)))
                    .values(completed=True)
                )
            session.commit()

    def stop(self) -> None:
        self._backfill_worker.stop()
