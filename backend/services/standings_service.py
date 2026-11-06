"""2026/2027 Champions League league-phase table.

Source order
------------
1. **StrikerAPI ``get_standings``** (league ``ucl``, season ``2026``) — the
   provider documents a Champions League league-phase table. It is accepted
   only if every row passes integrity checks (P = W + D + L, GD = GF − GA,
   at most 36 clubs). Field names beyond those shown in the public docs are
   read through a list of candidates.
2. **Calculated** from completed 2026/27 league-phase matches using the UEFA
   league-phase ranking rules (format introduced in 2024/25, 36 clubs, 8
   matches each):

   points → goal difference → goals scored → away goals scored → wins →
   away wins → opponents' total points → opponents' goal difference →
   opponents' goals scored. (Disciplinary points and club coefficient — the
   last two criteria — are not supplied by either provider; any remaining tie
   is listed alphabetically and flagged.)

Positions 1–8 go to the round of 16, 9–24 to the knockout play-offs,
25–36 are eliminated.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from backend.config import Settings
from backend.services.normalize import as_int, pick_first
from backend.services.providers import ProviderError, StrikerAPIClient
from backend.utils.cache import FileCache
from backend.utils.teams import normalize_team_name, same_team

log = logging.getLogger("ucl.standings")

LEAGUE_PHASE_TEAMS = 36
MATCHES_PER_TEAM = 8
LEAGUE_PHASE_MATCHES = LEAGUE_PHASE_TEAMS * MATCHES_PER_TEAM // 2   # 144
# 2026/27 league phase runs September 2026 – January 2027. Qualifying rounds
# finish in August and the knockout play-offs begin in February, so this date
# window isolates league-phase matches when the provider gives no round name.
LEAGUE_PHASE_START = "2026-09-01"
LEAGUE_PHASE_END = "2027-01-31"
STRIKER_STANDINGS_TTL = 3 * 3600

ZONES = [
    (1, 8, "round_of_16"),
    (9, 24, "playoff"),
    (25, 36, "eliminated"),
]

ROW_FIELDS = {
    "name": ["display_name", "team_name", "name", "team.display_name", "team.name"],
    "played": ["played", "games_played", "gp", "p"],
    "won": ["wins", "won", "w"],
    "drawn": ["draws", "drawn", "ties", "d"],
    "lost": ["losses", "lost", "l"],
    "gf": ["goals_for", "gf", "scored", "goals_scored"],
    "ga": ["goals_against", "ga", "conceded", "goals_conceded"],
    "gd": ["goal_difference", "goal_diff", "gd"],
    "points": ["points", "pts"],
    "rank": ["rank", "position", "pos"],
}


def zone_for(position: int) -> Optional[str]:
    for lo, hi, name in ZONES:
        if lo <= position <= hi:
            return name
    return None


def is_league_phase(match: Dict[str, Any]) -> bool:
    rnd = str(match.get("round") or "").lower()
    if rnd:
        if any(w in rnd for w in ("qualif", "play-off", "playoff", "round of", "quarter", "semi", "final")):
            return False
        if "league" in rnd or "matchday" in rnd:
            return True
    d = match.get("date") or ""
    return LEAGUE_PHASE_START <= d <= LEAGUE_PHASE_END


def compute_table(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ranked table from completed league-phase matches (UEFA criteria a–h)."""
    stats: Dict[str, Dict[str, Any]] = {}
    opponents: Dict[str, List[str]] = defaultdict(list)

    def row(team: Dict[str, Any]) -> Dict[str, Any]:
        key = normalize_team_name(team["name"])
        if key not in stats:
            stats[key] = {"key": key, "club": team["name"], "logo": team.get("logo"), "team_id": team.get("id"),
                          "played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0,
                          "away_gf": 0, "away_won": 0, "points": 0}
        elif not stats[key]["logo"] and team.get("logo"):
            stats[key]["logo"] = team["logo"]
        return stats[key]

    for m in matches:
        if m.get("status") != "completed" or not m.get("score") or not is_league_phase(m):
            continue
        hs, as_ = m["score"]["home"], m["score"]["away"]
        h, a = row(m["home"]), row(m["away"])
        opponents[h["key"]].append(a["key"])
        opponents[a["key"]].append(h["key"])
        for r, gf, ga, away in ((h, hs, as_, False), (a, as_, hs, True)):
            r["played"] += 1
            r["gf"] += gf
            r["ga"] += ga
            if away:
                r["away_gf"] += gf
            if gf > ga:
                r["won"] += 1
                r["points"] += 3
                if away:
                    r["away_won"] += 1
            elif gf == ga:
                r["drawn"] += 1
                r["points"] += 1
            else:
                r["lost"] += 1

    for r in stats.values():
        r["gd"] = r["gf"] - r["ga"]
    for key, r in stats.items():
        opp = [stats[o] for o in opponents[key] if o in stats]
        r["opp_points"] = sum(o["points"] for o in opp)
        r["opp_gd"] = sum(o["gd"] for o in opp)
        r["opp_gf"] = sum(o["gf"] for o in opp)

    def sort_key(r):
        return (-r["points"], -r["gd"], -r["gf"], -r["away_gf"], -r["won"], -r["away_won"],
                -r["opp_points"], -r["opp_gd"], -r["opp_gf"], r["club"].lower())

    def criteria(r):
        return sort_key(r)[:-1]

    ordered = sorted(stats.values(), key=sort_key)
    out = []
    for i, r in enumerate(ordered, start=1):
        unresolved = any(criteria(o) == criteria(r) for o in ordered if o is not r)
        out.append({
            "position": i, "club": r["club"], "logo": r["logo"],
            "played": r["played"], "won": r["won"], "drawn": r["drawn"], "lost": r["lost"],
            "gf": r["gf"], "ga": r["ga"], "gd": r["gd"], "points": r["points"],
            "zone": zone_for(i), "tie_unresolved": unresolved,
        })
    return out


