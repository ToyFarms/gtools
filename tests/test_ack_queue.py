from queue import Empty
import threading
import time
import pytest

from gtools.core.ack_queue import AckQueue


def test_put_get_ack_basic():
    q = AckQueue()
    q.put(1)
    q.put(2)

    assert q.qsize() == 2
    head = q.get()
    assert head == 1
    assert q.get() == 1

    q.ack()
    assert q.get() == 2
    q.ack()
    with pytest.raises(Empty):
        q.get(block=False)


def test_repeated_get_returns_same():
    q = AckQueue()
    q.put("a")
    a1 = q.get()
    a2 = q.get()
    assert a1 is a2


def test_done_alias():
    q = AckQueue()
    q.put("x")
    assert q.get() == "x"
    q.ack()
    with pytest.raises(Empty):
        q.get(block=False)


def test_qsize_empty_and_repr():
    q = AckQueue()
    assert q.empty()
    q.put(10)
    assert not q.empty()
    assert q.qsize() == 1


def test_get_non_blocking_empty_raises():
    q = AckQueue()
    with pytest.raises(Empty):
        q.get(block=False)


def test_get_non_blocking_sets_current():
    q = AckQueue()
    q.put(99)
    val = q.get(block=False)
    assert val == 99
    assert q.qsize() == 1


def test_get_with_timeout_success():
    q = AckQueue()

    def delayed_put():
        time.sleep(0.05)
        q.put("delayed")

    t = threading.Thread(target=delayed_put)
    t.start()

    val = q.get(block=True, timeout=1.0)
    assert val == "delayed"
    t.join()


def test_get_with_timeout_timeout_raises():
    q = AckQueue()
    start = time.monotonic()
    with pytest.raises(Empty):
        q.get(block=True, timeout=0.02)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.01


def test_ack_without_current_raises():
    q = AckQueue()
    with pytest.raises(RuntimeError):
        q.ack()


def test_internal_empty_on_ack_raises():
    q = AckQueue()
    q.put("one")
    q.get()
    with q._lock:
        q._queue.clear()
    with pytest.raises(RuntimeError) as exc:
        q.ack()
    assert "queue empty" in str(exc.value).lower()


def test_internal_head_mismatch_raises():
    q = AckQueue()
    q.put("first")
    q.put("second")
    q.get()
    with q._lock:
        q._queue[0] = object()
    with pytest.raises(RuntimeError) as exc:
        q.ack()
    assert "active item does not match" in str(exc.value).lower()


def test_threaded_multiple_getters_return_same():
    q = AckQueue()
    q.put("job")

    n = 5
    results = [None] * n

    def reader(i):
        results[i] = q.get()

    threads = [threading.Thread(target=reader, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r == "job" for r in results)


def test_threaded_ack_advances():
    q = AckQueue()
    q.put("a")
    q.put("b")

    collected = []

    def reader_once():
        collected.append(q.get())

    threads = [threading.Thread(target=reader_once) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(x == "a" for x in collected)

    q.ack()
    assert q.get() == "b"


def test_concurrent_puts_and_gets_stability():
    q = AckQueue()
    results = []

    def producer():
        for i in range(3):
            q.put(f"p{i}")
            time.sleep(0.01)

    def consumer_ack_sequence():
        for _ in range(3):
            v = q.get()
            results.append(v)
            time.sleep(0.02)
            q.ack()

    t1 = threading.Thread(target=producer)
    t2 = threading.Thread(target=consumer_ack_sequence)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results == ["p0", "p1", "p2"]


def test_ack_removes_head_identity():
    q = AckQueue()
    obj = []
    q.put(obj)
    q.get()
    q.ack()
    assert q.empty()


def test_repr_includes_current_after_get():
    q = AckQueue()
    q.put("z")
    q.get()
    r = repr(q)
    assert "z" in r


def test_multiple_ack_calls_sequence_and_errors():
    q = AckQueue()
    q.put("x")
    q.get()
    q.ack()
    with pytest.raises(RuntimeError):
        q.ack()
