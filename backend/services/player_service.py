"""Match intelligence: team stats, manager, formation and Key Players.

Every number comes from PitchAPI post-match endpoints. A stat that a provider
did not return stays ``None`` and is hidden by the UI — nothing is estimated.

Stat sources, in order of preference
-------------------------------------
* xG and shots       — ``/matches/{id}/shots`` (typed ``expected_goals`` per shot)
* assists, key passes, successful dribbles (take-ons won), tackles, minutes
                     — ``/matches/{id}/advanced/players`` (typed fields)
* goals, recoveries, and any of the above the advanced feed lacks
                     — ``/matches/{id}/players`` stat entries, read by their stable ``key``
"""
from __future__ import annotations

from backend.utils import clock

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.services.normalize import as_float
from backend.services.providers import PitchAPIClient, ProviderError
from backend.utils.cache import FileCache
from backend.utils.teams import same_team

log = logging.getLogger("ucl.players")

STAT_KEYS = {
    "minutes": ["minutes_played"],
    "goals": ["goals"],
    "assists": ["assists", "goal_assist"],
    "xg": ["expected_goals", "xg"],
    "shots": ["total_shots", "shots"],
    "key_passes": ["chances_created", "key_passes"],
    "dribbles": ["successful_dribbles", "dribbles_succeeded", "dribbles"],
    "tackles": ["tackles_won", "tackles"],
    "recoveries": ["recoveries", "ball_recovery", "ball_recoveries"],
}
STAT_FIELDS = list(STAT_KEYS.keys())
APPEARANCES_PER_PLAYER = 3
KEY_PLAYERS_PER_TEAM = 5
TEAM_MATCHES_SCANNED = 5
FRESH_MATCH_TTL = 6 * 3600        # re-fetch post-match data for 2 days after a match
SETTLED_AFTER = timedelta(days=2)

# Weights used only to *rank* players into the top five; never shown as a stat.
RANK_WEIGHTS = {"goals": 4.0, "assists": 3.0, "xg": 3.0, "key_passes": 1.0, "shots": 0.5,
                "dribbles": 0.5, "tackles": 0.5, "recoveries": 0.25}


def _stat_value(entry: Dict[str, Any]) -> Optional[float]:
    stat = entry.get("stat") if isinstance(entry, dict) else None
    if not isinstance(stat, dict):
        return None
    return as_float(stat.get("value"))


def parse_player_rows(rows: Any) -> Dict[str, Dict[str, Any]]:
    """``/matches/{id}/players`` → {player_id: {...}} using each entry's stable ``key``."""
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        player = row.get("player") or {}
        pid = player.get("id")
        if not pid:
            continue
        found: Dict[str, float] = {}
        for group in row.get("stats") or []:
            for entry in (group.get("stats") or {}).values() if isinstance(group, dict) else []:
                key = entry.get("key") if isinstance(entry, dict) else None
                val = _stat_value(entry)
                if key and val is not None:
                    found[key] = val
        rec = {
            "player_id": pid,
            "name": player.get("name"),
            "image": player.get("image_url") if str(player.get("image_url") or "").startswith("http") else None,
            "team_id": row.get("team_id"),
            "position": None,
        }
        for field, keys in STAT_KEYS.items():
            rec[field] = next((found[k] for k in keys if k in found), None)
        out[pid] = rec
    return out


def apply_advanced(lines: Dict[str, Dict[str, Any]], data: Any) -> None:
    players = data.get("players") if isinstance(data, dict) else None
    if not isinstance(players, list):
        return
    for p in players:
        ref = p.get("player") or {}
        pid = ref.get("id")
        if not pid:
            continue
        rec = lines.setdefault(pid, {"player_id": pid, "name": ref.get("name"), "image": None,
                                     "team_id": p.get("team_id"), "position": None,
                                     **{f: None for f in STAT_FIELDS}})
        passing, carrying, defending = p.get("passing") or {}, p.get("carrying") or {}, p.get("defending") or {}
        for field, value in (
            ("minutes", p.get("minutes_played")),
            ("assists", passing.get("assists")),
            ("key_passes", passing.get("key_passes")),
            ("dribbles", carrying.get("take_ons_won")),
            ("tackles", defending.get("tackles")),
        ):
            v = as_float(value)
            if v is not None:
                rec[field] = v
        if isinstance(p.get("goalkeeping"), dict):
            rec["position"] = "Goalkeeper"


