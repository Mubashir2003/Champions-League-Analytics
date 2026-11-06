"""Convert provider payloads into one internal match shape.

Internal match::

    {
      "key": str,               # stable dashboard key (the PitchAPI match id)
      "pitch_id": str,
      "season": "2026/2027",
      "date": "YYYY-MM-DD" | None,
      "kickoff_utc": ISO str | None,
      "status": "upcoming" | "completed" | "awaiting_result" | "postponed" | "cancelled",
      "home": {"id", "name", "logo"},
      "away": {"id", "name", "logo"},
      "score": {"home": int, "away": int} | None,
      "result_verified": bool,  # True when StrikerAPI confirmed the final score (internal only)
      "striker_game_id": str | None,
    }
"""
from __future__ import annotations

from backend.utils import clock

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from backend.utils.teams import normalize_team_name, same_team
from backend.utils.timezones import parse_utc

UPCOMING_STATUSES = {"upcoming", "scheduled", "notstarted", "not_started", "ns", "fixture", "tbd", "pre"}
FINISHED_STATUSES = {
    "played", "finished", "ft", "full_time", "fulltime", "final", "ended", "aet", "pen",
    "after_penalties", "after_extra_time", "complete", "completed", "post",
}
POSTPONED_STATUSES = {"postponed", "delayed", "suspended", "interrupted"}
CANCELLED_STATUSES = {"cancelled", "canceled", "abandoned", "awarded_void"}
# A match whose kickoff is this far in the past is assumed to have finished.
MATCH_DURATION = timedelta(hours=2, minutes=30)


def as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _team(ref: Any) -> Dict[str, Any]:
    if not isinstance(ref, dict):
        return {"id": None, "name": None, "logo": None}
    logo = ref.get("image_url")
    return {
        "id": ref.get("id"),
        "name": (ref.get("name") or "").strip() or None,
        "logo": logo if isinstance(logo, str) and logo.startswith(("https://", "http://")) else None,
    }


def classify_status(raw_status: Optional[str], kickoff: Optional[datetime], has_score: bool,
                    now: Optional[datetime] = None) -> str:
    now = now or clock.now_utc()
    s = (raw_status or "").strip().lower().replace(" ", "_").replace("-", "_")
    if s in CANCELLED_STATUSES:
        return "cancelled"
    if s in POSTPONED_STATUSES:
        return "postponed"
    if s in UPCOMING_STATUSES and (kickoff is None or kickoff > now):
        return "upcoming"
    if has_score and (s in FINISHED_STATUSES or (kickoff is not None and kickoff + MATCH_DURATION <= now)):
        return "completed"
    if kickoff is not None and kickoff > now:
        return "upcoming"
    if kickoff is None and not has_score:
        return "upcoming"
    return "awaiting_result"


