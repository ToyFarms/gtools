from typing import Callable, Any
import threading
import time
import heapq
from concurrent.futures import ThreadPoolExecutor


class ScheduledTask:
    __slots__ = ("_func", "_execute_at", "_cancelled", "_done", "_result", "_error", "_event", "__weakref__")

    def __init__(self, func: Callable, execute_at: float):
        self._func = func
        self._execute_at = execute_at
        self._cancelled = False
        self._done = False
        self._result: Any = None
        self._error: Exception | None = None
        self._event = threading.Event()

    def __lt__(self, other: "ScheduledTask") -> bool:
        return self._execute_at < other._execute_at

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def is_done(self) -> bool:
        return self._done

    @property
    def has_error(self) -> bool:
        return self._error is not None

    def cancel(self) -> bool:
        if not self._done:
            self._cancelled = True
            self._event.set()
            return True
        return False

    def join(self, timeout: float | None = None) -> None:
        self._event.wait(timeout)

    def result_or_raise(self) -> Any:
        self._event.wait()
        if self._error:
            raise self._error
        return self._result

    def result(self) -> tuple[Any, Exception | None]:
        self._event.wait()
        return self._result, self._error


class TaskScheduler:
    def __init__(self, max_workers: int | None = None):
        self._queue: list[ScheduledTask] = []
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._shutdown_flag = False
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def schedule(self, func: Callable, delay: float) -> ScheduledTask:
        execute_at = time.perf_counter() + delay
        task = ScheduledTask(func, execute_at)

        with self._condition:
            heapq.heappush(self._queue, task)
            self._condition.notify()

        return task

    def shutdown(self, wait: bool = True) -> None:
        with self._condition:
            self._shutdown_flag = True
            self._condition.notify()

        if wait:
            self._worker.join()

        self._executor.shutdown(wait=wait)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.shutdown()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._shutdown_flag:
                    if not self._queue:
                        self._condition.wait()
                        continue

                    wait_time = self._queue[0]._execute_at - time.perf_counter()
                    if wait_time <= 0:
                        break

                    self._condition.wait(wait_time)

                if self._shutdown_flag:
                    break

                task = heapq.heappop(self._queue)

            if task._cancelled:
                continue

            self._executor.submit(self._execute_task, task)

    def _execute_task(self, task: ScheduledTask) -> None:
        try:
            task._result = task._func()
        except Exception as e:
            task._error = e
        finally:
            task._done = True
            task._event.set()


_global_scheduler: TaskScheduler | None = None
_global_lock = threading.Lock()


def get_scheduler(max_workers: int | None = None) -> TaskScheduler:
    global _global_scheduler
    if _global_scheduler is None:
        with _global_lock:
            if _global_scheduler is None:
                _global_scheduler = TaskScheduler(max_workers=max_workers)
    return _global_scheduler


def schedule_task(func: Callable, delay: float) -> ScheduledTask:
    return get_scheduler().schedule(func, delay)
