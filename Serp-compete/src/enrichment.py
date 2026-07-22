"""Per-page / per-domain enrichment wiring for run_audit.

Purpose: Extract the EEAT / GEO / cluster enrichment decisions (fresh-scrape vs.
         cache-hit carry-forward, and the per-domain cluster gate) out of the
         monolithic run_audit() so the wiring logic is unit-testable without the
         live DataForSEO / Moz / spaCy / OpenAI stack (Finding 2 / P10). main.py
         now delegates to these helpers; the branch logic the pre-push sweep
         worried about lives here and is covered by tests/test_enrichment.py.
Spec:    suite_enhancement_spec_SERPCOMPETE_v1.md#SC-1 (Finding 1 & Finding 2 fixes)
Tests:   tests/test_enrichment.py

Everything is duck-typed: `db` is a DatabaseManager, the engines are passed in,
and a "page" is anything exposing `url` / `extraction_status` / `outline` /
`metadata` (as a real ScrapedPage does). Nothing heavy is imported here.
"""

from typing import Any, Dict, List

# The enrichment coverage counters, in one place so main.py and the tests agree.
_STAT_KEYS = (
    "eeat_fresh", "eeat_carried", "eeat_no_prior", "eeat_failed",
    "geo_fresh", "geo_carried", "geo_no_prior", "geo_failed",
    "cluster_fresh", "cluster_carried", "cluster_no_prior", "cluster_failed",
)


def new_enrichment_stats() -> Dict[str, int]:
    """Return a zeroed enrichment-coverage counter dict (Finding 4 / P2)."""
    return {k: 0 for k in _STAT_KEYS}


def enrich_scraped_page(db: Any, run_id: int, page: Any, page_authority: Any,
                        eeat_scorer: Any, geo_profiler: Any,
                        stats: Dict[str, int]) -> None:
    """Fresh-scrape path: score EEAT + profile GEO for a freshly-scraped page.

    A failure in either engine is counted and surfaced (never silently swallowed,
    P2) so a *systematic* fault is provable rather than an empty report section.
    """
    url = getattr(page, "url", "?")
    try:
        eeat_score = eeat_scorer.score_page(page, domain_authority=(page_authority or None))
        eeat_scorer.save_to_database(db, run_id, eeat_score)
        stats["eeat_fresh"] += 1
    except Exception as eeat_err:  # noqa: BLE001 - counted + surfaced below
        stats["eeat_failed"] += 1
        print(f"  ⚠️ EEAT scoring skipped for {url}: {eeat_err}")
    try:
        geo_profile = geo_profiler.profile_page(page)
        db.save_geo_profile(run_id, geo_profile)
        stats["geo_fresh"] += 1
    except Exception as geo_err:  # noqa: BLE001 - counted + surfaced below
        stats["geo_failed"] += 1
        print(f"  ⚠️ GEO profiling skipped for {url}: {geo_err}")


def carry_forward_cached_page(db: Any, run_id: int, url: str,
                              stats: Dict[str, int]) -> None:
    """Cache-hit path (Finding 1 / P8): the page is served from the 7-day semantic
    cache and is NOT re-scraped, so EEAT/GEO cannot recompute. Re-associate the
    URL's latest prior profile with this run so the report sections do not blank
    out on a re-run. A cache hit with no prior profile is counted, never faked.
    """
    if db.carry_forward_profile("eeat_scores", "url", url, run_id):
        stats["eeat_carried"] += 1
    else:
        stats["eeat_no_prior"] += 1
    if db.carry_forward_profile("geo_profiles", "url", url, run_id):
        stats["geo_carried"] += 1
    else:
        stats["geo_no_prior"] += 1


def finalize_domain_cluster(db: Any, run_id: int, domain: str,
                            scraped_pages: List[Any], had_cache_hit: bool,
                            cluster_detector: Any, stats: Dict[str, int]) -> None:
    """Per-domain internal-linking cluster detection.

    Hubs are a property of the *whole* domain, so the completeness of the page set
    matters. Compute fresh only when EVERY audited page for the domain was freshly
    scraped this run. If ANY page was cache-served, the fresh subset is an
    incomplete link graph that would under-count hubs (Finding 1 mixed-domain
    case) — so carry the latest prior (complete) cluster result forward instead.
    Only when there is no prior result to carry do we fall back to a best-effort
    partial compute on whatever fresh pages we have.
    """
    def _compute_fresh() -> None:
        try:
            result = cluster_detector.analyze_domain(domain, scraped_pages)
            cluster_detector.save_to_database(db, run_id, result)
            stats["cluster_fresh"] += 1
        except Exception as cl_err:  # noqa: BLE001 - counted + surfaced below
            stats["cluster_failed"] += 1
            print(f"  ⚠️ Cluster detection skipped for {domain}: {cl_err}")

    if scraped_pages and not had_cache_hit:
        # Entire domain freshly scraped → complete link graph.
        _compute_fresh()
    elif had_cache_hit:
        # Some/all pages were cache-served → prefer the last complete result.
        if db.carry_forward_profile("cluster_results", "domain", domain, run_id):
            stats["cluster_carried"] += 1
        elif scraped_pages:
            # Mixed domain with no prior to carry → best-effort partial (honest:
            # analyze_domain reports insufficient_data if the subset is too small).
            _compute_fresh()
        else:
            stats["cluster_no_prior"] += 1
    # else: domain had no audited pages this run → nothing to finalize.
