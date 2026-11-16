"""The audit universe: which (url, keyword) pairs an audit is allowed to look at.

Purpose: Tool 1 hands over the URLs and keywords it actually found ranking. Until
         this module existed, `main.run_audit` grouped those targets by domain and
         then threw them away, auditing each domain's DataForSEO
         `ranked_keywords/live` top-10 instead (Canada, API default order, no
         position filter). That is how run_11's "Traffic Magnets" came out as
         "archdiocese of vancouver", "airport heights medical clinic" (a St John's
         NL page) and "555 homer street", and why gpt-4o spent tokens reframing the
         Archdiocese of Vancouver (C-M-01, C-M-02, C-M-15).
Decision: owner decision 1, 2026-11-14, option (b) — the handoff is the PRIMARY
         universe; `ranked_keywords` stays as an ADDITIONAL enrichment, filtered,
         with each keyword's source carried through to the report so a reader can
         tell a ranked fact from an enrichment guess.
Spec:    docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md §3 Chunk C1, §4 decision 1
Tests:   Serp-compete/tests/test_audit_universe.py

The relevance test (used for enrichment admission AND for the vacuum / reframe gate
in C-M-02) is: the keyword is in the handoff keyword set, OR it contains a Tier-1 /
Tier-2 clinical term — AND it does not contain the domain's own brand token.

Matching mechanics (deliberate, and different from `semantic.py`'s token scan):
  * terms and brand tokens are matched on WORD BOUNDARIES over the raw keyword, so
    "air conditioning" is not clinical because of "condition" and "mapquest" is not
    a brand hit for "map". Multi-word terms ("chronic anxiety") match as phrases.
  * a brand token shorter than MIN_BRAND_TOKEN_LEN is not used for the brand drop:
    `m.yelp.com` derives the token "m", and one letter is noise, not a brand.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Keyword provenance values, persisted in traffic_magnets.keyword_source and
# competitor_metrics.keyword_source and printed in the briefing.
SOURCE_HANDOFF = "handoff"
SOURCE_ENRICHMENT = "ranked_keywords"

# See "Matching mechanics" above.
MIN_BRAND_TOKEN_LEN = 2


def _norm_keyword(keyword: Any) -> str:
    return " ".join(str(keyword or "").lower().split())


def group_targets_by_domain(
        targets: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """`{canonical domain: [its handoff targets]}` — one entry per SITE.

    Purpose: one site must be one audited competitor.
    Spec:    docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md §3 Chunk X
    Tests:   Serp-compete/tests/test_handoff_contract.py::TestDomainCanonicalForm

    Tool 1 writes `targets[].domain` as `netloc.lower()` with `www.` kept, while
    its own citation and brand paths strip it. Grouping on the raw string made
    one site two competitors whenever a handoff carried both spellings: two
    DataForSEO enrichment calls, two `competitors` rows, the site's keyword
    count split in half for the barbell and positioning, and the same brand
    token derived twice. `main.run_audit`'s omit-list test normalised while its
    grouping did not, so an omitted `www.` host was skipped and its bare twin
    audited.

    A function rather than an inline loop in `main.run_audit` because a test
    cannot reach that loop: `main` imports the whole application at module load
    and `run_audit` needs live API clients, so the only coverage the grouping
    ever had was a test that re-implemented it (the copy in
    `tests/test_handoff_ingestion.py` could not have caught this).

    Target URLs are untouched — the URL is what gets fetched, and
    `https://www.x.com/a` is not necessarily `https://x.com/a`.
    """
    from src.brand_utils import normalise_domain

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for target in targets or []:
        domain = normalise_domain((target or {}).get("domain"))
        if not domain:
            # A target with no domain cannot be attributed to a competitor.
            # Dropping it silently is what the caller's N-of-M line reports on;
            # keying it under "" would create a phantom domain in the report.
            continue
        groups.setdefault(domain, []).append(target)
    return groups


def handoff_keyword_set(targets: Iterable[Dict[str, Any]]) -> Set[str]:
    """Every keyword Tool 1 ranked: each target's primary keyword AND source keyword.

    Both, because `primary_keyword_for_url` is the keyword the URL ranked best for
    while `source_keyword` is the client's own target query that surfaced it; an
    enrichment keyword matching either is a ranked fact, not a guess.
    """
    out: Set[str] = set()
    for target in targets or []:
        for key in ("primary_keyword", "primary_keyword_for_url", "source_keyword"):
            value = _norm_keyword(target.get(key))
            if value:
                out.add(value)
    return out


def clinical_term_set(clinical_config: Optional[Dict[str, Any]]) -> List[str]:
    """Tier-1 + Tier-2 clinical vocabulary from config (`clinical.*`), lower-cased.

    Tier 3 is Bowen vocabulary; a competitor keyword carrying it is clinical too, so
    it is included. Editorial vocabulary stays in config (CLAUDE.md), never here.
    """
    config = clinical_config or {}
    terms: List[str] = []
    for tier in ("tier_1_medical", "tier_2_systems", "tier_3_bowen"):
        for term in config.get(tier) or []:
            term = str(term or "").strip().lower()
            if term:
                terms.append(term)
    return terms


def contains_term(text: Any, needle: Any, allow_plural: bool = True) -> bool:
    """Word-boundary containment — the ONE place this repo decides what "contains".

    `\\b` is unreliable next to non-word characters (a hyphen in 'self-regulation'),
    so the boundary is asserted explicitly. Used by the relevance test here, by
    `positioning.classify_query_tiers` and by `gsc_performance`'s query tiering, so a
    substring match cannot creep back into one of them: `term in query` made "air
    conditioning" a medical query because of "condition", and "food processing jobs"
    a systems query because of "process" (C-M-08).

    `allow_plural` tolerates a trailing "s"/"es" and nothing else, because the
    clinical dictionary now holds LEMMAS (decision 3): "symptom" has to match
    "anxiety symptoms". It is deliberately not a stemmer — "condition" must NOT match
    "conditioning" and "trauma" must NOT match "traumatic", which is the whole point
    of the boundary. Irregular plurals ("diagnoses") are not matched here; the page
    scorer lemmatises properly (semantic.count_terms) and this is the query path.
    """
    needle = str(needle or "").strip().lower()
    if not needle:
        return False
    haystack = " ".join(str(text or "").lower().split())
    suffix = r"(?:es|s)?" if allow_plural else ""
    pattern = r"(?<![a-z0-9])" + re.escape(needle) + suffix + r"(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def _contains(text: str, needle: str) -> bool:
    """Back-compat alias for the module-internal callers below."""
    return contains_term(text, needle)


def contains_clinical_term(keyword: Any, terms: Sequence[str]) -> bool:
    """True when the keyword carries any configured clinical term, on word boundaries."""
    text = _norm_keyword(keyword)
    if not text:
        return False
    return any(_contains(text, term) for term in terms or [])


def contains_brand_token(keyword: Any, brand_token: Any) -> bool:
    """True when the keyword contains the domain's own brand token.

    'jericho counselling' is jerichocounselling.com's own navigational query: it is
    not a content gap, so it must never become a magnet, a vacuum or a reframe.
    """
    token = str(brand_token or "").strip().lower()
    if len(token) < MIN_BRAND_TOKEN_LEN:
        return False
    return _contains(_norm_keyword(keyword), token)


def keyword_is_relevant(keyword: Any, handoff_keywords: Set[str],
                        clinical_terms: Sequence[str], brand_token: Any) -> bool:
    """The C-M-02 relevance test, in one place (the magnet / vacuum / reframe gate)."""
    text = _norm_keyword(keyword)
    if not text:
        return False
    if contains_brand_token(text, brand_token):
        return False
    return text in (handoff_keywords or set()) or contains_clinical_term(text, clinical_terms)


def new_universe_stats() -> Dict[str, int]:
    """Run-level counters, so a report can state how the universe was assembled."""
    return {"handoff": 0, "handoff_irrelevant": 0, "enrichment_kept": 0,
            "enrichment_dropped_brand": 0, "enrichment_dropped_irrelevant": 0,
            "enrichment_matched_handoff": 0}


def _dfs_fields(item: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Any, float]:
    """(url, keyword, organic rank, etv) out of one ranked_keywords item.

    C-C-17: the rank is `rank_group` — DataForSEO's ORGANIC position — falling back
    to `rank_absolute` only when it is absent. `rank_absolute` counts every SERP
    element, so a competitor sitting organically at #8 below three SERP features
    reads as 11 and drops out of a `<= 10` test, while the client's side of that same
    test is a GSC `position` computed on a different element model. The top-N
    comparison was therefore applied to two different scales.
    """
    serp_item = (item.get("ranked_serp_element") or {}).get("serp_item") or {}
    url = serp_item.get("url") or item.get("url")
    keyword = (item.get("keyword_data") or {}).get("keyword") or item.get("keyword")
    rank = serp_item.get("rank_group")
    if rank is None:
        rank = serp_item.get("rank_absolute")
    return url, keyword, rank, float(serp_item.get("etv") or 0)


def build_domain_universe(group_targets: Iterable[Dict[str, Any]],
                          dfs_items: Optional[Iterable[Dict[str, Any]]],
                          handoff_keywords: Set[str],
                          clinical_terms: Sequence[str],
                          brand_token: Any,
                          stats: Optional[Dict[str, int]] = None
                          ) -> List[Dict[str, Any]]:
    """The (url, keyword) rows this run may audit for ONE domain, handoff first.

    Each row: {url, keyword, position, traffic, keyword_source, keyword_relevant}.

    * Handoff rows are kept unconditionally — they are what Tool 1 ranked, and
      `position` is Tool 1's own rank, not a DataForSEO snapshot. `traffic` starts
      at 0.0 because the handoff carries no traffic estimate; it is filled in from
      DataForSEO's `etv` only when DataForSEO reports the SAME url AND keyword, so
      a 0 here means "not measured", never "no traffic".
    * Enrichment rows (DataForSEO `ranked_keywords`) must pass the relevance test.
      A dropped row is counted, never silently discarded (P2).
    """
    stats = stats if stats is not None else new_universe_stats()
    records: List[Dict[str, Any]] = []
    by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for target in group_targets or []:
        url = target.get("url")
        keyword = target.get("primary_keyword") or target.get("primary_keyword_for_url")
        if not url:
            continue
        key = (str(url), _norm_keyword(keyword))
        if key in by_key:
            continue
        relevant = keyword_is_relevant(keyword, handoff_keywords, clinical_terms, brand_token)
        record = {"url": url, "keyword": keyword, "position": target.get("rank"),
                  "traffic": 0.0, "keyword_source": SOURCE_HANDOFF,
                  "keyword_relevant": relevant}
        by_key[key] = record
        records.append(record)
        stats["handoff"] += 1
        if not relevant:
            stats["handoff_irrelevant"] += 1

    for item in dfs_items or []:
        url, keyword, position, traffic = _dfs_fields(item)
        if not url or not keyword:
            continue
        key = (str(url), _norm_keyword(keyword))
        existing = by_key.get(key)
        if existing is not None:
            # DataForSEO confirms a handoff target's own keyword: take the traffic
            # estimate (the only place one exists) but keep the handoff provenance
            # and the handoff's rank.
            if traffic and not existing["traffic"]:
                existing["traffic"] = traffic
            if existing["keyword_source"] == SOURCE_HANDOFF:
                stats["enrichment_matched_handoff"] += 1
            continue
        if contains_brand_token(keyword, brand_token):
            stats["enrichment_dropped_brand"] += 1
            continue
        if not keyword_is_relevant(keyword, handoff_keywords, clinical_terms, brand_token):
            stats["enrichment_dropped_irrelevant"] += 1
            continue
        record = {"url": url, "keyword": keyword, "position": position,
                  "traffic": traffic, "keyword_source": SOURCE_ENRICHMENT,
                  "keyword_relevant": True}
        by_key[key] = record
        records.append(record)
        stats["enrichment_kept"] += 1

    return records


def universe_summary_line(stats: Dict[str, int]) -> str:
    """One console/report line describing how the universe was assembled (P2)."""
    stats = stats or {}
    return (f"handoff targets {stats.get('handoff', 0)} "
            f"({stats.get('handoff_irrelevant', 0)} carry a rival brand token and so "
            f"cannot be magnets); enrichment keywords kept "
            f"{stats.get('enrichment_kept', 0)}, dropped "
            f"{stats.get('enrichment_dropped_brand', 0)} brand-token + "
            f"{stats.get('enrichment_dropped_irrelevant', 0)} off-topic; "
            f"{stats.get('enrichment_matched_handoff', 0)} DataForSEO rows confirmed a "
            f"handoff target's own keyword.")
