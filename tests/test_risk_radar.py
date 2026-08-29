"""
tests/test_risk_radar.py
~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the reputation-risk radar, and for ingesting the Moz block Tool 1
now attaches to the competitor handoff.

Spec: compete-spec.md#C6 (SC-8); producer side is
      serp-discover moz_api_upgrade_spec_v1.md#T.4

The module had no test file before the anchor-text detector was added. These
cover the new detector, its wiring into compute_risk_signals, and the handoff
ingestion — plus the two pre-existing detectors at the points the new code
touches them.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "Serp-compete")))

from src.handoff_moz import anchor_texts_by_domain, load_moz_block  # noqa: E402
from src.risk_radar import compute_risk_signals, detect_anchor_spam  # noqa: E402

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
        narrow = [{"text": "buy backlinks", "external_root_domains": 1},
                  {"text": "brand name", "external_root_domains": 999}]
        self.assertEqual(detect_anchor_spam(wide)["severity"], "high")
        self.assertEqual(detect_anchor_spam(narrow)["severity"], "medium")

    def test_evidence_says_links_received_not_links_bought(self):
        """Anchors are written by other sites: a domain can be the target of a
        scheme it had no part in, and the wording must keep that reading open."""
        evidence = detect_anchor_spam(REAL_ANCHORS)["evidence"]
        interpretation = evidence["interpretation"].lower()
        self.assertIn("received", interpretation)
        self.assertIn("not", interpretation)
        self.assertNotIn("penalty confirmed", interpretation)

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
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, "shared_config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        terms = cfg["risk_signals"]["anchor_spam_terms"]
        self.assertTrue(terms)
        self.assertIn("pbn", terms)


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
        """SC-8.3 — own-site warnings stay separable from competitor intel,
        and negative SEO against the client is exactly what this catches."""
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
        self.assertEqual(len(extracted["bowencenter.org"]), len(REAL_ANCHORS))

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


if __name__ == "__main__":
    unittest.main()
