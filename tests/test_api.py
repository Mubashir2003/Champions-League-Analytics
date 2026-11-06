"""End-to-end API tests against mocked providers (no network)."""
from __future__ import annotations

from datetime import timedelta

from tests.conftest import make_settings
from tests.mock_providers import PitchMock, StrikerMock

SEASON = "2026/2027"


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["season"] == SEASON
    assert body["providers"] == {"pitchapi": True, "strikerapi": True}


def test_pages_and_assets_load(client):
    for path in ["/", "/fixtures.html", "/match-details.html", "/standings.html", "/fixtures", "/standings",
                 "/css/style.css", "/css/responsive.css", "/js/app.js", "/js/overview.js", "/js/fixtures.js",
                 "/js/match-details.js", "/js/standings.js", "/assets/images/favicon.svg"]:
        r = client.get(path)
        assert r.status_code == 200, path
    assert client.get("/no-such-page").status_code == 404


def test_only_current_season_and_no_duplicates(client):
    r = client.get("/api/matches")
    assert r.status_code == 200
    matches = r.json()["matches"]
    keys = [m["key"] for m in matches]
    assert len(keys) == len(set(keys)), "duplicate fixtures"
    assert "m_old" not in keys, "previous-season match leaked"
    for m in matches:
        assert m["season"] == SEASON
        assert "2026-06-01" <= m["date"] <= "2027-07-31"


def test_provider_season_mismatch_is_rejected(build):
    client, *_ = build(pitch=PitchMock(season="2025/2026"))
    r = client.get("/api/matches")
    assert r.status_code == 200
    assert r.json()["matches"] == [], "old season must never be used as fallback"


def test_public_payload_has_no_technical_fields(client):
    for m in client.get("/api/matches").json()["matches"]:
        assert set(m) <= {"key", "season", "date", "kickoff_utc", "kickoff", "status", "home", "away", "score", "prediction"}
    detail = client.get("/api/matches/m_1").json()
    text = str(detail).lower()
    assert "stadium" not in text and "referee" not in text
    assert "pitchapi" not in text and "strikerapi" not in text


def test_recent_completed_limit_and_order(client):
    r = client.get("/api/matches", params={"status": "completed", "limit": 5})
    data = r.json()
    assert data["count"] == 5
    kicks = [m["kickoff_utc"] for m in data["matches"]]
    assert kicks == sorted(kicks, reverse=True), "newest first"
    assert all(m["status"] == "completed" and m["score"] for m in data["matches"])


def test_striker_reconciles_missing_result(build):
    client, services, pitch, striker = build()
    matches = {m["key"]: m for m in client.get("/api/matches").json()["matches"]}
    m8 = matches["m_8"]
    assert m8["status"] == "completed"
    assert m8["score"] == {"home": 1, "away": 0}
    tools = [c["tool"] for c in striker.calls]
    assert tools.count("list_games") == 1


def test_striker_calls_are_rate_limited(build):
    client, services, pitch, striker = build(striker=StrikerMock(games=[]))
    client.get("/api/matches")
    client.get("/api/matches")
    client.get("/api/standings")
    assert [c["tool"] for c in striker.calls].count("list_games") == 1, "must not spend credits on every request"
    # A manual refresh inside the 5-minute floor is also refused without calling the provider.
    r = client.post("/api/refresh/results")
    assert r.status_code == 200 and r.json()["called"] is False
    assert [c["tool"] for c in striker.calls].count("list_games") == 1


def test_striker_out_of_credits_is_handled(build):
    client, *_ = build(striker=StrikerMock(status=402))
    r = client.get("/api/matches")
    assert r.status_code == 200, "a StrikerAPI failure must not break fixtures"
    m8 = next(m for m in r.json()["matches"] if m["key"] == "m_8")
    assert m8["status"] == "awaiting_result" and m8["score"] is None


def test_predictions_on_upcoming_sum_to_100(client):
    upcoming = client.get("/api/matches", params={"status": "upcoming"}).json()["matches"]
    assert upcoming
    for m in upcoming:
        p = m["prediction"]["percent"]
        assert p["home"] + p["draw"] + p["away"] == 100
        assert all(v > 0 for v in p.values())


def test_predictions_are_frozen_after_kickoff(build, now):
    client, services, *_ = build()
    client.get("/api/matches")
    before = services.prediction_store.get("m_u1")
    assert before and not before["frozen"]
    # Move past kickoff; the stored pre-match prediction must not be recomputed.
    now["now"] = now["now"] + timedelta(days=20)
    client.get("/api/matches")
    after = services.prediction_store.get("m_u1")
    assert after["frozen"] is True
    assert after["percent"] == before["percent"] and after["issued_at"] == before["issued_at"]


