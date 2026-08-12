"""Minimal Dispatcharr API client.

Auth is a single ``X-API-Key`` header (verified against 192.168.0.148 —
``apps.accounts.authentication.ApiKeyAuthentication``). Uses the stdlib so the
first slice runs with zero dependencies; swap to httpx when we add retries/async.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class DispatcharrError(RuntimeError):
    pass


class Dispatcharr:
    def __init__(self, base_url: str, api_key: str, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._channel_cache: dict[int, str] = {}

    def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(
            url, headers={"X-API-Key": self.api_key, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise DispatcharrError(f"GET {path} -> HTTP {e.code} {e.reason}") from e
        except urllib.error.URLError as e:
            raise DispatcharrError(f"GET {path} failed: {e.reason}") from e

    def recordings(self) -> list[dict]:
        """All recordings. The endpoint returns a plain array (no pagination)."""
        data = self._get("/api/channels/recordings/")
        if isinstance(data, list):
            return data
        return data.get("results", []) if isinstance(data, dict) else []

    def channel_name(self, channel_id: int) -> str:
        """Resolve a channel id to its effective name (cached)."""
        if channel_id in self._channel_cache:
            return self._channel_cache[channel_id]
        name = ""
        try:
            ch = self._get(f"/api/channels/channels/{channel_id}/")
            name = ch.get("effective_name") or ch.get("name") or ""
        except DispatcharrError:
            name = ""
        self._channel_cache[channel_id] = name
        return name
