"""Chunk X — the handoff / export contract, consumer side.

Spec:  docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md §3 Chunk X
Doc:   docs/handoff_contract.md (the contract these tests hold the code to)

Every test here exercises the REAL consumer. The workplan asks for "a contract
test on both sides"; this is the serp-compete side. The serp-discover side is
not in this repo and is not covered here.

Why a new file rather than more cases in `tests/test_handoff_ingestion.py`:
that file is about the JSON Schema (is this document well-formed?). This one is
about the semantics the schema cannot express — what a field MEANS, which
spellings of a domain are the same site, which version's `rank` is comparable
to which, and what the tool must do when the producer sends something it
cannot trust.
"""
from __future__ import annotations

import json
import unittest

from src.audit_universe import group_targets_by_domain
from src.brand_utils import normalise_domain
from src.handoff_moz import (anchor_coverage, anchor_texts_by_domain,
                             client_domain_mismatch,
                             remember_client_domain,
                             validated_client_domain,
                             error_is_cached, handoff_rank_is_absolute,
                             remember_handoff_version, restrict_to_run,
                             validated_handoff_version)
from src.main import (_unsupported_handoff_version, convert_handoff_to_targets,
                      convert_legacy_to_targets)
from src.sov_analyzer import compute_sov


def _handoff(**overrides):
    """A minimal valid v1.1 handoff. Overrides are shallow."""
    base = {
        "schema_version": "1.1",
        "source_run_id": "run_20261116_0900",
        "source_run_timestamp": "2026-11-16T09:00:00Z",
        "client_domain": "livingsystems.ca",
        "client_brand_names": ["Living Systems", "Living Systems Counselling"],
        "targets": [
            {"url": "https://www.jerichocounselling.com/anxiety",
             "domain": "www.jerichocounselling.com", "rank": 3,
             "entity_type": "service", "content_type": "service",
             "title": "Anxiety Counselling", "source_keyword": "anxiety counselling",
             "primary_keyword_for_url": "anxiety counselling"},
            {"url": "https://jerichocounselling.com/couples",
             "domain": "jerichocounselling.com", "rank": 5,
             "entity_type": "service", "content_type": "service",
             "title": "Couples Counselling", "source_keyword": "couples counselling",
             "primary_keyword_for_url": "couples counselling"},
        ],
        "exclusions": {"client_urls_excluded": 0, "omit_list_excluded": 0,
                       "omit_list_used": []},
    }
    base.update(overrides)
    return base


class TestEveryContractFieldIsRead(unittest.TestCase):
    """A field the producer writes and the consumer drops is a silent defect.

    This is the C-C-13 class: `client_brand_names` was in the schema, written
    by Tool 1, listed in the docs — and discarded by the consumer, which then
    searched for the bare stem "livingsystems" instead. Nothing failed.
    """

    def test_the_targets_fields_all_survive_conversion(self):
        targets, _paa, _brands = convert_handoff_to_targets(_handoff())
        first = targets[0]
        # Mapped names are part of the contract: primary_keyword_for_url ->
        # primary_keyword is what the rest of the run reads.
        self.assertEqual(first["url"], "https://www.jerichocounselling.com/anxiety")
        self.assertEqual(first["domain"], "www.jerichocounselling.com")
        self.assertEqual(first["primary_keyword"], "anxiety counselling")
        self.assertEqual(first["source_keyword"], "anxiety counselling")
        self.assertEqual(first["rank"], 3)
        self.assertEqual(first["entity_type"], "service")
        self.assertEqual(first["content_type"], "service")
        self.assertEqual(first["title"], "Anxiety Counselling")

    def test_client_brand_names_reach_the_caller(self):
        _targets, _paa, brands = convert_handoff_to_targets(_handoff())
        self.assertEqual(brands, ["Living Systems", "Living Systems Counselling"])

    def test_est_traffic_is_zero_meaning_not_measured(self):
        """The handoff carries no traffic estimate. 0 here means "unmeasured",
        and `audit_universe` fills it from DataForSEO's `etv` only when
        DataForSEO reports the same url AND keyword."""
        targets, _paa, _brands = convert_handoff_to_targets(_handoff())
        self.assertTrue(all(t["est_traffic"] == 0 for t in targets))

    def test_the_handoff_has_no_paa_so_the_map_is_empty(self):
        """FEATURE_GUIDE §6.1 promised PAA context in reframes; the handoff has
        no such field, and C1 dropped the promise rather than inventing one.
        Re-adding it needs a producer change (Chunk X, PAA bullet) — until then
        this must stay empty, not be back-filled from anywhere."""
        _targets, paa, _brands = convert_handoff_to_targets(_handoff())
        self.assertEqual(paa, {})

    def test_the_legacy_path_reports_no_brand_names_rather_than_guessing(self):
        _targets, _paa, brands = convert_legacy_to_targets(
            {"organic_results": [{"Link": "https://x.com/a", "Source_Keyword": "k"}]})
        self.assertEqual(brands, [])


class TestDomainCanonicalForm(unittest.TestCase):
    """One site is one competitor, whichever spelling Tool 1 sent.

    Decision 4 (which side canonicalises) is OPEN. These tests assert only
    that this tool copes with both forms, which the workplan says is right
    either way — not where the long-term responsibility sits.
    """

    def test_both_spellings_of_one_site_are_one_group(self):
        groups = group_targets_by_domain(convert_handoff_to_targets(_handoff())[0])
        self.assertEqual(list(groups), ["jerichocounselling.com"])
        self.assertEqual(len(groups["jerichocounselling.com"]), 2)

    def test_the_target_urls_are_not_rewritten(self):
        """Grouping is canonical; fetching is not. `https://www.x.com/a` and
        `https://x.com/a` are not guaranteed to be the same page, so the URL
        the producer sent is the URL that gets scraped."""
        groups = group_targets_by_domain(convert_handoff_to_targets(_handoff())[0])
        urls = sorted(t["url"] for t in groups["jerichocounselling.com"])
        self.assertEqual(urls, ["https://jerichocounselling.com/couples",
                                "https://www.jerichocounselling.com/anxiety"])

    def test_mixed_case_is_the_same_site_too(self):
        handoff = _handoff(targets=[
            {"url": "https://Jericho.com/a", "domain": "Jericho.com", "rank": 1,
             "entity_type": "s", "content_type": "s", "title": "t",
             "source_keyword": "k", "primary_keyword_for_url": "k"},
            {"url": "https://www.jericho.com/b", "domain": "WWW.Jericho.com",
             "rank": 2, "entity_type": "s", "content_type": "s", "title": "t",
             "source_keyword": "k2", "primary_keyword_for_url": "k2"},
        ])
        groups = group_targets_by_domain(convert_handoff_to_targets(handoff)[0])
        self.assertEqual(list(groups), ["jericho.com"])

    def test_a_target_with_no_domain_is_dropped_not_keyed_under_blank(self):
        groups = group_targets_by_domain([{"domain": "", "url": "https://x/a"},
                                          {"domain": None, "url": "https://x/b"},
                                          {"domain": "real.com", "url": "https://real.com"}])
        self.assertEqual(list(groups), ["real.com"])

    def test_the_moz_block_still_matches_a_canonical_run_domain_list(self):
        """The coupling that makes this a contract test rather than two unit
        tests: Tool 1's `moz.domains` keys keep `www.` while the run's domain
        list is canonical. Comparing them raw filtered every `www.` host out,
        so a run whose Moz fetches failed would have reported no anchor risks
        and no unreadable domains either."""
        block = {"domains": {
            "www.jerichocounselling.com": {
                "status": "ok",
                "anchor_texts": {"status": "ok",
                                 "items": [{"anchor": "buy backlinks", "domains": 9}]}},
        }}
        run_domains = list(group_targets_by_domain(
            convert_handoff_to_targets(_handoff())[0]))

        coverage = anchor_coverage(block, run_domains)
        self.assertEqual(coverage["total"], 1)
        self.assertEqual(coverage["with_anchors"], 1)

        anchors = anchor_texts_by_domain(block)
        # The key is canonical, so the risk feed names the same domain the rest
        # of the report does.
        self.assertEqual(list(anchors), ["jerichocounselling.com"])
        self.assertEqual(list(restrict_to_run(anchors, run_domains)),
                         ["jerichocounselling.com"])


class TestSchemaVersionIsEnforced(unittest.TestCase):
    """`handoff.supported_versions` is an allowlist, and it is honoured."""

    def test_a_listed_version_is_accepted(self):
        self.assertIsNone(_unsupported_handoff_version(_handoff(schema_version="1.1")))

    def test_a_listed_2x_version_is_accepted(self):
        """serp-discover's chunk D1 bumped the producer to 2.0/2.1 (absolute
        ranks); refusing them would hard-fail every new handoff."""
        self.assertIsNone(_unsupported_handoff_version(_handoff(schema_version="2.0")))
        self.assertIsNone(_unsupported_handoff_version(_handoff(schema_version="2.1")))

    def test_an_unlisted_version_is_refused_with_a_reason(self):
        error = _unsupported_handoff_version(_handoff(schema_version="9.9"))
        self.assertIsNotNone(error)
        self.assertIn("9.9", error)
        self.assertIn("supported_versions", error)

    def test_an_absent_version_is_refused(self):
        handoff = _handoff()
        handoff.pop("schema_version")
        self.assertIsNotNone(_unsupported_handoff_version(handoff))

    def test_the_configured_list_matches_what_the_schema_documents(self):
        """A guard against the state C-C-14 found: the config listed 2.0/2.1
        while every real handoff and the schema itself carried 1.0/1.1, so
        enforcing the list would have rejected every file. Enforcement only
        helps while the two agree."""
        import os

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with open(os.path.join(root, "shared_config.json")) as f:
            supported = {str(v) for v in
                         json.load(f)["handoff"]["supported_versions"]}
        with open(os.path.join(root, "handoff_schema.json")) as f:
            described = json.load(f)["properties"]["schema_version"]["description"]
        for version in supported:
            self.assertIn(version, described,
                          f"shared_config accepts v{version} but handoff_schema.json's "
                          f"schema_version description does not mention it")


