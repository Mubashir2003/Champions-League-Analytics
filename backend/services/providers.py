"""HTTP clients for the two data providers.

PitchAPI (primary) — verified against the official ``pitchapi`` Python SDK
(v0.1.6, which mirrors the service's OpenAPI 3.1 description):

* ``GET {base}/v1/<path>`` with header ``X-API-KEY``.
* Success bodies are ``{"data": ...}``; errors are ``{"error": {"code", "message"}}``.
* 429 carries ``Retry-After``.
* Routes used here: ``/leagues``, ``/leagues/{id}/matches?season=&status=``,
  ``/matches/{id}``, ``/matches/{id}/lineups``, ``/matches/{id}/players``,
  ``/matches/{id}/advanced/players``, ``/matches/{id}/shots``, ``/matches/{id}/stats``.

StrikerAPI (secondary) — verified against https://strikerapi.com/docs and the
official ``strikerapi`` Python SDK (v0.1.4):

* ``POST {base}/v1/{tool_name}`` with a JSON body and header ``x-api-key``.
* Success bodies wrap the result in ``data``; ``X-Credits-Used`` /
  ``X-Credits-Remaining`` headers report credits. 401 auth, 402 out of
  credits, 404 not found, 429 rate limited.
* Tools used here: ``list_games`` (2 credits) and ``get_standings`` (2 credits).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import httpx

from backend.config import Settings

log = logging.getLogger("ucl.providers")


class ProviderError(Exception):
    """A provider call failed. ``status`` is the HTTP status when there was one."""

    def __init__(self, provider: str, message: str, status: Optional[int] = None, code: Optional[str] = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message
        self.status = status
        self.code = code


class ProviderNotConfigured(ProviderError):
    pass


def _error_message(payload: Any, status: int) -> tuple[str, Optional[str]]:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or f"HTTP {status}"), err.get("code")
        if isinstance(err, str) and err:
            return err, None
    return f"HTTP {status}", None


class PitchAPIClient:
    name = "pitchapi"

    def __init__(self, settings: Settings, transport: Optional[httpx.BaseTransport] = None, max_retries: int = 2):
        self.settings = settings
        base = settings.pitchapi_base_url.rstrip("/")
        self.base = base if base.endswith("/v1") else base + "/v1"
        self.max_retries = max_retries
        self._transport = transport

    @property
    def configured(self) -> bool:
        return self.settings.pitchapi_configured

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.settings.request_timeout,
            transport=self._transport,
            headers={
                "X-API-KEY": self.settings.pitchapi_api_key,
                "Accept": "application/json",
                "User-Agent": "ucl-analytics/1.0",
            },
        )

    def get(self, path: str, params: Optional[Dict[str, str]] = None) -> Any:
        if not self.configured:
            raise ProviderNotConfigured(self.name, "PITCHAPI_API_KEY is not set")
        params = {k: v for k, v in (params or {}).items() if v is not None} or None
        url = self.base + path
        attempt = 0
        with self._client() as http:
            while True:
                try:
                    resp = http.get(url, params=params)
                except httpx.RequestError as exc:
                    if attempt < self.max_retries:
                        time.sleep(min(2 ** attempt, 4))
                        attempt += 1
                        continue
                    raise ProviderError(self.name, f"network error: {exc}") from exc
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 4)
                    time.sleep(min(wait, 10))
                    attempt += 1
                    continue
                try:
                    payload = resp.json()
                except ValueError:
                    payload = None
                if 200 <= resp.status_code < 300:
                    if isinstance(payload, dict) and "data" in payload:
                        return payload["data"]
                    raise ProviderError(self.name, "malformed response (no data envelope)", resp.status_code)
                msg, code = _error_message(payload, resp.status_code)
                raise ProviderError(self.name, msg, resp.status_code, code)


class StrikerAPIClient:
    name = "strikerapi"

    def __init__(self, settings: Settings, transport: Optional[httpx.BaseTransport] = None, max_retries: int = 1):
        self.settings = settings
        base = settings.strikerapi_base_url.rstrip("/")
        self.base = base if base.endswith("/v1") else base + "/v1"
        self.max_retries = max_retries
        self._transport = transport
        self.last_credits_remaining: Optional[float] = None
        self.last_credits_used: Optional[float] = None

    @property
    def configured(self) -> bool:
        return self.settings.strikerapi_configured

    def call(self, tool: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        if not self.configured:
            raise ProviderNotConfigured(self.name, "STRIKERAPI_API_KEY is not set")
        body = {k: v for k, v in (arguments or {}).items() if v is not None}
        url = f"{self.base}/{tool}"
        attempt = 0
        with httpx.Client(
            timeout=self.settings.request_timeout,
            transport=self._transport,
            headers={
                "x-api-key": self.settings.strikerapi_api_key,
                "content-type": "application/json",
                "accept": "application/json",
                "user-agent": "ucl-analytics/1.0",
            },
        ) as http:
            while True:
                try:
                    resp = http.post(url, json=body)
                except httpx.RequestError as exc:
                    if attempt < self.max_retries:
                        time.sleep(1)
                        attempt += 1
                        continue
                    raise ProviderError(self.name, f"network error: {exc}") from exc
                for header, attr in (("x-credits-remaining", "last_credits_remaining"), ("x-credits-used", "last_credits_used")):
                    raw = resp.headers.get(header)
                    if raw is not None:
                        try:
                            setattr(self, attr, float(raw))
                        except ValueError:
                            pass
                if (resp.status_code == 429 or resp.status_code >= 500) and attempt < self.max_retries:
                    retry_after = resp.headers.get("retry-after")
                    wait = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else 2
                    time.sleep(min(wait, 10))
                    attempt += 1
                    continue
                try:
                    payload = resp.json()
                except ValueError:
                    payload = None
                if 200 <= resp.status_code < 300:
                    if payload is None:
                        raise ProviderError(self.name, "response was not JSON", resp.status_code)
                    if isinstance(payload, dict) and "data" in payload:
                        return payload["data"]
                    return payload
                msg, code = _error_message(payload, resp.status_code)
                if resp.status_code == 402:
                    msg = "out of StrikerAPI credits"
                raise ProviderError(self.name, msg, resp.status_code, code)
