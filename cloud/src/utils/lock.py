"""
lock.py — Atomic file-based counters for cross-process upload tracking.

Provides atomic_increment and atomic_read so multiple pipeline workers
can safely share a daily upload counter without a database.
Uses file locking via fcntl (Linux/Mac) with a fallback for Windows.
"""
from __future__ import annotations
import json
import logging
import os
import time
from pathlib import Path
from typing import Union

log = logging.getLogger(__name__)

# Try fcntl (POSIX); fall back to a manual spin-lock for Windows
try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False


def _lock_file(fh, exclusive: bool = True):
    if _HAS_FCNTL:
        op = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(fh, op)


def _unlock_file(fh):
    if _HAS_FCNTL:
        fcntl.flock(fh, fcntl.LOCK_UN)


def _read_counter(path: Path) -> int:
    try:
        data = json.loads(path.read_text())
        return int(data.get("count", 0))
    except Exception:
        return 0


def atomic_increment(path: Union[str, Path], amount: int = 1) -> int:
    """
    Atomically increment the integer counter stored at `path` by `amount`.
    Creates the file if it does not exist.
    Returns the new counter value.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Spin-lock for Windows where fcntl isn't available
    lock_path = path.with_suffix(".lock")
    deadline  = time.monotonic() + 10.0  # 10s timeout

    while not _HAS_FCNTL:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                log.warning("[Lock] Spin-lock timeout on %s — proceeding anyway", path)
                break
            time.sleep(0.02)

    try:
        # Open or create the counter file
        flag = "r+b" if path.exists() else "w+b"
        with open(path, flag) as fh:
            _lock_file(fh)
            try:
                fh.seek(0)
                raw = fh.read()
                try:
                    count = int(json.loads(raw).get("count", 0)) if raw.strip() else 0
                except Exception:
                    count = 0
                count += amount
                fh.seek(0)
                fh.write(json.dumps({"count": count}).encode())
                fh.truncate()
            finally:
                _unlock_file(fh)
        return count
    except Exception as e:
        log.error("[Lock] atomic_increment failed on %s: %s", path, e)
        return 0
    finally:
        if not _HAS_FCNTL:
            try:
                lock_path.unlink(missing_ok=True)
            except Exception:
                pass


def atomic_read(path: Union[str, Path]) -> int:
    """
    Atomically read the counter at `path`.
    Returns 0 if the file does not exist or is unreadable.
    """
    path = Path(path)
    if not path.exists():
        return 0

    try:
        with open(path, "rb") as fh:
            _lock_file(fh, exclusive=False)
            try:
                raw = fh.read()
                return int(json.loads(raw).get("count", 0)) if raw.strip() else 0
            except Exception:
                return 0
            finally:
                _unlock_file(fh)
    except Exception as e:
        log.debug("[Lock] atomic_read failed on %s: %s", path, e)
        return 0


def atomic_reset(path: Union[str, Path]) -> None:
    """Reset counter to zero."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        _lock_file(fh)
        try:
            fh.write(json.dumps({"count": 0}).encode())
        finally:
            _unlock_file(fh)
