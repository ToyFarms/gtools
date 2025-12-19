import threading
import time

import pytest

from gtools.core.signal import Signal


def test_create_signal_with_value() -> None:
    signal = Signal(42)
    assert signal.get() == 42


def test_create_signal_with_different_types() -> None:
    int_signal = Signal(10)
    assert int_signal.get() == 10

    str_signal = Signal("hello")
    assert str_signal.get() == "hello"

    list_signal = Signal([1, 2, 3])
    assert list_signal.get() == [1, 2, 3]

    dict_signal = Signal({"key": "value"})
    assert dict_signal.get() == {"key": "value"}


def test_set_value() -> None:
    signal = Signal(0)
    signal.set(100)
    assert signal.get() == 100


def test_set_multiple_times() -> None:
    signal = Signal(1)
    signal.set(2)
    signal.set(3)
    signal.set(4)
    assert signal.get() == 4


def test_update_with_function() -> None:
    signal = Signal(5)
    signal.update(lambda x: x * 2)
    assert signal.get() == 10


def test_update_increment() -> None:
    counter = Signal(0)
    counter.update(lambda x: x + 1)
    counter.update(lambda x: x + 1)
    assert counter.get() == 2


def test_is_derived_property() -> None:
    mutable = Signal(1)
    assert not mutable.is_derived

    derived = Signal.derive(lambda: mutable.get() * 2, mutable)
    assert derived.is_derived


def test_repr() -> None:
    mutable = Signal(42)
    assert "mutable" in repr(mutable)
    assert "42" in repr(mutable)

    derived = Signal.derive(lambda: mutable.get(), mutable)
    assert "derived" in repr(derived)


def test_bool_context() -> None:
    truthy = Signal(1)
    assert bool(truthy)

    falsy = Signal(0)
    assert not bool(falsy)

    empty_list = Signal([])
    assert not bool(empty_list)


def test_wait_until_already_true() -> None:
    signal = Signal(10)
    result = signal.wait_until(lambda x: x > 5, timeout=0.1)
    assert result is True


def test_wait_until_becomes_true() -> None:
    signal = Signal(0)

    def setter():
        time.sleep(0.1)
        signal.set(10)

    thread = threading.Thread(target=setter)
    thread.start()

    result = signal.wait_until(lambda x: x > 5, timeout=1.0)
    assert result is True
    assert signal.get() == 10

    thread.join()


def test_wait_until_timeout() -> None:
    signal = Signal(0)
    result = signal.wait_until(lambda x: x > 100, timeout=0.1)
    assert result is False


def test_wait_value_match() -> None:
    signal = Signal(0)

    def setter():
        time.sleep(0.1)
        signal.set(42)

    thread = threading.Thread(target=setter)
    thread.start()

    result = signal.wait_value(42, timeout=1.0)
    assert result is True

    thread.join()


def test_wait_value_timeout() -> None:
    signal = Signal(0)
    result = signal.wait_value(999, timeout=0.1)
    assert result is False


def test_wait_true() -> None:
    signal = Signal(0)

    def setter():
        time.sleep(0.1)
        signal.set(1)

    thread = threading.Thread(target=setter)
    thread.start()

    result = signal.wait_true(timeout=1.0)
    assert result is True

    thread.join()


def test_wait_false() -> None:
    signal = Signal(1)

    def setter():
        time.sleep(0.1)
        signal.set(0)

    thread = threading.Thread(target=setter)
    thread.start()

    result = signal.wait_false(timeout=1.0)
    assert result is True

    thread.join()


def test_wait_without_timeout() -> None:
    signal = Signal(100)
    result = signal.wait_until(lambda x: x > 50)
    assert result is True


def test_derived_signal_basic() -> None:
    source = Signal(5)
    doubled = Signal.derive(lambda: source.get() * 2, source)

    assert doubled.get() == 10


def test_derived_signal_updates() -> None:
    source = Signal(3)
    doubled = Signal.derive(lambda: source.get() * 2, source)

    assert doubled.get() == 6

    source.set(10)
    assert doubled.get() == 20


def test_derived_from_multiple_dependencies() -> None:
    x = Signal(2)
    y = Signal(3)
    sum_signal = Signal.derive(lambda: x.get() + y.get(), x, y)

    assert sum_signal.get() == 5

    x.set(10)
    assert sum_signal.get() == 13

    y.set(7)
    assert sum_signal.get() == 17


