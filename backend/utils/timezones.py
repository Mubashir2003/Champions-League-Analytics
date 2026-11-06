"""Kickoff-time conversion with :mod:`zoneinfo` (no hard-coded DST offsets)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PKT = "Asia/Karachi"


def parse_utc(value: Optional[str], fallback_date: Optional[str] = None) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (``2026-09-01T18:30:00Z``) into an aware UTC datetime.

    If only a date is available the time is unknown, so ``None`` is returned and
    callers fall back to showing the date alone.
    """
    if value:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            dt = None
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    return None


def _zone(name: Optional[str]) -> Optional[ZoneInfo]:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def format_in_zone(dt: datetime, tz_name: str) -> Optional[Dict[str, Any]]:
    zone = _zone(tz_name)
    if zone is None:
        return None
    local = dt.astimezone(zone)
    return {
        "timezone": tz_name,
        "abbreviation": local.tzname(),
        "iso": local.isoformat(),
        "date": local.strftime("%a %d %b %Y"),
        "time": local.strftime("%H:%M"),
    }


def kickoff_block(kickoff_utc: Optional[datetime], venue_tz: Optional[str]) -> Dict[str, Any]:
    """Everything the UI needs to show a kickoff in venue-local time and PKT."""
    if kickoff_utc is None:
        return {"utc": None, "local": None, "pkt": None}
    pkt = format_in_zone(kickoff_utc, PKT)
    if pkt:
        pkt["abbreviation"] = "PKT"
    return {
        "utc": kickoff_utc.isoformat().replace("+00:00", "Z"),
        "local": format_in_zone(kickoff_utc, venue_tz) if venue_tz else None,
        "pkt": pkt,
    }
