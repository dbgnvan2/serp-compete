"""
handoff_moz.py
~~~~~~~~~~~~~~
Read the optional Moz block from a Tool 1 competitor handoff, and hold the
facts about the validated handoff that the run needs after ingestion has
finished (its Moz block and its `schema_version`).

Purpose: give the reputation-risk radar the anchor-text distribution Tool 1
         collects, without widening any existing contract.
Spec:    serp-discover moz_api_upgrade_spec_v1.md#T.4 (producer side);
         compete-spec.md#C6 (consumer).
Tests:   tests/test_risk_radar.py::TestHandoffMozIngestion

Its own module rather than a helper in `main.py`: `main` imports the whole
application (pandas, the report generator, the API clients) at module load, so
anything living there cannot be unit-tested without the full dependency set.
These are pure functions over a dict and deserve to be reachable on their own.

File discovery stays in `main.py`, which already owns it — these functions take
a path, so there is no second implementation of "find the latest handoff" to
drift from the first.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

# brand_utils is dependency-free by design, so this import is safe here. There
# is deliberately no fallback: the `ImportError` branch that used to sit here
# defined a ninth copy of the host rule stripping `www.` only, so under it the
# client compare, the mismatch check, the anchor keys and `restrict_to_run` all
# silently reverted to the pre-Y1 rule and nothing could tell. An import that
# cannot be satisfied should fail, not degrade to a different answer (P45,
# cold review of chunk Y1).
from src.brand_utils import normalise_domain


def load_moz_block(handoff_path: Optional[str]) -> Dict[str, Any]:
    """Return the `moz` block from the handoff at *handoff_path*.

    Returns `{}` when the path is missing, the file is unreadable, or the
    handoff came from a Tool 1 run with the Moz features off (schema_version
    1.0). Nothing is inferred from an absent block: "Tool 1 did not collect
    this" and "Tool 1 collected it and found nothing" are different facts, and
    only the producer can tell them apart.
    """
    if not handoff_path:
        return {}
    try:
        with open(handoff_path, "r", encoding="utf-8") as f:
            handoff = json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning("Could not read the Moz block from %s: %s", handoff_path, exc)
        return {}
    return moz_block_from(handoff)


def moz_block_from(handoff: Any) -> Dict[str, Any]:
    """Return the `moz` block of an already-loaded handoff dict.

    The one definition of "which part of a handoff is the Moz block", shared by
    :func:`load_moz_block` and by `main.py`, which reuses the handoff it has
    already validated rather than reading the file a second time unchecked.
    """
    if not isinstance(handoff, dict):
        return {}
    moz = handoff.get("moz")
    return moz if isinstance(moz, dict) else {}


#: The `moz` block of the handoff the caller has already validated. Held here
#: rather than in `main.py` because `main` imports the whole application at
#: module load (pandas, spacy, the report generator), so state living there
#: cannot be exercised by a test — the same reason the rest of this module
#: exists (P21/P27).
_VALIDATED_MOZ_BLOCK: Dict[str, Any] = {}


def remember_moz_block(handoff: Any) -> None:
    """Retain the `moz` block of an already-validated handoff.

    Call with `{}` at the start of each ingestion: the legacy and manual paths
    never set a block, so a second run in one process would otherwise inherit
    the previous handoff's anchors (P8).

    Never raises. The caller runs this inside an ingestion guard whose handler
    exits the process, and an optional signal must not be able to abort the
    audit and blame the handoff file for it (P13).
    """
    global _VALIDATED_MOZ_BLOCK
    try:
        _VALIDATED_MOZ_BLOCK = moz_block_from(handoff)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Moz block not retained: %s", exc)
        _VALIDATED_MOZ_BLOCK = {}


def validated_moz_block() -> Dict[str, Any]:
    """The block retained by :func:`remember_moz_block`, or `{}`."""
    return _VALIDATED_MOZ_BLOCK


#: The `schema_version` of the handoff that was validated, retained for the
#: same reason and by the same call as the Moz block above. It is needed late
#: in the run — when the report's coverage block is assembled — and the
#: alternative was either re-reading the handoff file unvalidated (which the
#: caller's own comment warns against) or widening
#: `get_latest_market_data`'s return tuple, which every caller unpacks
#: positionally (P22).
_VALIDATED_SCHEMA_VERSION: str = ""


def remember_handoff_version(handoff: Any) -> None:
    """Retain the validated handoff's `schema_version`. Never raises.

    Call with `{}` at the start of each ingestion: the legacy and manual paths
    carry no version, and a second run in one process must not inherit the
    previous handoff's (P8).
    """
    global _VALIDATED_SCHEMA_VERSION
    try:
        version = (handoff or {}).get("schema_version") if isinstance(handoff, dict) else ""
        _VALIDATED_SCHEMA_VERSION = str(version or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Handoff version not retained: %s", exc)
        _VALIDATED_SCHEMA_VERSION = ""


#: The `client_domain` the producer published, retained for the same reason
#: and by the same call. Nothing read this field: compete takes the client host
#: from its own `shared_config.client.domain`, so the two tools' agreement on
#: which site is the client rested on two independently edited config values
#: that nothing reconciled (review chunk Y1). Reading it does not make it the
#: authority — this repo's own config stays that — but a mismatch is now
#: reported instead of producing a report about somebody else's client.
_VALIDATED_CLIENT_DOMAIN: str = ""


def remember_client_domain(handoff: Any) -> None:
    """Retain the validated handoff's `client_domain`. Never raises.

    Call with `{}` at the start of each ingestion, like the two above: the
    legacy and manual paths carry no client domain and a second run in one
    process must not inherit the previous handoff's (P8).
    """
    global _VALIDATED_CLIENT_DOMAIN
    try:
        raw = (handoff or {}).get("client_domain") if isinstance(handoff, dict) else ""
        _VALIDATED_CLIENT_DOMAIN = normalise_domain(raw or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Handoff client domain not retained: %s", exc)
        _VALIDATED_CLIENT_DOMAIN = ""


def validated_client_domain() -> str:
    """The canonical client host the handoff published, or `""`.

    `""` means the handoff did not say — the legacy or manual path, or a
    pre-2.0 file — which is not a disagreement.
    """
    return _VALIDATED_CLIENT_DOMAIN


def client_domain_mismatch(configured: str) -> str:
    """One sentence when the handoff's client is not this repo's, else `""`."""
    published = validated_client_domain()
    mine = normalise_domain(configured or "")
    if not published or not mine or published == mine:
        return ""
    return (f"the handoff was produced for `{published}` but this repo's "
            f"`shared_config.client.domain` is `{mine}` — every figure below "
            f"compares one client's SERPs with another's configuration")


def validated_handoff_version() -> str:
    """The version retained by :func:`remember_handoff_version`, or `""`.

    `""` means "no versioned handoff was ingested" — the legacy
    `market_analysis_*.json` or `manual_targets.json` path, or no source at
    all. It does not mean version 1.0.
    """
    return _VALIDATED_SCHEMA_VERSION


def handoff_rank_is_absolute(version: str = None,
                             absolute_versions: Optional[Iterable[Any]] = None) -> Optional[bool]:
    """Does this handoff's `targets[].rank` count results across whole SERPs?

    Purpose: stop a page-relative rank being printed as a SERP position.
    Spec:    docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md §3 Chunk X
             ("Rank semantics"), §1 H1 / D-C-01.
    Tests:   Serp-compete/tests/test_handoff_contract.py::TestRankSemantics

    serp-discover stores SerpAPI's per-page `position` verbatim as `Rank` and
    concatenates paginated pages without an offset, so in its 3-page mode the
    handoff's ranks run `1..9, 1..10, 1..10` — three results claim rank 1 and a
    page-3 result reports rank 2. Chunk D1 fixes the producer and bumps
    `schema_version`; until a handoff carries one of the versions listed in
    `handoff.absolute_rank_versions`, this tool is consuming page-relative
    ranks and the report has to say so.

    Returns None for `""` — the legacy and manual paths carry no version and
    no rank either, so there is nothing to qualify.
    """
    if version is None:
        version = validated_handoff_version()
    version = str(version or "")
    if not version:
        return None
    if absolute_versions is None:
        try:
            from src.database import load_shared_config
            absolute_versions = (load_shared_config().get("handoff", {}) or {}).get(
                "absolute_rank_versions") or []
        except Exception:  # noqa: BLE001 - never block a run on a config read
            absolute_versions = []
    return version in {str(v) for v in absolute_versions}


def moz_collected_at(moz_block: Dict[str, Any]) -> Optional[str]:
    """When the handoff was **assembled** (`moz.generated_at`).

    This is an upper bound on freshness, not a collection time: Tool 1 stamps
    it when it builds the block, and a domain served from its 30-day cache can
    be far older. Prefer the per-domain `fetched_at` that
    :func:`anchor_texts_by_domain` carries; this is the fallback for a handoff
    produced before Tool 1 sent per-domain dates.
    """
    value = (moz_block or {}).get("generated_at")
    return value if isinstance(value, str) and value else None


def _domain_collected_at(block: Dict[str, Any], fallback: Optional[str]) -> Optional[str]:
    """When THIS domain's signals were collected.

    Tool 1 carries `fetched_at` per domain precisely because a cached block can
    predate the handoff by weeks. Using the assembly timestamp for a cached
    domain reports 27-day-old anchors as a same-day observation, which is the
    stale attribution this is meant to prevent (P6).
    """
    value = block.get("fetched_at")
    return value if isinstance(value, str) and value else fallback


def anchor_texts_by_domain(moz_block: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extract `{canonical domain: {items, truncated}}` from a handoff `moz` block.

    Keys are normalised (lower-cased, `www.` stripped) because this dict's keys
    become the domain names the risk feed prints, and the rest of the run —
    `competitor_metrics`, the brand tokens, the omit list — uses the canonical
    form. A finding filed against `www.x.com` while every other section of the
    report calls the same site `x.com` reads as a second competitor (Chunk X,
    canonical domain form).

    Domains with no anchors are omitted rather than mapped to an empty block,
    so "no anchors were collected for this domain" cannot be read downstream as
    "this domain has no spam anchors".

    `truncated` is carried through because the producer sets it expressly so a
    capped page is not mistaken for a complete link profile — a detector that
    computes a share against a truncated sample is dividing by a denominator it
    knows is too small.

    Whether a domain is missing because Moz *errored* or because it genuinely
    has nothing is not knowable from this map by design; use
    :func:`anchor_coverage` to report that, and never infer it from absence.
    """
    out: Dict[str, Dict[str, Any]] = {}
    assembled_at = moz_collected_at(moz_block)
    entries = list(((moz_block or {}).get("domains") or {}).items())

    # The client's own anchors travel in `moz.client`, not `domains` — Tool 1
    # excludes the client from the competitor list by design. Including it here
    # is what lets the radar tag an own-site hit: without it, the branch that
    # would reveal a negative-SEO campaign aimed at the client had no data at
    # all, and was tested and documented against a shape the producer could
    # never emit (learnings P21).
    client = (moz_block or {}).get("client")
    if isinstance(client, dict) and client.get("domain"):
        # Appended last deliberately. If the same domain somehow appears in
        # both, it is one site, not two, and the client entry is the
        # authoritative source for the client's own anchors — so it should
        # win. What must NOT happen is that domain being counted twice, and
        # `anchor_coverage` handles that separately.
        entries.append((client["domain"], client))

    for domain, block in entries:
        if not isinstance(block, dict):
            continue
        anchors = block.get("anchor_texts") or {}
        items = anchors.get("items") or []
        if items:
            key = normalise_domain(domain)
            # Two spellings of one site can both carry anchors. They are one
            # link profile, so the richer sample wins rather than whichever the
            # producer happened to serialise last — except that the client entry
            # is appended last deliberately and must keep winning for its own
            # domain (see the comment above).
            existing = out.get(key)
            # The client's own domain is compared in the canonical form, like
            # every other host here. A raw compare made this test depend on
            # the producer's spelling of one field (review chunk Y1); files
            # already on disk carry the pre-chunk-X form.
            client_key = normalise_domain(
                ((moz_block or {}).get("client") or {}).get("domain", ""))
            if existing and len(existing.get("items") or []) > len(items) \
                    and normalise_domain(domain) != client_key:
                continue
            out[key] = {
                "items": items,
                "truncated": bool(anchors.get("truncated")),
                "collected_at": _domain_collected_at(block, assembled_at),
            }
    return out


