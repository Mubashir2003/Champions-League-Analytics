"""Persistent store of pre-match predictions (``data/predictions.json``).

Rules
-----
* A prediction is (re)issued for a match only while it is still upcoming —
  the latest issue before kickoff is the pre-match prediction.
* Once kickoff passes the record is **frozen** and never recomputed, so the
  model can be judged later against the real result.
* When the final score is known it is attached as ``result`` alongside (not
  replacing) the model's probabilities.
"""
from __future__ import annotations

from backend.utils import clock

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from backend.config import PREDICTIONS_FILE
from backend.utils.cache import read_json, write_json_atomic

_lock = threading.Lock()


class PredictionStore:
    def __init__(self, path: Path = PREDICTIONS_FILE):
        self.path = path

    def load(self) -> Dict[str, Any]:
        data = read_json(self.path, default=None)
        if not isinstance(data, dict) or not isinstance(data.get("predictions"), dict):
            return {"season": "2026/2027", "predictions": {}}
        return data

    def save(self, data: Dict[str, Any]) -> None:
        write_json_atomic(self.path, data)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self.load()["predictions"].get(key)

    def upsert_pre_match(self, key: str, record: Dict[str, Any], kickoff_utc: Optional[str], now: Optional[datetime] = None) -> Dict[str, Any]:
        """Store/refresh a prediction unless it is already frozen. Returns the stored record."""
        now = now or clock.now_utc()
        with _lock:
            data = self.load()
            existing = data["predictions"].get(key)
            if existing and existing.get("frozen"):
                return existing
            entry = dict(record)
            entry["kickoff_utc"] = kickoff_utc
            entry["issued_at"] = now.isoformat().replace("+00:00", "Z")
            entry["frozen"] = False
            data["predictions"][key] = entry
            self.save(data)
            return entry

    def freeze_started(self, kickoff_by_key: Dict[str, Optional[str]], now: Optional[datetime] = None) -> None:
        """Freeze every stored prediction whose match has kicked off."""
        now = now or clock.now_utc()
        with _lock:
            data = self.load()
            changed = False
            for key, entry in data["predictions"].items():
                if entry.get("frozen"):
                    continue
                ko = kickoff_by_key.get(key, entry.get("kickoff_utc"))
                if ko and _parse(ko) and _parse(ko) <= now:
                    entry["frozen"] = True
                    changed = True
            if changed:
                self.save(data)

    def attach_result(self, key: str, home_goals: int, away_goals: int) -> None:
        with _lock:
            data = self.load()
            entry = data["predictions"].get(key)
            if not entry:
                return
            result = {"home": int(home_goals), "away": int(away_goals)}
            if entry.get("result") != result:
                entry["result"] = result
                entry["frozen"] = True
                self.save(data)


def _parse(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


store = PredictionStore()
