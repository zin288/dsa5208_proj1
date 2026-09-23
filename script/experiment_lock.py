"""Filesystem lock preventing two workload/fault-injection processes from touching the cluster
at once (concurrent runs stop/partition the same containers and deadlock each other)."""
import os
import sys
from contextlib import contextmanager
from pathlib import Path

LOCK_PATH = Path(__file__).resolve().parent.parent / ".experiment.lock"


@contextmanager
def experiment_lock():
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        held_by = LOCK_PATH.read_text(encoding="utf-8").strip()
        sys.exit(
            f"Another experiment process is already running against this cluster "
            f"(lock held by: {held_by}). Wait for it to finish or delete {LOCK_PATH} "
            f"if you're sure it's stale, then retry."
        )
    try:
        os.write(fd, f"pid={os.getpid()} cmd={' '.join(sys.argv)}".encode("utf-8"))
        os.close(fd)
        yield
    finally:
        LOCK_PATH.unlink(missing_ok=True)
