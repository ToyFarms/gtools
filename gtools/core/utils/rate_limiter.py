import asyncio
from contextlib import contextmanager
import threading
import time
from typing import Any


class rate_limiter:
    def __init__(
        self,
        rps: float,
        backoff_initial: float = 1,
        backoff_base: float = 2,
    ) -> None:
        self.rps = rps
        self.request_delay = 1 / self.rps
        self._last_call = 0.0
        self._retry_attempts = 0
        self._backoff_initial = backoff_initial
        self._backoff_base = backoff_base
        self.lock = threading.Lock()

    def __enter__(self) -> "rate_limiter":
        with self.lock:
            if self._last_call == 0:
                self._last_call = time.monotonic()

            elapsed = time.monotonic() - self._last_call
            if elapsed < self.request_delay:
                time.sleep((self.request_delay - elapsed) / 1000000)

            return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        with self.lock:
            self._last_call = time.monotonic()

    def exp_backoff(self, delta: float) -> None:
        with self.lock:
            if self._retry_attempts == 0:
                return

            delay = self._backoff_initial + self._backoff_base**self._retry_attempts
            print(f"RATE LIMITED, WAITING {delay} seconds")
            time.sleep(delay)

            self._retry_attempts = max(0, int(self._retry_attempts + delta))


class async_rate_limiter:
    def __init__(
        self, rps: float, backoff_initial: float = 1.0, backoff_base: float = 2.0
    ) -> None:
        self.rps = rps
        self.request_delay = 1.0 / self.rps
        self._last_call = 0.0
        self._retry_attempts = 0
        self._backoff_initial = backoff_initial
        self._backoff_base = backoff_base

    async def __aenter__(self) -> "async_rate_limiter":
        loop = asyncio.get_running_loop()
        now = loop.time()
        if self._last_call == 0.0:
            self._last_call = now
            return self

        elapsed = now - self._last_call
        if elapsed < self.request_delay:
            await asyncio.sleep(self.request_delay - elapsed)

        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._last_call = asyncio.get_running_loop().time()

    async def exp_backoff(self, delta: float = 1.0) -> None:
        delay = self._backoff_initial + (self._backoff_base**self._retry_attempts)
        print(f"RATE LIMITED, WAITING {delay} seconds")
        await asyncio.sleep(delay)

        self._retry_attempts = max(0, int(self._retry_attempts + delta))


if __name__ == "__main__":
    i = 0
    start = time.time()
    while True:
        with rate_limiter(5):
            print(f"{i}, {time.time() - start}")
            i += 1