class TestAbsoluteRankVersionsTracksTheProducer(unittest.TestCase):
    """`absolute_rank_versions` records what serp-discover actually emits.

    It is not editorial. Its purpose is to retire the rank-column warning
    exactly when the ranks became trustworthy, so it has to stay in step with
    the producer's `schema_version` — and every version in it has to be one
    this tool will accept at all.
    """

    def _handoff_config(self):
        import os
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with open(os.path.join(root, "shared_config.json")) as f:
            return json.load(f)["handoff"]

    def test_the_2x_versions_are_listed_as_absolute(self):
        """serp-discover chunk D1 (2026-11-16) emits 2.0, or 2.1 with the moz
        block; both carry absolute ranks."""
        cfg = self._handoff_config()
        absolute = {str(v) for v in cfg.get("absolute_rank_versions") or []}
        self.assertIn("2.0", absolute)
        self.assertIn("2.1", absolute)

    def test_the_1x_versions_are_not_listed_as_absolute(self):
        """v1.x ranks were SerpAPI's per-page position; files are still on
        disk and must keep the warning."""
        absolute = {str(v) for v in
                    self._handoff_config().get("absolute_rank_versions") or []}
        self.assertNotIn("1.0", absolute)
        self.assertNotIn("1.1", absolute)

    def test_every_absolute_version_is_also_supported(self):
        """A version flagged absolute but not supported is unreachable: the
        run hard-fails before the warning is ever evaluated."""
        cfg = self._handoff_config()
        absolute = {str(v) for v in cfg.get("absolute_rank_versions") or []}
        supported = {str(v) for v in cfg.get("supported_versions") or []}
        self.assertTrue(
            absolute <= supported,
            f"absolute_rank_versions not in supported_versions: "
            f"{sorted(absolute - supported)}")

    def test_the_warning_retires_on_the_configured_versions(self):
        """End to end: a 2.0 handoff read with the repo's own config reports
        absolute ranks, a 1.1 one does not."""
        from src.handoff_moz import handoff_rank_is_absolute, remember_handoff_version
        absolute = [str(v) for v in
                    self._handoff_config().get("absolute_rank_versions") or []]
        try:
            remember_handoff_version(_handoff(schema_version="2.0"))
            self.assertTrue(handoff_rank_is_absolute(absolute_versions=absolute))
            remember_handoff_version(_handoff(schema_version="1.1"))
            self.assertFalse(handoff_rank_is_absolute(absolute_versions=absolute))
        finally:
            remember_handoff_version({})


class TestRankSemantics(unittest.TestCase):
    """`targets[].rank` is absolute from v2.0, page-relative in v1.0/v1.1 (H1).

    serp-discover's chunk D1 fixed the producer on 2026-11-16, but v1.x files
    are still on disk, so the contract is unchanged: know which version you
    are reading, and say so in the report.
    """

    def tearDown(self):
        remember_handoff_version({})

    def test_todays_versions_are_not_absolute(self):
        self.assertIs(handoff_rank_is_absolute("1.0", []), False)
        self.assertIs(handoff_rank_is_absolute("1.1", []), False)

    def test_a_version_the_owner_lists_is_absolute(self):
        self.assertIs(handoff_rank_is_absolute("1.2", ["1.2"]), True)

    def test_no_version_means_no_claim_either_way(self):
        """The legacy and manual paths carry no version and no rank, so the
        answer is None — not False, which would print a warning about a rank
        column that does not exist."""
        self.assertIsNone(handoff_rank_is_absolute("", []))

    def test_the_version_is_remembered_from_the_validated_handoff(self):
        remember_handoff_version(_handoff(schema_version="1.1"))
        self.assertEqual(validated_handoff_version(), "1.1")

    def test_a_second_ingestion_does_not_inherit_the_first_version(self):
        """P8: the legacy and manual paths set no version, and a run in the
        same process must not report the previous handoff's."""
        remember_handoff_version(_handoff(schema_version="1.1"))
        remember_handoff_version({})
        self.assertEqual(validated_handoff_version(), "")

    # What the REPORT does with this verdict is asserted against the real
    # rendered markdown in test_main_run_coverage.py
    # (test_chunk_x_the_report_warns_that_handoff_ranks_are_page_relative).
    # Re-implementing the report line here would repeat the mistake this chunk
    # removed from tests/test_handoff_ingestion.py.


