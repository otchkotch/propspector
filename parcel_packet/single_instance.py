from __future__ import annotations

import os
from pathlib import Path

from .settings import APP_DIR


LOCK_PATH = APP_DIR / "app.lock"


def acquire_single_instance_lock() -> int | None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists() and not _lock_process_is_running():
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    os.write(fd, str(os.getpid()).encode("ascii"))
    return fd


def _lock_process_is_running() -> bool:
    try:
        pid = int(LOCK_PATH.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    if pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def release_single_instance_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass
