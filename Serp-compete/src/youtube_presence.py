"""SC-7-YT Phase 1 — YouTube Presence Check (pure compute).

Purpose: For each competitor AND the client, decide channel existence + vitals from the
         YouTube Data API, with an honest state machine and an adversarial identity guard.
         Pure over an injected client (like sov_analyzer.compute_sov is pure over the
         export) — so it is fully unit-testable with a fake client; the live API surface
         lives in youtube_client.py and is integration-only (P10).
Spec:    sc7-yt-spec.md#3 (Phase 1)
Tests:   tests/test_youtube_presence.py::test_p1_1_none_found_distinct_from_error,
         ::test_p1_2_samename_not_autoconfirmed, ::test_p1_3_key_from_env_absent_skips,
         ::test_p1_5_quota_budget_surfaced, ::test_p1_6_client_always_present,
         ::test_p1_10_config_driven

Honest states (P1/P2): check_status ∈ {confirmed, candidate, none_found, error}. A quota /
5xx / network failure is `error` (has_channel None — retryable), NEVER silently `none_found`.

Confidence tiers (P7 — a same-name channel is NOT a confirmed match): `high` requires the
competitor's domain in the channel About OR a handle match; a bare name match is at most
`medium` (a `candidate`, owner-confirmable), never auto-`confirmed`.
"""
from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional

from src.youtube_client import YouTubeError, YouTubeTransientError

# Quota unit costs (YouTube Data API v3, current defaults — see sc7-yt-spec.md#3.2).
SEARCH_COST = 100
CHANNELS_COST = 1
PLAYLIST_COST = 1

# Signal strength ranking for picking the best candidate + mapping to a confidence tier.
_RANK_DOMAIN, _RANK_HANDLE, _RANK_NAME, _RANK_NONE = 3, 2, 1, 0


