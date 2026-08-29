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
    if not isinstance(handoff, dict):
        return {}
    moz = handoff.get("moz")
    return moz if isinstance(moz, dict) else {}


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
    for domain, block in ((moz_block or {}).get("domains") or {}).items():
        if not isinstance(block, dict):
            continue
        anchors = block.get("anchor_texts") or {}
        items = anchors.get("items") or []
        if items:
            out[domain] = {"items": items, "truncated": bool(anchors.get("truncated"))}
    return out


def anchor_coverage(moz_block: Dict[str, Any]) -> Dict[str, int]:
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
    for _domain, block in ((moz_block or {}).get("domains") or {}).items():
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
