"""Cross-platform advisory file locks released automatically when the owning process exits."""
import json
import os
import sys
import time
from pathlib import Path


class FileLock:
    def __init__(self, path, label):
        self.path = Path(path)
        self.label = label
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"\0")
            self.handle.flush()

        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.seek(1)
            owner = self.handle.read().decode("utf-8", errors="replace").strip()
            self.handle.close()
            self.handle = None
            raise SystemExit(f"Another {self.label} is active ({owner or 'owner metadata unavailable'}).")

        self.handle.seek(1)
        self.handle.truncate()
        metadata = {
            "pid": os.getpid(),
            "command": " ".join(sys.argv),
            "acquired_epoch": time.time(),
        }
        self.handle.write(json.dumps(metadata).encode("utf-8"))
        self.handle.flush()
        return self

    def release(self):
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None
