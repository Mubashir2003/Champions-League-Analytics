from __future__ import annotations

import math
from datetime import datetime, timezone

from backend.predictions.elo_poisson import (
    INITIAL_RATING, CompletedMatch, EloPoissonModel, outcome_probabilities, to_percentages,
)
from backend.predictions.evaluation import evaluate
from backend.services.normalize import normalize_striker_game, reconcile
from backend.services.standings_service import compute_table
from backend.utils.teams import normalize_team_name, same_team
from backend.utils.timezones import kickoff_block


def test_outcome_probabilities_sum_to_one():
    for lh, la in [(1.5, 1.2), (0.3, 3.1), (2.8, 0.4), (1.0, 1.0)]:
        h, d, a = outcome_probabilities(lh, la)
        assert math.isclose(h + d + a, 1.0, rel_tol=1e-9)


def test_percentages_always_total_100():
    for probs in [(0.333, 0.333, 0.334), (0.4449, 0.2551, 0.3), (0.999, 0.0005, 0.0005), (0.5, 0.25, 0.25)]:
        assert sum(to_percentages(probs)) == 100


def test_model_is_deterministic_and_learns():
    games = [CompletedMatch("a", "b", 3, 0, "2026-09-16"), CompletedMatch("c", "a", 0, 2, "2026-09-30")]
    m1, m2 = EloPoissonModel().fit(games), EloPoissonModel().fit(list(reversed(games)))
    assert m1.ratings == m2.ratings, "fit sorts by kickoff, so order of input does not matter"
    assert m1.rating("a") > INITIAL_RATING > m1.rating("b")
    p = m1.predict("a", "b")
    assert p.home_win > p.away_win
    assert p.home_pct + p.draw_pct + p.away_pct == 100


def test_home_advantage_with_equal_ratings():
    p = EloPoissonModel().predict("x", "y")
    assert p.home_win > p.away_win


def test_evaluation_metrics():
    recs = [
        {"frozen": True, "home_win": 0.6, "draw": 0.25, "away_win": 0.15, "result": {"home": 2, "away": 0}},
        {"frozen": True, "home_win": 0.3, "draw": 0.3, "away_win": 0.4, "result": {"home": 1, "away": 1}},
        {"frozen": False, "home_win": 0.5, "draw": 0.3, "away_win": 0.2},
    ]
    ev = evaluate(recs)
    assert ev["evaluated_matches"] == 2
    expected_brier = ((0.4 ** 2 + 0.25 ** 2 + 0.15 ** 2) + (0.3 ** 2 + 0.7 ** 2 + 0.4 ** 2)) / 2
    assert math.isclose(ev["brier_score"], round(expected_brier, 4))
    assert math.isclose(ev["log_loss"], round((-math.log(0.6) - math.log(0.3)) / 2, 4))
    assert ev["calibration"]


def test_team_name_normalisation():
    assert same_team("Bayern München", "FC Bayern Munich")
    assert same_team("Paris Saint-Germain", "PSG")
    assert same_team("SL Benfica", "Benfica")
    assert same_team("FC Internazionale Milano", "Inter")
    assert not same_team("Real Madrid", "Atletico Madrid")
    assert not same_team("Manchester City", "Manchester United")
    assert not same_team("Milan", "Internazionale")
    assert normalize_team_name("Fenerbahçe SK") == "fenerbahce"


def test_reconcile_requires_identity_and_date():
    matches = [{"key": "k", "status": "awaiting_result", "date": "2026-11-04", "score": None,
                "home": {"name": "Bayern München"}, "away": {"name": "Benfica"}}]
    wrong_date = normalize_striker_game({"game_id": "1", "date": "2026-11-10T20:00:00Z", "home_team": "Bayern Munich",
                                         "away_team": "Benfica", "home_score": 1, "away_score": 0})
    reversed_sides = normalize_striker_game({"game_id": "2", "date": "2026-11-04T20:00:00Z", "home_team": "Benfica",
                                             "away_team": "Bayern Munich", "home_score": 1, "away_score": 0})
    assert reconcile(matches, [wrong_date, reversed_sides]) == 0
    right = normalize_striker_game({"game_id": "3", "date": "2026-11-04T20:00:00Z", "home_team": {"name": "Bayern Munich"},
                                    "away_team": {"name": "SL Benfica"}, "home_score": 2, "away_score": 2})
    assert reconcile(matches, [right]) == 1 and matches[0]["score"] == {"home": 2, "away": 2}


def test_striker_game_missing_fields_is_ignored():
    assert normalize_striker_game({"game_id": "x", "home_team": "A"}) is None


def _m(h, a, hs, as_, date="2026-10-01"):
    return {"status": "completed", "date": date, "score": {"home": hs, "away": as_},
            "home": {"name": h, "logo": None}, "away": {"name": a, "logo": None}}


def test_uefa_tiebreakers_away_goals_then_wins():
    # A and B: same points (4), same GD (+1), same goals scored (3). A scored more away goals.
    matches = [
        _m("A", "C", 1, 1),   # A draw at home
        _m("D", "A", 1, 2),   # A wins away, 2 away goals
        _m("B", "E", 2, 1),   # B wins at home
        _m("F", "B", 1, 1),   # B draws away, 1 away goal
    ]
    table = compute_table(matches)
    order = [r["club"] for r in table]
    assert order.index("A") < order.index("B")
    a = next(r for r in table if r["club"] == "A")
    assert (a["points"], a["gd"], a["gf"]) == (4, 1, 3)


def test_away_goals_break_head_to_head_draw():
    table = compute_table([_m("A", "B", 1, 1)])
    assert table[0]["club"] == "B" and not table[0]["tie_unresolved"]   # B scored its goal away


def test_unresolved_tie_is_flagged():
    # C and D are identical on every criterion the data supports.
    table = compute_table([_m("C", "X", 1, 0), _m("D", "Y", 1, 0)])
    flagged = {r["club"]: r["tie_unresolved"] for r in table}
    assert flagged["C"] and flagged["D"]


def test_zoneinfo_handles_dst_without_hardcoded_offsets():
    summer = kickoff_block(datetime(2026, 9, 16, 19, 0, tzinfo=timezone.utc), "Europe/London")
    winter = kickoff_block(datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc), "Europe/London")
    assert summer["local"]["time"] == "20:00" and summer["local"]["abbreviation"] == "BST"
    assert winter["local"]["time"] == "20:00" and winter["local"]["abbreviation"] == "GMT"
    assert summer["pkt"]["time"] == "00:00" and winter["pkt"]["time"] == "01:00"
    assert kickoff_block(datetime(2026, 9, 16, 19, tzinfo=timezone.utc), None)["local"] is None
