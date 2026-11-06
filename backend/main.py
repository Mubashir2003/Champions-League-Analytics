"""UCL Analytics — FastAPI application.

Run from the project root:

    uvicorn backend.main:app --reload

Serves the REST API under ``/api`` and the dashboard (``frontend/``) at ``/``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.routes import router
from backend.config import FRONTEND_DIR, Settings, get_settings
from backend.predictions.store import PredictionStore, store as default_store
from backend.services.match_service import MatchService
from backend.services.player_service import PlayerService
from backend.services.providers import PitchAPIClient, StrikerAPIClient
from backend.services.standings_service import StandingsService
from backend.utils.cache import FileCache, cache as default_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

PAGES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/fixtures": "fixtures.html",
    "/fixtures.html": "fixtures.html",
    "/match": "match-details.html",
    "/match-details.html": "match-details.html",
    "/standings": "standings.html",
    "/standings.html": "standings.html",
}


@dataclass
class Services:
    settings: Settings
    pitch: PitchAPIClient
    striker: StrikerAPIClient
    cache: FileCache
    prediction_store: PredictionStore
    matches: MatchService
    players: PlayerService
    standings: StandingsService


def build_services(settings: Optional[Settings] = None, pitch_transport=None, striker_transport=None,
                   cache: Optional[FileCache] = None, prediction_store: Optional[PredictionStore] = None) -> Services:
    settings = settings or get_settings()
    cache = cache or default_cache
    prediction_store = prediction_store or default_store
    pitch = PitchAPIClient(settings, transport=pitch_transport)
    striker = StrikerAPIClient(settings, transport=striker_transport)
    return Services(
        settings=settings, pitch=pitch, striker=striker, cache=cache, prediction_store=prediction_store,
        matches=MatchService(settings, pitch, striker, cache, prediction_store),
        players=PlayerService(pitch, cache),
        standings=StandingsService(settings, striker, cache),
    )


def create_app(services: Optional[Services] = None) -> FastAPI:
    app = FastAPI(
        title="UCL Analytics API",
        version="1.0.0",
        description="UEFA Champions League 2026/2027 fixtures, results, standings, key players and Elo + Poisson predictions.",
    )
    app.state.services = services or build_services()
    app.include_router(router)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api"):
            return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "message": exc.detail})
        if exc.status_code == 404:
            return FileResponse(FRONTEND_DIR / "index.html", status_code=404)
        return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": "invalid_request", "message": "Invalid query parameters."})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logging.getLogger("ucl").exception("Unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": "Something went wrong."})

    for route, filename in PAGES.items():
        def _page(filename=filename):
            return FileResponse(FRONTEND_DIR / filename, media_type="text/html")
        app.add_api_route(route, _page, methods=["GET"], include_in_schema=False)

    for folder in ("css", "js", "assets"):
        app.mount(f"/{folder}", StaticFiles(directory=FRONTEND_DIR / folder), name=folder)
    return app


app = create_app()