class TestSovEngineCoverage(unittest.TestCase):
    """An engine that answered nothing is not an engine that found nothing.

    serp-discover writes brand-mention rows for engines it skipped or that
    failed (D-C-05 / D-C-11), carrying `questions_total: 0`.
    """

    @staticmethod
    def _export(**overrides):
        base = {
            "data_available": True,
            "engines": ["gemini", "perplexity"],
            "brand_mentions": [
                {"engine": "gemini", "brand": "Living Systems", "mention_count": 3,
                 "questions_total": 4, "is_client": True, "source": "gazetteer"},
                {"engine": "perplexity", "brand": "Living Systems", "mention_count": 0,
                 "questions_total": 0, "is_client": True, "source": "gazetteer"},
            ],
            "ai_citations": [],
            "answer_sentiment": [],
        }
        base.update(overrides)
        return base

    def test_a_zero_question_engine_publishes_no_shares(self):
        res = compute_sov(self._export(), ["theravive.com"], "2026-11-16")
        self.assertNotIn("perplexity", {r["engine"] for r in res["rows"]})

    def test_the_unmeasured_engine_is_named_rather_than_dropped_silently(self):
        res = compute_sov(self._export(), ["theravive.com"], "2026-11-16")
        self.assertEqual(res["unmeasured_engines"], ["perplexity"])

    def test_the_measured_engine_is_unaffected(self):
        res = compute_sov(self._export(), ["theravive.com"], "2026-11-16")
        gemini = [r for r in res["rows"] if r["engine"] == "gemini"]
        self.assertTrue(gemini)
        self.assertEqual(gemini[0]["presence_rate"], 0.75)   # 3 of 4 answers

    def test_an_engine_that_asked_and_found_nothing_keeps_its_rows(self):
        """A measured absence is a finding, not missing data: 0 mentions over 4
        questions must still be published."""
        res = compute_sov(self._export(brand_mentions=[
            {"engine": "gemini", "brand": "Living Systems", "mention_count": 0,
             "questions_total": 4, "is_client": True, "source": "gazetteer"},
        ]), ["theravive.com"], "2026-11-16")
        self.assertEqual([r["engine"] for r in res["rows"]], ["gemini"])
        self.assertEqual(res["unmeasured_engines"], [])

    def test_presence_rate_is_none_not_zero_when_the_count_is_missing(self):
        """0.0 asserts "named in none of the answers"; None says "no rate"."""
        res = compute_sov({
            "data_available": True, "engines": ["gemini"],
            "brand_mentions": [
                {"engine": "gemini", "brand": "A", "mention_count": 2,
                 "questions_total": 4, "is_client": True, "source": "g"},
                # Same engine, but this row carries no count of its own.
                {"engine": "gemini", "brand": "B", "mention_count": 1,
                 "is_client": False, "source": "g"},
            ],
            "ai_citations": [], "answer_sentiment": [],
        }, [], "2026-11-16")
        by_entity = {r["entity"]: r for r in res["rows"]}
        self.assertEqual(by_entity["A"]["presence_rate"], 0.5)
        self.assertIsNone(by_entity["B"]["presence_rate"])

    def test_engine_coverage_records_what_was_asked(self):
        res = compute_sov(self._export(), [], "2026-11-16")
        coverage = {c["engine"]: c for c in res["engine_coverage"]}
        self.assertEqual(coverage["gemini"]["questions_total"], 4)
        self.assertTrue(coverage["gemini"]["measured"])
        self.assertFalse(coverage["perplexity"]["measured"])

    def test_an_engine_with_no_rows_at_all_is_recorded_as_unknown(self):
        """Three states, not two.

        From the export alone, an engine with no brand-mention rows could have
        been asked 10 questions with no tracked brand coming back, or never have
        run. Recording it as measured-with-0-questions would be a row
        contradicting itself; recording it as *unmeasured* would claim knowledge
        the file does not carry. So it is NULL, and the report says coverage is
        unknown for it.
        """
        res = compute_sov({
            "data_available": True, "engines": ["gemini", "openai"],
            "brand_mentions": [
                {"engine": "gemini", "brand": "A", "mention_count": 1,
                 "questions_total": 2, "is_client": True, "source": "g"}],
            "ai_citations": [], "answer_sentiment": [],
        }, [], "2026-11-16")
        self.assertEqual({r["engine"] for r in res["rows"]}, {"gemini"})
        coverage = {c["engine"]: c for c in res["engine_coverage"]}
        self.assertIsNone(coverage["openai"]["measured"])
        self.assertIsNone(coverage["openai"]["questions_total"])
        # …and it is NOT named as unmeasured, which would overstate what is known.
        self.assertEqual(res["unmeasured_engines"], [])

    def test_the_unknown_state_survives_the_database(self):
        import os
        import tempfile

        from src.database import DatabaseManager

        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(os.path.join(tmp, "t.db"))
            run_id = db.create_run("livingsystems.ca")
            db.save_sov_coverage(run_id, [
                {"engine": "gemini", "questions_total": 4, "measured": True},
                {"engine": "openai", "questions_total": None, "measured": None},
                {"engine": "perplexity", "questions_total": 0, "measured": False},
            ])
            stored = {c["engine"]: c["measured"] for c in db.get_sov_coverage(run_id)}
            self.assertEqual(stored, {"gemini": True, "openai": None,
                                      "perplexity": False})

    def test_a_zero_question_engines_citations_are_dropped_too(self):
        """An engine that answered nothing cannot have cited anything, so
        publishing its citations alone would put a citation share in the report
        for a run that did not happen."""
        res = compute_sov({
            "data_available": True, "engines": ["perplexity"],
            "brand_mentions": [
                {"engine": "perplexity", "brand": "A", "mention_count": 0,
                 "questions_total": 0, "is_client": True, "source": "g"}],
            "ai_citations": [
                {"engine": "perplexity", "domain": "theravive.com",
                 "brand": "Theravive", "is_client": False, "cite_count": 3}],
            "answer_sentiment": [],
        }, ["theravive.com"], "2026-11-16")
        self.assertEqual(res["rows"], [])
        self.assertEqual(res["gaps"], [])
        self.assertEqual(res["unmeasured_engines"], ["perplexity"])

    def test_the_coverage_round_trips_through_the_database(self):
        import os
        import tempfile

        from src.database import DatabaseManager

        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(os.path.join(tmp, "t.db"))
            run_id = db.create_run("livingsystems.ca")
            res = compute_sov(self._export(), [], "2026-11-16")
            db.save_sov_coverage(run_id, res["engine_coverage"])
            stored = {c["engine"]: c for c in db.get_sov_coverage(run_id)}
            self.assertFalse(stored["perplexity"]["measured"])
            self.assertEqual(stored["gemini"]["questions_total"], 4)
            # Idempotent: saving the same run twice must not double the rows.
            db.save_sov_coverage(run_id, res["engine_coverage"])
            self.assertEqual(len(db.get_sov_coverage(run_id)), 2)

    def test_an_unrecorded_run_reads_as_unknown_not_as_complete(self):
        import os
        import tempfile

        from src.database import DatabaseManager

        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(os.path.join(tmp, "t.db"))
            run_id = db.create_run("livingsystems.ca")
            self.assertEqual(db.get_sov_coverage(run_id), [])