def restrict_to_run(anchors: Dict[str, Any], domains, client_domain: str = "") -> Dict[str, Any]:
    """Keep only the anchor entries belonging to this run's targets.

    Purpose: stop a signal being attributed to a domain the run never saw.
    Spec:    compete-spec.md#C6 (SC-8.4)
    Tests:   tests/test_risk_radar.py::TestRunScoping

    Tool 1 caches per domain for up to 30 days, so a handoff can carry anchors
    for a competitor that has since dropped out of the SERP entirely. Filing a
    finding against it would put a named third party in the report on the
    strength of data from a run that no longer reflects the market (P6).

    The client is always kept when present: it is excluded from the competitor
    list by design but is exactly the domain the own-site check is for.

    Both sides are compared in canonical form. Tool 1 writes `moz.domains` keys
    as `netloc.lower()` with `www.` kept while this run's domain list is
    canonical, so a plain lower-case comparison dropped every `www.` host —
    filtering the anchors down to nothing and rendering a run with real
    findings as one with none (Chunk X, canonical domain form).
    """
    keep = {normalise_domain(d) for d in (domains or []) if d}
    if client_domain:
        keep.add(normalise_domain(client_domain))
    return {d: v for d, v in (anchors or {}).items()
            if normalise_domain(d) in keep}


