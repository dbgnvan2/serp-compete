"""C6 / SC-8 — Reputation-Risk / Site-Reputation-Abuse Radar.

Purpose: Flag competitors (and warn on the client's own site) showing patterns Google
         penalizes — a sudden visibility collapse (visibility_cliff), an off-topic
         commercial subfolder on an authoritative domain (parasite_subfolder),
         ranking volatility, and a paid-link/PBN footprint in inbound anchor text
         (anchor_text_spam) — as PATTERN DETECTIONS, not confirmed penalties.
Spec:    suite_enhancement_spec_v1.md#C6 (SC-8) — see compete-spec.md#C6.
Tests:   tests/test_risk_radar.py

Reuse (don't rebuild): ranking volatility comes from db.get_volatility_alerts; the
visibility series from market_history; the topical-mismatch idea from the C2/SC-4 focus
work. New: the cliff + parasite detectors and the unified radar (own-site separated).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

DEFAULT_CLIFF_DROP_PCT = 0.3
DEFAULT_CLIFF_LOOKBACK = 6
DEFAULT_VOLATILITY_HIGH_SHIFT = 6
DEFAULT_COMMERCIAL_TERMS = [
    "casino", "loan", "loans", "cheap", "deal", "deals", "coupon", "promo", "betting",
    "crypto", "insurance", "buy", "discount", "vpn", "forex", "gambling", "payday",
]


def detect_visibility_cliff(series: List[float], config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """A step-change collapse: the latest visibility dropped >= cliff_drop_pct below the
    RECENT peak (SC-8.1). Severity scales with the drop; the drop % is in the evidence.

    The peak is taken from the last `cliff_lookback` snapshots only — a collapse that
    happened long ago and has since been flat-low scrolls out of the window and stops
    re-flagging every run (a full-history max would flag it forever)."""
    config = config or {}
    drop_pct = config.get("cliff_drop_pct", DEFAULT_CLIFF_DROP_PCT)
    lookback = config.get("cliff_lookback", DEFAULT_CLIFF_LOOKBACK)
    values = [float(v) for v in (series or []) if v is not None]
    if lookback and len(values) > lookback:
        values = values[-lookback:]
    if len(values) < 2:
        return None
    peak = max(values[:-1])
    latest = values[-1]
    if peak <= 0:
        return None
    drop = (peak - latest) / peak
    if drop >= drop_pct:
        severity = "high" if drop >= 0.5 else ("medium" if drop >= 0.3 else "low")
        return {"signal_type": "visibility_cliff", "severity": severity,
                "evidence": {"peak": peak, "latest": latest, "drop_pct": round(drop * 100.0, 1)}}
    return None


def _words(items: List[Any]) -> set:
    out: set = set()
    for it in items or []:
        out.update(re.findall(r"[a-z0-9]+", str(it).lower()))
    return out


def detect_parasite(subfolder: str, subfolder_keywords: List[str],
                    domain_core_terms: List[str], commercial_terms: List[str]) -> Optional[Dict[str, Any]]:
    """A parasite/affiliate arm: a subfolder whose keywords are BOTH topically
    mismatched from the domain's core AND commercial-intent (SC-8.2). Requires both —
    the subfolder NAME alone never triggers it (only its keywords are inspected)."""
    sub = _words(subfolder_keywords)
    if not sub:
        return None
    topical_mismatch = len(sub & _words(domain_core_terms)) == 0
    # Word-boundary match (not substring) so "deal" doesn't fire on "dealing", nor
    # "promo" on "promoting" — a whole-word commercial term must appear in a keyword.
    has_commercial = bool(sub & {str(ct).strip().lower() for ct in (commercial_terms or [])})
    if topical_mismatch and has_commercial:
        return {"signal_type": "parasite_subfolder", "severity": "medium",
                "evidence": {"subfolder": subfolder, "topical_mismatch": True,
                             "has_commercial_intent": True,
                             "sample_keywords": list(subfolder_keywords)[:5]}}
    return None


DEFAULT_ANCHOR_SPAM_TERMS = [
    "backlinks", "dofollow", "pbn", "link building", "buy backlinks",
    "guest post", "seo service", "rank first page", "cheap seo",
]
DEFAULT_ANCHOR_SPAM_MIN_DOMAINS = 1
DEFAULT_ANCHOR_SPAM_HIGH_SHARE = 0.25


def _normalised(text: Any) -> str:
    """Lower-case, punctuation-stripped, space-delimited form of *text*.

    Padded with spaces so a term can be matched on whole-word boundaries —
    "seo service" must not fire on "seo services-and-more" being a substring
    of some longer token run, and "pbn" must not fire inside "pbnetwork".
    """
    return " " + " ".join(re.findall(r"[a-z0-9]+", str(text).lower())) + " "


def detect_anchor_spam(anchor_texts: List[Dict[str, Any]],
                       config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Flag inbound anchor text carrying a paid-link / PBN footprint (SC-8.4).

    Purpose: surface link-scheme patterns in the anchor distribution Tool 1
             now hands over, as a pattern detection.
    Spec:    moz_api_upgrade_spec_v1.md#T.4 (producer); compete-spec.md#C6.
    Tests:   tests/test_risk_radar.py::TestAnchorSpam

    Anchors are written by *other* sites, so this says the domain **receives**
    spam-shaped links — never that it bought them. A domain can be the target
    of a negative-SEO or scraper campaign it had no part in, and the evidence
    is worded to keep that reading open. Like every signal in this module it
    is a pattern detection, not a confirmed penalty.

    Severity follows the share of linking root domains behind the matched
    anchors, not the number of distinct phrases: one spam anchor carried by
    forty domains matters more than four carried by one each.
    """
    config = config or {}
    terms = config.get("anchor_spam_terms", DEFAULT_ANCHOR_SPAM_TERMS)
    min_domains = config.get("anchor_spam_min_domains", DEFAULT_ANCHOR_SPAM_MIN_DOMAINS)
    high_share = config.get("anchor_spam_high_share", DEFAULT_ANCHOR_SPAM_HIGH_SHARE)
    normalised_terms = [_normalised(t).strip() for t in (terms or []) if str(t).strip()]
    if not normalised_terms:
        return None

    matched, matched_domains, total_domains = [], 0, 0
    for entry in anchor_texts or []:
        if not isinstance(entry, dict):
            continue
        try:
            domains = int(entry.get("external_root_domains") or 0)
        except (TypeError, ValueError):
            domains = 0
        total_domains += domains
        haystack = _normalised(entry.get("text"))
        hits = [t for t in normalised_terms if f" {t} " in haystack]
        if hits and domains >= min_domains:
            matched_domains += domains
            matched.append({
                "text": str(entry.get("text") or "")[:160],
                "external_root_domains": domains,
                "matched_terms": hits,
            })

    if not matched:
        return None

    # Guard the division: a matched anchor always contributes to both sides,
    # so total_domains cannot be 0 here, but an explicit floor keeps a future
    # change to the accumulation from producing a ZeroDivisionError.
    share = (matched_domains / total_domains) if total_domains else 0.0
    matched.sort(key=lambda m: m["external_root_domains"], reverse=True)
    return {
        "signal_type": "anchor_text_spam",
        "severity": "high" if share >= high_share else "medium",
        "evidence": {
            "matched_anchor_count": len(matched),
            "linking_domains_matched": matched_domains,
            "linking_domains_sampled": total_domains,
            "share_of_sampled_linking_domains": round(share, 3),
            "sample_anchors": matched[:5],
            "interpretation": (
                "Inbound anchors show a paid-link/PBN footprint. Anchors are "
                "written by other sites, so this indicates links RECEIVED, not "
                "links necessarily bought — a domain can be targeted by a "
                "scheme it had no part in. Pattern detection, not a penalty."
            ),
        },
    }