class TestMozCachedErrors(unittest.TestCase):
    """A cached error re-served for 30 days is one outage, not thirty."""

    ASSEMBLED = "2026-11-16T09:00:00+00:00"

    def test_a_block_fetched_during_the_run_is_fresh(self):
        self.assertIs(error_is_cached({"fetched_at": "2026-11-16T08:40:00+00:00"},
                                      self.ASSEMBLED, 24.0), False)

    def test_a_month_old_block_is_a_cache_hit(self):
        self.assertIs(error_is_cached({"fetched_at": "2026-10-18T08:00:00+00:00"},
                                      self.ASSEMBLED, 24.0), True)

    def test_an_undated_block_is_neither(self):
        self.assertIsNone(error_is_cached({}, self.ASSEMBLED, 24.0))

    def test_an_unparseable_date_is_neither(self):
        self.assertIsNone(error_is_cached({"fetched_at": "last Tuesday"},
                                          self.ASSEMBLED, 24.0))

    def test_a_naive_timestamp_is_read_as_utc_rather_than_crashing(self):
        """Tool 1 has emitted both `...Z` and offset-less stamps."""
        self.assertIs(error_is_cached({"fetched_at": "2026-10-18T08:00:00"},
                                      "2026-11-16T09:00:00", 24.0), True)

    def test_the_coverage_splits_them_without_inflating_the_total(self):
        from src.risk_radar import anchor_caveat_lines, anchor_data_unreadable

        block = {"generated_at": self.ASSEMBLED, "domains": {
            "fresh.com": {"anchor_texts": {"status": "error"},
                          "fetched_at": "2026-11-16T08:55:00+00:00"},
            "cached.com": {"anchor_texts": {"status": "error"},
                           "fetched_at": "2026-10-18T08:00:00+00:00"},
            "undated.com": {"anchor_texts": {"status": "error"}},
        }}
        counts = anchor_coverage(block, ["fresh.com", "cached.com", "undated.com"])
        self.assertEqual(counts["errored"], 3)
        self.assertEqual(counts["errored_cached"], 1)
        self.assertEqual(counts["errored_age_unknown"], 1)
        # The sub-counts are OF `errored`, so the unreadable total stays 3.
        self.assertEqual(anchor_data_unreadable(counts), 3)

        lines = " ".join(anchor_caveat_lines(["anchor_text_spam"], counts))
        self.assertIn("cache", lines)
        self.assertIn("no collection date", lines)

    def test_no_extra_clause_when_every_error_is_this_runs(self):
        from src.risk_radar import anchor_caveat_lines

        block = {"generated_at": self.ASSEMBLED, "domains": {
            "fresh.com": {"anchor_texts": {"status": "error"},
                          "fetched_at": "2026-11-16T08:55:00+00:00"}}}
        counts = anchor_coverage(block, ["fresh.com"])
        lines = " ".join(anchor_caveat_lines([], counts))
        self.assertNotIn("cache", lines)


if __name__ == "__main__":
    unittest.main()


