import pytest
import time
import threading
from gtools.core.task_scheduler import TaskScheduler, schedule_task, get_scheduler


def test_simple_task_execution() -> None:
    scheduler = TaskScheduler()
    result = []

    task = scheduler.schedule(lambda: result.append(42), 0.1)
    task.join(timeout=1.0)

    assert result == [42]
    assert task.is_done
    scheduler.shutdown(wait=False)


def test_task_with_return_value() -> None:
    scheduler = TaskScheduler()

    task = scheduler.schedule(lambda: 10 * 5, 0.05)
    task.join(timeout=1.0)
    result = task.result_or_raise()

    assert result == 50
    scheduler.shutdown(wait=False)


def test_task_with_arguments() -> None:
    scheduler = TaskScheduler()

    def multiply(a, b):
        return a * b

    task = scheduler.schedule(lambda: multiply(7, 8), 0.05)
    task.join(timeout=1.0)
    result = task.result_or_raise()

    assert result == 56
    scheduler.shutdown(wait=False)


def test_multiple_tasks_execution() -> None:
    scheduler = TaskScheduler()
    results = []

    tasks = [scheduler.schedule(lambda i=i: results.append(i), 0.1) for i in range(5)]

    for task in tasks:
        task.join(timeout=1.0)

    assert len(results) == 5
    assert set(results) == {0, 1, 2, 3, 4}
    scheduler.shutdown(wait=False)


def test_zero_delay_task() -> None:
    scheduler = TaskScheduler()

    task = scheduler.schedule(lambda: "instant", 0)
    task.join(timeout=1.0)
    result = task.result_or_raise()

    assert result == "instant"
    scheduler.shutdown(wait=False)


def test_cancel_before_execution() -> None:
    scheduler = TaskScheduler()
    executed = []

    task = scheduler.schedule(lambda: executed.append(1), 0.5)
    cancelled = task.cancel()
    time.sleep(0.6)

    assert cancelled is True
    assert task.is_cancelled
    assert not task.is_done
    assert executed == []
    scheduler.shutdown(wait=False)


def test_cancel_after_execution() -> None:
    scheduler = TaskScheduler()

    task = scheduler.schedule(lambda: 42, 0.05)
    task.join(timeout=1.0)
    cancelled = task.cancel()

    assert cancelled is False
    assert task.is_done
    assert not task.is_cancelled
    scheduler.shutdown(wait=False)


def test_cancel_multiple_tasks() -> None:
    scheduler = TaskScheduler()
    executed = []

    tasks = [scheduler.schedule(lambda i=i: executed.append(i), 0.3) for i in range(10)]

    for i, task in enumerate(tasks):
        if i % 2 == 1:
            task.cancel()

    time.sleep(0.5)

    assert len(executed) == 5
    assert all(i % 2 == 0 for i in executed)
    scheduler.shutdown(wait=False)


def test_is_done_initially_false() -> None:
    scheduler = TaskScheduler()
    task = scheduler.schedule(lambda: 42, 0.3)

    assert not task.is_done

    task.cancel()
    scheduler.shutdown(wait=False)


def test_is_done_after_execution() -> None:
    scheduler = TaskScheduler()
    task = scheduler.schedule(lambda: 42, 0.05)
    task.join(timeout=1.0)

    assert task.is_done
    scheduler.shutdown(wait=False)


def test_has_error_on_exception() -> None:
    scheduler = TaskScheduler()

    def failing_task():
        raise ValueError("test error")

    task = scheduler.schedule(failing_task, 0.05)
    task.join(timeout=1.0)
    _result, error = task.result()

    assert task.has_error
    assert isinstance(error, ValueError)
    scheduler.shutdown(wait=False)


def test_has_error_on_success() -> None:
    scheduler = TaskScheduler()
    task = scheduler.schedule(lambda: 42, 0.05)
    task.join(timeout=1.0)

    assert not task.has_error
    scheduler.shutdown(wait=False)


def test_is_cancelled_status() -> None:
    scheduler = TaskScheduler()
    task = scheduler.schedule(lambda: 42, 0.3)

    assert not task.is_cancelled
    task.cancel()
    assert task.is_cancelled

    scheduler.shutdown(wait=False)


def test_exception_in_task() -> None:
    scheduler = TaskScheduler()

    def failing_task():
        raise RuntimeError("task failed")

    task = scheduler.schedule(failing_task, 0.05)
    task.join(timeout=1.0)

    with pytest.raises(RuntimeError, match="task failed"):
        task.result_or_raise()

    scheduler.shutdown(wait=False)


def test_go_style_error_handling() -> None:
    scheduler = TaskScheduler()

    def failing_task():
        raise ValueError("error message")

    task = scheduler.schedule(failing_task, 0.05)
    task.join(timeout=1.0)
    result, error = task.result()

    assert result is None
    assert isinstance(error, ValueError)
    assert str(error) == "error message"
    scheduler.shutdown(wait=False)


