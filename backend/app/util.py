"""Small helpers shared by the providers."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path

from .config import settings

_thread_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


@contextmanager
def file_lock(name: str):
    """Serialise a piece of work across worker processes and threads.

    Uses an advisory lock on a file in the storage folder, so the two render
    worker processes take turns (for example: one voice download, or one
    rate-limited request, at a time). Yields the lock file's path.
    """
    d = settings.storage_dir / ".locks"
    d.mkdir(parents=True, exist_ok=True)
    path: Path = d / f"{name}.lock"
    with _guard:
        tlock = _thread_locks.setdefault(name, threading.Lock())
    with tlock, open(path, "a+") as fh:
        try:
            import fcntl

            fcntl.flock(fh, fcntl.LOCK_EX)
        except (ImportError, OSError):  # no flock here: the thread lock still applies
            pass
        yield path