class TestGscPullIsStated(unittest.TestCase):
    """Chunk X (GSC bullet): the report must say which GSC pull it is.

    The two tools pulled GSC with different windows and filters and neither
    report said so, so a figure from one was read beside a figure from the
    other as though they described the same traffic.
    """

    @staticmethod
    def _markdown(gsc_settings):
        from src.reporting import gsc_pull_note

        return gsc_pull_note({"gsc_settings": gsc_settings})

    def test_the_report_section_uses_this_note(self):
        """The note is only worth testing if the section actually renders it.

        Asserted by rendering the real GSC section's text through the same
        function the section calls, and checking the section calls it — the
        alternative was standing up a full `generate_summary`, which also
        writes the Excel workbook and needs a populated database.
        """
        import inspect

        from src.reporting import ReportGenerator

        source = inspect.getsource(ReportGenerator.generate_summary)
        # Chunk Y17: the section hands the note its already-loaded messages,
        # so the words come from one read rather than one per section.
        self.assertIn("gsc_pull_note(self.config, m)", source)

    def test_the_window_country_and_device_are_printed(self):
        markdown = self._markdown({"date_range_days": 90, "country": "can"})
        self.assertIn("last 90 days", markdown)
        self.assertIn("country `can`", markdown)
        # Chunk X: the pull filters the device too, and the default when the
        # key is absent is the `desktop` the DataForSEO snapshot requests.
        self.assertIn("desktop only", markdown)
        self.assertNotIn("all devices", markdown)

    def test_an_unfiltered_device_is_declared_as_not_comparable(self):
        """Clicks averaged over desktop and mobile are not comparable with a
        desktop-only SERP snapshot, so the report says so rather than printing
        the CTR beside the rank in silence."""
        markdown = self._markdown({"date_range_days": 90, "country": "can",
                                   "device": "all"})
        self.assertIn("every device", markdown)
        self.assertIn("desktop and mobile clicks averaged together", markdown)

    @staticmethod
    def _request(gsc_settings):
        """Build a real GSC request body and hand it back.

        A source-text guard proves nothing here: the mutation that matters
        leaves the filter text in place inside a dead branch. So the request
        is built by the real method against a service that records the body.
        """
        from types import SimpleNamespace

        from src.gsc_performance import GSCManager

        class _Recorder:
            def __init__(self):
                self.bodies = []

            def searchanalytics(self):
                return self

            def query(self, siteUrl=None, body=None):
                self.bodies.append(body)
                return SimpleNamespace(execute=lambda: {"rows": []})

        service = _Recorder()
        manager = GSCManager.__new__(GSCManager)
        manager.config = {
            "auth": {"gsc_property_url": "https://livingsystems.ca/"},
            "gsc_settings": gsc_settings,
        }
        manager.service = service
        manager._cached_sites = None
        manager.fetch_performance_data()
        return service.bodies[0]

    def _filters(self, gsc_settings):
        groups = self._request(gsc_settings).get("dimensionFilterGroups") or []
        return groups[0]["filters"] if groups else []

    def test_the_request_filters_the_device_the_line_claims(self):
        """The caveat is only true if the request carries the filter."""
        from src.gsc_performance import GSC_DEVICES

        self.assertEqual(GSC_DEVICES["desktop"], "DESKTOP")
        filters = self._filters({"date_range_days": 90, "country": "can"})
        self.assertIn({"dimension": "device", "operator": "equals",
                       "expression": "DESKTOP"}, filters)

    def test_the_country_filter_is_not_lost_when_the_device_one_is_added(self):
        """Both filters live in one group, so the request carries both."""
        filters = self._filters({"date_range_days": 90, "country": "can"})
        self.assertIn({"dimension": "country", "operator": "equals",
                       "expression": "can"}, filters)
        self.assertEqual(len(filters), 2, filters)

    def test_an_unfiltered_device_sends_no_device_filter(self):
        """`device: all` is the state the report calls not comparable; the
        request must actually be unfiltered, or the line is wrong."""
        filters = self._filters({"date_range_days": 90, "country": "can",
                                 "device": "all"})
        self.assertEqual([f["dimension"] for f in filters], ["country"])

    def test_the_line_does_not_assert_the_other_tools_filters(self):
        """Nothing here reads serp-discover's config, so this report cannot
        state its country or device as fact (P6). It said "all devices,
        global", which stopped being true at that tool's chunk D5."""
        markdown = self._markdown({"date_range_days": 90, "country": "can"})
        self.assertNotIn("global", markdown)
        self.assertIn("states in its own report", markdown)

    def test_a_typo_is_not_printed_as_a_deliberate_choice(self):
        """An unrecognised `gsc_settings.device` pulls every device, exactly as
        `all` does, but it is a misconfiguration. Printing the two identically
        hid it behind a sentence that read deliberate."""
        markdown = self._markdown({"date_range_days": 90, "country": "can",
                                   "device": "deksotp"})
        self.assertIn("which GSC does not accept", markdown)
        self.assertIn("NOT comparable", markdown)
        self.assertIn("not by choice", markdown)
        # Not the wording a deliberate `all` gets.
        self.assertNotIn("averaged together, while", markdown)

    def test_a_non_desktop_device_is_declared_not_comparable(self):
        """`mobile` printed "mobile only" and then said nothing, which is the
        one case that is certainly not comparable with the SERP snapshot."""
        markdown = self._markdown({"date_range_days": 90, "country": "can",
                                   "device": "mobile"})
        self.assertIn("mobile only", markdown)
        self.assertIn("NOT comparable", markdown)

    def test_comparability_is_checked_against_the_snapshot_not_asserted(self):
        """"The country filter matches the DataForSEO snapshot" was printed for
        any non-empty country, so `usa` claimed comparability with a Canada
        snapshot. The claim is now a comparison with the config the DataForSEO
        calls read."""
        from src.api_clients import snapshot_market

        self.assertEqual(snapshot_market()["country"], "can")
        matching = self._markdown({"date_range_days": 90, "country": "can"})
        self.assertIn("so the two are comparable", matching)
        other = self._markdown({"date_range_days": 90, "country": "usa"})
        self.assertIn("NOT the same market", other)
        self.assertNotIn("so the two are comparable", other)

    def test_the_serp_calls_read_the_same_snapshot_config(self):
        """The two sides of the comparability claim must be one value, not a
        config key beside a Python literal (P4/P6)."""
        import inspect

        from src import api_clients

        source = inspect.getsource(api_clients)
        # One literal only: the documented fallback beside the config key.
        self.assertEqual(source.count('"location_code": 2124'), 1, source.count(
            '"location_code": 2124'))
        self.assertIn('snapshot_market()["location_code"]', source)
        self.assertIn('snapshot_market()["device"]', source)

    @staticmethod
    def _written(render):
        """Run a report writer against a stubbed `open` and return its text.

        The writers put their files in the project root, so this must not let
        them run for real. Asserting over the source text instead was vacuous:
        the strike report also names `_pull_note()` in a `print`, so dropping
        it from the markdown left a green guard.
        """
        from unittest import mock

        chunks = []
        handle = mock.MagicMock()
        handle.write.side_effect = chunks.append
        opener = mock.MagicMock()
        opener.return_value.__enter__.return_value = handle
        with mock.patch("builtins.open", opener):
            render()
        return "".join(chunks)

    def _manager(self):
        from src.gsc_performance import GSCManager

        from src.briefing_messages import Messages

        manager = GSCManager.__new__(GSCManager)
        manager.config = {
            "auth": {"gsc_property_url": "https://livingsystems.ca/"},
            "gsc_settings": {"date_range_days": 90, "country": "can"},
        }
        # What `__init__` holds (chunk Y17). Read here rather than inside
        # `_pull_note` for the reason the real manager does: these tests patch
        # `open` to capture the write, and a read inside the write window gets
        # the mock.
        manager.messages = Messages()
        return manager

    def test_the_strike_list_states_the_pull(self):
        """Only the summary carried the note; the strike list prints positions
        and impressions from the same narrowed pull."""
        import pandas as pd

        manager = self._manager()
        text = self._written(
            lambda: manager.generate_strike_report(pd.DataFrame()))
        self.assertIn("_Pull: last 90 days", text)
        self.assertIn("desktop only", text)

    def test_the_gap_report_states_the_pull(self):
        import pandas as pd

        manager = self._manager()
        text = self._written(lambda: manager.generate_report(
            pd.DataFrame(), pd.DataFrame(), []))
        self.assertIn("_Pull: last 90 days", text)

    def test_an_empty_gsc_report_does_not_read_as_nothing_to_do(self):
        """Zero rows is also what a failed pull prints, so the empty state
        names the filters rather than standing alone (P1).

        Read from the RENDERED markdown, not from the method's source: the
        sentence moved into `briefing_messages.json` in chunk Y17, and a
        source-text assertion would have gone green the moment the words left
        Python while the report still printed nothing (P19/P27)."""
        import pandas as pd

        manager = self._manager()
        text = self._written(
            lambda: manager.generate_strike_report(pd.DataFrame()))
        self.assertIn("also what a failed pull", text)
        self.assertIn("Check the filters", text)

    def test_the_report_path_does_not_import_the_gsc_dependencies(self):
        """`GSC_DEVICES` at module scope pulled google-auth, googleapiclient,
        spacy and openai into every report render."""
        import inspect

        from src import reporting

        head = inspect.getsource(reporting).split("def md_table")[0]
        self.assertNotIn("from src.gsc_performance import", head)

    def test_a_non_default_window_is_printed_as_configured(self):
        """The line is read from the key `GSCManager` reads, so changing the
        window changes the report rather than leaving a stale 90 behind."""
        markdown = self._markdown({"date_range_days": 28, "country": "can"})
        self.assertIn("last 28 days", markdown)
        self.assertNotIn("last 90 days", markdown)

    def test_no_country_filter_is_declared_as_not_comparable(self):
        """Without the filter this is global traffic, and the DataForSEO SERP
        snapshot is Canada-scoped — the report must not let the two be read
        side by side as the same market."""
        markdown = self._markdown({"date_range_days": 90, "country": ""})
        self.assertIn("no country filter", markdown)
        self.assertIn("NOT comparable", markdown)


