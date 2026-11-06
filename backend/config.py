"""Application configuration.

All secrets are read from environment variables (optionally loaded from a
``.env`` file at the project root). Nothing in this module is ever sent to the
browser: the frontend talks only to this backend's ``/api`` routes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else default


def _is_placeholder(value: str) -> bool:
    return not value or value.upper().startswith("YOUR_")


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Provider credentials (backend only)
    pitchapi_api_key: str = field(default_factory=lambda: _env("PITCHAPI_API_KEY"))
    strikerapi_api_key: str = field(default_factory=lambda: _env("STRIKERAPI_API_KEY"))

    # Provider hosts
    pitchapi_base_url: str = field(
        default_factory=lambda: _env("PITCHAPI_BASE_URL", "https://api.pitchapi.dev").rstrip("/")
    )
    strikerapi_base_url: str = field(
        default_factory=lambda: _env("STRIKERAPI_BASE_URL", "https://mcp.strikerapi.com/v1").rstrip("/")
    )

    # Competition scope — fixed to 2026/2027 by design.
    season_label: str = "2026/2027"          # PitchAPI season format (fall-spring league)
    striker_season: int = 2026               # StrikerAPI: season by the year it starts
    season_start: str = "2026-06-01"         # earliest date a 2026/27 UCL fixture can carry (qualifying)
    season_end: str = "2027-07-31"
    # Optional override if PitchAPI's league id for the Champions League is known.
    pitchapi_ucl_league_id: str = field(default_factory=lambda: _env("PITCHAPI_UCL_LEAGUE_ID"))

    # Caching / refresh policy
    fixtures_ttl_seconds: int = field(default_factory=lambda: _int_env("FIXTURES_TTL_SECONDS", 900))
    striker_min_refresh_minutes: int = field(
        default_factory=lambda: _int_env("STRIKER_MIN_REFRESH_MINUTES", 60)
    )
    # A match is only checked against StrikerAPI once this many minutes have
    # passed since kickoff (StrikerAPI is a post-match source, not live scores).
    striker_result_delay_minutes: int = field(
        default_factory=lambda: _int_env("STRIKER_RESULT_DELAY_MINUTES", 150)
    )
    request_timeout: float = 25.0

    display_timezone: str = "Asia/Karachi"   # PKT

    @property
    def pitchapi_configured(self) -> bool:
        return not _is_placeholder(self.pitchapi_api_key)

    @property
    def strikerapi_configured(self) -> bool:
        return not _is_placeholder(self.strikerapi_api_key)


DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
PREDICTIONS_FILE = DATA_DIR / "predictions.json"
TEAM_TIMEZONES_FILE = DATA_DIR / "team_timezones.json"
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def get_settings() -> Settings:
    return Settings()