def parse_striker_table(data: Any) -> Optional[List[Dict[str, Any]]]:
    rows = None
    if isinstance(data, dict):
        rows = data.get("standings") or data.get("table") or data.get("rows")
    elif isinstance(data, list):
        rows = data
    if not isinstance(rows, list) or not rows:
        return None
    groups = {str(r.get("group_name") or "") for r in rows if isinstance(r, dict)}
    if len(groups) > 1:
        league_groups = [g for g in groups if "league" in g.lower()]
        if len(league_groups) != 1:
            return None  # not a single league-phase table
        rows = [r for r in rows if str(r.get("group_name") or "") == league_groups[0]]
    parsed = []
    for r in rows:
        if not isinstance(r, dict):
            return None
        vals = {f: (pick_first(r, ROW_FIELDS[f], want=str) if f == "name" else as_int(pick_first(r, ROW_FIELDS[f])))
                for f in ROW_FIELDS}
        if vals["gd"] is None and vals["gf"] is not None and vals["ga"] is not None:
            vals["gd"] = vals["gf"] - vals["ga"]
        required = ("name", "played", "won", "drawn", "lost", "gf", "ga", "gd", "points")
        if any(vals[f] is None for f in required):
            return None
        if vals["played"] != vals["won"] + vals["drawn"] + vals["lost"] or vals["gd"] != vals["gf"] - vals["ga"]:
            return None
        parsed.append(vals)
    if len(parsed) > LEAGUE_PHASE_TEAMS:
        return None
    parsed.sort(key=lambda v: (v["rank"] if v["rank"] is not None else 999))
    return [{
        "position": i, "club": v["name"], "logo": None,
        "played": v["played"], "won": v["won"], "drawn": v["drawn"], "lost": v["lost"],
        "gf": v["gf"], "ga": v["ga"], "gd": v["gd"], "points": v["points"],
        "zone": zone_for(i), "tie_unresolved": False,
    } for i, v in enumerate(parsed, start=1)]


class StandingsService:
    def __init__(self, settings: Settings, striker: StrikerAPIClient, cache: FileCache):
        self.settings = settings
        self.striker = striker
        self.cache = cache

    def _striker_table(self) -> Optional[List[Dict[str, Any]]]:
        if not self.striker.configured:
            return None
        cached = self.cache.get("striker", "standings", STRIKER_STANDINGS_TTL)
        if cached is None:
            try:
                data = self.striker.call("get_standings", {"league": "ucl", "season": self.settings.striker_season})
            except ProviderError as exc:
                log.warning("StrikerAPI standings unavailable: %s", exc.message)
                stale = self.cache.get("striker", "standings", None)
                data = stale.get("payload") if isinstance(stale, dict) else None
            else:
                self.cache.set("striker", "standings", {"payload": data})
        else:
            data = cached.get("payload") if isinstance(cached, dict) else None
        if data is None:
            return None
        # Reject anything labelled with another season.
        season_text = str(pick_first(data, ["season", "season_name"]) or "") if isinstance(data, dict) else ""
        if season_text and "2026" not in season_text:
            return None
        return parse_striker_table(data)

    def build(self, matches: List[Dict[str, Any]]) -> Dict[str, Any]:
        computed = compute_table(matches)
        league_matches = [m for m in matches if is_league_phase(m)]
        played = sum(1 for m in league_matches if m.get("status") == "completed" and m.get("score"))

        official = self._striker_table()
        rows, method = computed, "calculated"
        if official:
            logos = {normalize_team_name(r["club"]): r["logo"] for r in computed if r.get("logo")}
            for r in official:
                r["logo"] = logos.get(normalize_team_name(r["club"]))
                if not r["logo"]:
                    for m in matches:
                        for side in ("home", "away"):
                            if same_team(m[side]["name"], r["club"]) and m[side].get("logo"):
                                r["logo"] = m[side]["logo"]
                                break
                        if r["logo"]:
                            break
            official_played = sum(r["played"] for r in official) // 2
            # Use the provider table only if it is at least as up to date as our verified results.
            if official_played >= played:
                rows, method, played = official, "provider", official_played

        return {
            "season": self.settings.season_label,
            "phase": "League phase",
            "rows": rows,
            "matches_played": played,
            "matches_total": LEAGUE_PHASE_MATCHES,
            "complete": played >= LEAGUE_PHASE_MATCHES,
            "method": method,
            "zones": [{"from": lo, "to": hi, "zone": z} for lo, hi, z in ZONES],
        }
