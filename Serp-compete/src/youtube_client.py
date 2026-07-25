"""SC-7-YT Phase 1 — hardened YouTube Data API client.

Purpose: A sanctioned, quota-bounded HTTPS surface to the official YouTube Data API v3
         (channel existence + vitals). This is the metadata *check* half of SC-7-YT — it
         is NOT the yt-dlp scraper (that stays confined to `ptd`, Phase 2). It sits beside
         `api_clients.py`'s DataForSEO/Moz clients and is hardened the same way:
         timeout + retry + backoff, transient (429 / 5xx / quotaExceeded) distinguished
         from terminal (P5/P1), mirroring DataForSEOClient.get_search_volume.
Spec:    sc7-yt-spec.md#3.5 (hardening), #3.6 (key handling)
Tests:   tests/test_youtube_presence.py::test_p1_4_api_client_hardened

The API key is read from env ONLY (config names the env var via `api_key_env`; the key is
NEVER stored in config or code). Absent key → `available=False` and no call is made, so
Phase 1 can degrade honestly (data_available:false) instead of crashing.

The LIVE API path is integration-only and untested-by-design (P10): the key is not
provisioned yet. The unit test exercises the retry / transient-vs-terminal branching with
a mocked `requests.get`; it never touches the network.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://www.googleapis.com/youtube/v3/"

# A 403 can be transient (quota/rate) or terminal (bad key / access). Only these reasons
# are retryable — editorial, but tiny and API-defined, so kept in-code with a citation.
_TRANSIENT_403_REASONS = {"quotaexceeded", "ratelimitexceeded", "backenderror",
                          "userratelimitexceeded"}


class YouTubeError(Exception):
    """A terminal Data API failure (bad request / not found / auth) — do not retry."""


class YouTubeTransientError(YouTubeError):
    """A retryable Data API failure (429 / 5xx / quotaExceeded) — the honest state is a
    retryable `error`, NEVER `none_found` (P1)."""


class YouTubeDataClient:
    """Thin, hardened wrapper over the three Data API endpoints Phase 1 needs.

    Cost per call (quota units, tracked by the caller): search.list ~100,
    channels.list 1, playlistItems.list 1.
    """

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, *, timeout: int = 30,
                 max_retries: int = 3):
        cfg = cfg or {}
        self.key = os.getenv(cfg.get("api_key_env", "YOUTUBE_API_KEY"))
        self.available = bool(self.key)
        self.timeout = timeout
        self.max_retries = max_retries

    # -- transport -----------------------------------------------------------
    def _get(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """GET BASE+endpoint with retry + backoff. Returns parsed JSON on 200.

        Raises YouTubeTransientError on 429/5xx/quotaExceeded after retries (retryable),
        YouTubeError on a terminal non-200. Hardened like DataForSEOClient.get_search_volume.
        """
        if not self.available:
            # Guard: never build a keyless request (P1.3 — no silent unauthenticated call).
            raise YouTubeError("YouTube Data API key absent — client unavailable")
        url = BASE_URL + endpoint
        q = {**params, "key": self.key}
        last_reason = ""
        for attempt in range(self.max_retries):
            try:
                resp = requests.get(url, params=q, timeout=self.timeout)
            except requests.RequestException as e:
                last_reason = f"network: {e}"
                time.sleep(1.5 * (attempt + 1))  # backoff before retry (429-friendly)
                continue
            if resp.status_code == 200:
                return resp.json() or {}
            if self._is_transient(resp):
                last_reason = f"transient HTTP {resp.status_code}"
                time.sleep(1.5 * (attempt + 1))
                continue
            # Terminal non-200 (bad key, 400, 404) — do not retry.
            raise YouTubeError(f"YouTube Data API {endpoint} HTTP {resp.status_code}: "
                               f"{(resp.text or '')[:200]}")
        raise YouTubeTransientError(
            f"YouTube Data API {endpoint} failed after {self.max_retries} attempts ({last_reason})")

    @staticmethod
    def _is_transient(resp: Any) -> bool:
        if resp.status_code == 429 or resp.status_code >= 500:
            return True
        if resp.status_code == 403:
            try:
                errs = (resp.json() or {}).get("error", {}).get("errors", [])
                reasons = {str(e.get("reason", "")).lower() for e in errs}
            except (ValueError, AttributeError):
                reasons = set()
            return bool(reasons & _TRANSIENT_403_REASONS)
        return False

    # -- endpoints -----------------------------------------------------------
    def search_channels(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """search.list?type=channel — candidate channels for a brand query (~100 units)."""
        data = self._get("search", {"part": "snippet", "type": "channel",
                                     "q": query, "maxResults": max_results})
        out: List[Dict[str, Any]] = []
        for item in data.get("items", []) or []:
            snip = item.get("snippet", {}) or {}
            cid = (item.get("id", {}) or {}).get("channelId") or snip.get("channelId")
            if cid:
                out.append({"channel_id": cid, "title": snip.get("title", ""),
                            "description": snip.get("description", "")})
        return out

    def get_channels(self, channel_id: Optional[str] = None,
                     handle: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """channels.list by id or handle — stats + uploads playlist (1 unit). None if absent."""
        params: Dict[str, Any] = {"part": "snippet,statistics,contentDetails"}
        if handle:
            params["forHandle"] = handle.lstrip("@")
        elif channel_id:
            params["id"] = channel_id
        else:
            return None
        data = self._get("channels", params)
        items = data.get("items", []) or []
        if not items:
            return None
        it = items[0]
        snip = it.get("snippet", {}) or {}
        stats = it.get("statistics", {}) or {}
        uploads = (((it.get("contentDetails", {}) or {}).get("relatedPlaylists", {}) or {})
                   .get("uploads"))
        return {
            "channel_id": it.get("id"),
            "title": snip.get("title", ""),
            "description": snip.get("description", ""),
            "custom_url": snip.get("customUrl", ""),
            "subscriber_count": _to_int(stats.get("subscriberCount")),
            "video_count": _to_int(stats.get("videoCount")),
            "uploads_playlist_id": uploads,
            "hidden_subscriber_count": bool(stats.get("hiddenSubscriberCount")),
        }

    def get_recent_uploads(self, uploads_playlist_id: str,
                           max_results: int = 10) -> List[str]:
        """playlistItems.list on the uploads playlist — recent upload dates (1 unit)."""
        if not uploads_playlist_id:
            return []
        data = self._get("playlistItems", {"part": "contentDetails,snippet",
                                           "playlistId": uploads_playlist_id,
                                           "maxResults": max_results})
        dates: List[str] = []
        for item in data.get("items", []) or []:
            cd = item.get("contentDetails", {}) or {}
            snip = item.get("snippet", {}) or {}
            published = cd.get("videoPublishedAt") or snip.get("publishedAt")
            if published:
                dates.append(published)
        return dates


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
