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

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

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


#: Fallback only — `shared_config.json` `risk_signals.anchor_spam_terms` is the
#: editorial source of record. Kept byte-identical to it and guarded by a test,
#: because a fallback that silently drifts makes the same anchors score
#: differently depending on which call path reached the detector (P4).
DEFAULT_ANCHOR_SPAM_TERMS = [
    "backlinks", "dofollow", "pbn", "link building", "buy backlinks",
    "guest post", "seo service", "seo services", "rank first page",
    "cheap seo", "link farm", "paid links",
]
#: An anchor carried by fewer than this many root domains is ignored entirely.
DEFAULT_ANCHOR_SPAM_MIN_DOMAINS = 1
#: The WIDEST single matched anchor must reach at least this many root domains
#: before the signal can rise above "low".
#:
#: Deliberately not a sum across anchors. Moz gives a reach count per anchor
#: and no per-anchor domain identity, so summing double-counts any root domain
#: that carries more than one matched anchor — and one PBN page typically
#: carries several variants at once. Summing let five anchors of reach 1, all
#: from a single scraper, clear a floor of 5 and name a competitor "high" (P7).
DEFAULT_ANCHOR_SPAM_MIN_ANCHOR_REACH = 5
DEFAULT_ANCHOR_SPAM_HIGH_SHARE = 0.25


def _normalised(text: Any) -> str:
    """Lower-case, punctuation-stripped, space-delimited form of *text*.

    Padded with spaces so a term can be matched on whole-word boundaries —
    "seo service" must not fire on "seo services-and-more" being a substring
    of some longer token run, and "pbn" must not fire inside "pbnetwork".
    """
    return " " + " ".join(re.findall(r"[a-z0-9]+", str(text).lower())) + " "


_REACH_UNMEASURED = (
    "Anchor text matched a paid-link/PBN pattern, but its reach could not be "
    "measured, so there is nothing here about scale — treat this as a prompt "
    "to look, not as a finding. Anchors are written by other sites."
)

_RECEIVED_NOT_BOUGHT = (
    "Inbound anchors show a paid-link/PBN footprint. Anchors are written by "
    "other sites, so this indicates links RECEIVED, not links necessarily "
    "bought — a domain can be targeted by a scheme it had no part in. "
    "Pattern detection, not a confirmed penalty."
)


def detect_anchor_spam(anchor_texts: List[Dict[str, Any]],
                       config: Optional[Dict[str, Any]] = None,
                       sample_truncated: bool = False,
                       collected_at: Optional[str] = None) -> Optional[Dict[str, Any]]:
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

    min_reach = config.get("anchor_spam_min_anchor_reach",
                           DEFAULT_ANCHOR_SPAM_MIN_ANCHOR_REACH)

    matched, matched_domains, total_domains, unparseable = [], 0, 0, 0
    for entry in anchor_texts or []:
        if not isinstance(entry, dict):
            continue
        raw_reach = entry.get("external_root_domains")
        try:
            domains = int(raw_reach)
        except (TypeError, ValueError):
            # None, not 0. `int(0)` succeeds, so a genuinely measured zero must
            # keep falling through the min_domains gate as ordinary data —
            # routing it here would manufacture a signal out of a measurement
            # that says "no reach" (P1/P14).
            domains = None
        haystack = _normalised(entry.get("text"))
        hits = [t for t in normalised_terms if f" {t} " in haystack]
        if hits and domains is None:
            # The text matched but its reach is missing or unreadable. Dropping
            # it silently would turn a producer field rename into a permanent
            # "no signal" from non-empty input, with a green suite (P19/P2).
            unparseable += 1
            logger.warning(
                "Anchor matched %s but carries no usable external_root_domains "
                "(%r) — counted as unmeasured, not as clean", hits, raw_reach)
            continue
        if domains is None:
            continue
        total_domains += domains
        if hits and domains >= min_domains:
            matched_domains += domains
            matched.append({
                "text": str(entry.get("text") or "")[:160],
                "external_root_domains": domains,
                "matched_terms": hits,
            })

    if not matched:
        if unparseable:
            return {
                "signal_type": "anchor_text_spam",
                "severity": "low",
                "evidence": {
                    # 0, not `unparseable`: nothing was measurably matched.
                    # Reusing this key for a second quantity gave one field two
                    # meanings across the two return paths (P19/P22).
                    "matched_anchor_count": 0,
                    "unmeasured_anchor_count": unparseable,
                    "linking_domains_matched": 0,
                    "linking_domains_sampled": total_domains,
                    "share_of_sampled_linking_domains": 0.0,
                    "sample_anchors": [],
                    "sample_truncated": bool(sample_truncated),
                    "collected_at": collected_at,
                    "interpretation": _REACH_UNMEASURED,
                },
            }
        return None

    # Guard the division: a matched anchor always contributes to both sides,
    # so total_domains cannot be 0 here, but an explicit floor keeps a future
    # change to the accumulation from producing a ZeroDivisionError.
    share = (matched_domains / total_domains) if total_domains else 0.0
    # Severity ladder. `share` alone is not evidence: with a single anchor
    # sampled it is 1.0 by arithmetic, which would name a competitor at high
    # severity off one scraped link (P7). The floor is the WIDEST single
    # matched anchor, not the sum across anchors — see the constant's note. And
    # a truncated sample has a systematically small denominator, which the
    # producer flags expressly so a capped list is not read as complete (P9).
    widest = max(m["external_root_domains"] for m in matched)
    # Anchors whose reach could not be read are excluded from the denominator,
    # so a sample full of them yields a share computed over a fraction of the
    # data. That is the same defect `sample_truncated` already guards against,
    # with a different cause — a fix to one reveals the class (P5/P9).
    materially_unmeasured = unparseable > len(matched)
    if widest < min_reach:
        severity = "low"
    elif share >= high_share and not sample_truncated and not materially_unmeasured:
        severity = "high"
    else:
        severity = "medium"

    matched.sort(key=lambda m: m["external_root_domains"], reverse=True)
    return {
        "signal_type": "anchor_text_spam",
        "severity": severity,
        "evidence": {
            "matched_anchor_count": len(matched),
            "unmeasured_anchor_count": unparseable,
            "linking_domains_matched": matched_domains,
            "linking_domains_sampled": total_domains,
            "share_of_sampled_linking_domains": round(share, 3),
            "sample_truncated": bool(sample_truncated),
            "reach_unmeasured_for": unparseable,
            # Tool 1 caches anchors for up to 30 days, so this can be well
            # before the run's detected_at. Stating it stops a stale signal
            # reading as a fresh observation (P6).
            "collected_at": collected_at,
            "sample_anchors": matched[:5],
            "interpretation": _RECEIVED_NOT_BOUGHT,
        },
    }