def test_kickoff_times_local_and_pkt(client):
    m = next(m for m in client.get("/api/matches").json()["matches"] if m["key"] == "m_u1")
    k = m["kickoff"]
    assert k["utc"] == "2026-11-25T20:00:00Z"
    assert k["local"]["timezone"] == "Europe/London" and k["local"]["time"] == "20:00"   # GMT in late November
    assert k["pkt"]["time"] == "01:00" and k["pkt"]["abbreviation"] == "PKT"
    m1 = next(m for m in client.get("/api/matches").json()["matches"] if m["key"] == "m_1")
    assert m1["kickoff"]["local"]["time"] == "21:00"   # Madrid, CEST (UTC+2) in September


def test_match_detail_key_players(client):
    r = client.get("/api/matches/m_u3")   # PSG (H) vs Real Madrid (A), upcoming
    assert r.status_code == 200
    body = r.json()
    for side in ("home", "away"):
        team = body["teams"][side]
        players = team["key_players"]
        assert len(players) == 5
        for p in players:
            assert 1 <= len(p["appearances"]) <= 3
            assert [a["label"] for a in p["appearances"]] == [f"Appearance {i}" for i in range(1, len(p["appearances"]) + 1)]
            for a in p["appearances"]:
                assert "date" not in a and "kickoff" not in a
                assert a["stats"]["minutes"] and a["stats"]["minutes"] > 0
        intel = team["intel"]
        assert intel["manager"] and intel["formation"]
    rma = body["teams"]["away"]["key_players"]
    assert any(len(p["appearances"]) == 3 for p in rma)
    top = rma[0]
    assert top["totals"]["xg"] is not None and top["totals"]["recoveries"] is not None


def test_match_detail_completed_has_stats(client):
    body = client.get("/api/matches/m_7").json()
    assert body["match"]["score"] == {"home": 3, "away": 1}
    labels = [s["label"] for s in body["team_stats"]]
    assert "Ball possession" in labels


def test_unknown_match_is_404(client):
    r = client.get("/api/matches/m_old")
    assert r.status_code == 404
    assert r.json()["error"] == "http_error"


def test_standings_calculated(client):
    data = client.get("/api/standings").json()
    assert data["season"] == SEASON and data["method"] == "calculated"
    rows = {r["club"]: r for r in data["rows"]}
    assert "Fenerbahçe" not in rows, "qualifying matches are not league phase"
    rm = rows["Real Madrid"]
    assert (rm["played"], rm["won"], rm["drawn"], rm["lost"], rm["gf"], rm["ga"], rm["points"]) == (3, 2, 1, 0, 7, 4, 7)
    assert data["rows"][0]["club"] == "Real Madrid"
    assert data["matches_played"] == 8 and data["complete"] is False
    assert [r["position"] for r in data["rows"]] == list(range(1, len(data["rows"]) + 1))


def test_standings_prefers_valid_provider_table(build):
    table = {"standings": [
        {"group_name": "UEFA Champions League 2026-2027 League Phase", "rank": i + 1, "display_name": name,
         "played": 8, "wins": w, "draws": d, "losses": 8 - w - d, "goals_for": gf, "goals_against": ga,
         "goal_difference": gf - ga, "points": 3 * w + d}
        for i, (name, w, d, gf, ga) in enumerate([("Real Madrid", 6, 1, 18, 6), ("Arsenal", 5, 2, 14, 7)])
    ]}
    client, *_ = build(striker=StrikerMock(standings=table))
    data = client.get("/api/standings").json()
    assert data["method"] == "provider"
    assert data["rows"][0]["club"] == "Real Madrid" and data["rows"][0]["logo"]


def test_standings_rejects_inconsistent_provider_table(build):
    bad = {"standings": [{"group_name": "League Phase", "rank": 1, "display_name": "Real Madrid", "played": 8,
                          "wins": 6, "draws": 1, "losses": 0, "goals_for": 10, "goals_against": 2, "points": 19}]}
    client, *_ = build(striker=StrikerMock(standings=bad))
    assert client.get("/api/standings").json()["method"] == "calculated"


def test_standings_empty_state(build):
    client, *_ = build(pitch=PitchMock(matches=[]))
    data = client.get("/api/standings").json()
    assert data["rows"] == [] and data["matches_played"] == 0


def test_provider_outage_returns_502(build):
    client, *_ = build(pitch=PitchMock(fail=True))
    r = client.get("/api/matches")
    assert r.status_code == 502
    assert r.json()["error"] == "data_unavailable"


def test_not_configured_returns_503(build):
    client, *_ = build(settings=make_settings(pitch_key="YOUR_PITCHAPI_KEY", striker_key=""))
    r = client.get("/api/matches")
    assert r.status_code == 503
    assert client.get("/api/health").json()["providers"] == {"pitchapi": False, "strikerapi": False}


def test_providers_endpoint_never_exposes_keys(client):
    text = client.get("/api/providers").text
    assert "pk_test_key" not in text and "sk_test_key" not in text


def test_refresh_endpoints(client):
    r = client.post("/api/refresh")
    assert r.status_code == 200 and r.json()["refreshed"] is True
    assert client.post("/api/refresh/results").status_code == 200
    assert client.get("/api/model/evaluation").status_code == 200


def test_invalid_query_is_422(client):
    assert client.get("/api/matches", params={"status": "bogus"}).status_code == 422
