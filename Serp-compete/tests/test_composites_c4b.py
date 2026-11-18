"""The composite scores: barbell, EEAT, cluster, GEO (C4b — C-M-09, C-M-10, C-M-12,
C-M-13, C-M-14).

Promotes probes/compete_method/p03_eeat_cluster_geo.py (§A–E) and
p04_overlap_positioning_brand.py §B to behaviour tests. Each case is one of the
probes' own inputs, asserted against what the owner would now read.

Decision 8 (raise `max_audit_pages_per_domain` or demote these sections to boolean
evidence tables) is still OPEN, so these tests lock the conservative half: the
arithmetic, the withheld verdicts and the language. They do not assume either answer.
"""
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from src.cluster_detector import ClusterDetector
from src.database import DatabaseManager
from src.eeat_scorer import EEATScorer
from src.geo_profiler import GeoProfiler
from src.positioning import compute_authority, compute_focus, positioning_row
from src.reporting import ReportGenerator

CONFIG = {
    "credential_list": ["PhD", "RCC", "MA"],
    "eeat_weights": {
        "experience": {"has_author_byline": 0.3, "has_publish_date": 0.3,
                       "first_person_count_normalised": 0.4},
        "expertise": {"has_credentials_in_byline": 0.6,
                      "tier_3_or_tier_2_present": 0.4},
        "authoritativeness": {"domain_authority_normalised": 0.5,
                              "external_link_count_normalised": 0.3,
                              "schema_organization_present": 0.2},
        "trustworthiness": {"is_https": 0.4, "has_contact_link": 0.3,
                            "has_privacy_link": 0.3},
    },
    "geo_signals": {"strong_tier_min_signals": 3, "moderate_tier_min_signals": 1,
                    "interrogatives": ["how", "what", "why", "can", "is"]},
    "cluster_thresholds": {"hub_in_degree_threshold": 2, "min_pages_for_signal": 3},
    "positioning": {"authority_threshold": 50, "focus_threshold": 50,
                    "authority_weights": {"moz_da": 0.7, "top10": 0.3},
                    "top10_saturation": 10, "min_signal_rankings": 2,
                    "min_focus_tokens": 12},
}


def _page(url="https://comp.com/a", *, metadata=None, outline=None,
          status="complete", text="we work with families on distance and pursuit"):
    meta = {"author_byline": None, "publish_date": None, "update_date": None,
            "schema_types": [], "has_faq_schema": False, "has_article_schema": False,
            "has_localbusiness_schema": False, "image_hosts": [], "image_count": 0,
            "likely_original_images_count": 0, "external_link_count": 3,
            "internal_link_count": 0, "internal_links": [], "is_https": True,
            "has_contact_link": True, "has_privacy_link": True,
            "case_study_signal": False}
    meta.update(metadata or {})
    return SimpleNamespace(url=url, extraction_status=status, outline=outline or [],
                           first_500_words=text, scoring_text=text,
                           scoring_word_count=len(text.split()), metadata=meta)


# ── C-M-09: the authority axis compares like with like ───────────────────────

def test_cm09_the_client_is_no_longer_authoritative_by_construction():
    """The probe's numbers: client DA 35 with 240 GSC queries saturated the top-10
    component, giving 0.7x35 + 0.3x100 = 54.5 and the `authoritative` quadrant, while
    a competitor needed avg PA >= ~29 AND all 10 sampled keywords in the top 10 to
    reach 50 — and the PA > 50 filter capped the field above it."""
    saturated = compute_authority(35, 240, CONFIG["positioning"])
    assert saturated == pytest.approx(54.5)        # what it used to be

    # Restricted to the shared handoff universe, the client's count is a real count.
    shared = compute_authority(35, 2, CONFIG["positioning"])
    assert shared < 50                             # no longer authoritative by default


def test_cm09_a_missing_domain_authority_is_excluded_not_zeroed():
    assert compute_authority(None, 5, CONFIG["positioning"]) == pytest.approx(50.0)
    assert compute_authority(None, 0, CONFIG["positioning"]) is None


def test_cm09_the_row_records_which_authority_it_used():
    row = positioning_row("comp.com",
                          {"moz_da": 40, "top10_count": 3, "medical_total": 10,
                           "systems_total": 6, "authority_basis": "moz_domain_authority",
                           "top10_universe": "handoff keywords"},
                          False, CONFIG["positioning"])
    assert row["rationale"]["authority_basis"] == "moz_domain_authority"
    assert row["rationale"]["top10_universe"] == "handoff keywords"


# ── C-M-10: focus is withheld on a thin sample ───────────────────────────────