ANCHOR_SPAM_CAVEAT = (
    "_`anchor_text_spam` reflects links **received**, not links bought: anchors are "
    "written by other sites, so a domain can be targeted by a scheme it had no part in._"
)


def anchor_data_unreadable(coverage) -> int:
    """How many domains' anchor data could not be read.

    One definition, imported by both the report's section gate and its caveat
    text. Duplicating the sum let a new bucket land in one place and not the
    other, producing a section with no caveat or a caveat with no section (P19).

    "Read fine, no anchors" is deliberately excluded: it is an answer, not a
    failure to get one.
    """
    coverage = coverage or {}
    if coverage.get("fetch_status") == "unavailable":
        return max(1, coverage.get("total", 0))
    return (coverage.get("errored", 0) + coverage.get("skipped", 0)
            + coverage.get("unknown", 0))


def anchor_caveat_lines(signal_types, coverage=None):
    """Return the anchor-text caveat lines a risk section must carry.

    Purpose: keep the disclaimer and the coverage note decidable — and
             testable — without pandas or tabulate, which the rendering path
             needs and some environments lack.
    Spec:    compete-spec.md#C6 (SC-8.4)
    Tests:   tests/test_risk_radar.py::TestReportCaveats

    Two separate obligations:

    - Whenever an `anchor_text_spam` row is present, the "received, not bought"
      caveat must travel with it. Naming a third party under "patterns Google
      penalizes" without it reads as an accusation.
    - Whenever anchor data could not be read for some domains, say so. Silence
      about an unreadable domain is indistinguishable from a clean verdict, and
      the console note does not reach the artifact anyone reads (P25).
    """
    lines = []
    if "anchor_text_spam" in set(signal_types or ()):
        lines.append(ANCHOR_SPAM_CAVEAT)
    coverage = coverage or {}
    if coverage.get("fetch_status") == "unavailable":
        # F4: a total failure of the anchor path must not render identically to
        # a clean run. Without this the console note is the only trace (P25).
        lines.append(
            "_Anchor-text data could not be retrieved for this run"
            + (f" ({coverage['reason']})" if coverage.get("reason") else "")
            + ", so no anchor-text signals could be computed. This is not "
              "evidence of a clean link profile for any competitor._")
        return lines
    if anchor_data_unreadable(coverage):
        causes = ", ".join(
            f"{coverage.get(bucket, 0)} {label}"
            for bucket, label in (("errored", "errored"), ("skipped", "skipped"),
                                  ("unknown", "unrecognised status"))
            if coverage.get(bucket, 0))
        lines.append(
            f"_Anchor-text coverage: {coverage.get('with_anchors', 0)} of "
            f"{coverage.get('total', 0)} domain(s) had readable anchor data "
            f"({causes}). Absence of an anchor signal below is not evidence of a clean "
            f"link profile for the domains that could not be read._")
    return lines


def compute_risk_signals(volatility_alerts: List[Dict[str, Any]],
                         series_by_domain: Dict[str, List[float]],
                         parasite_candidates: List[Dict[str, Any]],
                         own_domain: str, config: Optional[Dict[str, Any]] = None,
                         anchor_texts_by_domain: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                         anchor_collected_at: Optional[str] = None
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
        # anchors may arrive as a bare list (a direct caller) or as the
        # producer's page block carrying its own truncation flag.
        if isinstance(anchors, dict):
            items, truncated = anchors.get("items") or [], bool(anchors.get("truncated"))
        else:
            items, truncated = anchors, False
        add(domain, detect_anchor_spam(items, config, sample_truncated=truncated,
                                       collected_at=anchor_collected_at))
    for alert in volatility_alerts or []:
        shift = alert.get("shift") or 0
        add(alert.get("domain"), {
            "signal_type": "ranking_volatility",
            "severity": "high" if abs(shift) >= high_shift else "medium",
            "evidence": {"position_shift": shift}})
    return rows
