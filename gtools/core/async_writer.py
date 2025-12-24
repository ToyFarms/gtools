from pathlib import Path
from queue import Empty, Full, Queue
import threading
import time
from typing import IO, Any


class AsyncFileWriter:
    def __init__(
        self,
        daemon: bool = True,
        inactive_ttl: float = 60.0,
        sweep_interval: float = 10.0,
    ) -> None:
        self._q: Queue[tuple[Any, str, str]] = Queue(-1)
        self._stop = threading.Event()
        self._inactive_ttl = inactive_ttl
        self._sweep_interval = sweep_interval
        self._thread = threading.Thread(
            target=self._run,
            daemon=daemon,
            name="async-file-writer",
        )
        self._thread.start()

    def submit(self, data: Any, filename: str, mode: str = "a") -> bool:
        try:
            self._q.put_nowait((data, filename, mode))
            return True
        except Full:
            return False

    def _run(self):
        files: dict[tuple[str, str], tuple[IO[Any], float]] = {}
        last_sweep = time.monotonic()

        try:
            while not (self._stop.is_set() and self._q.empty()):
                try:
                    data, filename, mode = self._q.get(timeout=0.2)
                except Empty:
                    data = None

                now = time.monotonic()

                if data is not None:
                    key = (filename, mode)
                    try:
                        handle, _ = files.get(key, (None, None))
                        if handle is None:
                            handle = open(filename, mode)

                        if isinstance(data, (bytes, bytearray)):
                            handle.write(data)
                        else:
                            handle.write(str(data))

                        handle.flush()
                        files[key] = (handle, now)
                    except Exception:
                        pass
                    finally:
                        try:
                            self._q.task_done()
                        except Exception:
                            pass

                if now - last_sweep >= self._sweep_interval:
                    cutoff = now - self._inactive_ttl
                    for key, (handle, last_used) in list(files.items()):
                        if last_used < cutoff:
                            try:
                                handle.close()
                            except Exception:
                                pass
                            files.pop(key, None)
                    last_sweep = now
        finally:
            for handle, _ in files.values():
                try:
                    handle.close()
                except Exception:
                    pass

    def close(self, wait: bool = True) -> None:
        self._stop.set()
        if wait:
            self._thread.join()


GLOBAL_ASYNC_FILE_WRITER = AsyncFileWriter()


def write_async(data: Any, filename: str | Path, mode: str = "w") -> bool:
    Path(filename).parent.mkdir(parents=True, exist_ok=True)
    return GLOBAL_ASYNC_FILE_WRITER.submit(data, str(filename), mode)
