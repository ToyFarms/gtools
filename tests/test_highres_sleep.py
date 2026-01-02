import time
import pytest

from gtools.core.highres_sleep import sleep_ns

DURATIONS_NS = [
    1,
    100,
    1_000,
    10_000,
    100_000,
    1_000_000,
    10_000_000,
    100_000_000,
]
RUNS_PER_DURATION = 20
ERROR_THRESHOLD_NS = 1_000_000
MAJORITY = 80/100


def test_sleep_ns_precision() -> None:
    per_duration_results = []
    total_runs = 0
    total_successes = 0

    time.sleep(0.001)

    for dur_ns in DURATIONS_NS:
        successes = 0
        for _ in range(RUNS_PER_DURATION):
            t0 = time.perf_counter_ns()
            sleep_ns(dur_ns)
            t1 = time.perf_counter_ns()

            elapsed_ns = t1 - t0
            error_ns = abs(elapsed_ns - int(dur_ns))

            if error_ns < ERROR_THRESHOLD_NS:
                successes += 1

            total_runs += 1

        per_duration_results.append((dur_ns, successes, RUNS_PER_DURATION))
        total_successes += successes

    required = total_runs * MAJORITY
    if total_successes < required:
        per_lines = []
        for dur_ns, succ, runs in per_duration_results:
            percent = (succ * 100.0) / runs
            per_lines.append(f"{dur_ns} ns: {succ}/{runs} ({percent:.1f}%)")

        diag = (
            f"Precision requirement not met: {total_successes}/{total_runs} "
            f"runs within {ERROR_THRESHOLD_NS} ns (1 ms). Required > {MAJORITY * 100:.1f}% ({required}/{total_runs}).\n"
            "Per-duration success rates:\n  " + "\n  ".join(per_lines)
        )
        pytest.fail(diag)

    assert total_successes >= required
