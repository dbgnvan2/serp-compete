"""C3 / SC-5 — Branded-Demand Competitive Benchmark.

Purpose: How does the client's brand-search demand compare to competitors'? You can't
         read a competitor's GSC, so estimate from public search volume: expand each
         brand into a branded query set, sum DataForSEO search volume, and compare
         shares + period-over-period growth. The client's own figure is anchored to
         first-party GSC (serp-discover D2) when available and labelled distinctly.
Spec:    suite_enhancement_spec_v1.md#C3 (SC-5) — see compete-spec.md#C3.
Tests:   tests/test_brand_demand.py

Design notes:
    * Pure logic + an injectable ``volume_provider`` (so it's tested without live
      DataForSEO). The real provider is DataForSEOClient.get_search_volume (mocked in
      tests; integration-only on real runs).
    * Own vs estimated (SC-5.1): the client's row carries est_branded_click_share (from
      D2 GSC when available) with estimation_basis "gsc_anchored"; every competitor is
      "volume_estimated". A generic brand name (SC-5.4) is pruned, never guessed.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

DEFAULT_MODIFIERS = ["reviews", "pricing", "login", "cost", "vs"]
DEFAULT_GROWTH_WINDOW = 3
# C-M-03 ambiguous-brand gate. A bare stem that is also a dictionary word
# ("lavender", "bach", "clear", "coast") carries search demand that has nothing to
# do with the practice. When the bare token's volume towers over the display
# brand's by this factor, the brand name cannot be attributed and the row's share
# and growth are withheld. Editorial default, uncalibrated, 2026-11-14
# (shared_config `branded_demand.ambiguous_brand_ratio`).
DEFAULT_AMBIGUOUS_BRAND_RATIO = 10.0


def expand_branded_queries(brand: str, modifiers: List[str]) -> List[str]:
    """The branded query set: the bare brand plus each editable modifier (SC-5.2)."""
    brand = str(brand or "").strip()
    if not brand:
        return []
    queries = [brand]
    for m in modifiers or []:
        m = str(m or "").strip()
        if m:
            queries.append(f"{brand} {m}")
    return queries


def is_generic_brand(brand: str, generic_terms: List[str]) -> bool:
    """A brand name too generic to attribute demand to (SC-5.4) — pruned, not guessed."""
    b = str(brand or "").strip().lower()
    return bool(b) and b in {str(g).strip().lower() for g in (generic_terms or [])}


def _aggregate_monthly(monthly_lists: List[List[Dict[str, Any]]]) -> List[int]:
    """Sum per-(year,month) search volume across a domain's queries → a time-ordered
    series (oldest→newest) of monthly totals."""
    by_month: Dict[tuple, int] = {}
    for series in monthly_lists:
        for point in series or []:
            key = (point.get("year"), point.get("month"))
            if key[0] is None or key[1] is None:
                continue
            by_month[key] = by_month.get(key, 0) + int(point.get("search_volume") or 0)
    return [by_month[k] for k in sorted(by_month)]


def compute_growth(series: List[int], window: int = DEFAULT_GROWTH_WINDOW) -> Optional[float]:
    """Period-over-period growth over EQUAL-length windows (SC-5.3): the last `window`
    months vs the `window` before them. None when there isn't enough history or the
    prior window is zero (can't divide)."""
    if window <= 0 or len(series) < 2 * window:
        return None
    recent = sum(series[-window:])
    prior = sum(series[-2 * window:-window])
    if prior <= 0:
        return None
    return round((recent - prior) / prior, 3)


def is_ambiguous_brand(display_volume: int, token_volume: int,
                       ratio: float = DEFAULT_AMBIGUOUS_BRAND_RATIO) -> bool:
    """True when the bare stem's demand swamps the display brand's (C-M-03).

    `max(display_volume, 1)` so a display brand with no measured volume beside a
    bare token with plenty still reads as ambiguous rather than dividing by zero;
    both at zero is not ambiguous, it is simply unmeasured.
    """
    if ratio <= 0 or token_volume <= 0:
        return False
    return float(token_volume) >= float(ratio) * max(float(display_volume), 1.0)


def compute_branded_demand(brand_by_domain: Dict[str, str],
                           volume_provider: Callable[[List[str]], Dict[str, Dict[str, Any]]],
                           config: Dict[str, Any], period: str,
                           own_domain: Optional[str] = None,
                           own_anchor: Optional[float] = None,
                           ambiguity_token_by_domain: Optional[Dict[str, str]] = None
                           ) -> List[Dict[str, Any]]:
    """One benchmark row per domain: branded_search_volume, share, growth, the query
    strings used, and (for the client only) the GSC-anchored click share. Pure over
    the provider's returned volumes.

    `brand_by_domain` must carry the DISPLAY brand ("Lavender Counselling").
    `ambiguity_token_by_domain` optionally carries the bare stem ("lavender"): when
    its volume swamps the display brand's, the brand name cannot be attributed, so
    the row is labelled `ambiguous_brand` and its share and growth are withheld and
    it is excluded from the share denominator (C-M-03).
    """
    modifiers = config.get("branded_modifiers", DEFAULT_MODIFIERS)
    generic = config.get("generic_brand_prune", [])
    window = int(config.get("growth_window_months", DEFAULT_GROWTH_WINDOW))
    ratio = float(config.get("ambiguous_brand_ratio", DEFAULT_AMBIGUOUS_BRAND_RATIO))
    own = (own_domain or "").lower()
    tokens = ambiguity_token_by_domain or {}

    volume: Dict[str, int] = {}
    growth: Dict[str, Optional[float]] = {}
    pruned: Dict[str, bool] = {}
    queries_used: Dict[str, List[str]] = {}
    ambiguous: Dict[str, bool] = {}
    unmeasured: Dict[str, bool] = {}
    for domain, brand in brand_by_domain.items():
        if not brand or is_generic_brand(brand, generic):
            pruned[domain] = True
            queries_used[domain] = []
            continue
        queries = expand_branded_queries(brand, modifiers)
        queries_used[domain] = list(queries)
        vols = volume_provider(queries)
        # C-C-11: `None` is the provider saying "I could not answer" (a 429 on the
        # third of twenty per-brand calls), `{}` is "I answered and had no rows".
        # Collapsing the first into 0 reported that competitor as having no branded
        # demand at all, at a 0.00% share, with estimation_basis `volume_estimated` —
        # a transient outage rendered as a measured fact about a brand (P1).
        if vols is None:
            unmeasured[domain] = True
            continue
        volume[domain] = sum(int(v.get("search_volume") or 0) for v in vols.values())
        growth[domain] = compute_growth(
            _aggregate_monthly([v.get("monthly_searches", []) for v in vols.values()]), window)

        # The ambiguity probe is a separate call for the bare stem alone, so its
        # volume never enters the branded total.
        token = str(tokens.get(domain) or "").strip()
        if token and token.lower() != str(brand).strip().lower():
            probe = volume_provider([token]) or {}   # None (outage) → no probe, no gate
            token_volume = sum(int(v.get("search_volume") or 0) for v in probe.values())
            if is_ambiguous_brand(volume[domain], token_volume, ratio):
                ambiguous[domain] = True
                queries_used[domain].append(f"[ambiguity probe] {token}")

    # Ambiguous rows are excluded from the denominator: their share is withheld, so
    # counting their volume in the total would silently shrink everybody else's.
    total = sum(v for d, v in volume.items() if not ambiguous.get(d))
    # Every non-pruned brand returned zero volume → the source (DataForSEO) is almost
    # certainly unavailable, not that the whole market has no branded demand. Say so
    # rather than render a table of zeros as fact (P1/P2).
    volume_unavailable = sum(volume.values()) == 0 and len(volume) > 0
    rows: List[Dict[str, Any]] = []
    for domain, brand in brand_by_domain.items():
        if pruned.get(domain):
            rows.append({"domain": domain, "brand": brand, "period": period,
                         "branded_search_volume": None, "branded_volume_share": None,
                         "branded_growth": None, "est_branded_click_share": None,
                         "estimation_basis": "pruned_generic_brand",
                         "queries": queries_used.get(domain, [])})
            continue
        if unmeasured.get(domain):
            # NULL volume, no share, no growth: this brand was not measured this run.
            rows.append({"domain": domain, "brand": brand, "period": period,
                         "branded_search_volume": None, "branded_volume_share": None,
                         "branded_growth": None, "est_branded_click_share": None,
                         "estimation_basis": "volume_unavailable",
                         "queries": queries_used.get(domain, [])})
            continue
        vol = volume[domain]
        is_own = bool(own) and domain.lower() == own
        if volume_unavailable:
            basis = "volume_unavailable"
        elif ambiguous.get(domain):
            basis = "ambiguous_brand"
        elif is_own and own_anchor is not None:
            basis = "gsc_anchored"
        else:
            basis = "volume_estimated"
        withheld = basis == "ambiguous_brand"
        rows.append({
            "domain": domain, "brand": brand, "period": period,
            "branded_search_volume": vol,
            "branded_volume_share": (None if withheld else
                                     (round(100.0 * vol / total, 2) if total else 0.0)),
            "branded_growth": (None if withheld else growth[domain]),
            "est_branded_click_share": (own_anchor if is_own else None),
            "estimation_basis": basis,
            "queries": queries_used.get(domain, []),
        })
    return rows
