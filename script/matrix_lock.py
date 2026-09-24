"""Lock the whole matrix runner so only one runner can control the cluster."""
import atexit
import os
import sys
from pathlib import Path

LOCK_PATH = Path(__file__).resolve().parent.parent / ".matrix.lock"
_acquired = False


def _release():
    global _acquired
    if _acquired:
        LOCK_PATH.unlink(missing_ok=True)
        _acquired = False


def acquire():
    global _acquired
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        holder = LOCK_PATH.read_text(encoding="utf-8").strip()
        raise SystemExit(f"Another matrix runner is active ({holder}); exiting this duplicate runner.")
    os.write(fd, f"pid={os.getpid()} cmd={' '.join(sys.argv)}".encode("utf-8"))
    os.close(fd)
    _acquired = True
    atexit.register(_release)


def release():
    _release()
