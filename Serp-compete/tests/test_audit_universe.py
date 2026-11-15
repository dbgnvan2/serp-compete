"""Tests for src/audit_universe.py — which (url, keyword) pairs an audit may look at.

Promotes `docs/review_2026-11-04/probes/compete_method/p02_reporting_db.py` §B and the
C-M-01 trace to behaviour tests: the universe is built from the handoff (what Tool 1
actually ranked), DataForSEO `ranked_keywords` is admitted only as filtered enrichment,
and every dropped keyword is counted rather than silently discarded.

Owner decision 1(b), 2026-11-14 — see
docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md §4.
"""
import pytest

from src.audit_universe import (
    SOURCE_ENRICHMENT, SOURCE_HANDOFF, build_domain_universe, clinical_term_set,
    contains_brand_token, contains_clinical_term, handoff_keyword_set,
    keyword_is_relevant, new_universe_stats, universe_summary_line,
)

CLINICAL = {
    "tier_1_medical": ["therapy", "condition", "symptom"],
    "tier_2_systems": ["differentiation", "chronic anxiety", "self-regulation"],
    "tier_3_bowen": ["emotional cutoff"],
}
TERMS = clinical_term_set(CLINICAL)


def _target(url, keyword, rank=3, source_keyword=None):
    return {"domain": "comp.com", "url": url, "primary_keyword": keyword, "rank": rank,
            "source_keyword": source_keyword or keyword, "est_traffic": 0}


def _dfs_item(url, keyword, rank_absolute=4, etv=50.0):
    return {"ranked_serp_element": {"serp_item": {"url": url,
                                                  "rank_absolute": rank_absolute,
                                                  "etv": etv}},
            "keyword_data": {"keyword": keyword}}


# ── the handoff keyword set ────────────────────────────────────────────────────

def test_handoff_keyword_set_carries_primary_and_source_keywords():
    targets = [_target("https://c.com/a", "couples therapy vancouver",
                       source_keyword="How much is couples therapy in Vancouver?")]
    assert handoff_keyword_set(targets) == {
        "couples therapy vancouver", "how much is couples therapy in vancouver?"}


def test_handoff_keyword_set_reads_the_raw_schema_field_too():
    """Ingestion renames `primary_keyword_for_url` → `primary_keyword`; a caller that
    passes raw handoff targets must get the same set, not an empty one."""
    assert handoff_keyword_set(
        [{"primary_keyword_for_url": "Anxiety Counselling", "source_keyword": ""}]
    ) == {"anxiety counselling"}


# ── matching mechanics ────────────────────────────────────────────────────────

def test_clinical_match_is_word_boundary_not_substring():
    """'air conditioning' must not read as clinical because of 'condition' — the
    substring match in classify_query_tiers is exactly that bug (C-M-08)."""
    assert contains_clinical_term("couples therapy", TERMS)
    assert not contains_clinical_term("air conditioning repair", TERMS)


def test_clinical_match_handles_hyphenated_and_multiword_terms():
    assert contains_clinical_term("self-regulation for teens", TERMS)
    assert contains_clinical_term("chronic anxiety help", TERMS)


def test_brand_token_match_is_word_boundary_and_ignores_one_letter_tokens():
    assert contains_brand_token("jericho counselling reviews", "jericho")
    assert not contains_brand_token("mapquest directions", "map")
    # m.yelp.com derives the token 'm'; one letter is noise, not a brand.
    assert not contains_brand_token("m is for mother", "m")


def test_relevance_requires_handoff_or_clinical_and_never_the_rival_brand():
    handoff = {"couples counselling north vancouver"}
    assert keyword_is_relevant("couples counselling north vancouver", handoff, TERMS, "jericho")
    assert keyword_is_relevant("family therapy", handoff, TERMS, "jericho")
    assert not keyword_is_relevant("555 homer street", handoff, TERMS, "jericho")
    # in the handoff set AND clinical, but it is the rival's own brand → not an opening
    assert not keyword_is_relevant("jericho therapy", handoff | {"jericho therapy"},
                                   TERMS, "jericho")


# ── the universe itself ───────────────────────────────────────────────────────

