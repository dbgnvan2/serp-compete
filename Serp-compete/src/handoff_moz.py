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


def anchor_texts_by_domain(moz_block: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Extract `{domain: [anchor, ...]}` from a handoff `moz` block.

    Domains whose anchor fetch failed or found nothing are omitted rather than
    mapped to an empty list, so "no anchors were collected for this domain"
    cannot be read downstream as "this domain has no spam anchors".
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for domain, block in ((moz_block or {}).get("domains") or {}).items():
        if not isinstance(block, dict):
            continue
        items = ((block.get("anchor_texts") or {}).get("items")) or []
        if items:
            out[domain] = items
    return out
