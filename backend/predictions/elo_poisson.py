"""Reproducible Elo + Poisson match model.

1. **Elo.** Every club starts the 2026/27 season at the same rating. Ratings
   are updated after each completed 2026/27 Champions League match in
   kickoff order, with a home-advantage term and a goal-difference multiplier.
   No previous-season data is used.
2. **Poisson.** The rating gap (including home advantage) scales the
   competition's average home/away scoring rates into two expected-goal
   values, λ_home and λ_away. Independent Poisson distributions give the
   probability of every scoreline up to ``MAX_GOALS``; summing the cells gives
   home-win / draw / away-win probabilities.

The model is deterministic: same inputs → same outputs. All parameters are
module-level constants so they can be tuned and evaluated (see
``evaluation.py``).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

INITIAL_RATING = 1500.0
K_FACTOR = 24.0
HOME_ADVANTAGE = 50.0          # Elo points
RATING_SCALE = 1000.0          # rating gap that multiplies the scoring rate by 10
MAX_GOALS = 10
# Priors for average goals per match by side, used until enough 2026/27
# matches exist to estimate them (MIN_MATCHES_FOR_RATES).
PRIOR_HOME_GOALS = 1.55
PRIOR_AWAY_GOALS = 1.25
MIN_MATCHES_FOR_RATES = 20
MODEL_VERSION = "elo-poisson-1.0"


@dataclass
class CompletedMatch:
    home: str
    away: str
    home_goals: int
    away_goals: int
    kickoff: str  # ISO string; used only for ordering


@dataclass
class Prediction:
    home_win: float
    draw: float
    away_win: float
    home_pct: int
    draw_pct: int
    away_pct: int
    lambda_home: float
    lambda_away: float
    home_rating: float
    away_rating: float
    model_version: str = MODEL_VERSION

    def as_dict(self) -> Dict[str, object]:
        return {
            "home_win": round(self.home_win, 6),
            "draw": round(self.draw, 6),
            "away_win": round(self.away_win, 6),
            "percent": {"home": self.home_pct, "draw": self.draw_pct, "away": self.away_pct},
            "expected_goals": {"home": round(self.lambda_home, 3), "away": round(self.lambda_away, 3)},
            "ratings": {"home": round(self.home_rating, 1), "away": round(self.away_rating, 1)},
            "model_version": self.model_version,
        }


def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def outcome_probabilities(lam_home: float, lam_away: float, max_goals: int = MAX_GOALS) -> Tuple[float, float, float]:
    ph = [poisson_pmf(i, lam_home) for i in range(max_goals + 1)]
    pa = [poisson_pmf(j, lam_away) for j in range(max_goals + 1)]
    home = draw = away = 0.0
    for i, p_i in enumerate(ph):
        for j, p_j in enumerate(pa):
            cell = p_i * p_j
            if i > j:
                home += cell
            elif i == j:
                draw += cell
            else:
                away += cell
    total = home + draw + away  # < 1 because of truncation; renormalise
    return home / total, draw / total, away / total


def to_percentages(probs: Iterable[float]) -> List[int]:
    """Integer percentages that always total exactly 100 (largest-remainder method)."""
    values = [max(0.0, float(p)) for p in probs]
    total = sum(values) or 1.0
    raw = [v / total * 100.0 for v in values]
    floors = [int(math.floor(r)) for r in raw]
    remainder = 100 - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: (raw[i] - floors[i], raw[i]), reverse=True)
    for i in order[:remainder]:
        floors[i] += 1
    return floors


@dataclass
class EloPoissonModel:
    ratings: Dict[str, float] = field(default_factory=dict)
    home_rate: float = PRIOR_HOME_GOALS
    away_rate: float = PRIOR_AWAY_GOALS
    matches_used: int = 0

    def rating(self, team: str) -> float:
        return self.ratings.get(team, INITIAL_RATING)

    @staticmethod
    def expected_score(rating_diff: float) -> float:
        return 1.0 / (1.0 + 10 ** (-rating_diff / 400.0))

    def update(self, m: CompletedMatch) -> None:
        rh, ra = self.rating(m.home), self.rating(m.away)
        exp_home = self.expected_score(rh + HOME_ADVANTAGE - ra)
        if m.home_goals > m.away_goals:
            actual = 1.0
        elif m.home_goals == m.away_goals:
            actual = 0.5
        else:
            actual = 0.0
        margin = abs(m.home_goals - m.away_goals)
        multiplier = math.log(margin + 1) + 1.0 if margin > 0 else 1.0
        delta = K_FACTOR * multiplier * (actual - exp_home)
        self.ratings[m.home] = rh + delta
        self.ratings[m.away] = ra - delta

    def fit(self, matches: Iterable[CompletedMatch]) -> "EloPoissonModel":
        ordered = sorted(matches, key=lambda m: m.kickoff or "")
        for m in ordered:
            self.update(m)
        self.matches_used = len(ordered)
        if len(ordered) >= MIN_MATCHES_FOR_RATES:
            self.home_rate = sum(m.home_goals for m in ordered) / len(ordered)
            self.away_rate = sum(m.away_goals for m in ordered) / len(ordered)
            # Guard against degenerate early-season rates.
            self.home_rate = min(max(self.home_rate, 0.6), 3.5)
            self.away_rate = min(max(self.away_rate, 0.5), 3.0)
        return self

    def predict(self, home: str, away: str) -> Prediction:
        rh, ra = self.rating(home), self.rating(away)
        diff = rh + HOME_ADVANTAGE - ra
        lam_h = self.home_rate * 10 ** (diff / (2 * RATING_SCALE))
        lam_a = self.away_rate * 10 ** (-diff / (2 * RATING_SCALE))
        p_home, p_draw, p_away = outcome_probabilities(lam_h, lam_a)
        pct = to_percentages([p_home, p_draw, p_away])
        return Prediction(p_home, p_draw, p_away, pct[0], pct[1], pct[2], lam_h, lam_a, rh, ra)


def build_model(completed: Iterable[CompletedMatch], before: Optional[str] = None) -> EloPoissonModel:
    """Fit on completed matches, optionally only those that kicked off before ``before`` (ISO)."""
    pool = [m for m in completed if before is None or (m.kickoff and m.kickoff < before)]
    return EloPoissonModel().fit(pool)