def test_chained_derived_signals() -> None:
    base = Signal(2)
    doubled = Signal.derive(lambda: base.get() * 2, base)
    quadrupled = Signal.derive(lambda: doubled.get() * 2, doubled)

    assert quadrupled.get() == 8

    base.set(5)
    assert doubled.get() == 10
    assert quadrupled.get() == 20


def test_derived_signal_complex_logic() -> None:
    numbers = Signal([1, 2, 3, 4, 5])
    sum_evens = Signal.derive(lambda: sum(x for x in numbers.get() if x % 2 == 0), numbers)

    assert sum_evens.get() == 6

    numbers.set([2, 4, 6, 8])
    assert sum_evens.get() == 20


def test_derived_signal_no_dependencies_error() -> None:
    with pytest.raises(ValueError, match="must have at least one dependency"):
        Signal.derive(lambda: 42)


def test_derived_signal_set_error() -> None:
    source = Signal(1)
    derived = Signal.derive(lambda: source.get() * 2, source)

    with pytest.raises(ValueError, match="cannot set value of derived signal"):
        derived.set(100)


def test_derived_signal_update_error() -> None:
    source = Signal(1)
    derived = Signal.derive(lambda: source.get() * 2, source)

    with pytest.raises(ValueError, match="cannot update value of derived signal"):
        derived.update(lambda x: x + 1)


def test_derived_signal_only_updates_on_change() -> None:
    call_count = {"value": 0}

    source = Signal(5)

    def derive():
        call_count["value"] += 1
        return source.get() % 2

    derived = Signal.derive(derive, source)

    _ = call_count["value"]

    source.set(7)
    source.set(9)

    assert derived.get() == 1


def test_concurrent_sets() -> None:
    signal = Signal(0)
    iterations = 100

    def incrementer():
        for _ in range(iterations):
            signal.update(lambda x: x + 1)

    threads = [threading.Thread(target=incrementer) for _ in range(5)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert signal.get() == iterations * 5


def test_concurrent_reads_and_writes() -> None:
    signal = Signal(0)
    errors = []

    def writer():
        for i in range(50):
            signal.set(i)
            time.sleep(0.001)

    def reader():
        try:
            for _ in range(50):
                value = signal.get()
                assert isinstance(value, int)
                time.sleep(0.001)
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=writer),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0


def test_multiple_waiters() -> None:
    signal = Signal(0)
    results = []

    def waiter(target):
        result = signal.wait_value(target, timeout=2.0)
        results.append(result)

    threads = [
        threading.Thread(target=waiter, args=(5,)),
        threading.Thread(target=waiter, args=(5,)),
        threading.Thread(target=waiter, args=(5,)),
    ]

    for t in threads:
        t.start()

    time.sleep(0.1)
    signal.set(5)

    for t in threads:
        t.join()

    assert all(results)


def test_derived_signal_thread_safety() -> None:
    source = Signal(0)
    derived = Signal.derive(lambda: source.get() * 2, source)
    errors = []

    def updater():
        try:
            for i in range(50):
                source.set(i)
                time.sleep(0.001)
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            for _ in range(50):
                value = derived.get()
                assert value % 2 == 0
                time.sleep(0.001)
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=updater),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0


def test_batch_update_basic() -> None:
    signal = Signal({"x": 0, "y": 0})

    with signal.batch_update():
        data = signal.get()
        data["x"] = 10
        data["y"] = 20

    result = signal.get()
    assert result["x"] == 10
    assert result["y"] == 20


def test_batch_update_with_derived() -> None:
    base = Signal([1, 2, 3])
    total = Signal.derive(lambda: sum(base.get()), base)

    assert total.get() == 6

    with base.batch_update():
        lst = base.get()
        lst.append(4)
        lst.append(5)

    assert total.get() == 15


def test_batch_update_derived_signal_error() -> None:
    source = Signal(1)
    derived = Signal.derive(lambda: source.get() * 2, source)

    with pytest.raises(ValueError, match="cannot batch update derived signal"):
        with derived.batch_update():
            pass


def test_batch_update_multiple_dependents() -> None:
    base = Signal(5)
    doubled = Signal.derive(lambda: base.get() * 2, base)
    tripled = Signal.derive(lambda: base.get() * 3, base)

    with base.batch_update():
        base.set(10)

    assert doubled.get() == 20
    assert tripled.get() == 30


def test_signal_with_none() -> None:
    signal = Signal(None)
    assert signal.get() is None

    signal.set(42)  # pyright: ignore
    assert signal.get() == 42

    signal.set(None)
    assert signal.get() is None


