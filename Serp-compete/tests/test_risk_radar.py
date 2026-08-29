"""Tests for C6 / SC-8 — Reputation-Risk Radar (src/risk_radar.py).

Covers SC-8.1 (a synthetic ~60% visibility drop → visibility_cliff high with the drop %
in evidence), SC-8.2 (parasite needs topical mismatch AND commercial intent, not the
subfolder name alone), SC-8.3 (own-site signals separated from competitor signals),
SC-8.4 (paid-link/PBN footprints in inbound anchor text, and ingesting the Moz block
Tool 1 attaches to the competitor handoff), plus the DB reader/writer.
"""
import json
import os
import tempfile
import unittest

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

        NOTE: this exercises the radar, not a live path. Tool 1 excludes the
        client's own domain from the handoff's moz.domains, so client anchors
        never arrive today. Recorded in TODO.md; the tagging is asserted here
        so the radar is correct if that ever changes.
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

    def test_coverage_reaches_the_report_call(self):
        """The coverage note is worthless if it stops at the console (P25)."""
        self.assertIn("anchor_coverage",
                      self._method_call_kwargs("generate_summary"))

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