def _norm(s: Any) -> str:
    """Alphanumeric-only lower-case token, for name/handle comparison."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _stem(domain: str) -> str:
    return str(domain or "").split(".")[0].lower()


def compute_presence(client: Any, competitor_domains: List[str], client_domain: str,
                     brand_by_domain: Dict[str, str], cfg: Dict[str, Any],
                     snapshot_date: str, client_brand: Optional[str] = None) -> Dict[str, Any]:
    """Return {data_available, rows, stats}. See module docstring for the state machine.

    `brand_by_domain` supplies each domain's derived brand token (from
    brand_utils.derive_brand_name) for name matching; `client_brand` is the client's
    display name used as its search query (falls back to its token/stem).
    """
    stats = {"checked": 0, "confirmed": 0, "candidates": 0, "none_found": 0,
             "errors": 0, "skipped": 0, "notable": 0, "units_used": 0, "budget_hit": False}

    # No key → honest skip (P1.3). Mirrors sov's data_available:false degradation.
    if not getattr(client, "available", False):
        return {"data_available": False, "rows": [], "stats": stats}

    max_candidates = int(cfg.get("max_candidates_per_competitor", 3))
    active_days = int(cfg.get("active_recency_days", 180))
    budget = int(cfg.get("daily_quota_budget", 5000))
    min_notable = int(cfg.get("min_subscribers_notable", 0))
    channel_map = cfg.get("channel_map", {}) or {}

    # Client first (P1.6 — the client anchors the report), then competitors, de-duped.
    ordered: List[tuple] = [(client_domain, True)]
    seen = {client_domain}
    for d in competitor_domains:
        if d not in seen:
            ordered.append((d, False))
            seen.add(d)

    rows: List[Dict[str, Any]] = []
    for idx, (domain, is_client) in enumerate(ordered):
        mapped = channel_map.get(domain)
        # Conservative estimate (P9): a discovery may probe up to max_candidates channels
        # before resolving, so budget for all of them — never underestimate and overrun.
        est_cost = (CHANNELS_COST + PLAYLIST_COST) if mapped else \
                   (SEARCH_COST + max_candidates * CHANNELS_COST + PLAYLIST_COST)

        # Quota budget stop (P9): announce (via stats) and mark the rest retryable — never
        # a silent truncation, never none_found.
        if stats["units_used"] + est_cost > budget:
            stats["budget_hit"] = True
            for rest_domain, rest_is_client in ordered[idx:]:
                rows.append(_state_row(rest_domain, rest_is_client, snapshot_date, "error",
                                       "quota_budget_skipped"))
                stats["skipped"] += 1
            break

        token = brand_by_domain.get(domain) or _stem(domain)
        search_term = (client_brand or token or _stem(domain)) if is_client else _stem(domain)

        try:
            row, units = _check_one(client, domain, is_client, token, search_term, mapped,
                                    max_candidates, active_days, snapshot_date)
        except (YouTubeTransientError, YouTubeError) as e:
            basis = "transient_error" if isinstance(e, YouTubeTransientError) else "api_error"
            rows.append(_state_row(domain, is_client, snapshot_date, "error", basis))
            stats["errors"] += 1
            stats["checked"] += 1
            # Count the units already spent before the failure (best-effort accounting).
            stats["units_used"] += SEARCH_COST if not mapped else CHANNELS_COST
            continue

        rows.append(row)
        stats["units_used"] += units
        stats["checked"] += 1
        stats[{"confirmed": "confirmed", "candidate": "candidates",
               "none_found": "none_found"}.get(row["check_status"], "errors")] += 1
        # A channel is "notable" once it clears the config subscriber floor (P4). Surfaced in
        # stats so the caller can announce it — the threshold is live config, not decorative.
        if (min_notable > 0 and row.get("has_channel")
                and (row.get("subscriber_count") or 0) >= min_notable):
            stats["notable"] += 1

    return {"data_available": True, "rows": rows, "stats": stats}


def _check_one(client, domain, is_client, token, search_term, mapped, max_candidates,
               active_days, snapshot_date):
    """Look up one domain; return (row, units_used). Raises on API failure (caller → error)."""
    units = 0
    stem = _stem(domain)

    # 1. channel_map short-circuit (owner-confirmed steady state, ~2 units).
    if mapped:
        handle_or_id = mapped[0] if isinstance(mapped, list) else mapped
        by_handle = str(handle_or_id).startswith("@")
        chan = client.get_channels(handle=handle_or_id) if by_handle \
            else client.get_channels(channel_id=handle_or_id)
        units += CHANNELS_COST
        if not chan:
            return _state_row(domain, is_client, snapshot_date, "none_found",
                              "channel_map_miss"), units
        last_date, recent, u = _uploads(client, chan.get("uploads_playlist_id"), active_days,
                                        snapshot_date)
        units += u
        return _channel_row(domain, is_client, snapshot_date, chan, "high", "handle",
                            "confirmed", "channel_map_confirmed", last_date, recent), units

    # 2. Discover: search → score candidates → resolve the best (~102 units).
    candidates = client.search_channels(search_term, max_candidates)
    units += SEARCH_COST
    if not candidates:
        return _state_row(domain, is_client, snapshot_date, "none_found", "none_found"), units

    best = None  # (rank, confidence, basis, channel_detail)
    for cand in candidates:
        detail = client.get_channels(channel_id=cand.get("channel_id"))
        units += CHANNELS_COST
        if not detail:
            continue
        rank, confidence, basis = _score(detail, domain, stem, token)
        if best is None or rank > best[0]:
            best = (rank, confidence, basis, detail)
        if rank == _RANK_DOMAIN:
            break  # strongest possible signal — stop probing further candidates

    if best is None or best[0] == _RANK_NONE:
        return _state_row(domain, is_client, snapshot_date, "none_found", "none_found"), units

    rank, confidence, basis, detail = best
    check_status = "confirmed" if confidence == "high" else "candidate"
    last_date, recent, u = _uploads(client, detail.get("uploads_playlist_id"), active_days,
                                    snapshot_date)
    units += u
    return _channel_row(domain, is_client, snapshot_date, detail, confidence, basis,
                        check_status, "data_api_discovery", last_date, recent), units


def _domain_in_text(domain: str, text: str) -> bool:
    """Word-boundary domain match (P7 — never a bare substring). Allows an optional
    subdomain prefix (www.livingsystems.ca) but rejects a domain that is only a substring of
    a longer token: `comp.com` must NOT match inside `notcomp.com` or `comp.company`."""
    if not domain or not text:
        return False
    pattern = (r"(?<![A-Za-z0-9])(?:[A-Za-z0-9-]+\.)*" + re.escape(domain)
               + r"(?![A-Za-z0-9.-])")
    return re.search(pattern, text) is not None


def _score(detail, domain, stem, token):
    """Adversarial identity scoring (P7). Returns (rank, confidence, match_basis)."""
    d = str(domain or "").lower()
    desc = str(detail.get("description", "")).lower()
    custom = str(detail.get("custom_url", "")).lower()
    ntitle = _norm(detail.get("title"))
    ncustom = _norm(custom)
    nstem, ntoken = _norm(stem), _norm(token)

    domain_in_about = _domain_in_text(d, desc) or _domain_in_text(d, custom)
    handle = bool(ncustom) and (ncustom == nstem or (bool(ntoken) and ncustom == ntoken))
    # Name tier is intentionally HIGH-RECALL (substring, not word-boundary): candidates come
    # from a brand-relevance-ranked search.list, and a name match only ever yields `candidate`
    # (owner-confirmed), NEVER `confirmed` — so recall (don't miss a real channel titled
    # "<Brand> Counselling" for a "<brand>.ca" domain) is worth the noisier confirm list. The
    # strict word-boundary discipline lives in domain_in_about, which is what earns `high`.
    name_exact = bool(ntitle) and ((bool(nstem) and nstem in ntitle) or
                                   (bool(ntoken) and ntoken in ntitle))

    if domain_in_about:
        return _RANK_DOMAIN, "high", "domain_in_about"
    if handle:
        return _RANK_HANDLE, "high", "handle"
    if name_exact:
        return _RANK_NAME, "medium", "name_exact"
    return _RANK_NONE, "low", "none"


def _uploads(client, uploads_playlist_id, active_days, snapshot_date):
    """Return (last_upload_date, uploads_recent, units). active_days is config-driven (P4)."""
    if not uploads_playlist_id:
        return None, 0, 0
    iso_dates = client.get_recent_uploads(uploads_playlist_id) or []
    parsed: List[datetime.date] = []
    for s in iso_dates:
        try:
            parsed.append(datetime.date.fromisoformat(str(s)[:10]))
        except ValueError:
            continue
    if not parsed:
        return None, 0, PLAYLIST_COST
    try:
        snap = datetime.date.fromisoformat(str(snapshot_date)[:10])
    except ValueError:
        snap = max(parsed)
    cutoff = snap - datetime.timedelta(days=active_days)
    recent = sum(1 for dt in parsed if dt >= cutoff)
    return max(parsed).isoformat(), recent, PLAYLIST_COST


def _channel_row(domain, is_client, snapshot_date, chan, confidence, basis, check_status,
                 estimation_basis, last_upload_date, uploads_recent):
    handle = chan.get("custom_url") or None
    cid = chan.get("channel_id")
    return {
        "domain": domain, "is_client": is_client, "checked_at": snapshot_date,
        "has_channel": True, "channel_id": cid, "handle": handle,
        "channel_title": chan.get("title"),
        "channel_url": (f"https://www.youtube.com/channel/{cid}" if cid else None),
        "subscriber_count": chan.get("subscriber_count"),
        "video_count": chan.get("video_count"),
        "last_upload_date": last_upload_date, "uploads_recent": uploads_recent,
        "match_confidence": confidence, "match_basis": basis,
        "check_status": check_status, "estimation_basis": estimation_basis,
    }


def _state_row(domain, is_client, snapshot_date, check_status, estimation_basis):
    """A no-channel row: none_found (has_channel False) or error (has_channel None — P1)."""
    has_channel = False if check_status == "none_found" else None
    return {
        "domain": domain, "is_client": is_client, "checked_at": snapshot_date,
        "has_channel": has_channel, "channel_id": "", "handle": None,
        "channel_title": None, "channel_url": None, "subscriber_count": None,
        "video_count": None, "last_upload_date": None, "uploads_recent": None,
        "match_confidence": "low", "match_basis": "none",
        "check_status": check_status, "estimation_basis": estimation_basis,
    }
