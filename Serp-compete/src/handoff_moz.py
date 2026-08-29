"""
handoff_moz.py
~~~~~~~~~~~~~~
Read the optional Moz block from a Tool 1 competitor handoff.

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
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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
    """Extract `{domain: {items, truncated}}` from a handoff `moz` block.

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
        entries.append((client["domain"], client))

    for domain, block in entries:
        if not isinstance(block, dict):
            continue
        anchors = block.get("anchor_texts") or {}
        items = anchors.get("items") or []
        if items:
            out[domain] = {
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
    """
    keep = {str(d).lower() for d in (domains or []) if d}
    if client_domain:
        keep.add(client_domain.lower())
    return {d: v for d, v in (anchors or {}).items() if str(d).lower() in keep}


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
    """
    counts = {"total": 0, "with_anchors": 0, "read_no_anchors": 0,
              "no_record": 0, "errored": 0, "skipped": 0, "unknown": 0}
    all_domains = ((moz_block or {}).get("domains") or {})
    if domains is not None or client_domain:
        # Count only what this run examined. Tool 1 builds moz.domains from
        # every organic competitor and caps the fetch at max_competitors, so
        # counting the whole block made the report warn about ~30 domains this
        # run never looked at — a claim of blindness it does not have, which is
        # the same class of dishonesty as claiming a clean bill (P3/P6).
        keep = {str(d).lower() for d in (domains or []) if d}
        if client_domain:
            keep.add(client_domain.lower())
        all_domains = {d: v for d, v in all_domains.items() if str(d).lower() in keep}
    blocks = list(all_domains.values())
    client = (moz_block or {}).get("client")
    if isinstance(client, dict) and client.get("anchor_texts"):
        # Counted alongside the competitors: a failed fetch of the client's own
        # anchors must be as visible as any other, and it is the one that would
        # hide a negative-SEO campaign aimed at the client.
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
