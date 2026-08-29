"""Tests for C6 / SC-8 — Reputation-Risk Radar (src/risk_radar.py).

Covers SC-8.1 (a synthetic ~60% visibility drop → visibility_cliff high with the drop %
in evidence), SC-8.2 (parasite needs topical mismatch AND commercial intent, not the
subfolder name alone), SC-8.3 (own-site signals separated from competitor signals),
SC-8.4 (paid-link/PBN footprints in inbound anchor text, and ingesting the Moz block
Tool 1 attaches to the competitor handoff), plus the DB reader/writer.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pytest

from src.database import DatabaseManager
from src.handoff_moz import anchor_coverage, anchor_texts_by_domain, load_moz_block
from src.risk_radar import anchor_caveat_lines, anchor_data_unreadable
from src.risk_radar import (
    detect_visibility_cliff, detect_parasite, compute_risk_signals,
    detect_anchor_spam,
)

CONFIG = {"cliff_drop_pct": 0.5, "volatility_high_shift": 6,
          "commercial_terms": ["casino", "loan", "cheap", "bonus"]}


# ── SC-8.1 visibility cliff ───────────────────────────────────────────────────

def test_sc81_visibility_cliff_high_with_drop_pct():
    sig = detect_visibility_cliff([100, 90, 80, 40], CONFIG)   # peak 100, latest 40 → 60%
    assert sig["signal_type"] == "visibility_cliff"
    assert sig["severity"] == "high"
    assert sig["evidence"]["drop_pct"] == 60.0


def test_no_cliff_when_stable():
    assert detect_visibility_cliff([100, 98, 99], CONFIG) is None
    assert detect_visibility_cliff([100], CONFIG) is None      # too little history


def test_sc81_cliff_medium_severity_reachable():
    """Sweep F4: with cliff_drop_pct 0.3 the medium/low tiers are live (not always high)."""
    sig = detect_visibility_cliff([100, 65], {"cliff_drop_pct": 0.3, "cliff_lookback": 6})
    assert sig["severity"] == "medium"     # 35% drop → medium


def test_cliff_historical_drop_scrolls_out_of_window():
    """Sweep F4: a collapse that happened long ago (outside cliff_lookback) and has been
    flat-low since must STOP re-flagging on every future run."""
    cfg = {"cliff_drop_pct": 0.3, "cliff_lookback": 3}
    assert detect_visibility_cliff([100, 40, 40, 40, 40], cfg) is None   # last 3 are flat


# ── SC-8.2 parasite requires mismatch AND commercial intent ───────────────────

def test_sc82_parasite_requires_mismatch_and_commercial():
    core = ["therapy", "counselling"]
    assert detect_parasite("/deals", ["cheap casino bonus"], core, CONFIG["commercial_terms"]) is not None
    assert detect_parasite("/blog", ["gardening tips"], core, CONFIG["commercial_terms"]) is None      # mismatch, no commercial
    assert detect_parasite("/x", ["therapy cheap"], core, CONFIG["commercial_terms"]) is None          # on-topic (overlap) + commercial


def test_sc82_word_boundary_no_false_positive_on_substring():
    """Sweep F3: 'dealing'/'promoting' must NOT match the commercial words 'deal'/'promo'
    (word-boundary, not substring) — legitimate therapy content isn't flagged."""
    core = ["mindfulness", "coaching"]   # /grief keywords are a topical mismatch vs core
    assert detect_parasite("/grief", ["dealing with grief", "promoting healing"],
                           core, ["deal", "promo", "casino"]) is None


def test_sc82_subfolder_name_alone_does_not_flag():
    # subfolder literally "/casino" but its keywords are on-topic → NOT a parasite
    assert detect_parasite("/casino", ["therapy for anxiety"], ["therapy"],
                           CONFIG["commercial_terms"]) is None


# ── SC-8.3 own-site signals separated from competitor signals ─────────────────

def test_sc83_own_and_competitor_signals_separated():
    rows = compute_risk_signals(
        volatility_alerts=[{"domain": "rival.com", "shift": 8}],
        series_by_domain={"livingsystems.ca": [100, 30]},   # own-site cliff
        parasite_candidates=[], own_domain="livingsystems.ca", config=CONFIG)
    own = [r for r in rows if r["is_own_site"]]
    comp = [r for r in rows if not r["is_own_site"]]
    assert any(r["domain"] == "livingsystems.ca" and r["signal_type"] == "visibility_cliff" for r in own)
    assert any(r["domain"] == "rival.com" and r["signal_type"] == "ranking_volatility" for r in comp)


# ── DB reader + writer ────────────────────────────────────────────────────────

def test_save_risk_signals_roundtrip(tmp_path):
    db = DatabaseManager(str(tmp_path / "r.db"))
    run_id = db.create_run("c.com")
    rows = compute_risk_signals([], {"a.com": [100, 20]}, [], "livingsystems.ca", CONFIG)
    db.save_risk_signals(run_id, rows, detected_at="2026-07-22")
    with db._get_connection() as conn:
        got = conn.execute("SELECT signal_type, evidence_json FROM risk_signal WHERE run_id=?",
                           (run_id,)).fetchall()
    assert len(got) == 1 and got[0][0] == "visibility_cliff"
    assert json.loads(got[0][1])["drop_pct"] == 80.0


def test_get_parasite_candidates_core_from_other_subfolders(tmp_path):
    db = DatabaseManager(str(tmp_path / "p.db"))
    run_id = db.create_run("c.com")
    db.save_competitor_metrics([
        {"domain": "big.com", "url": "https://big.com/therapy/anxiety", "keyword": "therapy anxiety", "position": 3, "traffic": 10},
        {"domain": "big.com", "url": "https://big.com/therapy/grief", "keyword": "grief counselling", "position": 5, "traffic": 5},
        {"domain": "big.com", "url": "https://big.com/casino/slots", "keyword": "best casino bonus", "position": 2, "traffic": 100},
    ], run_id)
    cands = db.get_parasite_candidates(run_id)
    casino = next(c for c in cands if c["subfolder"] == "/casino")
    assert "best casino bonus" in casino["keywords"]
    # core comes from the OTHER subfolders (/therapy), enabling the mismatch judgement
    core_text = " ".join(casino["core_terms"]).lower()
    assert "therapy" in core_text or "grief" in core_text


def test_get_visibility_series_graceful_and_with_data(tmp_path):
    db = DatabaseManager(str(tmp_path / "v.db"))
    assert db.get_visibility_series("x.com") == []   # market_history absent → graceful, no crash
    with db._get_connection() as conn:
        conn.execute("""CREATE TABLE market_history (id INTEGER PRIMARY KEY, domain TEXT,
            url TEXT, keyword TEXT, rank INTEGER, da INTEGER, systems_score REAL,
            medical_score REAL, timestamp DATETIME)""")
        conn.execute("INSERT INTO market_history (domain, rank, timestamp) VALUES ('x.com', 3, '2026-01-01')")
        conn.execute("INSERT INTO market_history (domain, rank, timestamp) VALUES ('x.com', 15, '2026-01-02')")
        conn.commit()
    assert db.get_visibility_series("x.com") == [1.0, 0.0]   # day1 rank3→top10=1; day2 rank15→0


# ── SC-8.4 anchor-text spam ───────────────────────────────────────────────────

