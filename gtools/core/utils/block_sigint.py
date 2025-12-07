from contextlib import contextmanager
import signal


@contextmanager
def block_sigint():
    old = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old)