def normalize_pitch_match(raw: Dict[str, Any], season_label: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    home, away = _team(raw.get("home_team")), _team(raw.get("away_team"))
    if not home["name"] or not away["name"]:
        return None
    kickoff = parse_utc(raw.get("time_utc"))
    date = raw.get("date") or (kickoff.date().isoformat() if kickoff else None)
    sh, sa = as_int(raw.get("score_home")), as_int(raw.get("score_away"))
    has_score = sh is not None and sa is not None
    status = classify_status(raw.get("status"), kickoff, has_score, now)
    return {
        "key": str(raw["id"]),
        "pitch_id": str(raw["id"]),
        "season": season_label,
        "date": date,
        "kickoff_utc": kickoff.isoformat().replace("+00:00", "Z") if kickoff else None,
        "status": status,
        "home": home,
        "away": away,
        "score": {"home": sh, "away": sa} if (has_score and status == "completed") else None,
        "result_verified": False,
        "striker_game_id": None,
    }


def in_season_window(match: Dict[str, Any], start: str, end: str) -> bool:
    d = match.get("date") or (match.get("kickoff_utc") or "")[:10]
    return bool(d) and start <= d <= end


def dedupe(matches: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop duplicate fixtures: same id, or same pairing on the same date."""
    seen_ids, seen_pairs, out = set(), set(), []
    for m in matches:
        pair = (normalize_team_name(m["home"]["name"]), normalize_team_name(m["away"]["name"]), m.get("date"))
        if m["key"] in seen_ids or pair in seen_pairs:
            continue
        seen_ids.add(m["key"])
        seen_pairs.add(pair)
        out.append(m)
    return out


# ── StrikerAPI ─────────────────────────────────────────────────────────────
# StrikerAPI's public docs list the tools, arguments and credit costs, but do
# not publish the field names inside a ``list_games`` game object. The paths
# below are the candidates we accept; the first one present wins. If your live
# responses use a different name, add it here — nothing else needs to change.
STRIKER_GAME_FIELDS = {
    "id": ["game_id", "id", "event_id", "match_id"],
    "kickoff": ["start_time", "kickoff", "kickoff_utc", "date_utc", "datetime", "start", "utc_date", "date", "game_date"],
    "status": ["status", "state", "status_detail", "status.type", "status.name"],
    "home_name": ["home_team.display_name", "home_team.name", "home_team", "home.display_name", "home.name",
                  "home", "home_name", "home_display_name", "home_team_name"],
    "away_name": ["away_team.display_name", "away_team.name", "away_team", "away.display_name", "away.name",
                  "away", "away_name", "away_display_name", "away_team_name"],
    "home_score": ["home_score", "score_home", "home_goals", "score.home", "home_team.score", "home.score"],
    "away_score": ["away_score", "score_away", "away_goals", "score.away", "away_team.score", "away.score"],
}


def pick(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def pick_first(obj: Any, paths: List[str], want=None) -> Any:
    for p in paths:
        v = pick(obj, p)
        if v is None:
            continue
        if want is str and not isinstance(v, str):
            continue
        return v
    return None


def normalize_striker_game(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A StrikerAPI final result, or ``None`` if the essentials are missing."""
    if not isinstance(raw, dict):
        return None
    f = STRIKER_GAME_FIELDS
    home = pick_first(raw, f["home_name"], want=str)
    away = pick_first(raw, f["away_name"], want=str)
    hs, as_ = as_int(pick_first(raw, f["home_score"])), as_int(pick_first(raw, f["away_score"]))
    ko_raw = pick_first(raw, f["kickoff"], want=str)
    kickoff = parse_utc(ko_raw)
    date = kickoff.date().isoformat() if kickoff else (ko_raw[:10] if ko_raw and len(ko_raw) >= 10 else None)
    if not home or not away or hs is None or as_ is None or not date:
        return None
    gid = pick_first(raw, f["id"])
    return {
        "id": str(gid) if gid is not None else f"{normalize_team_name(home)}|{normalize_team_name(away)}|{date}",
        "home": home,
        "away": away,
        "home_score": hs,
        "away_score": as_,
        "date": date,
        "status": pick_first(raw, f["status"], want=str),
    }


def reconcile(matches: List[Dict[str, Any]], striker_results: Iterable[Dict[str, Any]],
              max_day_gap: int = 1) -> int:
    """Attach StrikerAPI final scores to PitchAPI matches in place.

    Matching uses normalised home/away identity and kickoff date (±``max_day_gap``
    days for UTC/local date differences) — never provider ids. Returns the
    number of matches updated.
    """
    results = list(striker_results)
    updated = 0
    for m in matches:
        if m["status"] in ("upcoming", "cancelled") or not m.get("date"):
            continue
        try:
            mdate = datetime.fromisoformat(m["date"]).date()
        except ValueError:
            continue
        for r in results:
            try:
                rdate = datetime.fromisoformat(r["date"]).date()
            except ValueError:
                continue
            if abs((rdate - mdate).days) > max_day_gap:
                continue
            if same_team(m["home"]["name"], r["home"]) and same_team(m["away"]["name"], r["away"]):
                m["score"] = {"home": r["home_score"], "away": r["away_score"]}
                m["status"] = "completed"
                m["result_verified"] = True
                m["striker_game_id"] = r["id"]
                updated += 1
                break
    return updated
