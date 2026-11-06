"""Fixtures, results and predictions for the 2026/2027 Champions League only."""
from __future__ import annotations

from backend.utils import clock

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.config import Settings
from backend.predictions.elo_poisson import CompletedMatch, build_model
from backend.predictions.store import PredictionStore
from backend.services.normalize import (
    dedupe,
    in_season_window,
    normalize_pitch_match,
    normalize_striker_game,
    reconcile,
)
from backend.services.providers import PitchAPIClient, ProviderError, ProviderNotConfigured, StrikerAPIClient
from backend.utils.cache import FileCache
from backend.utils.teams import home_timezone_for, normalize_team_name
from backend.utils.timezones import kickoff_block, parse_utc

log = logging.getLogger("ucl.matches")

EXCLUDE_LEAGUE_WORDS = ("women", "youth", "u19", "u-19", "u21", "afc", "caf", "concacaf", "ofc", "asian", "african")
LEAGUE_CACHE_TTL = 7 * 24 * 3600
STRIKER_STATE_KEY = "state"


class DataUnavailable(Exception):
    """No 2026/27 fixture data could be obtained (provider down or not configured)."""

    def __init__(self, reason: str, status_code: int = 503):
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class MatchService:
    def __init__(self, settings: Settings, pitch: PitchAPIClient, striker: StrikerAPIClient,
                 cache: FileCache, predictions: PredictionStore):
        self.settings = settings
        self.pitch = pitch
        self.striker = striker
        self.cache = cache
        self.predictions = predictions
        self._lock = threading.Lock()
        self.last_error: Optional[str] = None

    # ── league resolution ───────────────────────────────────────────────
    def resolve_league_id(self, force: bool = False) -> str:
        if self.settings.pitchapi_ucl_league_id:
            return self.settings.pitchapi_ucl_league_id
        if not force:
            cached = self.cache.get("pitchapi", "ucl_league", LEAGUE_CACHE_TTL)
            if isinstance(cached, dict) and cached.get("id"):
                return cached["id"]
        data = self.pitch.get("/leagues")
        leagues = data.get("leagues", []) if isinstance(data, dict) else []
        candidates = []
        for lg in leagues:
            name = str(lg.get("name") or "").lower()
            if "champions league" not in name or any(w in name for w in EXCLUDE_LEAGUE_WORDS):
                continue
            seasons = lg.get("seasons") or []
            score = (2 if self.settings.season_label in seasons else 0) + (1 if name.strip() in ("champions league", "uefa champions league") else 0)
            candidates.append((score, lg))
        if not candidates:
            raise DataUnavailable("The Champions League is not listed by the fixtures provider.", 503)
        candidates.sort(key=lambda c: c[0], reverse=True)
        chosen = candidates[0][1]
        self.cache.set("pitchapi", "ucl_league", {"id": chosen["id"], "name": chosen.get("name"), "seasons": chosen.get("seasons")})
        return chosen["id"]

    # ── fixtures ────────────────────────────────────────────────────────
    def _fetch_fixtures_raw(self, force: bool) -> List[Dict[str, Any]]:
        key = "ucl_" + self.settings.season_label.replace("/", "_")
        if not force:
            cached = self.cache.get("fixtures", key, self.settings.fixtures_ttl_seconds)
            if isinstance(cached, list):
                return cached
        league_id = self.resolve_league_id()
        try:
            data = self.pitch.get(f"/leagues/{league_id}/matches",
                                  {"season": self.settings.season_label, "status": "all"})
        except ProviderError as exc:
            # INVALID_PARAMETER means the provider has no 2026/2027 season for this league.
            if exc.status == 400:
                self.cache.set("fixtures", key, [])
                return []
            stale = self.cache.get("fixtures", key, None)
            if isinstance(stale, list):
                log.warning("PitchAPI failed (%s); serving last cached 2026/27 fixtures", exc.message)
                self.last_error = exc.message
                return stale
            raise
        if not isinstance(data, dict):
            return []
        league = data.get("league") or {}
        # Never accept another season's matches as a fallback.
        if league.get("season") and league.get("season") != self.settings.season_label:
            log.warning("PitchAPI returned season %s instead of %s; ignoring", league.get("season"), self.settings.season_label)
            self.cache.set("fixtures", key, [])
            return []
        raw = [m for m in (data.get("matches") or []) if isinstance(m, dict)]
        self.cache.set("fixtures", key, raw)
        self.last_error = None
        return raw

    def get_matches(self, force: bool = False, auto_results: bool = True) -> List[Dict[str, Any]]:
        if not self.pitch.configured:
            raise DataUnavailable("Fixture data is not configured yet.", 503)
        with self._lock:
            try:
                raw = self._fetch_fixtures_raw(force)
            except ProviderNotConfigured as exc:
                raise DataUnavailable(exc.message, 503) from exc
            except ProviderError as exc:
                self.last_error = exc.message
                raise DataUnavailable("Fixture data is temporarily unavailable.", 502) from exc

            now = clock.now_utc()
            matches = [normalize_pitch_match(r, self.settings.season_label, now) for r in raw]
            matches = [m for m in matches if m and in_season_window(m, self.settings.season_start, self.settings.season_end)]
            matches = dedupe(matches)

            if auto_results:
                self._maybe_refresh_results(matches, force=False)
            reconcile(matches, self._stored_striker_results())

            for m in matches:
                tz = home_timezone_for(m["home"]["name"])
                m["kickoff"] = kickoff_block(parse_utc(m.get("kickoff_utc")), tz)
            self._attach_predictions(matches, now)
            matches.sort(key=lambda m: (m.get("kickoff_utc") or m.get("date") or ""))
            return matches

    # ── StrikerAPI results ──────────────────────────────────────────────
    def _stored_striker_results(self) -> List[Dict[str, Any]]:
        stored = self.cache.get("striker", "final_results", None)
        return list(stored.values()) if isinstance(stored, dict) else []

    def _striker_state(self) -> Dict[str, Any]:
        state = self.cache.get("striker", STRIKER_STATE_KEY, None)
        return state if isinstance(state, dict) else {}

    def _needs_results(self, matches: List[Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
        delay = timedelta(minutes=self.settings.striker_result_delay_minutes)
        stored = self._stored_striker_results()
        pending = []
        for m in matches:
            ko = parse_utc(m.get("kickoff_utc"))
            if m["status"] in ("upcoming", "cancelled", "postponed") or ko is None or ko + delay > now:
                continue
            probe = [dict(m, score=m.get("score"))]
            if reconcile(probe, stored) == 0:
                pending.append(m)
        return pending

    def _maybe_refresh_results(self, matches: List[Dict[str, Any]], force: bool) -> Dict[str, Any]:
        if not self.striker.configured:
            return {"called": False, "reason": "not_configured"}
        now = clock.now_utc()
        state = self._striker_state()
        last = state.get("last_call_epoch")
        min_gap = self.settings.striker_min_refresh_minutes * 60
        hard_floor = 5 * 60  # even a forced refresh never calls more often than this
        if last and time.time() - last < (hard_floor if force else min_gap):
            return {"called": False, "reason": "rate_limited_locally",
                    "next_allowed_in_seconds": int((hard_floor if force else min_gap) - (time.time() - last))}
        pending = self._needs_results(matches, now)
        if not pending:
            return {"called": False, "reason": "nothing_pending"}
        earliest = min(m["date"] for m in pending if m.get("date"))
        frm = (datetime.fromisoformat(earliest).date() - timedelta(days=1)).isoformat()
        to = now.date().isoformat()
        return self._fetch_striker_results(frm, to)

    def _fetch_striker_results(self, frm: str, to: str, max_pages: int = 5) -> Dict[str, Any]:
        stored = self.cache.get("striker", "final_results", None)
        stored = stored if isinstance(stored, dict) else {}
        offset, pages, added = None, 0, 0
        state = self._striker_state()
        try:
            while pages < max_pages:
                data = self.striker.call("list_games", {
                    "league": "ucl",
                    "season": self.settings.striker_season,
                    "status": "final",
                    "from": frm,
                    "to": to,
                    "limit": 100,
                    "offset": offset,
                })
                pages += 1
                games = data.get("games", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                for g in games:
                    norm = normalize_striker_game(g)
                    if norm and self.settings.season_start <= norm["date"] <= self.settings.season_end:
                        if norm["id"] not in stored:
                            added += 1
                        stored[norm["id"]] = norm
                offset = data.get("next_offset") if isinstance(data, dict) else None
                if not offset:
                    break
        except ProviderError as exc:
            state.update({"last_call_epoch": time.time(), "last_error": exc.message, "last_status": exc.status})
            self.cache.set("striker", STRIKER_STATE_KEY, state)
            log.warning("StrikerAPI result check failed: %s", exc.message)
            return {"called": True, "ok": False, "error": exc.message}
        self.cache.set("striker", "final_results", stored)
        state.update({
            "last_call_epoch": time.time(),
            "last_error": None,
            "last_status": 200,
            "credits_remaining": self.striker.last_credits_remaining,
            "pages": pages,
        })
        self.cache.set("striker", STRIKER_STATE_KEY, state)
        return {"called": True, "ok": True, "pages": pages, "new_results": added,
                "credits_remaining": self.striker.last_credits_remaining}

    def refresh_results(self) -> Dict[str, Any]:
        if not self.striker.configured:
            raise DataUnavailable("Result verification is not configured.", 503)
        matches = self.get_matches(auto_results=False)
        with self._lock:
            outcome = self._maybe_refresh_results(matches, force=True)
        return outcome

    # ── predictions ─────────────────────────────────────────────────────
    @staticmethod
    def completed_for_model(matches: List[Dict[str, Any]]) -> List[CompletedMatch]:
        out = []
        for m in matches:
            if m["status"] == "completed" and m.get("score"):
                out.append(CompletedMatch(
                    home=normalize_team_name(m["home"]["name"]),
                    away=normalize_team_name(m["away"]["name"]),
                    home_goals=m["score"]["home"],
                    away_goals=m["score"]["away"],
                    kickoff=m.get("kickoff_utc") or m.get("date") or "",
                ))
        return out

    def _attach_predictions(self, matches: List[Dict[str, Any]], now: datetime) -> None:
        completed = self.completed_for_model(matches)
        model = build_model(completed)  # all results known so far; only upcoming matches are predicted
        self.predictions.freeze_started({m["key"]: m.get("kickoff_utc") for m in matches}, now)
        for m in matches:
            if m["status"] == "upcoming" and m.get("kickoff_utc"):
                pred = model.predict(normalize_team_name(m["home"]["name"]), normalize_team_name(m["away"]["name"]))
                record = pred.as_dict()
                record.update({"home": m["home"]["name"], "away": m["away"]["name"], "matches_in_model": model.matches_used})
                stored = self.predictions.upsert_pre_match(m["key"], record, m.get("kickoff_utc"), now)
                m["prediction"] = {"percent": stored["percent"], "type": "model_estimate"}
            else:
                if m["status"] == "completed" and m.get("score"):
                    self.predictions.attach_result(m["key"], m["score"]["home"], m["score"]["away"])
                stored = self.predictions.get(m["key"])
                m["prediction"] = ({"percent": stored["percent"], "type": "pre_match_model_estimate"}
                                   if stored and stored.get("frozen") else None)

    # ── lookups ────────────────────────────────────────────────────────
    def get_match(self, key: str) -> Optional[Dict[str, Any]]:
        for m in self.get_matches():
            if m["key"] == key:
                return m
        return None
