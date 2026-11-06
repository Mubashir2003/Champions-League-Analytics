"""REST endpoints. Responses never include API keys or raw provider payloads."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from backend.predictions.evaluation import evaluate
from backend.services.match_service import DataUnavailable

router = APIRouter(prefix="/api")

PUBLIC_MATCH_FIELDS = ("key", "season", "date", "kickoff_utc", "kickoff", "status", "home", "away", "score", "prediction")


def _services(request: Request):
    return request.app.state.services


def public_match(m: Dict[str, Any]) -> Dict[str, Any]:
    """Strip internal/provider-only fields before sending a match to the browser."""
    return {k: m.get(k) for k in PUBLIC_MATCH_FIELDS}


def _unavailable(exc: DataUnavailable) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": "data_unavailable", "message": exc.reason})


@router.get("/health")
def health(request: Request):
    s = _services(request)
    return {
        "status": "ok",
        "season": s.settings.season_label,
        "time_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "providers": {"pitchapi": s.pitch.configured, "strikerapi": s.striker.configured},
    }


@router.get("/matches")
def list_matches(
    request: Request,
    status: Optional[str] = Query(None, pattern="^(upcoming|completed|all)$"),
    limit: Optional[int] = Query(None, ge=1, le=500),
    order: Optional[str] = Query(None, pattern="^(asc|desc)$"),
):
    s = _services(request)
    try:
        matches = s.matches.get_matches()
    except DataUnavailable as exc:
        return _unavailable(exc)
    if status == "upcoming":
        matches = [m for m in matches if m["status"] in ("upcoming", "postponed")]
    elif status == "completed":
        matches = [m for m in matches if m["status"] in ("completed", "awaiting_result")]
    if status == "completed" and order != "asc":
        matches = sorted(matches, key=lambda m: m.get("kickoff_utc") or m.get("date") or "", reverse=True)
    elif order == "desc":
        matches = list(reversed(matches))
    total = len(matches)
    if limit:
        matches = matches[:limit]
    return {"season": s.settings.season_label, "count": len(matches), "total": total,
            "matches": [public_match(m) for m in matches]}


@router.get("/matches/{match_key}")
def match_detail(request: Request, match_key: str):
    s = _services(request)
    try:
        all_matches = s.matches.get_matches()
    except DataUnavailable as exc:
        return _unavailable(exc)
    match = next((m for m in all_matches if m["key"] == match_key), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found in the 2026/2027 Champions League.")
    detail = s.players.match_detail(match, all_matches)
    return {"match": public_match(match), **detail}


@router.get("/standings")
def standings(request: Request):
    s = _services(request)
    try:
        matches = s.matches.get_matches()
    except DataUnavailable as exc:
        return _unavailable(exc)
    return s.standings.build(matches)


@router.get("/providers")
def providers(request: Request):
    """Configuration/health of each provider (for operators; not linked from the UI)."""
    s = _services(request)
    striker_state = s.cache.get("striker", "state", None) or {}
    return {
        "pitchapi": {
            "configured": s.pitch.configured,
            "base_url": s.pitch.base,
            "role": "fixtures, teams, logos, lineups, player and match statistics",
            "last_error": s.matches.last_error,
            "fixtures_cache_age_seconds": s.cache.age("fixtures", "ucl_" + s.settings.season_label.replace("/", "_")),
        },
        "strikerapi": {
            "configured": s.striker.configured,
            "base_url": s.striker.base,
            "role": "completed-match result verification (post-match, not live)",
            "min_refresh_minutes": s.settings.striker_min_refresh_minutes,
            "last_error": striker_state.get("last_error"),
            "credits_remaining": striker_state.get("credits_remaining"),
            "stored_final_results": len(s.matches._stored_striker_results()),
        },
    }


@router.get("/model/evaluation")
def model_evaluation(request: Request):
    s = _services(request)
    records = list(s.prediction_store.load()["predictions"].values())
    return {"model": "Elo + Poisson", **evaluate(records)}


@router.post("/refresh")
def refresh(request: Request):
    s = _services(request)
    try:
        matches = s.matches.get_matches(force=True, auto_results=False)
    except DataUnavailable as exc:
        return _unavailable(exc)
    return {"refreshed": True, "matches": len(matches),
            "upcoming": sum(1 for m in matches if m["status"] == "upcoming"),
            "completed": sum(1 for m in matches if m["status"] == "completed")}


@router.post("/refresh/results")
def refresh_results(request: Request):
    s = _services(request)
    try:
        outcome = s.matches.refresh_results()
    except DataUnavailable as exc:
        return _unavailable(exc)
    if outcome.get("called") and not outcome.get("ok"):
        return JSONResponse(status_code=502, content={"error": "result_check_failed", "message": outcome.get("error")})
    return outcome
