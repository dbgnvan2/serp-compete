"""C2 / SC-4 — Barbell Positioning Diagnostic.

Purpose: Place each domain on a 2x2 barbell — an AUTHORITY axis (0-100, blending
         EEAT authoritativeness + Moz DA + top-10 ranking count) against a FOCUS
         axis (0-100 = tier-identity concentration, 1 - normalized entropy of the
         medical-vs-systems tier distribution). Winners sit at the two ends
         (authoritative / niche_owner); the undifferentiated middle loses. Thin or
         un-scoreable domains are emerging / insufficient_data — never silently middle.
Spec:    suite_enhancement_spec_v1.md#C2 (SC-4) — see compete-spec.md#C2.
Tests:   tests/test_positioning.py

Design notes:
    * Reuse, don't rebuild. Authority reuses the competitors table (Moz DA) and
      competitor_metrics (top-10 count); focus reuses the semantic tier scores already
      in traffic_magnets. tag_competitor_position's discrete labels remain — this adds
      the continuous 2x2, it doesn't replace them.
    * Commensurability (SC-4 review fix). Authority = {Moz DA, top-10 count} for BOTH
      competitors and the client, so the two sides of the plot use the SAME formula.
      EEAT is deliberately NOT in the authority axis: it is competitor-only (the client
      isn't page-audited, so it could never be commensurable) and it already embeds Moz
      DA internally, which would double-count DA. Competitor EEAT stays in its own
      report section.
    * Pure logic (data in → data out); the DB/GSC glue lives in run_audit.
    * The client is ALWAYS plotted (SC-4.1). Compete audits competitors, not the
      client, so the client's authority comes from config DA + its GSC top-10 count
      and its focus from classifying its GSC queries into tiers (estimation_basis
      "first_party_gsc" vs "audited_pages" for competitors). When the client has no
      GSC data it is still plotted, as insufficient_data.
    * "Focus" here is tier-identity concentration (a domain with a clear medical- or
      systems-language identity is a specialist), NOT topic-count breadth — a
      deliberate, tool-appropriate framing, labelled in the report.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

QUAD_AUTHORITATIVE = "authoritative"
QUAD_NICHE_OWNER = "niche_owner"
QUAD_MIDDLE = "middle"
QUAD_EMERGING = "emerging"
QUAD_INSUFFICIENT = "insufficient_data"

DEFAULT_AUTHORITY_THRESHOLD = 50
DEFAULT_FOCUS_THRESHOLD = 50
DEFAULT_AUTHORITY_WEIGHTS = {"moz_da": 0.7, "top10": 0.3}
DEFAULT_TOP10_SATURATION = 10
DEFAULT_MIN_SIGNAL_RANKINGS = 2


def normalized_entropy(counts: List[float]) -> float:
    """Shannon entropy of the distribution, normalized to 0..1 by log(k).

    0.0 = fully concentrated (one bucket), 1.0 = uniform across the k non-empty
    buckets. Empty or single-bucket input → 0.0 (maximally concentrated).
    """
    positive = [float(c) for c in counts if c and c > 0]
    total = sum(positive)
    if total <= 0 or len(positive) <= 1:
        return 0.0
    ps = [c / total for c in positive]
    h = -sum(p * math.log(p) for p in ps)
    return h / math.log(len(positive))


def compute_authority(moz_da: Optional[float], top10_count: Optional[int],
                      config: Dict[str, Any]) -> Optional[float]:
    """0-100 authority composite from {Moz DA, top-10 count} — the SAME formula for
    competitors and the client (SC-4 commensurability fix). Renormalized over the
    components actually present (a missing DA is excluded, never counted as 0).
    Returns None when no component is available."""
    weights = config.get("authority_weights", DEFAULT_AUTHORITY_WEIGHTS)
    saturation = config.get("top10_saturation", DEFAULT_TOP10_SATURATION) or DEFAULT_TOP10_SATURATION
    comps: List[Tuple[float, float]] = []  # (value_0_100, weight)
    if moz_da is not None:
        comps.append((max(0.0, min(float(moz_da), 100.0)), weights.get("moz_da", 0.7)))
    if top10_count is not None and top10_count > 0:
        comps.append((min(top10_count / saturation, 1.0) * 100.0, weights.get("top10", 0.3)))
    wsum = sum(w for _, w in comps)
    if not comps or wsum <= 0:
        return None
    return round(sum(v * w for v, w in comps) / wsum, 1)


def compute_focus(medical_total: float, systems_total: float) -> Optional[float]:
    """0-100 focus = tier-identity concentration = (1 - normalized_entropy) * 100.
    Returns None when there is no tier signal at all (can't place the domain)."""
    medical = float(medical_total or 0)
    systems = float(systems_total or 0)
    if medical + systems <= 0:
        return None
    return round((1.0 - normalized_entropy([medical, systems])) * 100.0, 1)


def classify_quadrant(authority: float, focus: float, config: Dict[str, Any]) -> str:
    """The barbell 2x2 (SC-4.3). High authority → authoritative (the large-and-
    authoritative end); else high focus → niche_owner (the small-and-niche end);
    else the undifferentiated middle."""
    if authority >= config.get("authority_threshold", DEFAULT_AUTHORITY_THRESHOLD):
        return QUAD_AUTHORITATIVE
    if focus >= config.get("focus_threshold", DEFAULT_FOCUS_THRESHOLD):
        return QUAD_NICHE_OWNER
    return QUAD_MIDDLE


def classify_query_tiers(queries: List[str], clinical_vocab: Dict[str, Any]) -> Tuple[int, int]:
    """Classify the client's GSC queries into (medical, systems) tier counts using the
    editorial `clinical` vocab — the client's focus input (it isn't page-audited)."""
    t1 = [str(w).lower() for w in (clinical_vocab.get("tier_1_medical") or [])]
    systems_terms = [str(w).lower() for w in
                     ((clinical_vocab.get("tier_2_systems") or []) +
                      (clinical_vocab.get("tier_3_bowen") or []))]
    medical = systems = 0
    for q in queries or []:
        ql = str(q or "").lower()
        if any(term in ql for term in t1):
            medical += 1
        if any(term in ql for term in systems_terms):
            systems += 1
    return medical, systems


def positioning_row(domain: str, inputs: Dict[str, Any], is_client: bool,
                    config: Dict[str, Any]) -> Dict[str, Any]:
    """Compute one domain's authority, focus, quadrant, and the driving numbers.

    A domain missing either axis → insufficient_data. A thin domain (fewer than
    min_signal_rankings top-10 rankings) is emerging ONLY if it is also below the
    authority threshold — an established, high-DA rival that simply doesn't rank for
    the tracked keywords is still authoritative, not "emerging". Never silently middle.
    """
    moz = inputs.get("moz_da")
    top10 = int(inputs.get("top10_count") or 0)
    medical = inputs.get("medical_total") or 0
    systems = inputs.get("systems_total") or 0
    authority = compute_authority(moz, top10, config)
    focus = compute_focus(medical, systems)
    min_signal = config.get("min_signal_rankings", DEFAULT_MIN_SIGNAL_RANKINGS)
    auth_threshold = config.get("authority_threshold", DEFAULT_AUTHORITY_THRESHOLD)

    if authority is None or focus is None:
        quadrant = QUAD_INSUFFICIENT
    elif top10 < min_signal and authority < auth_threshold:
        quadrant = QUAD_EMERGING
    else:
        quadrant = classify_quadrant(authority, focus, config)

    rationale = {
        "moz_da": moz, "top10_count": top10,
        "medical_total": medical, "systems_total": systems,
        "authority_score": authority, "focus_score": focus,
        "authority_threshold": auth_threshold,
        "focus_threshold": config.get("focus_threshold", DEFAULT_FOCUS_THRESHOLD),
    }
    return {
        "domain": domain,
        "is_client": is_client,
        "authority_score": authority,
        "focus_score": focus,
        "quadrant": quadrant,
        "rationale": rationale,
        "estimation_basis": "first_party_gsc" if is_client else "audited_pages",
    }


def compute_positioning(competitor_inputs: Dict[str, Dict[str, Any]],
                        client_domain: str, client_inputs: Dict[str, Any],
                        config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Positioning rows for every competitor PLUS the client (always plotted, SC-4.1)."""
    rows = [positioning_row(domain, inputs, False, config)
            for domain, inputs in sorted(competitor_inputs.items())]
    rows.append(positioning_row(client_domain, client_inputs or {}, True, config))
    return rows