@pytest.mark.parametrize("medical,systems", [(3, 0), (3, 0.5), (3, 1.5)])
def test_cm10_the_probes_focus_cases_are_now_withheld(medical, systems):
    """p04 §B: {3, 0} gave focus 100 and `niche_owner`; {3, 0.5} gave 40.8 and
    `middle`; {3, 1.5} gave 8.2 — one "relationship" token moved a domain across the
    quadrant boundary, and the manual calls the middle the softest target."""
    assert compute_focus(medical, systems, 12) is None


def test_cm10_the_report_prints_the_counts_behind_the_focus(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rg = ReportGenerator(str(tmp_path / "pos.db"))
    run_id = rg.db.create_run("livingsystems.ca")
    rg.db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0, "keyword_source": "handoff"}], run_id=run_id)
    rows = [positioning_row("comp.com",
                            {"moz_da": 40, "top10_count": 1, "medical_total": 3,
                             "systems_total": 0,
                             "authority_basis": "moz_domain_authority"},
                            False, CONFIG["positioning"])]
    rg.db.save_positioning(run_id, rows, computed_at="2026-11-15")
    content = rg.generate_summary("livingsystems.ca", run_id=run_id)
    assert "tier_tokens" in content
    assert "positioning.min_focus_tokens" in content
    assert "insufficient_data" in content


# ── C-M-12: EEAT confidence is coverage, and the precision is honest ─────────

def test_cm12_confidence_is_signal_coverage_not_a_constant():
    """p03 §A–C: "confidence is high for every page that loaded and low only for
    blocked pages", while the config describes 0.0-0.5 / 0.5-0.8 / 0.8-1.0 bands over
    signal coverage that were never computed."""
    scorer = EEATScorer(CONFIG)
    full = scorer.score_page(_page(metadata={"author_byline": "Jane Smith, RCC",
                                             "publish_date": "2026-01-01",
                                             "schema_types": ["Organization"]}),
                             domain_authority=40)
    assert full.score_confidence == "high"

    # No DA measured and no byline/date: a thinner page must not read "high".
    thin = scorer.score_page(_page(), domain_authority=None)
    assert thin.score_confidence in ("medium", "low")
    assert thin.score_confidence != "high"


def test_cm12_a_blocked_page_is_low_confidence_with_no_scores():
    scorer = EEATScorer(CONFIG)
    blocked = scorer.score_page(_page(status="blocked"), domain_authority=40)
    assert blocked.score_confidence == "low"
    assert all(v is None for v in blocked.scores.values())


