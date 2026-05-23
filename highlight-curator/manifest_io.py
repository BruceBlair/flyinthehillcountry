"""Atomic read-modify-write helpers for manifest.json.

All manifest writers should use these helpers to avoid partial-write
corruption and cross-process races.
"""

import fcntl
import json
import os
from pathlib import Path
from typing import Callable


def atomic_write_json(path: Path, data: dict) -> None:
    """Write data to path atomically via a temp file + os.replace()."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def locked_manifest_update(path: Path, modify_fn: Callable[[dict], None]) -> None:
    """Exclusive-lock path.lock, read manifest, call modify_fn, atomically write.

    Safe to call from multiple processes concurrently.
    """
    lock_path = path.with_suffix(".lock")
    with open(lock_path, "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            manifest = json.loads(path.read_text()) if path.exists() else {"entries": []}
            modify_fn(manifest)
            atomic_write_json(path, manifest)
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)
