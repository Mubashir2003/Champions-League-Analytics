from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend.main import build_services, create_app  # noqa: E402
from backend.predictions.store import PredictionStore  # noqa: E402
from backend.utils import clock  # noqa: E402
from backend.utils.cache import FileCache  # noqa: E402
from tests.mock_providers import PitchMock, StrikerMock  # noqa: E402

FIXED_NOW = datetime(2026, 11, 6, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def now(monkeypatch):
    state = {"now": FIXED_NOW}
    monkeypatch.setattr(clock, "now_utc", lambda: state["now"])
    return state


def make_settings(pitch_key="pk_test_key", striker_key="sk_test_key", **kw) -> Settings:
    return Settings(
        pitchapi_api_key=pitch_key, strikerapi_api_key=striker_key,
        pitchapi_base_url="https://api.pitchapi.test", strikerapi_base_url="https://mcp.strikerapi.test/v1",
        pitchapi_ucl_league_id="", **kw,
    )


@pytest.fixture
def build(tmp_path, now):
    def _build(pitch=None, striker=None, settings=None):
        pitch = pitch or PitchMock()
        striker = striker or StrikerMock()
        services = build_services(
            settings=settings or make_settings(),
            pitch_transport=httpx.MockTransport(pitch),
            striker_transport=httpx.MockTransport(striker),
            cache=FileCache(tmp_path / "cache"),
            prediction_store=PredictionStore(tmp_path / "predictions.json"),
        )
        client = TestClient(create_app(services), raise_server_exceptions=False)
        return client, services, pitch, striker
    return _build


@pytest.fixture
def client(build):
    return build()[0]