def compute_risk_signals(volatility_alerts: List[Dict[str, Any]],
                         series_by_domain: Dict[str, List[float]],
                         parasite_candidates: List[Dict[str, Any]],
                         own_domain: str, config: Optional[Dict[str, Any]] = None,
                         anchor_texts_by_domain: Optional[Dict[str, List[Dict[str, Any]]]] = None
                         ) -> List[Dict[str, Any]]:
    """Unify the detectors into one risk feed, tagging each signal is_own_site so the
    report can separate own-site warnings from competitor intel (SC-8.3)."""
    config = config or {}
    own = (own_domain or "").lower()
    commercial = config.get("commercial_terms", DEFAULT_COMMERCIAL_TERMS)
    high_shift = config.get("volatility_high_shift", DEFAULT_VOLATILITY_HIGH_SHIFT)
    rows: List[Dict[str, Any]] = []

    def add(domain: Optional[str], sig: Optional[Dict[str, Any]]) -> None:
        if sig and domain:
            rows.append({**sig, "domain": domain, "is_own_site": domain.lower() == own})

    for domain, series in (series_by_domain or {}).items():
        add(domain, detect_visibility_cliff(series, config))
    for cand in parasite_candidates or []:
        add(cand.get("domain"), detect_parasite(
            cand.get("subfolder"), cand.get("keywords"), cand.get("core_terms"), commercial))
    for domain, anchors in (anchor_texts_by_domain or {}).items():
        add(domain, detect_anchor_spam(anchors, config))
    for alert in volatility_alerts or []:
        shift = alert.get("shift") or 0
        add(alert.get("domain"), {
            "signal_type": "ranking_volatility",
            "severity": "high" if abs(shift) >= high_shift else "medium",
            "evidence": {"position_shift": shift}})
    return rows