def test_handoff_targets_are_audited_not_discarded():
    """C-M-01: `group_targets` used to be unused — the audit asked DataForSEO for each
    domain's top-10 instead. The handoff URL and its keyword must be in the universe."""
    targets = [_target("https://comp.com/couples", "couples therapy", rank=2)]
    rows = build_domain_universe(targets, [], {"couples therapy"}, TERMS, "comp")
    assert [(r["url"], r["keyword"], r["position"], r["keyword_source"]) for r in rows] == [
        ("https://comp.com/couples", "couples therapy", 2, SOURCE_HANDOFF)]
    assert rows[0]["keyword_relevant"] is True


def test_handoff_rank_is_kept_not_the_dataforseo_snapshot():
    targets = [_target("https://comp.com/a", "couples therapy", rank=2)]
    dfs = [_dfs_item("https://comp.com/a", "couples therapy", rank_absolute=57, etv=900.0)]
    rows = build_domain_universe(targets, dfs, {"couples therapy"}, TERMS, "comp")
    assert len(rows) == 1
    assert rows[0]["position"] == 2            # Tool 1's rank, not rank_absolute 57
    assert rows[0]["traffic"] == 900.0         # but the ETV is the only one available
    assert rows[0]["keyword_source"] == SOURCE_HANDOFF


def test_off_topic_enrichment_keywords_are_dropped_and_counted():
    """run_11's magnets were 'archdiocese of vancouver', 'airport heights medical clinic'
    and '555 homer street'. None is in the handoff set or carries a clinical term."""
    stats = new_universe_stats()
    dfs = [_dfs_item("https://rcav.org/", "archdiocese of vancouver"),
           _dfs_item("https://rcav.org/x", "555 homer street"),
           _dfs_item("https://rcav.org/y", "grief counselling")]
    rows = build_domain_universe([], dfs, {"grief counselling"}, TERMS, "rcav", stats)
    assert [r["keyword"] for r in rows] == ["grief counselling"]
    assert rows[0]["keyword_source"] == SOURCE_ENRICHMENT
    assert stats["enrichment_dropped_irrelevant"] == 2
    assert stats["enrichment_kept"] == 1


def test_enrichment_keyword_carrying_the_rivals_brand_is_dropped():
    stats = new_universe_stats()
    dfs = [_dfs_item("https://jerichocounselling.com/", "jericho counselling")]
    rows = build_domain_universe([], dfs, set(), TERMS, "jericho", stats)
    assert rows == []
    assert stats["enrichment_dropped_brand"] == 1


def test_handoff_keyword_with_the_rivals_brand_is_audited_but_not_a_magnet():
    """It is what Tool 1 ranked, so it stays in the universe; it is the rival's own
    navigational query, so it can never be a magnet / vacuum / reframe target."""
    stats = new_universe_stats()
    rows = build_domain_universe([_target("https://j.com/", "jericho counselling")], [],
                                 {"jericho counselling"}, TERMS, "jericho", stats)
    assert len(rows) == 1 and rows[0]["keyword_relevant"] is False
    assert stats["handoff_irrelevant"] == 1


def test_handoff_rows_come_first_so_they_get_the_audit_slots():
    """Only `technical.max_audit_pages_per_domain` URLs are scraped per domain, so the
    order decides what is actually audited."""
    rows = build_domain_universe(
        [_target("https://c.com/handoff", "couples therapy")],
        [_dfs_item("https://c.com/other", "family therapy")],
        {"couples therapy"}, TERMS, "c")
    assert [r["keyword_source"] for r in rows] == [SOURCE_HANDOFF, SOURCE_ENRICHMENT]


def test_traffic_defaults_to_zero_meaning_not_measured():
    rows = build_domain_universe([_target("https://c.com/a", "couples therapy")], [],
                                 {"couples therapy"}, TERMS, "c")
    assert rows[0]["traffic"] == 0.0


def test_duplicate_url_keyword_pairs_are_collapsed():
    targets = [_target("https://c.com/a", "couples therapy"),
               _target("https://c.com/a", "Couples Therapy")]
    rows = build_domain_universe(targets, [], {"couples therapy"}, TERMS, "c")
    assert len(rows) == 1


def test_summary_line_states_every_counter():
    stats = new_universe_stats()
    build_domain_universe([_target("https://c.com/a", "couples therapy")],
                          [_dfs_item("https://c.com/b", "555 homer street")],
                          {"couples therapy"}, TERMS, "c", stats)
    line = universe_summary_line(stats)
    assert "handoff targets 1" in line and "off-topic" in line