def _shared_config():
    """shared_config.json lives at the outer repo root, one level above this
    inner package."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    with open(os.path.join(root, "shared_config.json"), encoding="utf-8") as f:
        return json.load(f)


#: Anchors as Tool 1 actually delivers them — this is the real shape captured
#: from bowencenter.org, PBN phrases included.
REAL_ANCHORS = [
    {"text": "bowen center", "external_root_domains": 108, "external_pages": 410},
    {"text": "", "external_root_domains": 53, "external_pages": 488},
    {"text": "bowencenter.org", "external_root_domains": 53, "external_pages": 174},
    {"text": "www.bowencenter.org", "external_root_domains": 47, "external_pages": 251},
    {"text": "high quality dofollow backlinks da 50 pa 40 premium pbn network "
             "service bowencenter.org rank first page google fast seo link "
             "building buy backlinks online cheap",
     "external_root_domains": 44, "external_pages": 45},
    {"text": "visit website", "external_root_domains": 35, "external_pages": 204},
]

CLEAN_ANCHORS = [
    {"text": "bowen center", "external_root_domains": 108, "external_pages": 410},
    {"text": "family systems training", "external_root_domains": 20, "external_pages": 40},
]


class TestAnchorSpam(unittest.TestCase):
    """SC-8.4 — a paid-link/PBN footprint in inbound anchor text."""

    def test_detects_pbn_anchors_in_real_data(self):
        signal = detect_anchor_spam(REAL_ANCHORS)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["signal_type"], "anchor_text_spam")
        self.assertEqual(signal["evidence"]["matched_anchor_count"], 1)
        self.assertEqual(signal["evidence"]["linking_domains_matched"], 44)

    def test_clean_anchor_profile_yields_no_signal(self):
        self.assertIsNone(detect_anchor_spam(CLEAN_ANCHORS))

    def test_empty_input_yields_no_signal(self):
        self.assertIsNone(detect_anchor_spam([]))
        self.assertIsNone(detect_anchor_spam(None))

    def test_terms_match_on_whole_words_not_substrings(self):
        """"pbn" must not fire inside "pbnetwork", nor "backlinks" inside a
        longer token — the parasite detector already holds this line."""
        anchors = [{"text": "pbnetwork solutions and backlinkstrategy",
                    "external_root_domains": 30}]
        self.assertIsNone(detect_anchor_spam(anchors))

    def test_multi_word_terms_match_as_phrases(self):
        anchors = [{"text": "cheap link building packages",
                    "external_root_domains": 10}]
        signal = detect_anchor_spam(anchors)
        self.assertIsNotNone(signal)
        self.assertIn("link building",
                      signal["evidence"]["sample_anchors"][0]["matched_terms"])

    def test_severity_follows_share_of_linking_domains(self):
        """One spam anchor carried by many domains outranks several carried by
        one each — severity is about reach, not phrase count."""
        wide = [{"text": "buy backlinks", "external_root_domains": 90},
                {"text": "brand name", "external_root_domains": 10}]
        narrow = [{"text": "buy backlinks", "external_root_domains": 6},
                  {"text": "brand name", "external_root_domains": 999}]
        self.assertEqual(detect_anchor_spam(wide)["severity"], "high")
        self.assertEqual(detect_anchor_spam(narrow)["severity"], "medium")

    def test_a_single_link_cannot_reach_high_severity(self):
        """Adversarial: with one anchor sampled the share is 1.0 by
        arithmetic, not by evidence. A competitor must not be named at high
        severity because one scraped directory linked to them (P7)."""
        one_link = [{"text": "cheap seo", "external_root_domains": 1}]
        signal = detect_anchor_spam(one_link)
        self.assertEqual(signal["evidence"]["share_of_sampled_linking_domains"], 1.0)
        self.assertEqual(signal["severity"], "low")

    def test_anchor_reach_floor_is_configurable(self):
        anchors = [{"text": "buy backlinks", "external_root_domains": 6},
                   {"text": "brand", "external_root_domains": 4}]
        self.assertEqual(detect_anchor_spam(anchors)["severity"], "high")
        self.assertEqual(
            detect_anchor_spam(
                anchors, {"anchor_spam_min_anchor_reach": 50})["severity"],
            "low")

    def test_many_narrow_anchors_from_one_source_cannot_reach_high(self):
        """Adversarial, and the case that defeated the first version of this
        floor: one PBN page typically carries several anchor variants at once.
        Moz gives reach per anchor with no domain identity, so summing across
        anchors double-counts a single source — five anchors of reach 1 cleared
        a floor of 5 and named a competitor "high" off one scraper (P7)."""
        one_source = [{"text": t, "external_root_domains": 1} for t in
                      ("buy backlinks", "cheap seo", "dofollow", "pbn",
                       "guest post")]
        signal = detect_anchor_spam(one_source)
        self.assertEqual(signal["evidence"]["share_of_sampled_linking_domains"], 1.0)
        self.assertEqual(signal["severity"], "low")

    def test_a_measured_zero_is_data_not_an_unreadable_value(self):
        """`int(0)` succeeds, so a measured zero must keep falling through the
        ordinary reach gate. Routing it to the unmeasured branch manufactured a
        competitor-naming signal from a measurement that says "no reach", with
        an interpretation that contradicted itself (P1/P14)."""
        self.assertIsNone(
            detect_anchor_spam([{"text": "buy backlinks",
                                 "external_root_domains": 0}]))

    def test_truncated_sample_cannot_reach_high_severity(self):
        """The producer flags a capped page expressly so it is not read as a
        complete link profile — the share's denominator is known to be too
        small, so it cannot support "high" (P9)."""
        anchors = [{"text": "buy backlinks", "external_root_domains": 90},
                   {"text": "brand name", "external_root_domains": 10}]
        self.assertEqual(detect_anchor_spam(anchors)["severity"], "high")
        truncated = detect_anchor_spam(anchors, sample_truncated=True)
        self.assertEqual(truncated["severity"], "medium")
        self.assertTrue(truncated["evidence"]["sample_truncated"])

    def test_matched_text_with_unmeasurable_reach_is_reported_not_dropped(self):
        """Zero-from-non-empty must be loud: a producer field rename would
        otherwise turn every match into a silent "no signal" (P19/P2)."""
        anchors = [{"text": "buy backlinks pbn dofollow",
                    "external_root_domains": None}]
        signal = detect_anchor_spam(anchors)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["severity"], "low")
        self.assertEqual(signal["evidence"]["unmeasured_anchor_count"], 1)
        self.assertIn("could not be measured",
                      signal["evidence"]["interpretation"])

    def test_unmeasured_signal_does_not_assert_a_footprint(self):
        """The branch that says "scale unknown" must not also assert a
        paid-link footprint in the next sentence — that text is printed
        verbatim under a named competitor (P14)."""
        signal = detect_anchor_spam([{"text": "buy backlinks",
                                      "external_root_domains": None}])
        interpretation = signal["evidence"]["interpretation"]
        self.assertNotIn("Inbound anchors show", interpretation)
        self.assertIn("prompt to look, not as a finding", interpretation)

    def test_matched_anchor_count_means_one_thing_on_both_paths(self):
        """One key, one meaning: the unmeasured path must not reuse it for a
        different quantity (P19/P22)."""
        unmeasured = detect_anchor_spam(
            [{"text": "buy backlinks", "external_root_domains": None}])["evidence"]
        self.assertEqual(unmeasured["matched_anchor_count"], 0)
        self.assertEqual(unmeasured["unmeasured_anchor_count"], 1)
        measured = detect_anchor_spam(
            [{"text": "buy backlinks", "external_root_domains": 9}])["evidence"]
        self.assertEqual(measured["matched_anchor_count"], 1)
        self.assertEqual(measured["unmeasured_anchor_count"], 0)

    def test_evidence_says_links_received_not_links_bought(self):
        """Anchors are written by other sites: a domain can be the target of a
        scheme it had no part in, and the wording must keep that reading open."""
        interpretation = detect_anchor_spam(REAL_ANCHORS)["evidence"]["interpretation"]
        # Assert the load-bearing clauses, not that the sentence contains the
        # word "not" — which is true of almost any English sentence and left
        # this guard unable to fail (P27).
        self.assertIn("links RECEIVED", interpretation)
        self.assertIn("not links necessarily bought", interpretation)
        self.assertIn("targeted by a scheme it had no part in", interpretation)
        self.assertIn("not a confirmed penalty", interpretation)

    def test_terms_are_configurable(self):
        signal = detect_anchor_spam(
            CLEAN_ANCHORS, {"anchor_spam_terms": ["family systems training"]})
        self.assertIsNotNone(signal)

    def test_empty_term_list_disables_the_detector(self):
        self.assertIsNone(
            detect_anchor_spam(REAL_ANCHORS, {"anchor_spam_terms": []}))

    def test_min_domains_threshold_is_respected(self):
        anchors = [{"text": "buy backlinks", "external_root_domains": 2}]
        self.assertIsNone(
            detect_anchor_spam(anchors, {"anchor_spam_min_domains": 5}))
        self.assertIsNotNone(
            detect_anchor_spam(anchors, {"anchor_spam_min_domains": 2}))

    def test_malformed_entries_do_not_raise(self):
        anchors = [None, "a string", {"text": None},
                   {"text": "buy backlinks", "external_root_domains": "not a number"},
                   {"text": "buy backlinks", "external_root_domains": 5}]
        signal = detect_anchor_spam(anchors)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["evidence"]["linking_domains_matched"], 5)

    def test_samples_are_ordered_by_reach(self):
        anchors = [{"text": "buy backlinks", "external_root_domains": 3},
                   {"text": "cheap seo", "external_root_domains": 40}]
        samples = detect_anchor_spam(anchors)["evidence"]["sample_anchors"]
        self.assertEqual(samples[0]["external_root_domains"], 40)

    def test_shipped_config_carries_the_terms(self):
        """The term list is editorial and belongs in shared_config.json, not
        in Python source (this repo's CLAUDE.md)."""
        cfg = _shared_config()
        terms = cfg["risk_signals"]["anchor_spam_terms"]
        self.assertTrue(terms)
        self.assertIn("pbn", terms)

    def test_code_fallbacks_match_the_editorial_config_exactly(self):
        """A fallback that drifts from config makes the same anchors score
        differently by call path, and editing the JSON stops changing
        behaviour (P4). The term list already diverged once; the three numeric
        settings are duplicated the same way and are covered here too."""
        from src import risk_radar as rr
        cfg = _shared_config()["risk_signals"]
        self.assertEqual(list(rr.DEFAULT_ANCHOR_SPAM_TERMS),
                         cfg["anchor_spam_terms"])
        self.assertEqual(rr.DEFAULT_ANCHOR_SPAM_MIN_DOMAINS,
                         cfg["anchor_spam_min_domains"])
        self.assertEqual(rr.DEFAULT_ANCHOR_SPAM_HIGH_SHARE,
                         cfg["anchor_spam_high_share"])
        self.assertEqual(rr.DEFAULT_ANCHOR_SPAM_MIN_ANCHOR_REACH,
                         cfg["anchor_spam_min_anchor_reach"])


class TestRadarWiring(unittest.TestCase):
    """The detector must actually run inside compute_risk_signals."""

    def test_anchor_signal_reaches_the_unified_feed(self):
        rows = compute_risk_signals(
            volatility_alerts=[], series_by_domain={}, parasite_candidates=[],
            own_domain="livingsystems.ca",
            anchor_texts_by_domain={"bowencenter.org": REAL_ANCHORS})
        anchor_rows = [r for r in rows if r["signal_type"] == "anchor_text_spam"]
        self.assertEqual(len(anchor_rows), 1)
        self.assertEqual(anchor_rows[0]["domain"], "bowencenter.org")

    def test_own_site_anchor_spam_is_tagged(self):
        """SC-8.3 — own-site warnings stay separable from competitor intel.

        The radar's tagging, in isolation. The live path — the client's anchors
        arriving via `moz.client` — is covered by TestOwnSiteAnchorPath.
        """
        rows = compute_risk_signals(
            volatility_alerts=[], series_by_domain={}, parasite_candidates=[],
            own_domain="livingsystems.ca",
            anchor_texts_by_domain={"livingsystems.ca": REAL_ANCHORS})
        self.assertTrue(rows[0]["is_own_site"])

    def test_omitting_anchors_leaves_existing_behaviour_unchanged(self):
        """The parameter is optional: callers that never pass it behave
        exactly as they did before."""
        without = compute_risk_signals(
            volatility_alerts=[{"domain": "a.com", "shift": 9}],
            series_by_domain={}, parasite_candidates=[], own_domain="x.com")
        with_empty = compute_risk_signals(
            volatility_alerts=[{"domain": "a.com", "shift": 9}],
            series_by_domain={}, parasite_candidates=[], own_domain="x.com",
            anchor_texts_by_domain={})
        self.assertEqual(without, with_empty)
        self.assertEqual(len(without), 1)

    def test_config_flows_through_to_the_detector(self):
        rows = compute_risk_signals(
            volatility_alerts=[], series_by_domain={}, parasite_candidates=[],
            own_domain="x.com", config={"anchor_spam_terms": []},
            anchor_texts_by_domain={"bowencenter.org": REAL_ANCHORS})
        self.assertEqual(rows, [])


class TestHandoffMozIngestion(unittest.TestCase):
    """Reading the Moz block Tool 1 attaches to the handoff."""

    HANDOFF = {
        "schema_version": "1.1",
        "source_run_id": "r1",
        "source_run_timestamp": "2026-08-28T12:00:00+00:00",
        "client_domain": "livingsystems.ca",
        "client_brand_names": ["Living Systems"],
        "targets": [],
        "exclusions": {"client_urls_excluded": 0, "omit_list_excluded": 0,
                       "omit_list_used": []},
        "moz": {
            "generated_at": "2026-08-28T12:00:00+00:00",
            "locale": "en-CA", "scope": "domain",
            "domains": {
                "bowencenter.org": {
                    "data_available": True, "status": "ok",
                    "anchor_texts": {"status": "ok", "items": REAL_ANCHORS,
                                     "returned": len(REAL_ANCHORS),
                                     "truncated": False},
                },
                "nodata.example": {
                    "data_available": False, "status": "no_record",
                    "anchor_texts": {"status": "no_record", "items": [],
                                     "returned": 0, "truncated": False},
                },
            },
        },
    }

    @staticmethod
    def _with_handoff(payload):
        """Write a handoff to a temp file and read its Moz block back."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "competitor_handoff_test.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            return load_moz_block(path)

    def test_moz_block_is_read_from_the_handoff(self):
        block = self._with_handoff(self.HANDOFF)
        self.assertIn("bowencenter.org", block["domains"])

    def test_v1_0_handoff_without_moz_yields_empty(self):
        payload = {k: v for k, v in self.HANDOFF.items() if k != "moz"}
        payload["schema_version"] = "1.0"
        self.assertEqual(self._with_handoff(payload), {})

    def test_unreadable_handoff_yields_empty_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "competitor_handoff_broken.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not json")
            self.assertEqual(load_moz_block(path), {})

    def test_missing_handoff_yields_empty(self):
        self.assertEqual(load_moz_block(None), {})
        self.assertEqual(load_moz_block("/nonexistent/handoff.json"), {})

    def test_anchor_extraction_skips_domains_with_no_anchors(self):
        """A domain whose anchor fetch found nothing is omitted, not mapped to
        an empty list — "no anchors collected" must not read downstream as
        "no spam anchors"."""
        extracted = anchor_texts_by_domain(self.HANDOFF["moz"])
        self.assertEqual(list(extracted), ["bowencenter.org"])
        self.assertEqual(len(extracted["bowencenter.org"]["items"]), len(REAL_ANCHORS))

    def test_truncation_flag_survives_extraction(self):
        block = {"domains": {"a.com": {"anchor_texts": {
            "status": "ok", "items": REAL_ANCHORS, "truncated": True}}}}
        self.assertTrue(anchor_texts_by_domain(block)["a.com"]["truncated"])

    def test_coverage_separates_errored_from_empty(self):
        """A Moz outage must not render as a clean bill of health: "we could
        not look" and "we looked and found nothing" are different (P1/P2)."""
        block = {"domains": {
            "ok.com": {"anchor_texts": {"status": "ok", "items": REAL_ANCHORS}},
            "empty.com": {"anchor_texts": {"status": "no_record", "items": []}},
            "broken.com": {"anchor_texts": {"status": "error", "items": []}},
        }}
        counts = anchor_coverage(block)
        self.assertEqual(counts, {"total": 3, "with_anchors": 1, "no_record": 1,
                                  "errored": 1, "skipped": 0, "unknown": 0,
                                  "read_no_anchors": 0})

    def test_coverage_counts_a_skipped_domain_as_skipped_not_no_record(self):
        """A domain Tool 1 capped or dropped for quota carries no anchor_texts
        key at all, so its status lives on the domain block. Counting it as
        "no record" turned "we ran out of budget" into "we looked and found
        nothing" — transient read as terminal, inside the function written to
        stop exactly that (P1)."""
        block = {"domains": {
            "a.com": {"status": "skipped_run_cap"},
            "b.com": {"status": "skipped_quota"},
            "c.com": {"status": "no_record"},
        }}
        counts = anchor_coverage(block)
        self.assertEqual(counts["skipped"], 2)
        self.assertEqual(counts["no_record"], 1)

    def test_anchor_extraction_tolerates_an_empty_block(self):
        self.assertEqual(anchor_texts_by_domain({}), {})
        self.assertEqual(anchor_texts_by_domain(None), {})

    def test_end_to_end_handoff_to_signal(self):
        """The whole path: a real handoff in, a risk signal out."""
        anchors = anchor_texts_by_domain(self.HANDOFF["moz"])
        rows = compute_risk_signals(
            volatility_alerts=[], series_by_domain={}, parasite_candidates=[],
            own_domain="livingsystems.ca", anchor_texts_by_domain=anchors)
        self.assertEqual([r["signal_type"] for r in rows], ["anchor_text_spam"])
        self.assertEqual(rows[0]["domain"], "bowencenter.org")

class TestReportCaveats(unittest.TestCase):
    """SC-8.4 — the disclaimer and the coverage note must reach the report.

    The seam lives in risk_radar, not reporting: the caveat is a property of
    the signal, and reporting.py imports pandas at module scope, so a guard
    placed there would be unimportable — and therefore skipped — in any
    environment without it, leaving the most sensitive line in the change with
    no executable test at all (P25/P27).
    """

    @staticmethod
    def _lines(signal_types, coverage=None):
        from src.risk_radar import anchor_caveat_lines
        return anchor_caveat_lines(signal_types, coverage)

    def test_anchor_signal_brings_the_received_not_bought_caveat(self):
        lines = self._lines(["anchor_text_spam"])
        self.assertEqual(len(lines), 1)
        self.assertIn("received", lines[0])
        self.assertIn("not links bought", lines[0])
        self.assertIn("no part in", lines[0])

    def test_no_anchor_signal_means_no_caveat(self):
        self.assertEqual(self._lines(["ranking_volatility", "visibility_cliff"]), [])

    def test_unreadable_domains_produce_a_coverage_line(self):
        """A run where every anchor fetch failed must not render identically
        to a clean one."""
        lines = self._lines([], {"total": 3, "with_anchors": 0, "errored": 2,
                                 "skipped": 1, "no_record": 0, "unknown": 0})
        self.assertEqual(len(lines), 1)
        self.assertIn("0 of 3", lines[0])
        self.assertIn("not evidence of a clean link profile", lines[0])

    def test_skipped_domains_count_as_unreadable(self):
        lines = self._lines([], {"total": 2, "with_anchors": 1, "errored": 0,
                                 "skipped": 1, "no_record": 0, "unknown": 0})
        self.assertTrue(lines)

    def test_fully_readable_coverage_adds_no_noise(self):
        self.assertEqual(
            self._lines([], {"total": 3, "with_anchors": 3, "errored": 0,
                             "skipped": 0, "no_record": 0, "unknown": 0}),
            [])

    def test_both_lines_appear_together(self):
        lines = self._lines(["anchor_text_spam"],
                            {"total": 2, "with_anchors": 1, "errored": 1,
                             "skipped": 0, "no_record": 0, "unknown": 0})
        self.assertEqual(len(lines), 2)

class TestMainWiring(unittest.TestCase):
    """main.py cannot be imported here (it pulls pandas/spacy at module load),
    so its call sites are checked by parsing rather than executing. Matching
    source *text* would also match a comment; the AST cannot (P19 corollary)."""

    @staticmethod
    def _tree():
        import ast
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        with open(os.path.join(root, "main.py"), encoding="utf-8") as f:
            return ast.parse(f.read())

    def _call_kwargs(self, func_name):
        import ast
        for node in ast.walk(self._tree()):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == func_name):
                return {kw.arg for kw in node.keywords}
        raise AssertionError(f"main.py never calls {func_name}")

    def test_anchor_kwargs_are_passed_by_name_not_unpacked(self):
        """`**dict(zip(...))` truncates to the shorter side without error, so a
        change on either side would silently drop a kwarg — a silent drop
        inside the code added to prevent silent drops (P2)."""
        kwargs = self._call_kwargs("run_comparison_features")
        self.assertIn("anchor_texts_by_domain", kwargs)
        self.assertIn("anchor_coverage", kwargs)
        self.assertNotIn(None, kwargs, "a **unpacking is still present")

    def _method_call_kwargs(self, method_name):
        import ast
        for node in ast.walk(self._tree()):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == method_name):
                return {kw.arg for kw in node.keywords}
        raise AssertionError(f"main.py never calls {method_name}")

    def test_fetch_failure_returns_the_unavailable_sentinel(self):
        """The except branch must return a coverage dict that is
        distinguishable from "nothing was attempted", or a total failure of
        the anchor path renders as a clean run (P2/P25)."""
        import ast
        for node in ast.walk(self._tree()):
            if not (isinstance(node, ast.FunctionDef)
                    and node.name == "_handoff_anchor_texts"):
                continue
            handlers = [h for h in ast.walk(node) if isinstance(h, ast.ExceptHandler)]
            self.assertTrue(handlers, "_handoff_anchor_texts has no except branch")
            returned = "".join(ast.unparse(n) for h in handlers
                               for n in ast.walk(h) if isinstance(n, ast.Return))
            self.assertIn("fetch_status", returned)
            self.assertIn("unavailable", returned)
            return
        self.fail("main.py has no _handoff_anchor_texts")

    def test_coverage_is_persisted_not_threaded_to_the_report(self):
        """The report reads coverage from the DB, so an OLD run's report can
        still say what could not be read. A threaded parameter only ever
        describes the run happening right now."""
        import ast
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        with open(os.path.join(root, "reporting.py"), encoding="utf-8") as f:
            reporting_src = f.read()
        self.assertIn("get_anchor_coverage", reporting_src)
        self.assertNotIn("anchor_coverage",
                         self._method_call_kwargs("generate_summary"))

    def test_coverage_is_saved_alongside_the_signals(self):
        import ast
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        with open(os.path.join(root, "comparison_features.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        saved = {n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn("save_anchor_coverage", saved)
        self.assertIn("save_risk_signals", saved)

class TestCoverageHonesty(unittest.TestCase):
    """Third-sweep fixes: a caveat must have a cause, and a total failure must
    not look like a clean run."""

    def test_read_with_no_anchors_is_not_unreadable(self):
        """The producer's ordinary shape for "ranking data, no anchor text" is
        status ok with empty items. Counting it unreadable put a warning about
        untrustworthy data on a clean run, listing no cause at all (P1/P14)."""
        block = {"domains": {
            "a.com": {"status": "ok", "anchor_texts": {
                "status": "ok",
                "items": [{"text": "brand", "external_root_domains": 3}]}},
            "b.com": {"status": "ok", "anchor_texts": {
                "status": "ok", "items": [], "returned": 0}},
        }}
        counts = anchor_coverage(block)
        self.assertEqual(counts["read_no_anchors"], 1)
        self.assertEqual(counts["unknown"], 0)
        self.assertEqual(anchor_data_unreadable(counts), 0)
        self.assertEqual(anchor_caveat_lines([], counts), [])

    def test_an_unrecognised_status_is_still_unreadable(self):
        counts = anchor_coverage({"domains": {"a.com": {"status": "who_knows"}}})
        self.assertEqual(counts["unknown"], 1)
        self.assertEqual(anchor_data_unreadable(counts), 1)

    def test_caveat_names_only_causes_that_occurred(self):
        counts = {"total": 3, "with_anchors": 1, "errored": 2, "skipped": 0,
                  "no_record": 0, "unknown": 0, "read_no_anchors": 0}
        line = anchor_caveat_lines([], counts)[0]
        self.assertIn("2 errored", line)
        self.assertNotIn("0 skipped", line)

    def test_total_fetch_failure_is_reported_not_silent(self):
        """A failed anchor path must not render identically to a run where
        nothing was attempted — the one case where silence is correct (P2)."""
        unavailable = {"total": 0, "fetch_status": "unavailable",
                       "reason": "handoff unreadable"}
        self.assertGreaterEqual(anchor_data_unreadable(unavailable), 1)
        line = anchor_caveat_lines([], unavailable)[0]
        self.assertIn("could not be retrieved", line)
        self.assertIn("handoff unreadable", line)
        self.assertIn("not evidence of a clean link profile", line)

    def test_nothing_attempted_stays_silent(self):
        """A schema-1.0 handoff carries no moz block; silence is correct."""
        self.assertEqual(anchor_caveat_lines([], {}), [])
        self.assertEqual(anchor_data_unreadable({}), 0)

    def test_unmeasured_anchors_cap_severity(self):
        """Unmeasured anchors leave the denominator, so a share computed over a
        fraction of the sample cannot support "high" — the same guard
        sample_truncated already applies, different cause (P5/P9)."""
        anchors = [{"text": "buy backlinks", "external_root_domains": 9}]
        self.assertEqual(detect_anchor_spam(anchors)["severity"], "high")
        swamped = anchors + [{"text": "buy backlinks",
                              "external_root_domains": None} for _ in range(5)]
        signal = detect_anchor_spam(swamped)
        self.assertEqual(signal["severity"], "medium")
        self.assertEqual(signal["evidence"]["reach_unmeasured_for"], 5)


class TestReportWiring(unittest.TestCase):
    """The caveat render must be reachable from reporting.py, and provably so.

    Testing the seam's return value says nothing about whether anyone calls it:
    deleting the render left the suite at exactly its baseline. reporting.py
    cannot be imported here (pandas), but it can be parsed — which is what the
    same commit already does for main.py (P21/P27).
    """

    @staticmethod
    def _source():
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        with open(os.path.join(root, "reporting.py"), encoding="utf-8") as f:
            return f.read()

    def test_reporting_calls_the_caveat_builder(self):
        import ast
        called = {
            node.func.id for node in ast.walk(ast.parse(self._source()))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("anchor_caveat_lines", called)

    def test_reporting_uses_the_shared_unreadable_definition(self):
        import ast
        called = {
            node.func.id for node in ast.walk(ast.parse(self._source()))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("anchor_data_unreadable", called)

    def test_report_section_opens_when_data_was_unreadable(self):
        """Otherwise a run where every fetch failed produces no section at all
        and the caveat has nowhere to appear."""
        import ast
        for node in ast.walk(ast.parse(self._source())):
            if (isinstance(node, ast.If) and isinstance(node.test, ast.BoolOp)
                    and isinstance(node.test.op, ast.Or)
                    and any(isinstance(v, ast.Name) and v.id == "unreadable"
                            for v in node.test.values)):
                return
        self.fail("the risk section is not gated on `... or unreadable`")

class TestOwnSiteAnchorPath(unittest.TestCase):
    """The client's own anchors must reach the detector and be tagged.

    Tool 1 excludes the client from `moz.domains`, so its anchors travel in
    `moz.client`. Before Tool 1 sent them and this read them, the own-site
    branch — the one that would reveal negative SEO aimed at the client — was
    tested and documented against data the producer could never emit (P21).
    """

    CLIENT_ANCHORS = [
        {"text": "buy backlinks cheap seo", "external_root_domains": 40},
        {"text": "living systems counselling", "external_root_domains": 12},
    ]

    BLOCK = {
        "generated_at": "2026-08-28T12:00:00+00:00",
        "locale": "en-CA", "scope": "domain",
        "client": {
            "domain": "livingsystems.ca",
            "brand_authority": {"status": "ok", "data_available": True, "score": 1},
            "anchor_texts": {"status": "ok", "items": CLIENT_ANCHORS,
                             "returned": 2, "truncated": False},
        },
        "domains": {
            "bowencenter.org": {
                "data_available": True, "status": "ok",
                "anchor_texts": {"status": "ok", "items": REAL_ANCHORS,
                                 "returned": len(REAL_ANCHORS), "truncated": False},
            },
        },
    }

    def test_client_anchors_are_extracted(self):
        extracted = anchor_texts_by_domain(self.BLOCK)
        self.assertIn("livingsystems.ca", extracted)
        self.assertEqual(len(extracted["livingsystems.ca"]["items"]), 2)

    def test_competitor_anchors_still_extracted_alongside(self):
        extracted = anchor_texts_by_domain(self.BLOCK)
        self.assertEqual(set(extracted), {"livingsystems.ca", "bowencenter.org"})

    def test_own_site_signal_is_tagged_from_a_real_producer_shape(self):
        """End to end on the shape Tool 1 actually emits — the assertion the
        old own-site test could not make."""
        rows = compute_risk_signals(
            volatility_alerts=[], series_by_domain={}, parasite_candidates=[],
            own_domain="livingsystems.ca",
            anchor_texts_by_domain=anchor_texts_by_domain(self.BLOCK))
        own = [r for r in rows if r["is_own_site"]]
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0]["domain"], "livingsystems.ca")
        self.assertEqual(own[0]["signal_type"], "anchor_text_spam")

    def test_a_clean_client_profile_raises_no_own_site_signal(self):
        block = dict(self.BLOCK)
        block["client"] = dict(self.BLOCK["client"])
        block["client"]["anchor_texts"] = {
            "status": "ok", "truncated": False, "returned": 1,
            "items": [{"text": "living systems counselling",
                       "external_root_domains": 30}]}
        rows = compute_risk_signals(
            volatility_alerts=[], series_by_domain={}, parasite_candidates=[],
            own_domain="livingsystems.ca",
            anchor_texts_by_domain=anchor_texts_by_domain(block))
        self.assertEqual([r["is_own_site"] for r in rows], [False])

    def test_client_is_counted_in_coverage(self):
        """A failed fetch of the client's own anchors must be as visible as any
        other — it is the one that would hide a campaign aimed at the client."""
        self.assertEqual(anchor_coverage(self.BLOCK)["total"], 2)
        self.assertEqual(anchor_coverage(self.BLOCK)["with_anchors"], 2)

    def test_a_handoff_without_a_client_entry_still_works(self):
        block = {"domains": self.BLOCK["domains"]}
        self.assertEqual(list(anchor_texts_by_domain(block)), ["bowencenter.org"])
        self.assertEqual(anchor_coverage(block)["total"], 1)

    def test_a_client_entry_without_anchors_is_not_counted(self):
        """Brand Authority alone must not inflate the anchor coverage total."""
        block = {"domains": {}, "client": {
            "domain": "livingsystems.ca",
            "brand_authority": {"status": "ok", "data_available": True, "score": 1}}}
        self.assertEqual(anchor_texts_by_domain(block), {})
        self.assertEqual(anchor_coverage(block)["total"], 0)

class TestStaleAttribution(unittest.TestCase):
    """SC-8.4: anchors can be up to 30 days old, and can outlive a competitor."""

    BLOCK = {
        "generated_at": "2026-08-01T09:00:00+00:00",
        "locale": "en-CA", "scope": "domain",
        "domains": {"bowencenter.org": {"status": "ok", "anchor_texts": {
            "status": "ok", "items": REAL_ANCHORS, "truncated": False}}},
    }

    def test_collected_at_is_read_from_the_block(self):
        from src.handoff_moz import moz_collected_at
        self.assertEqual(moz_collected_at(self.BLOCK), "2026-08-01T09:00:00+00:00")
        self.assertIsNone(moz_collected_at({}))
        self.assertIsNone(moz_collected_at({"generated_at": ""}))

    def test_collected_at_reaches_the_evidence(self):
        """Tool 1 caches for 30 days, so a signal stamped only with the run's
        detected_at asserts a freshness the data does not have (P6)."""
        signal = detect_anchor_spam(REAL_ANCHORS, collected_at="2026-08-01T09:00:00+00:00")
        self.assertEqual(signal["evidence"]["collected_at"], "2026-08-01T09:00:00+00:00")

    def test_collected_at_reaches_the_evidence_via_the_radar(self):
        rows = compute_risk_signals(
            volatility_alerts=[], series_by_domain={}, parasite_candidates=[],
            own_domain="livingsystems.ca",
            anchor_texts_by_domain=anchor_texts_by_domain(self.BLOCK),
            anchor_collected_at="2026-08-01T09:00:00+00:00")
        self.assertEqual(rows[0]["evidence"]["collected_at"],
                         "2026-08-01T09:00:00+00:00")

    def test_unmeasured_branch_also_carries_collected_at(self):
        signal = detect_anchor_spam(
            [{"text": "buy backlinks", "external_root_domains": None}],
            collected_at="2026-08-01T09:00:00+00:00")
        self.assertEqual(signal["evidence"]["collected_at"],
                         "2026-08-01T09:00:00+00:00")

    def test_absent_generated_at_is_none_not_a_guess(self):
        signal = detect_anchor_spam(REAL_ANCHORS)
        self.assertIsNone(signal["evidence"]["collected_at"])

    def test_moz_block_from_handles_every_shape(self):
        from src.handoff_moz import moz_block_from
        handoff = {"schema_version": "1.1", "moz": self.BLOCK}
        self.assertEqual(moz_block_from(handoff), self.BLOCK)
        self.assertEqual(moz_block_from({"schema_version": "1.0"}), {})
        self.assertEqual(moz_block_from(None), {})
        self.assertEqual(moz_block_from({"moz": "not a dict"}), {})

    def test_the_file_loader_uses_the_same_extractor(self):
        """One definition of "which part of a handoff is the Moz block", so the
        validated-reuse path and the file path cannot drift.

        Asserts they AGREE on the same document — the previous version of this
        test only exercised moz_block_from, so mutating load_moz_block left it
        green while its name promised otherwise (P27)."""
        from src.handoff_moz import load_moz_block, moz_block_from
        handoff = {"schema_version": "1.1", "moz": self.BLOCK}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "competitor_handoff_x.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(handoff, f)
            self.assertEqual(load_moz_block(path), moz_block_from(handoff))
            self.assertEqual(load_moz_block(path), self.BLOCK)


class TestMainReusesTheValidatedBlock(unittest.TestCase):
    """main.py must not re-read the handoff unvalidated (parsed, not imported)."""

    @staticmethod
    def _tree():
        import ast
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        with open(os.path.join(root, "main.py"), encoding="utf-8") as f:
            return ast.parse(f.read())

    def test_anchor_path_does_not_reload_the_handoff_file(self):
        """The first read is schema-validated; a second raw read of the same
        file let the moz block bypass validation entirely (P6/P11)."""
        import ast
        for node in ast.walk(self._tree()):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == "_handoff_anchor_texts"):
                body = ast.unparse(node)
                self.assertIn("_VALIDATED_MOZ_BLOCK", body)
                self.assertNotIn("find_latest_handoff_file", body)
                self.assertNotIn("load_moz_block", body)
                return
        self.fail("main.py has no _handoff_anchor_texts")

    def test_the_validated_block_is_remembered_on_every_handoff_path(self):
        """Including the schema-file-missing branch, which still ingests."""
        import ast
        calls = [n for n in ast.walk(self._tree())
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "_remember_moz_block"]
        self.assertGreaterEqual(len(calls), 2)

class TestRunScoping(unittest.TestCase):
    """SC-8.4: a signal must not be attributed to a domain this run never saw."""

    ANCHORS = {"bowencenter.org": {"items": REAL_ANCHORS, "truncated": False},
               "gone.example": {"items": REAL_ANCHORS, "truncated": False},
               "livingsystems.ca": {"items": REAL_ANCHORS, "truncated": False}}

    def test_domains_outside_the_run_are_dropped(self):
        from src.handoff_moz import restrict_to_run
        kept = restrict_to_run(self.ANCHORS, ["bowencenter.org"], "livingsystems.ca")
        self.assertEqual(set(kept), {"bowencenter.org", "livingsystems.ca"})

    def test_the_client_is_kept_even_though_it_is_not_a_competitor(self):
        """It is excluded from the competitor list by design and is exactly the
        domain the own-site check exists for."""
        from src.handoff_moz import restrict_to_run
        kept = restrict_to_run(self.ANCHORS, [], "livingsystems.ca")
        self.assertEqual(set(kept), {"livingsystems.ca"})

    def test_matching_is_case_insensitive(self):
        from src.handoff_moz import restrict_to_run
        kept = restrict_to_run({"BowenCenter.org": {"items": []}},
                               ["bowencenter.org"], "")
        self.assertEqual(set(kept), {"BowenCenter.org"})

    def test_no_client_and_no_domains_keeps_nothing(self):
        from src.handoff_moz import restrict_to_run
        self.assertEqual(restrict_to_run(self.ANCHORS, [], ""), {})

    def test_empty_input_is_safe(self):
        from src.handoff_moz import restrict_to_run
        self.assertEqual(restrict_to_run(None, ["a.com"], "b.com"), {})


class TestCoveragePersistence(unittest.TestCase):
    """SC-8.4: a past run's anchor coverage must be recoverable.

    Every DatabaseManager here is given an explicit temporary path — never the
    default, which resolves to the real application database (P28).
    """

    COVERAGE = {"total": 3, "with_anchors": 1, "read_no_anchors": 0,
                "no_record": 1, "errored": 1, "skipped": 0, "unknown": 0,
                "collected_at": "2026-08-01T09:00:00+00:00"}

    def _db(self, name="ac.db"):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        return DatabaseManager(os.path.join(self._tmp.name, name))

    def test_coverage_round_trips(self):
        db = self._db()
        db.save_anchor_coverage(1, self.COVERAGE, detected_at="2026-08-28")
        got = db.get_anchor_coverage(1)
        self.assertEqual(got["total"], 3)
        self.assertEqual(got["errored"], 1)
        self.assertEqual(got["collected_at"], "2026-08-01T09:00:00+00:00")

    def test_unrecorded_run_returns_empty_not_a_clean_bill(self):
        """{} means "this run predates the table", not "everything was
        readable" — the caller must not render a clean claim from it."""
        self.assertEqual(self._db().get_anchor_coverage(999), {})

    def test_resaving_a_run_is_idempotent(self):
        db = self._db()
        db.save_anchor_coverage(1, self.COVERAGE, detected_at="2026-08-28")
        db.save_anchor_coverage(1, {**self.COVERAGE, "errored": 2},
                                detected_at="2026-08-28")
        self.assertEqual(db.get_anchor_coverage(1)["errored"], 2)

    def test_a_total_failure_is_recorded_distinguishably(self):
        """A run that attempted nothing and a run whose every fetch failed must
        stay apart after the fact, which is the whole point of storing it."""
        db = self._db()
        db.save_anchor_coverage(1, {"total": 0, "fetch_status": "unavailable",
                                    "reason": "handoff unreadable"},
                                detected_at="2026-08-28")
        db.save_anchor_coverage(2, {}, detected_at="2026-08-28")
        self.assertEqual(db.get_anchor_coverage(1)["fetch_status"], "unavailable")
        self.assertIsNone(db.get_anchor_coverage(2)["fetch_status"])

    def test_stored_coverage_drives_the_caveat(self):
        """The point of persisting it: an old run's report can still say what
        could not be read."""
        db = self._db()
        db.save_anchor_coverage(1, self.COVERAGE, detected_at="2026-08-28")
        lines = anchor_caveat_lines([], db.get_anchor_coverage(1))
        self.assertTrue(lines)
        self.assertIn("1 errored", lines[0])

class TestSweepFixes(unittest.TestCase):
    """Findings from the pre-push sweep of the coverage/staleness batch."""

    BLOCK = {
        "generated_at": "2026-08-28T12:00:00+00:00",
        "domains": {
            "cached.example": {"status": "ok", "fetched_at": "2026-08-01T09:00:00+00:00",
                               "anchor_texts": {"status": "ok", "items": REAL_ANCHORS}},
            "fresh.example": {"status": "ok", "fetched_at": "2026-08-28T12:00:00+00:00",
                              "anchor_texts": {"status": "ok", "items": REAL_ANCHORS}},
            "capped.example": {"status": "skipped_run_cap"},
        },
    }

    # F3 — per-domain freshness, not the assembly timestamp
    def test_per_domain_fetched_at_beats_the_assembly_timestamp(self):
        """`generated_at` is stamped when Tool 1 assembles the handoff. A domain
        served from its 30-day cache is far older, and using the assembly time
        reports 27-day-old anchors as a same-day observation (P6)."""
        extracted = anchor_texts_by_domain(self.BLOCK)
        self.assertEqual(extracted["cached.example"]["collected_at"],
                         "2026-08-01T09:00:00+00:00")
        self.assertEqual(extracted["fresh.example"]["collected_at"],
                         "2026-08-28T12:00:00+00:00")

    def test_assembly_timestamp_is_only_the_fallback(self):
        """A handoff from a Tool 1 that predates per-domain dates still gets
        something, clearly labelled as the upper bound it is."""
        block = {"generated_at": "2026-08-28T12:00:00+00:00", "domains": {
            "old.example": {"status": "ok",
                            "anchor_texts": {"status": "ok", "items": REAL_ANCHORS}}}}
        self.assertEqual(anchor_texts_by_domain(block)["old.example"]["collected_at"],
                         "2026-08-28T12:00:00+00:00")

    def test_per_domain_date_reaches_the_signal(self):
        rows = compute_risk_signals(
            volatility_alerts=[], series_by_domain={}, parasite_candidates=[],
            own_domain="x.com",
            anchor_texts_by_domain=anchor_texts_by_domain(self.BLOCK),
            anchor_collected_at="2026-08-28T12:00:00+00:00")
        by_domain = {r["domain"]: r["evidence"]["collected_at"] for r in rows}
        self.assertEqual(by_domain["cached.example"], "2026-08-01T09:00:00+00:00")

    # F2 — coverage must describe the set the signals describe
    def test_coverage_counts_only_the_domains_this_run_examined(self):
        """Tool 1 builds moz.domains from every organic competitor and caps the
        fetch, so counting the whole block made the report warn about domains
        this run never looked at (P3/P6)."""
        scoped = anchor_coverage(self.BLOCK, ["cached.example"], "")
        self.assertEqual(scoped["total"], 1)
        self.assertEqual(scoped["skipped"], 0)
        whole = anchor_coverage(self.BLOCK)
        self.assertEqual(whole["total"], 3)
        self.assertEqual(whole["skipped"], 1)

    def test_unscoped_coverage_still_counts_everything(self):
        """Passing no scope keeps the old behaviour, so a caller that has no
        target set is not silently given a zeroed count."""
        self.assertEqual(anchor_coverage(self.BLOCK)["total"], 3)

    # F8 — an unrecorded run must not read as a clean one
    def test_unrecorded_coverage_says_so(self):
        lines = anchor_caveat_lines([], {"unrecorded": True})
        self.assertEqual(len(lines), 1)
        self.assertIn("not recorded", lines[0])
        self.assertIn("not evidence", lines[0])
        self.assertEqual(anchor_data_unreadable({"unrecorded": True}), 1)

    def test_a_genuinely_clean_run_still_says_nothing(self):
        self.assertEqual(
            anchor_caveat_lines([], {"total": 2, "with_anchors": 2, "errored": 0,
                                     "skipped": 0, "unknown": 0}), [])


class TestSweepFixesPersistence(unittest.TestCase):
    """DB-side sweep fixes. Explicit temp paths only (P28)."""

    def _db(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        return DatabaseManager(os.path.join(self._tmp.name, "s.db"))

    # F6 — the total-failure caveat must keep its cause across the round trip
    def test_reason_survives_persistence(self):
        db = self._db()
        db.save_anchor_coverage(1, {"total": 0, "fetch_status": "unavailable",
                                    "reason": "handoff unreadable"},
                                detected_at="2026-08-28")
        got = db.get_anchor_coverage(1)
        self.assertEqual(got["reason"], "handoff unreadable")
        line = anchor_caveat_lines([], got)[0]
        self.assertIn("handoff unreadable", line)

    def test_collected_at_survives_persistence(self):
        db = self._db()
        db.save_anchor_coverage(1, {"total": 1, "collected_at": "2026-08-01T09:00:00+00:00"},
                                detected_at="2026-08-28")
        self.assertEqual(db.get_anchor_coverage(1)["collected_at"],
                         "2026-08-01T09:00:00+00:00")

    # F7 — a real DB error must not masquerade as "predates the table"
    def _raising_cursor(self, message):
        """A connection whose cursor.execute raises inside the guarded block.

        Patching _get_connection itself raises BEFORE the try, so the except
        branch is never entered and the test passes whatever the handler does.
        """
        cursor = MagicMock()
        cursor.execute.side_effect = sqlite3.OperationalError(message)
        conn = MagicMock()
        conn.cursor.return_value = cursor
        conn.__enter__ = lambda _self: conn
        conn.__exit__ = lambda *_: False
        return conn

    def test_a_real_database_error_is_not_swallowed(self):
        """The missing-table branch is unreachable — _create_tables() runs on
        every construction — so left broad this caught "database is locked" and
        reported it as an unrecorded run, silently (P1/P2)."""
        db = self._db()
        with patch.object(db, "_get_connection",
                          return_value=self._raising_cursor("database is locked")):
            with self.assertRaises(sqlite3.OperationalError):
                db.get_anchor_coverage(1)

    def test_a_genuinely_missing_table_still_degrades(self):
        """The one case the catch is for: a DB predating the table."""
        db = self._db()
        with patch.object(db, "_get_connection",
                          return_value=self._raising_cursor(
                              "no such table: anchor_coverage")):
            self.assertEqual(db.get_anchor_coverage(1), {})

class TestRunScopeIsTheIngestedSet(unittest.TestCase):
    """run_domains, not competitor_keywords, must scope the anchor signals.

    competitor_keywords is what survived the later relevant-pages and PA
    filters, and the relevant-pages check is a DataForSEO call. A 429 there
    would silently drop a competitor's anchor signal and print a scope claim
    that is false (P1/P2).
    """

    def test_run_domains_scopes_the_anchors_not_competitor_keywords(self):
        import src.comparison_features as cf
        captured = {}

        def fake_restrict(anchors, scope, client):
            captured["scope"] = list(scope or [])
            return {}

        import src.handoff_moz as hm
        with patch.object(hm, "restrict_to_run", fake_restrict), \
                tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(os.path.join(tmp, "rs.db"))
            run_id = db.create_run("livingsystems.ca")
            cf.run_comparison_features(
                db, run_id, {"client": {"domain": "livingsystems.ca"}},
                "livingsystems.ca",
                {"survived.example": set()},          # competitor_keywords
                MagicMock(), MagicMock(), tmp,
                anchor_texts_by_domain={"dropped.example": {"items": []}},
                anchor_coverage={},
                run_domains=["survived.example", "dropped.example"])

        self.assertIn("scope", captured, "restrict_to_run was never reached")
        self.assertIn("dropped.example", captured["scope"],
                      "a domain the run ingested was excluded because a later "
                      "filter dropped it")

class TestCodeReviewFixes(unittest.TestCase):
    """Findings from the orthogonal /code-review pass over the same range."""

    BLOCK = {"domains": {
        "a.com": {"status": "ok", "anchor_texts": {
            "status": "ok", "items": [{"text": "x", "external_root_domains": 1}]}},
        "b.com": {"status": "error", "anchor_texts": {"status": "error", "items": []}},
    }}

    def test_a_client_domain_alone_does_not_zero_the_counts(self):
        """Scoping triggered on client_domain alone filtered every competitor
        out and returned all zeros, so a run where a fetch errored rendered as
        clean — the caveat saw 0 unreadable (P2)."""
        counts = anchor_coverage(self.BLOCK, None, "livingsystems.ca")
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["errored"], 1)
        self.assertEqual(anchor_data_unreadable(counts), 1)
        self.assertTrue(anchor_caveat_lines([], counts))

    def test_an_explicit_domain_list_still_scopes(self):
        counts = anchor_coverage(self.BLOCK, ["a.com"], "livingsystems.ca")
        self.assertEqual(counts["total"], 1)

    def test_a_domain_in_both_client_and_domains_is_counted_once(self):
        """One site, not two. Counting it twice inflated the denominator the
        coverage caveat reports."""
        block = {"domains": {"me.com": {"status": "error", "anchor_texts": {
                     "status": "error", "items": []}}},
                 "client": {"domain": "me.com", "anchor_texts": {
                     "status": "ok", "items": [{"text": "y",
                                                "external_root_domains": 2}]}}}
        self.assertEqual(anchor_coverage(block, ["me.com"], "me.com")["total"], 1)

    def test_the_client_entry_wins_for_its_own_domain(self):
        """Same domain means one site, and the client entry is the
        authoritative source for the client's own anchors — it must not be
        dropped in favour of an empty competitor block."""
        block = {"domains": {"me.com": {"status": "error", "anchor_texts": {
                     "status": "error", "items": []}}},
                 "client": {"domain": "me.com", "anchor_texts": {
                     "status": "ok", "items": [{"text": "y",
                                                "external_root_domains": 2}]}}}
        extracted = anchor_texts_by_domain(block)
        self.assertEqual(extracted["me.com"]["items"][0]["text"], "y")

    def test_run_scope_is_the_union_not_a_fallback(self):
        """A parameter whose default is the broken behaviour only works while
        every caller remembers to pass it. The scope is now the union of both
        sets, so omitting run_domains cannot silently narrow it."""
        import src.comparison_features as cf
        import inspect
        src = inspect.getsource(cf.run_comparison_features)
        self.assertIn("set(domains or []) | set(run_domains or [])", src)
        from src.handoff_moz import restrict_to_run
        anchors = {"filtered-out.example": {"items": []},
                   "survived.example": {"items": []}}
        scope = set(["survived.example"]) | set(
            ["survived.example", "filtered-out.example"])
        self.assertEqual(set(restrict_to_run(anchors, scope, "")), set(anchors))
