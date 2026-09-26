"""Lock the whole matrix runner so only one runner can control the cluster."""
import atexit
from pathlib import Path

from file_lock import FileLock

LOCK_PATH = Path(__file__).resolve().parent.parent / ".matrix.lock"
_lock = FileLock(LOCK_PATH, "matrix runner")


def acquire():
    _lock.acquire()
    atexit.register(_lock.release)


def release():
    _lock.release()