def test_cm12_the_report_states_the_value_set_and_uses_one_decimal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rg = ReportGenerator(str(tmp_path / "eeat.db"))
    run_id = rg.db.create_run("livingsystems.ca")
    rg.db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    with rg.db.connection() as conn:
        conn.execute(
            "INSERT INTO eeat_scores (run_id, url, scored_at, experience_score, "
            "expertise_score, authoritativeness_score, trustworthiness_score, "
            "score_confidence) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, "https://comp.com/a", "2026-11-15", 0.26, 0.4, 0.0, 0.7, "medium"))
        conn.commit()
    content = rg.generate_summary("livingsystems.ca", run_id=run_id)
    assert "weighted sum of BOOLEAN signals" in content
    assert "0.3" in content and "0.26" not in content      # 1 dp, not 2
    assert "signal coverage" in content


# ── C-M-13: the cluster graph is host-normalised ─────────────────────────────

def test_cm13_the_www_mismatch_no_longer_reads_as_isolated():
    """p03 §D: "Same three pages with absolute `https://c.ca/...` links while scraped
    as `https://www.c.ca/...` → isolated" — and the manual ranks `isolated`
    competitors as easier to overtake."""
    detector = ClusterDetector(CONFIG)
    pages = [
        _page("https://www.c.ca/", metadata={"internal_links": []}),
        _page("https://www.c.ca/a", metadata={"internal_links": ["https://c.ca/"]}),
        _page("https://www.c.ca/b", metadata={"internal_links": ["https://c.ca/"]}),
    ]
    result = detector.analyze_domain("c.ca", pages)
    assert result.cluster_signal == "clustered"
    assert "hub_is_homepage=yes" in result.resolution_caveat


def test_cm13_the_caveat_says_what_isolated_cannot_distinguish():
    detector = ClusterDetector(CONFIG)
    pages = [_page(f"https://c.ca/{i}", metadata={"internal_links": []})
             for i in range(3)]
    result = detector.analyze_domain("c.ca", pages)
    assert result.cluster_signal == "isolated"
    assert "cannot distinguish" in result.resolution_caveat
    assert "hub_is_homepage=no" in result.resolution_caveat


# ── C-M-14: GEO rewards question structure, not WordPress defaults ───────────

def test_cm14_a_stock_wordpress_post_no_longer_outscores_an_faq_page():
    """p03 §E: the stock WP post (Organization + Person schema, byline "admin",
    published_time, zero question headings) read **Strong**; the FAQ page with
    FAQPage schema and two genuine question headings but no byline or date read
    **Moderate**."""
    profiler = GeoProfiler(CONFIG)
    wp_post = profiler.profile_page(_page(
        metadata={"schema_types": ["Organization", "Person"],
                  "author_byline": "admin", "publish_date": "2026-01-01"},
        outline=[{"level": "h2", "text": "Our Services", "order": 0}]))
    faq_page = profiler.profile_page(_page(
        metadata={"has_faq_schema": True, "schema_types": ["FAQPage"]},
        outline=[{"level": "h2", "text": "What is differentiation?", "order": 0},
                 {"level": "h2", "text": "How does therapy help?", "order": 1}]))

    assert faq_page.extractability_tier == "Strong"
    assert wp_post.extractability_tier in ("Weak", "Moderate")
    assert wp_post.extractability_tier != "Strong"


def test_cm14_a_generic_byline_is_not_authorship():
    profiler = GeoProfiler(CONFIG)
    generic = profiler.profile_page(_page(metadata={"author_byline": "admin"}))
    named = profiler.profile_page(_page(metadata={"author_byline": "Jane Smith"}))
    assert "named author byline" not in generic.present_signals
    assert "named author byline" in named.present_signals


def test_cm14_the_why_cited_sentence_no_longer_asserts_causation():
    profiler = GeoProfiler(CONFIG)
    profile = profiler.profile_page(_page(
        metadata={"has_faq_schema": True, "schema_types": ["FAQPage"]},
        outline=[{"level": "h2", "text": "What is differentiation?", "order": 0}]))
    assert "make the page easy for AI answer engines to quote" not in profile.why_cited
    assert "not measured here" in profile.why_cited


def test_cm14_the_section_is_renamed_and_says_it_measures_no_citations(tmp_path,
                                                                      monkeypatch):
    monkeypatch.chdir(tmp_path)
    rg = ReportGenerator(str(tmp_path / "geo.db"))
    run_id = rg.db.create_run("livingsystems.ca")
    rg.db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    with rg.db.connection() as conn:
        conn.execute(
            "INSERT INTO geo_profiles (run_id, url, profiled_at, extractability_tier, "
            "question_heading_count, present_signals, why_cited) VALUES (?,?,?,?,?,?,?)",
            (run_id, "https://comp.com/a", "2026-11-15", "Strong", 2, "[]", "why"))
        conn.commit()
    content = rg.generate_summary("livingsystems.ca", run_id=run_id)
    assert "## Extractability signals (structural, unvalidated)" in content
    assert "Why Competitors Get Cited" not in content
    assert "Nothing in this section measures citations" in content


def test_cm14_strong_tiers_are_checked_against_real_citations(tmp_path, monkeypatch):
    """The AI-visibility export is the one real citation record in the system, and the
    extractability section never looked at it."""
    monkeypatch.chdir(tmp_path)
    rg = ReportGenerator(str(tmp_path / "geocite.db"))
    run_id = rg.db.create_run("livingsystems.ca")
    rg.db.save_competitor_metrics(
        [{"domain": "cited.com", "url": "https://cited.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    with rg.db.connection() as conn:
        for url, tier in (("https://cited.com/a", "Strong"),
                          ("https://uncited.com/a", "Strong")):
            conn.execute(
                "INSERT INTO geo_profiles (run_id, url, profiled_at, "
                "extractability_tier, question_heading_count, present_signals, "
                "why_cited) VALUES (?,?,?,?,?,?,?)",
                (run_id, url, "2026-11-15", tier, 2, "[]", "why"))
        conn.commit()
    rg.db.save_sov(run_id, [{"engine": "gemini", "snapshot_date": "2026-11-15",
                             "entity": "cited.com", "entity_type": "domain",
                             "is_client": False, "category": "competitor",
                             "mention_share": 10.0, "citation_share": 25.0,
                             "presence_rate": 0.5, "avg_sentiment": None,
                             "cited_gap": False}])
    content = rg.generate_summary("livingsystems.ca", run_id=run_id)
    assert "Checked against the AI-visibility export" in content
    assert "1 of 2" in content
    assert "uncited.com" in content
