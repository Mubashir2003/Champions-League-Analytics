"""Mocked PitchAPI / StrikerAPI HTTP transports for tests.

Payload shapes mirror the official SDK models (pitchapi 0.1.6, strikerapi 0.1.4).
These are TEST FIXTURES only — the application never loads them.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

LOGO = "https://img.test.invalid/teams/{}.png"
LEAGUE_ID = "l_ucl"

TEAMS = {
    "t_rma": "Real Madrid",
    "t_bay": "Bayern München",
    "t_ars": "Arsenal",
    "t_int": "Internazionale",
    "t_psg": "Paris Saint-Germain",
    "t_ben": "Benfica",
    "t_fen": "Fenerbahçe",
}


def team(tid: str) -> Dict[str, Any]:
    return {"id": tid, "name": TEAMS[tid], "image_url": LOGO.format(tid)}


def match(mid, home, away, time_utc, status, sh=None, sa=None):
    return {"id": mid, "home_team": team(home), "away_team": team(away), "date": time_utc[:10],
            "time_utc": time_utc, "status": status, "score_home": sh, "score_away": sa}


COMPLETED = [
    match("m_q1", "t_ben", "t_fen", "2026-08-20T19:00:00Z", "played", 1, 0),      # qualifying (not league phase)
    match("m_1", "t_rma", "t_ben", "2026-09-16T19:00:00Z", "played", 2, 1),
    match("m_2", "t_ars", "t_int", "2026-09-17T19:00:00Z", "played", 1, 1),
    match("m_3", "t_psg", "t_bay", "2026-09-17T19:00:00Z", "played", 3, 0),
    match("m_4", "t_ben", "t_ars", "2026-09-30T19:00:00Z", "played", 0, 2),
    match("m_5", "t_bay", "t_rma", "2026-10-01T19:00:00Z", "played", 2, 2),
    match("m_6", "t_int", "t_psg", "2026-10-21T19:00:00Z", "played", 1, 0),
    match("m_7", "t_rma", "t_ars", "2026-10-22T19:00:00Z", "played", 3, 1),
]
# Played but PitchAPI has no score yet — StrikerAPI supplies the final result.
AWAITING = [match("m_8", "t_bay", "t_ben", "2026-11-04T20:00:00Z", "played")]
UPCOMING = [
    match("m_u1", "t_ars", "t_bay", "2026-11-25T20:00:00Z", "upcoming"),
    match("m_u2", "t_ben", "t_int", "2026-11-26T17:45:00Z", "upcoming"),
    match("m_u3", "t_psg", "t_rma", "2026-12-09T20:00:00Z", "upcoming"),
]
OUT_OF_SEASON = [match("m_old", "t_psg", "t_int", "2026-05-30T19:00:00Z", "played", 5, 0)]
DUPLICATE = [dict(COMPLETED[1])]

ALL_MATCHES = COMPLETED + AWAITING + UPCOMING + OUT_OF_SEASON + DUPLICATE

STRIKER_GAMES = [
    {"game_id": "s_901", "date": "2026-11-04T20:00:00Z", "status": "final",
     "home_team": {"display_name": "FC Bayern Munich"}, "away_team": {"display_name": "SL Benfica"},
     "home_score": 1, "away_score": 0},
    {"game_id": "s_902", "date": "2026-10-22T19:00:00Z", "status": "final",
     "home_team": {"display_name": "Real Madrid"}, "away_team": {"display_name": "Arsenal"},
     "home_score": 3, "away_score": 1},
]


def players_for(tid: str) -> List[Dict[str, Any]]:
    return [{"id": f"p_{tid}_{i}", "name": f"{TEAMS[tid]} Player {i}",
             "image_url": f"https://img.test.invalid/players/{tid}_{i}.png", "position_id": i} for i in range(1, 9)]


def _entry(key, value, typ="integer"):
    return {"key": key, "stat": {"type": typ, "value": value}}


def player_rows(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for side in ("home_team", "away_team"):
        tid = m[side]["id"]
        for i, p in enumerate(players_for(tid), start=1):
            minutes = 0 if i == 8 else (90 if i <= 6 else 25)  # player 8 is an unused sub
            rows.append({
                "player": {"id": p["id"], "name": p["name"], "image_url": p["image_url"], "position_id": i},
                "team_id": tid,
                "stats": [
                    {"key": "top_stats", "title": "Top stats", "stats": {
                        "Minutes played": _entry("minutes_played", minutes),
                        "Goals": _entry("goals", 1 if (i == 1 and minutes) else 0),
                    }},
                    {"key": "defense", "title": "Defense", "stats": {
                        "Recoveries": _entry("recoveries", i % 4),
                    }},
                ],
            })
    return rows


def advanced_players(m: Dict[str, Any]) -> Dict[str, Any]:
    out = []
    for side in ("home_team", "away_team"):
        tid = m[side]["id"]
        for i, p in enumerate(players_for(tid), start=1):
            if i == 8:
                continue
            out.append({
                "player": {"id": p["id"], "name": p["name"], "shirt_number": i},
                "team_id": tid,
                "minutes_played": 90 if i <= 6 else 25,
                "passing": {"key_passes": i % 3, "assists": 1 if i == 2 else 0},
                "carrying": {"take_ons_won": i % 2},
                "defending": {"tackles": (i + 1) % 4},
                "goalkeeping": {"claims": 1} if i == 6 else None,
            })
    return {"match_id": m["id"], "sorted_by": "actions", "players": out}


def shots(m: Dict[str, Any]) -> Dict[str, Any]:
    out = []
    for side in ("home_team", "away_team"):
        tid = m[side]["id"]
        for i in (1, 2, 3):
            out.append({"id": f"s_{m['id']}_{tid}_{i}", "player": {"id": f"p_{tid}_{i}", "name": "x"},
                        "team_id": tid, "x": 90, "y": 30, "expected_goals": 0.1 * i,
                        "is_on_target": True, "is_inside_box": True, "shot_type": "RightFoot",
                        "situation": "RegularPlay", "minute": 10 * i, "event_type": "Miss"})
    return {"match_id": m["id"], "periods": [{"period": "FirstHalf", "shots": out}]}


def lineups(m: Dict[str, Any]) -> Dict[str, Any]:
    def side(tid, formation, coach):
        return {"formation": formation, "confirmed": True, "coach": {"name": coach}, "starters": [], "subs": []}
    return {"match_id": m["id"], "home_team": m["home_team"], "away_team": m["away_team"],
            "home": side(m["home_team"]["id"], "4-3-3", f"Coach of {m['home_team']['name']}"),
            "away": side(m["away_team"]["id"], "4-2-3-1", f"Coach of {m['away_team']['name']}")}


def stats(m: Dict[str, Any]) -> Dict[str, Any]:
    return {"match_id": m["id"], "home_team": m["home_team"], "away_team": m["away_team"], "periods": [
        {"period": "All", "groups": [{"group_name": "Top stats", "items": [
            {"title": "Ball possession", "key": "BallPossesion", "home": "55", "away": "45", "format_type": "integer"},
            {"title": "Total shots", "key": "total_shots", "home": "12", "away": "9", "format_type": "integer"},
        ]}]}]}


def summary(m: Dict[str, Any]) -> Dict[str, Any]:
    return {**m, "league": {"id": LEAGUE_ID, "name": "Champions League"}, "season": "2026/2027",
            "round_name": "League phase", "referee": "Some Referee", "stadium": "Some Stadium"}


def _ok(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"data": data})


def _err(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message}})


class PitchMock:
    def __init__(self, season: str = "2026/2027", matches: Optional[List[Dict[str, Any]]] = None, fail: bool = False):
        self.season = season
        self.matches = ALL_MATCHES if matches is None else matches
        self.fail = fail
        self.calls: List[str] = []
        self.by_id = {m["id"]: m for m in self.matches}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(str(request.url))
        assert request.headers.get("X-API-KEY") == "pk_test_key"
        if self.fail:
            return _err(503, "SERVICE_UNAVAILABLE", "down")
        if path == "/v1/leagues":
            return _ok({"leagues": [
                {"id": "l_women", "name": "UEFA Women's Champions League", "country_code": "EU", "is_free": True, "seasons": ["2026/2027"]},
                {"id": LEAGUE_ID, "name": "Champions League", "country_code": "EU", "is_free": True, "seasons": ["2025/2026", "2026/2027"]},
            ]})
        if path == f"/v1/leagues/{LEAGUE_ID}/matches":
            assert request.url.params.get("season") == "2026/2027"
            assert request.url.params.get("status") == "all"
            return _ok({"league": {"id": LEAGUE_ID, "name": "Champions League", "season": self.season}, "matches": self.matches})
        parts = path.split("/")
        if len(parts) >= 4 and parts[2] == "matches":
            m = self.by_id.get(parts[3])
            if not m:
                return _err(404, "RESOURCE_NOT_FOUND", "no match")
            sub = "/".join(parts[4:])
            played = m["status"] == "played" and m["score_home"] is not None
            if sub == "":
                return _ok(summary(m))
            if not played:
                return _err(404, "RESOURCE_NOT_FOUND", "not played")
            if sub == "players":
                return _ok(player_rows(m))
            if sub == "advanced/players":
                return _ok(advanced_players(m))
            if sub == "shots":
                return _ok(shots(m))
            if sub == "lineups":
                return _ok(lineups(m))
            if sub == "stats":
                return _ok(stats(m))
        return _err(404, "RESOURCE_NOT_FOUND", "unknown route")


class StrikerMock:
    def __init__(self, games: Optional[List[Dict[str, Any]]] = None, standings: Any = None, status: int = 200):
        self.games = STRIKER_GAMES if games is None else games
        self.standings = standings
        self.status = status
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers.get("x-api-key") == "sk_test_key"
        body = json.loads(request.content or b"{}")
        tool = request.url.path.rsplit("/", 1)[-1]
        self.calls.append({"tool": tool, **body})
        headers = {"X-Credits-Used": "2", "X-Credits-Remaining": "480"}
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "out of credits"}, headers=headers)
        if tool == "list_games":
            assert body.get("league") == "ucl" and body.get("season") == 2026 and body.get("status") == "final"
            return httpx.Response(200, json={"data": {"count": len(self.games), "games": self.games}}, headers=headers)
        if tool == "get_standings":
            if self.standings is None:
                return httpx.Response(404, json={"error": "no table"}, headers=headers)
            return httpx.Response(200, json={"data": self.standings}, headers=headers)
        return httpx.Response(404, json={"error": "unknown tool"})
