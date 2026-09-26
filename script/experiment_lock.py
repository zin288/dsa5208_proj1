"""Prevent concurrent workloads or fault injectors from controlling one cluster."""
from contextlib import contextmanager
from pathlib import Path

from file_lock import FileLock

LOCK_PATH = Path(__file__).resolve().parent.parent / ".experiment.lock"


@contextmanager
def experiment_lock():
    lock = FileLock(LOCK_PATH, "experiment")
    lock.acquire()
    try:
        yield
    finally:
        lock.release()
