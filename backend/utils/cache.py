"""Tiny JSON file cache.

Each entry is stored as ``data/cache/<namespace>/<key>.json`` with the time it
was written, so a reader can decide whether it is still fresh. Writes are
atomic (temp file + replace) so a crash never leaves half a file behind.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

from backend.config import CACHE_DIR

_lock = threading.Lock()
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _path(namespace: str, key: str, root: Optional[Path] = None) -> Path:
    base = (root or CACHE_DIR) / _SAFE.sub("_", namespace)
    return base / (_SAFE.sub("_", key) + ".json")


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return default


class FileCache:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root

    def get(self, namespace: str, key: str, max_age: Optional[float] = None) -> Any:
        """Return the cached value, or ``None`` if missing or older than ``max_age`` seconds.

        ``max_age=None`` means the entry never expires (used for finished-match data).
        """
        entry = read_json(_path(namespace, key, self.root))
        if not isinstance(entry, dict) or "stored_at" not in entry:
            return None
        if max_age is not None and time.time() - float(entry["stored_at"]) > max_age:
            return None
        return entry.get("value")

    def age(self, namespace: str, key: str) -> Optional[float]:
        entry = read_json(_path(namespace, key, self.root))
        if not isinstance(entry, dict) or "stored_at" not in entry:
            return None
        return time.time() - float(entry["stored_at"])

    def set(self, namespace: str, key: str, value: Any) -> None:
        with _lock:
            write_json_atomic(_path(namespace, key, self.root), {"stored_at": time.time(), "value": value})

    def clear(self, namespace: str) -> None:
        folder = (self.root or CACHE_DIR) / _SAFE.sub("_", namespace)
        if folder.is_dir():
            for f in folder.glob("*.json"):
                try:
                    f.unlink()
                except OSError:
                    pass


cache = FileCache()