def test_wait_on_none_value() -> None:
    signal = Signal(42)

    def setter():
        time.sleep(0.1)
        signal.set(None)  # pyright: ignore

    thread = threading.Thread(target=setter)
    thread.start()

    result = signal.wait_value(None, timeout=1.0)  # pyright: ignore
    assert result is True

    thread.join()


def test_complex_predicate() -> None:
    signal = Signal([])

    def setter():
        time.sleep(0.1)
        signal.set([1, 2, 3, 4, 5])

    thread = threading.Thread(target=setter)
    thread.start()

    result = signal.wait_until(lambda x: len(x) > 3 and sum(x) > 10, timeout=1.0)
    assert result is True

    thread.join()


def test_immediate_notify_on_set() -> None:
    signal = Signal(0)
    start_time = time.time()

    def setter():
        time.sleep(0.05)
        signal.set(100)

    thread = threading.Thread(target=setter)
    thread.start()

    result = signal.wait_until(lambda x: x > 50, timeout=5.0)
    elapsed = time.time() - start_time

    assert result is True
    assert elapsed < 1.0

    thread.join()


def test_signal_with_mutable_object() -> None:
    signal = Signal([1, 2, 3])

    lst = signal.get()
    lst.append(4)

    assert signal.get() == [1, 2, 3, 4]


def test_zero_timeout() -> None:
    signal = Signal(0)
    result = signal.wait_until(lambda x: x > 100, timeout=0)
    assert result is False


def test_derived_with_exception_in_derive() -> None:
    source = Signal(0)

    def derive():
        if source.get() == 0:
            raise ValueError("cannot derive from zero")
        return source.get() * 2

    with pytest.raises(ValueError, match="cannot derive from zero"):
        Signal.derive(derive, source)


def test_self_referential_derived_chain() -> None:
    base = Signal(1)
    level1 = Signal.derive(lambda: base.get() + 1, base)
    level2 = Signal.derive(lambda: level1.get() + 1, level1)
    level3 = Signal.derive(lambda: level2.get() + 1, level2)

    assert level3.get() == 4

    base.set(10)
    assert level1.get() == 11
    assert level2.get() == 12
    assert level3.get() == 13


def test_counter_with_threshold() -> None:
    counter = Signal(0)
    threshold_reached = []

    def monitor():
        counter.wait_until(lambda x: x >= 10, timeout=2.0)
        threshold_reached.append(True)

    thread = threading.Thread(target=monitor)
    thread.start()

    for i in range(15):
        counter.update(lambda x: x + 1)
        time.sleep(0.01)

    thread.join()
    assert len(threshold_reached) == 1
    assert counter.get() >= 10


def test_status_machine() -> None:
    status = Signal("idle")

    def worker():
        status.set("working")
        time.sleep(0.1)
        status.set("done")

    thread = threading.Thread(target=worker)
    thread.start()

    status.wait_value("working", timeout=1.0)
    assert status.get() == "working"

    status.wait_value("done", timeout=1.0)
    assert status.get() == "done"

    thread.join()


def test_derived_derived_metrics() -> None:
    total_sales = Signal(1000)
    cost = Signal(600)

    profit = Signal.derive(lambda: total_sales.get() - cost.get(), total_sales, cost)

    profit_margin = Signal.derive(lambda: (profit.get() / total_sales.get()) * 100 if total_sales.get() > 0 else 0, profit, total_sales)

    assert profit.get() == 400
    assert profit_margin.get() == 40.0

    total_sales.set(2000)
    assert profit.get() == 1400
    assert profit_margin.get() == 70.0

    cost.set(1000)
    assert profit.get() == 1000
    assert profit_margin.get() == 50.0


def test_producer_consumer() -> None:
    queue_size = Signal(0)
    max_size = 5
    items_produced = []
    items_consumed = []

    def producer():
        for i in range(10):
            queue_size.wait_until(lambda x: x < max_size, timeout=2.0)
            queue_size.update(lambda x: x + 1)
            items_produced.append(i)
            time.sleep(0.01)

    def consumer():
        for _ in range(10):
            queue_size.wait_until(lambda x: x > 0, timeout=2.0)
            queue_size.update(lambda x: x - 1)
            items_consumed.append(True)
            time.sleep(0.02)

    prod_thread = threading.Thread(target=producer)
    cons_thread = threading.Thread(target=consumer)

    prod_thread.start()
    cons_thread.start()

    prod_thread.join()
    cons_thread.join()

    assert len(items_produced) == 10
    assert len(items_consumed) == 10
    assert queue_size.get() == 0