class TestTheClientsOwnHostIsRecognisedInEitherForm(unittest.TestCase):
    """Review chunk Y1 — the consumer compares hosts, not spellings.

    Handoff files already on disk carry the pre-chunk-X form, so the client
    entry's `domain` can be `www.livingsystems.ca` while every competitor key
    beside it is bare. A raw compare made the client's own anchors lose to a
    richer competitor sample filed under the same site.
    """

    def _block(self, client_spelling):
        return {
            "generated_at": "2026-11-17T00:00:00Z",
            "domains": {
                "livingsystems.ca": {
                    "anchor_texts": {"items": [{"anchor_text": "a"},
                                               {"anchor_text": "b"},
                                               {"anchor_text": "c"}]}},
            },
            "client": {
                "domain": client_spelling,
                "anchor_texts": {"items": [{"anchor_text": "own"}]}},
        }

    def test_the_client_entry_wins_whatever_form_it_is_written_in(self):
        for spelling in ("livingsystems.ca", "WWW.LivingSystems.ca",
                         "m.livingsystems.ca"):
            anchors = anchor_texts_by_domain(self._block(spelling))
            self.assertEqual(
                [i["anchor_text"] for i in anchors["livingsystems.ca"]["items"]],
                ["own"], spelling)


class TestTheHandoffsClientIsCheckedAgainstThisRepos(unittest.TestCase):
    """Review chunk Y1 — a handoff produced for another client is reported.

    Tool 1 publishes `client_domain`; nothing here read it, so a handoff for
    one site could be audited against another site's `shared_config`, and
    every figure compared one client's SERPs with another's configuration.
    """

    def setUp(self):
        remember_client_domain({})

    tearDown = setUp

    def test_a_handoff_for_another_client_is_named_as_a_mismatch(self):
        remember_client_domain({"client_domain": "someoneelse.ca"})
        self.assertEqual(validated_client_domain(), "someoneelse.ca")
        note = client_domain_mismatch("livingsystems.ca")
        self.assertIn("someoneelse.ca", note)
        self.assertIn("livingsystems.ca", note)

    def test_the_same_client_in_another_form_is_not_a_mismatch(self):
        remember_client_domain({"client_domain": "WWW.LivingSystems.ca"})
        self.assertEqual(client_domain_mismatch("livingsystems.ca"), "")

    def test_a_handoff_that_does_not_say_is_not_a_disagreement(self):
        """The legacy and manual paths carry no client domain. Silence is not
        a mismatch (P1)."""
        remember_client_domain({})
        self.assertEqual(validated_client_domain(), "")
        self.assertEqual(client_domain_mismatch("livingsystems.ca"), "")

    def test_the_previous_handoffs_client_is_not_inherited(self):
        remember_client_domain({"client_domain": "someoneelse.ca"})
        remember_client_domain({})
        self.assertEqual(client_domain_mismatch("livingsystems.ca"), "")

    def test_the_report_carries_the_mismatch_not_just_the_console(self):
        """The console line is read once; the report is what is still here
        weeks later, and without the caveat it reads clean."""
        from src.reporting import client_mismatch_line

        remember_client_domain({"client_domain": "someoneelse.ca"})
        note = client_domain_mismatch("livingsystems.ca")
        line = client_mismatch_line({"client_domain_mismatch": note})
        self.assertIn("Client mismatch", line)
        self.assertIn("someoneelse.ca", line)
        self.assertEqual(client_mismatch_line({}), "")
        self.assertEqual(client_mismatch_line(None), "")

    def test_the_report_header_renders_that_line(self):
        """`generate_summary` writes the workbook and needs a populated
        database, so the call is asserted on the assembly rather than by
        standing the whole report up."""
        import inspect

        from src.reporting import ReportGenerator

        source = inspect.getsource(ReportGenerator.generate_summary)
        self.assertIn("client_mismatch_line(run_coverage, m)", source)

    def test_the_check_runs_before_the_no_targets_abort(self):
        """A handoff for the wrong client is a likely reason for there to be
        no targets at all; behind the abort the run died without naming it."""
        import inspect

        from src import main

        # The audit's body moved into `_run_audit` when review chunk
        # Y13 wrapped `run_audit` to report a failed database cleanup
        # on every exit path; the ordering this checks is in the body.
        source = inspect.getsource(main._run_audit)
        self.assertIn("client_domain_mismatch", source)
        self.assertLess(source.index("client_domain_mismatch("),
                        source.index("No competitors identified"))
        self.assertIn('"client_domain_mismatch": client_mismatch',
                      inspect.getsource(main))