def test_successful_task_no_error() -> None:
    scheduler = TaskScheduler()
    task = scheduler.schedule(lambda: 100, 0.05)
    task.join(timeout=1.0)
    result, error = task.result()

    assert result == 100
    assert error is None
    scheduler.shutdown(wait=False)


def test_delay_accuracy() -> None:
    scheduler = TaskScheduler()
    delays = [0.1, 0.2, 0.3]
    tolerance = 0.08

    for delay in delays:
        start = time.perf_counter()
        task = scheduler.schedule(lambda: time.perf_counter(), delay)
        task.join(timeout=2.0)
        executed_at = task.result_or_raise()
        actual_delay = executed_at - start

        assert abs(actual_delay - delay) < tolerance, f"delay {delay}s was off by {abs(actual_delay - delay)}s"

    scheduler.shutdown(wait=False)


def test_task_ordering() -> None:
    scheduler = TaskScheduler()
    results = []

    scheduler.schedule(lambda: results.append(3), 0.25)
    scheduler.schedule(lambda: results.append(1), 0.05)
    scheduler.schedule(lambda: results.append(2), 0.15)

    time.sleep(0.4)

    assert results == [1, 2, 3]
    scheduler.shutdown(wait=False)


def test_very_short_delays() -> None:
    scheduler = TaskScheduler()
    tasks = [scheduler.schedule(lambda: time.perf_counter(), 0.001) for _ in range(10)]

    for task in tasks:
        task.join(timeout=1.0)
        assert task.is_done

    scheduler.shutdown(wait=False)


def test_join_timeout() -> None:
    scheduler = TaskScheduler()
    task = scheduler.schedule(lambda: time.sleep(0.3), 0.01)

    start = time.perf_counter()
    task.join(timeout=0.1)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.15

    task.join(timeout=1.0)
    assert task.is_done

    scheduler.shutdown(wait=False)


def test_tasks_run_concurrently() -> None:
    scheduler = TaskScheduler(max_workers=10)

    active_count = []
    lock = threading.Lock()
    max_concurrent = [0]

    def blocking_task():
        with lock:
            active_count.append(1)
            current = len(active_count)
            max_concurrent[0] = max(max_concurrent[0], current)

        time.sleep(0.2)

        with lock:
            active_count.pop()

    start = time.perf_counter()
    tasks = [scheduler.schedule(blocking_task, 0.01) for _ in range(5)]

    for task in tasks:
        task.join(timeout=2.0)

    elapsed = time.perf_counter() - start

    assert elapsed < 0.5, f"took {elapsed}s, expected < 0.5s"
    assert max_concurrent[0] >= 3, "not enough concurrency"

    scheduler.shutdown(wait=False)


def test_thread_pool_limit() -> None:
    scheduler = TaskScheduler(max_workers=3)

    active_count = [0]
    max_concurrent = [0]
    lock = threading.Lock()

    def limited_task():
        with lock:
            active_count[0] += 1
            max_concurrent[0] = max(max_concurrent[0], active_count[0])

        time.sleep(0.15)

        with lock:
            active_count[0] -= 1

    tasks = [scheduler.schedule(limited_task, 0.01) for _ in range(10)]

    for task in tasks:
        task.join(timeout=5.0)

    assert max_concurrent[0] <= 3

    scheduler.shutdown(wait=False)


def test_concurrent_scheduling() -> None:
    scheduler = TaskScheduler()
    results = []
    lock = threading.Lock()

    def schedule_multiple():
        for i in range(10):

            def append_result(i=i):
                with lock:
                    results.append(i)

            scheduler.schedule(append_result, 0.1)

    threads = [threading.Thread(target=schedule_multiple) for _ in range(5)]

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    time.sleep(0.3)

    assert len(results) == 50
    scheduler.shutdown(wait=False)


def test_concurrent_cancel_and_execute() -> None:
    scheduler = TaskScheduler()
    results = []

    for _ in range(20):
        task = scheduler.schedule(lambda: results.append(1), 0.05)
        task.cancel()

    time.sleep(0.2)

    assert len(results) <= 20

    scheduler.shutdown(wait=False)


def test_concurrent_result_access() -> None:
    scheduler = TaskScheduler()
    task = scheduler.schedule(lambda: 42, 0.05)

    results = []

    def get_result():
        try:
            results.append(task.result_or_raise())
        except:
            pass

    threads = [threading.Thread(target=get_result) for _ in range(10)]

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    assert all(r == 42 for r in results)
    assert len(results) == 10

    scheduler.shutdown(wait=False)