#: Hours by which a domain's `fetched_at` may trail the handoff's
#: `generated_at` and still count as fetched during that run. Editorial and
#: uncalibrated (2026-11-16, decision 7): a Tool 1 run is assembled in one
#: session, so anything collected more than a day before assembly came out of
#: its 30-day cache rather than off the wire. Overridden by
#: `risk_signals.moz_cache_tolerance_hours`.
DEFAULT_MOZ_CACHE_TOLERANCE_HOURS = 24.0


def _cache_tolerance_hours() -> float:
    try:
        from src.database import load_shared_config
    except ImportError:  # pragma: no cover - standalone use
        return DEFAULT_MOZ_CACHE_TOLERANCE_HOURS
    try:
        signals = load_shared_config().get("risk_signals", {}) or {}
        return float(signals.get("moz_cache_tolerance_hours",
                                 DEFAULT_MOZ_CACHE_TOLERANCE_HOURS))
    except Exception:  # noqa: BLE001 - an optional signal must not abort a run
        return DEFAULT_MOZ_CACHE_TOLERANCE_HOURS


def _parse_iso(value: Any) -> Optional[datetime]:
    """A timezone-aware datetime from an ISO 8601 string, else None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def error_is_cached(block: Dict[str, Any], assembled_at: Any,
                    tolerance_hours: Optional[float] = None) -> Optional[bool]:
    """True when this domain's error block was re-served from Tool 1's cache.

    Purpose: stop one Moz outage reading as N fresh ones.

    Tool 1 caches a competitor's Moz block for up to 30 days and can cache it
    with a failed sub-call in it (D-C-10), so the same error is re-served every
    run until the cache expires. A consumer that counts `status == "error"`
    without its age reports a month-old failure as today's outage, and reports
    five such domains as five separate failures — the transient-as-permanent
    collapse in reverse (P1).

    Returns None when the age cannot be established: neither "fresh" nor
    "cached" may be assumed from a missing timestamp.
    """
    if tolerance_hours is None:
        tolerance_hours = _cache_tolerance_hours()
    fetched = _parse_iso(block.get("fetched_at"))
    assembled = _parse_iso(assembled_at)
    if fetched is None or assembled is None:
        return None
    return (assembled - fetched).total_seconds() > tolerance_hours * 3600.0


def anchor_coverage(moz_block: Dict[str, Any], domains=None,
                    client_domain: str = "") -> Dict[str, int]:
    """Count how the anchor fetch actually went, per status.

    Purpose: keep a Moz outage from reading as a clean bill of health.
    Tests:   tests/test_risk_radar.py::TestHandoffMozIngestion

    The producer distinguishes ok / no_record / error precisely so the consumer
    can tell "we looked and found nothing" from "we could not look". Collapsing
    both into an absent domain would let a run of 429s render as "no anchor
    risks found" (learnings P1/P2), so the counts are reported alongside the
    signals rather than inferred from what is missing.

    `errored` stays the total number of error blocks. `errored_cached` and
    `errored_age_unknown` are sub-counts of it, not additions to it, so an
    existing reader of `errored` keeps its meaning (P22).
    """
    counts = {"total": 0, "with_anchors": 0, "read_no_anchors": 0,
              "no_record": 0, "errored": 0, "skipped": 0, "unknown": 0,
              "errored_cached": 0, "errored_age_unknown": 0}
    assembled_at = moz_collected_at(moz_block)
    tolerance = _cache_tolerance_hours()
    all_domains = ((moz_block or {}).get("domains") or {})
    # Scope ONLY on an explicit domain list. Triggering on client_domain alone
    # filtered every competitor out and returned all zeros, so a run where a
    # fetch errored rendered as clean — the caveat sees 0 unreadable (P2).
    if domains is not None:
        # Count only what this run examined. Tool 1 builds moz.domains from
        # every organic competitor and caps the fetch at max_competitors, so
        # counting the whole block made the report warn about ~30 domains this
        # run never looked at — a claim of blindness it does not have, which is
        # the same class of dishonesty as claiming a clean bill (P3/P6).
        # Canonical form on both sides: Tool 1's keys keep `www.` and the run's
        # domain list does not, so a lower-case-only comparison dropped every
        # `www.` host and returned all zeros — a run where fetches errored then
        # rendered as clean, which is the very thing this function exists to
        # prevent (Chunk X, canonical domain form).
        keep = {normalise_domain(d) for d in (domains or []) if d}
        if client_domain:
            keep.add(normalise_domain(client_domain))
        all_domains = {d: v for d, v in all_domains.items()
                       if normalise_domain(d) in keep}
    client = (moz_block or {}).get("client")
    client_domain_key = normalise_domain((client or {}).get("domain", ""))
    if isinstance(client, dict) and client.get("anchor_texts") and client_domain_key:
        # The client block WINS for its own domain, matching
        # anchor_texts_by_domain. Counting the `domains` block while extraction
        # analysed the client block made the caveat say the client's anchors
        # could not be read on the very run where they were read — and an
        # own-site signal may have been raised from them (P6).
        all_domains = {d: v for d, v in all_domains.items()
                       if normalise_domain(d) != client_domain_key}
    blocks = list(all_domains.values())
    if isinstance(client, dict) and client.get("anchor_texts"):
        # A failed fetch of the client's own anchors must be as visible as any
        # other — it is the one that would hide a campaign aimed at the client.
        blocks.append(client)
    for block in blocks:
        if not isinstance(block, dict):
            continue
        counts["total"] += 1
        anchors = block.get("anchor_texts") or {}
        if anchors.get("items"):
            counts["with_anchors"] += 1
            continue
        # A domain the producer capped or skipped for quota carries no
        # `anchor_texts` key at all, so its status lives on the domain block.
        # Falling back to it matters: without this, "Tool 1 ran out of row
        # budget" was counted as "Moz has no record", which is exactly the
        # transient-as-terminal collapse this function exists to prevent (P1).
        status = anchors.get("status") or block.get("status")
        if status == "error":
            counts["errored"] += 1
            # …and whether it is this run's outage or a cached one being
            # re-served. Five domains carrying a month-old cached failure are
            # one historical outage, not five fresh ones, and the report should
            # not ask the owner to go and check Moz over them (D-C-10).
            cached = error_is_cached(block, assembled_at, tolerance)
            if cached is True:
                counts["errored_cached"] += 1
            elif cached is None:
                counts["errored_age_unknown"] += 1
        elif status in ("skipped_run_cap", "skipped_quota"):
            counts["skipped"] += 1
        elif status == "no_record":
            counts["no_record"] += 1
        elif status == "ok":
            # Read successfully, genuinely no anchors. This is the producer's
            # ordinary shape for a domain with ranking data but no anchor text,
            # and it is NOT unreadable — bucketing it "unknown" put a caveat
            # warning of untrustworthy data on a clean run, naming no cause
            # ("0 errored, 0 skipped, 0 no record"). The same measured-vs-
            # unmeasured collapse the detector was just fixed for (P1/P14).
            counts["read_no_anchors"] += 1
        else:
            counts["unknown"] += 1
    return counts