class TestTheHostRuleIsTheProducersRule(unittest.TestCase):
    """Review chunk Y1 cold review — mirroring the prefix list is not enough.

    `normalise_domain` kept the scheme, the path, the port and the userinfo
    while the producer stripped all four, so `https://m.x.ca/p` was `x.ca`
    there and the whole string here. `tests/host_canonical_cases.json` is the
    one definition both repos are checked against, byte-identical on both
    sides the way `handoff_schema.json` is.
    """

    def _table(self):
        import os

        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "host_canonical_cases.json"),
                  encoding="utf-8") as f:
            return json.load(f)["cases"], here

    def test_every_case_comes_out_canonical(self):
        cases, _ = self._table()
        for raw, expected in cases.items():
            self.assertEqual(normalise_domain(raw), expected, repr(raw))

    def test_the_table_has_not_drifted_from_the_producers(self):
        import os

        _, here = self._table()
        theirs = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(here))), "serp-discover", "tests",
            "host_canonical_cases.json")
        if not os.path.exists(theirs):          # the sibling repo is optional
            self.skipTest("serp-discover not checked out beside this repo")
        with open(theirs, "rb") as f:
            a = f.read()
        with open(os.path.join(here, "host_canonical_cases.json"), "rb") as f:
            b = f.read()
        self.assertEqual(a, b,
                         "the two repos' host case tables have drifted")

    def test_the_handoff_module_has_no_weaker_copy_of_the_rule(self):
        """`handoff_moz` carried an `ImportError` fallback that stripped
        `www.` only, so under it the client compare, the mismatch check and
        every anchor key silently reverted to the pre-Y1 rule (P45)."""
        import inspect

        from src import handoff_moz

        self.assertIs(handoff_moz.normalise_domain, normalise_domain)
        self.assertNotIn("removeprefix", inspect.getsource(handoff_moz))
