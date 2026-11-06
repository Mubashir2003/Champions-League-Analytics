"""Evaluate frozen pre-match predictions against actual results.

Metrics (three-way outcome H/D/A):
* Brier score — mean squared error of the probability vector (0 is perfect, lower is better).
* Log loss — mean negative log-probability of the observed outcome (lower is better).
* Calibration — predicted vs observed frequency per probability bin.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List

OUTCOMES = ("home", "draw", "away")


def outcome_of(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if home_goals == away_goals:
        return "draw"
    return "away"


def brier(probs: Dict[str, float], outcome: str) -> float:
    return sum((probs[o] - (1.0 if o == outcome else 0.0)) ** 2 for o in OUTCOMES)


def log_loss(probs: Dict[str, float], outcome: str, eps: float = 1e-12) -> float:
    return -math.log(max(probs[outcome], eps))


def calibration(samples: List[Dict[str, Any]], bins: int = 10) -> List[Dict[str, Any]]:
    edges = [i / bins for i in range(bins + 1)]
    out = []
    for b in range(bins):
        lo, hi = edges[b], edges[b + 1]
        preds, hits = [], 0
        for s in samples:
            for o in OUTCOMES:
                p = s["probs"][o]
                if lo <= p < hi or (b == bins - 1 and p == 1.0):
                    preds.append(p)
                    hits += 1 if s["outcome"] == o else 0
        if preds:
            out.append({
                "bin": f"{lo:.1f}-{hi:.1f}",
                "count": len(preds),
                "mean_predicted": round(sum(preds) / len(preds), 4),
                "observed_frequency": round(hits / len(preds), 4),
            })
    return out


def evaluate(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    samples = []
    for rec in records:
        result = rec.get("result")
        if not rec.get("frozen") or not isinstance(result, dict):
            continue
        try:
            probs = {"home": float(rec["home_win"]), "draw": float(rec["draw"]), "away": float(rec["away_win"])}
            outcome = outcome_of(int(result["home"]), int(result["away"]))
        except (KeyError, TypeError, ValueError):
            continue
        samples.append({"probs": probs, "outcome": outcome})
    n = len(samples)
    if n == 0:
        return {"evaluated_matches": 0, "brier_score": None, "log_loss": None, "accuracy": None, "calibration": []}
    correct = sum(1 for s in samples if max(s["probs"], key=s["probs"].get) == s["outcome"])
    return {
        "evaluated_matches": n,
        "brier_score": round(sum(brier(s["probs"], s["outcome"]) for s in samples) / n, 4),
        "log_loss": round(sum(log_loss(s["probs"], s["outcome"]) for s in samples) / n, 4),
        "accuracy": round(correct / n, 4),
        "calibration": calibration(samples),
    }