def apply_shots(lines: Dict[str, Dict[str, Any]], data: Any) -> None:
    periods = data.get("periods") if isinstance(data, dict) else None
    if not isinstance(periods, list):
        return
    totals: Dict[str, Dict[str, float]] = {}
    for period in periods:
        for shot in period.get("shots") or []:
            if shot.get("is_own_goal"):
                continue
            pid = (shot.get("player") or {}).get("id")
            if not pid:
                continue
            t = totals.setdefault(pid, {"shots": 0.0, "xg": 0.0})
            t["shots"] += 1
            t["xg"] += as_float(shot.get("expected_goals")) or 0.0
    for pid, rec in lines.items():
        if pid in totals:
            rec["shots"] = totals[pid]["shots"]
            rec["xg"] = round(totals[pid]["xg"], 2)
        elif rec.get("minutes"):
            # The shots feed is complete for the match: a player who played and is absent took no shots.
            rec["shots"] = 0.0
            rec["xg"] = 0.0


def team_xg_from_shots(data: Any, home_id: Optional[str], away_id: Optional[str]) -> Optional[Dict[str, float]]:
    periods = data.get("periods") if isinstance(data, dict) else None
    if not isinstance(periods, list):
        return None
    xg = {"home": 0.0, "away": 0.0}
    for period in periods:
        for shot in period.get("shots") or []:
            side = "home" if shot.get("team_id") == home_id else "away" if shot.get("team_id") == away_id else None
            if side:
                xg[side] += as_float(shot.get("expected_goals")) or 0.0
    return {k: round(v, 2) for k, v in xg.items()}


