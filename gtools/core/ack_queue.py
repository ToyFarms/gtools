from collections import deque
from queue import Empty
import threading
import time


class AckQueue[T]:
    def __init__(self):
        self._queue: deque[T] = deque()
        self._current = None
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)

    def put(self, item: T) -> None:
        with self._cv:
            self._queue.append(item)
            self._cv.notify_all()

    def get(self, block: bool = True, timeout: float | None = None) -> T:
        with self._cv:
            if self._current is not None:
                return self._current

            if not block:
                if not self._queue:
                    raise Empty
                self._current = self._queue[0]
                return self._current

            deadline = None
            if timeout is not None:
                deadline = time.monotonic() + timeout

            while True:
                if self._current is not None:
                    return self._current
                if self._queue:
                    self._current = self._queue[0]
                    return self._current

                if timeout is None or deadline is None:
                    self._cv.wait()
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise Empty
                    self._cv.wait(remaining)

    def get_nowait(self):
        return self.get(block=False)

    def ack(self) -> None:
        with self._cv:
            if self._current is None:
                raise RuntimeError("no active item to acknowledge")

            if not self._queue:
                self._current = None
                raise RuntimeError("queue empty while an active item existed (internal error)")

            head = self._queue.popleft()
            if head is not self._current and head != self._current:
                self._current = None
                raise RuntimeError("active item does not match queue head (internal error)")

            self._current = None
            self._cv.notify_all()

    def qsize(self):
        with self._lock:
            return len(self._queue)

    def empty(self):
        with self._lock:
            return len(self._queue) == 0

    def __repr__(self):
        with self._lock:
            return f"AckQueue(current={self._current!r}, queue={list(self._queue)!r})"