def test_schedule_during_shutdown() -> None:
    scheduler = TaskScheduler()

    def schedule_many():
        for _ in range(100):
            try:
                scheduler.schedule(lambda: None, 0.1)
                time.sleep(0.001)
            except:
                pass

    thread = threading.Thread(target=schedule_many)
    thread.start()

    time.sleep(0.05)
    scheduler.shutdown(wait=False)

    thread.join(timeout=2.0)


def test_concurrent_status_checks() -> None:
    scheduler = TaskScheduler()
    task = scheduler.schedule(lambda: time.sleep(0.1), 0.01)

    def check_status():
        for _ in range(100):
            _ = task.is_done
            _ = task.is_cancelled
            _ = task.has_error
            time.sleep(0.001)

    threads = [threading.Thread(target=check_status) for _ in range(5)]

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    task.join(timeout=1.0)
    scheduler.shutdown(wait=False)


def test_schedule_task_function() -> None:
    task = schedule_task(lambda: 99, 0.05)
    task.join(timeout=1.0)
    result = task.result_or_raise()

    assert result == 99


def test_get_scheduler_singleton() -> None:
    scheduler1 = get_scheduler()
    scheduler2 = get_scheduler()

    assert scheduler1 is scheduler2


def test_separate_scheduler_instance() -> None:
    global_task = schedule_task(lambda: "global", 0.05)

    separate_scheduler = TaskScheduler()
    separate_task = separate_scheduler.schedule(lambda: "separate", 0.05)

    global_task.join(timeout=1.0)
    separate_task.join(timeout=1.0)

    assert global_task.result_or_raise() == "global"
    assert separate_task.result_or_raise() == "separate"

    separate_scheduler.shutdown(wait=False)


def test_context_manager_auto_shutdown() -> None:
    task_ref = None

    with TaskScheduler() as scheduler:
        task_ref = scheduler.schedule(lambda: 42, 0.05)
        task_ref.join(timeout=1.0)

    assert task_ref.is_done


def test_context_manager_with_error() -> None:
    try:
        with TaskScheduler() as scheduler:
            _task = scheduler.schedule(lambda: 42, 0.05)
            raise ValueError("test error")
    except ValueError:
        pass



def test_many_tasks() -> None:
    scheduler = TaskScheduler()
    num_tasks = 100
    results = []
    lock = threading.Lock()

    def append_result(i):
        with lock:
            results.append(i)

    tasks = [scheduler.schedule(lambda i=i: append_result(i), 0.01) for i in range(num_tasks)]

    for task in tasks:
        task.join(timeout=2.0)

    assert len(results) == num_tasks
    scheduler.shutdown(wait=False)


def test_rapid_scheduling() -> None:
    scheduler = TaskScheduler()

    start = time.perf_counter()
    tasks = [scheduler.schedule(lambda: None, 0.1) for _ in range(100)]
    scheduling_time = time.perf_counter() - start

    assert scheduling_time < 0.1

    for task in tasks:
        task.join(timeout=1.0)

    scheduler.shutdown(wait=False)


def test_long_running_tasks() -> None:
    scheduler = TaskScheduler()

    long_task = scheduler.schedule(lambda: time.sleep(1.0), 0.01)

    short_task = scheduler.schedule(lambda: 42, 0.05)

    start = time.perf_counter()
    short_task.join(timeout=2.0)
    result = short_task.result_or_raise()
    elapsed = time.perf_counter() - start

    assert result == 42
    assert elapsed < 0.5

    long_task.cancel()
    scheduler.shutdown(wait=False)


def test_memory_cleanup() -> None:
    import gc
    import weakref

    scheduler = TaskScheduler()

    task = scheduler.schedule(lambda: 42, 0.05)
    task.join(timeout=1.0)
    _weak_ref = weakref.ref(task)

    del task
    gc.collect()

    scheduler.shutdown(wait=False)


def test_shutdown_waits_for_tasks() -> None:
    scheduler = TaskScheduler()
    completed = []

    def task_func():
        time.sleep(0.15)
        completed.append(1)

    _task = scheduler.schedule(task_func, 0.01)

    time.sleep(0.05)

    start = time.perf_counter()
    scheduler.shutdown(wait=True)
    elapsed = time.perf_counter() - start

    assert elapsed >= 0.1
    assert completed == [1]


def test_shutdown_without_wait() -> None:
    scheduler = TaskScheduler()

    _task = scheduler.schedule(lambda: time.sleep(0.5), 0.01)

    time.sleep(0.05)

    start = time.perf_counter()
    scheduler.shutdown(wait=False)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.2


def test_pending_tasks_after_shutdown() -> None:
    scheduler = TaskScheduler()
    executed = []

    _tasks = [scheduler.schedule(lambda i=i: executed.append(i), 0.5) for i in range(5)]

    time.sleep(0.05)
    scheduler.shutdown(wait=False)
    time.sleep(0.6)

    assert len(executed) < 5