class PlayerService:
    def __init__(self, pitch: PitchAPIClient, cache: FileCache):
        self.pitch = pitch
        self.cache = cache

    # ── cached post-match fetches ─────────────────────────────────────────
    def _ttl_for(self, match: Dict[str, Any]) -> Optional[float]:
        ko = match.get("kickoff_utc")
        try:
            kickoff = datetime.fromisoformat(ko.replace("Z", "+00:00")) if ko else None
        except ValueError:
            kickoff = None
        if kickoff and clock.now_utc() - kickoff > SETTLED_AFTER:
            return None
        return FRESH_MATCH_TTL

    def _get_cached(self, match: Dict[str, Any], suffix: str) -> Any:
        """Fetch ``/matches/{id}{suffix}``; ``None`` on 404 / unavailable analytics."""
        mid = match["pitch_id"]
        ns = "match_" + (suffix.strip("/").replace("/", "_") or "summary")
        cached = self.cache.get(ns, mid, self._ttl_for(match))
        if cached is not None:
            return cached.get("payload")
        try:
            payload = self.pitch.get(f"/matches/{mid}{suffix}")
        except ProviderError as exc:
            if exc.status in (404, 400):
                self.cache.set(ns, mid, {"payload": None})
                return None
            log.warning("PitchAPI %s%s failed: %s", mid, suffix, exc.message)
            return None
        self.cache.set(ns, mid, {"payload": payload})
        return payload

    def player_lines(self, match: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        lines = parse_player_rows(self._get_cached(match, "/players"))
        apply_advanced(lines, self._get_cached(match, "/advanced/players"))
        apply_shots(lines, self._get_cached(match, "/shots"))
        return lines

    # ── team intelligence ────────────────────────────────────────────────
    def team_side_in(self, match: Dict[str, Any], team_name: str) -> Optional[str]:
        if same_team(match["home"]["name"], team_name):
            return "home"
        if same_team(match["away"]["name"], team_name):
            return "away"
        return None

    def recent_team_matches(self, all_matches: List[Dict[str, Any]], team_name: str,
                            up_to: Optional[str], limit: int) -> List[Dict[str, Any]]:
        pool = [m for m in all_matches
                if m["status"] == "completed" and self.team_side_in(m, team_name)
                and (up_to is None or (m.get("kickoff_utc") or "") <= up_to)]
        pool.sort(key=lambda m: m.get("kickoff_utc") or "", reverse=True)
        return pool[:limit]

    def team_intel(self, recent: List[Dict[str, Any]], team_name: str) -> Dict[str, Any]:
        """Manager and formation from the team's latest completed fixture with a confirmed lineup."""
        for m in recent:
            lineups = self._get_cached(m, "/lineups")
            side = self.team_side_in(m, team_name)
            data = lineups.get(side) if isinstance(lineups, dict) and side else None
            if not isinstance(data, dict) or data.get("confirmed") is False:
                continue
            coach = data.get("coach") or {}
            formation = data.get("formation") or None
            manager = coach.get("name") if isinstance(coach, dict) else None
            if formation or manager:
                opponent = m["away"]["name"] if side == "home" else m["home"]["name"]
                return {"manager": manager, "formation": formation, "formation_match": f"vs {opponent}"}
        return {"manager": None, "formation": None, "formation_match": None}

    # ── key players ──────────────────────────────────────────────────────
    def key_players(self, recent: List[Dict[str, Any]], team_name: str) -> List[Dict[str, Any]]:
        per_player: Dict[str, Dict[str, Any]] = {}
        for m in recent:  # newest first
            side = self.team_side_in(m, team_name)
            team_id = m[side]["id"] if side else None
            opponent = m["away"]["name"] if side == "home" else m["home"]["name"]
            score = m.get("score") or {}
            gf, ga = (score.get("home"), score.get("away")) if side == "home" else (score.get("away"), score.get("home"))
            result = None
            if gf is not None and ga is not None:
                result = {"for": gf, "against": ga, "outcome": "W" if gf > ga else "D" if gf == ga else "L"}
            for pid, line in self.player_lines(m).items():
                if team_id and line.get("team_id") and line["team_id"] != team_id:
                    continue
                if not line.get("minutes"):
                    continue  # unused substitute: not an appearance
                p = per_player.setdefault(pid, {"player_id": pid, "name": line.get("name"), "image": line.get("image"),
                                                "position": line.get("position"), "appearances": []})
                p["image"] = p["image"] or line.get("image")
                p["position"] = p["position"] or line.get("position")
                if len(p["appearances"]) < APPEARANCES_PER_PLAYER:
                    p["appearances"].append({
                        "opponent": opponent,
                        "venue": "H" if side == "home" else "A",
                        "result": result,
                        "stats": {f: (int(line[f]) if f not in ("xg",) and line.get(f) is not None else line.get(f))
                                  for f in STAT_FIELDS},
                    })
        ranked = []
        for p in per_player.values():
            totals = {f: sum((a["stats"].get(f) or 0) for a in p["appearances"]) for f in STAT_FIELDS}
            available = {f: any(a["stats"].get(f) is not None for a in p["appearances"]) for f in STAT_FIELDS}
            score = sum(RANK_WEIGHTS.get(f, 0) * totals[f] for f in RANK_WEIGHTS) + totals["minutes"] / 90.0
            for i, a in enumerate(p["appearances"], start=1):
                a["label"] = f"Appearance {i}"
            p["totals"] = {f: (round(totals[f], 2) if f == "xg" else int(totals[f])) if available[f] else None
                           for f in STAT_FIELDS}
            p["_rank"] = score
            ranked.append(p)
        ranked.sort(key=lambda p: (p["_rank"], p["totals"].get("minutes") or 0), reverse=True)
        for p in ranked:
            p.pop("_rank", None)
        return ranked[:KEY_PLAYERS_PER_TEAM]

    # ── match page ───────────────────────────────────────────────────────
    def team_stats(self, match: Dict[str, Any]) -> List[Dict[str, Any]]:
        if match["status"] != "completed":
            return []
        data = self._get_cached(match, "/stats")
        rows: List[Dict[str, Any]] = []
        periods = data.get("periods") if isinstance(data, dict) else None
        if isinstance(periods, list) and periods:
            chosen = next((p for p in periods if str(p.get("period", "")).lower() in ("all", "match", "full", "fulltime", "full_time")),
                          periods[0])
            for group in chosen.get("groups") or []:
                for item in group.get("items") or []:
                    if item.get("home") in (None, "") and item.get("away") in (None, ""):
                        continue
                    rows.append({"key": item.get("key"), "label": item.get("title"),
                                 "home": item.get("home"), "away": item.get("away"),
                                 "group": group.get("group_name")})
        seen, unique = set(), []
        for r in rows:
            ident = r["key"] or r["label"]
            if ident in seen:
                continue
            seen.add(ident)
            unique.append(r)
        if not any((r["key"] or "").lower() in ("expected_goals", "xg") for r in unique):
            xg = team_xg_from_shots(self._get_cached(match, "/shots"), match["home"]["id"], match["away"]["id"])
            if xg:
                unique.insert(0, {"key": "expected_goals", "label": "Expected goals (xG)",
                                  "home": f"{xg['home']:.2f}", "away": f"{xg['away']:.2f}", "group": "Shots"})
        return unique[:24]

    def match_detail(self, match: Dict[str, Any], all_matches: List[Dict[str, Any]]) -> Dict[str, Any]:
        reference = match.get("kickoff_utc") if match["status"] == "completed" else clock.now_utc().isoformat().replace("+00:00", "Z")
        teams = {}
        for side in ("home", "away"):
            name = match[side]["name"]
            recent = self.recent_team_matches(all_matches, name, reference, TEAM_MATCHES_SCANNED)
            teams[side] = {
                **match[side],
                "intel": self.team_intel(recent, name),
                "key_players": self.key_players(recent, name),
                "matches_considered": len(recent),
            }
        round_name = None
        if match["status"] == "completed":
            summary = self._get_cached(match, "")
            if isinstance(summary, dict):
                round_name = summary.get("round_name")
        return {"teams": teams, "team_stats": self.team_stats(match), "round": round_name}
