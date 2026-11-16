"""The clinical vocabulary has two sources, and they must not drift.

`scoring_logic.load_dictionary` prefers `shared_config.json → clinical` and
falls back to `clinical_dictionary.json`. Both files are in the repo and both
carry all three tiers, so the Tier-1 vocabulary a run scores with depends on
which one loaded — and nothing checked that they say the same thing.

This matters because of owner decision 3 (2026-11-15): five words were removed
from Tier 1, and `technical.vacuum_min_medical` was then **re-set from 10 to 6
to match the shorter vocabulary**. If the two sources drift, a run that falls
back to `clinical_dictionary.json` scores with one vocabulary against a floor
calibrated for the other, and the magnet, vacuum and reframe lists change with
no visible cause. Chunk C4's own notes record that the decision "had to be
applied to both files" — by hand, because nothing enforced it.

Coverage on 2026-11-16 had the fallback branch (`scoring_logic.py:29-41`)
untested.
"""
from __future__ import annotations

import json
import os
import unittest
import unittest.mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

#: config key → dictionary key. They are NOT the same name for tier 3, which is
#: itself a small trap: `clinical.tier_3_bowen` in both files becomes
#: `tier_3_bowen_expert` in the loaded dict.
TIER_KEYS = (("tier_1_medical", "tier_1_medical"),
             ("tier_2_systems", "tier_2_systems"),
             ("tier_3_bowen", "tier_3_bowen"))


def _config():
    with open(os.path.join(ROOT, "shared_config.json"), encoding="utf-8") as f:
        return json.load(f)


def _dictionary():
    with open(os.path.join(ROOT, "clinical_dictionary.json"), encoding="utf-8") as f:
        return json.load(f)


class TestTheTwoSourcesAgree(unittest.TestCase):

    def test_every_tier_is_identical_in_both_files(self):
        config_clinical = _config()["clinical"]
        dictionary = _dictionary()
        for config_key, dictionary_key in TIER_KEYS:
            configured = set(config_clinical.get(config_key, []))
            fallback = set(dictionary.get(dictionary_key, []))
            self.assertEqual(
                configured, fallback,
                f"`clinical.{config_key}` differs between shared_config.json and "
                f"clinical_dictionary.json. A run that falls back to the "
                f"dictionary would score with a different vocabulary than the "
                f"one `technical.vacuum_min_medical` was set for (owner "
                f"decision 3). Only in config: "
                f"{sorted(configured - fallback)}; only in the dictionary: "
                f"{sorted(fallback - configured)}")

    def test_the_removed_words_are_absent_from_both(self):
        """Decision 3 removed these five from Tier 1. A word creeping back into
        either file raises every page's medical_score against a floor that was
        lowered to 6 because they were gone."""
        removed = {"therapy", "patient", "patients", "condition", "trauma"}
        config_tier_1 = set(_config()["clinical"]["tier_1_medical"])
        dictionary_tier_1 = set(_dictionary()["tier_1_medical"])
        self.assertEqual(removed & config_tier_1, set())
        self.assertEqual(removed & dictionary_tier_1, set())

    def test_the_dictionary_records_why_they_were_removed(self):
        """Decision 3 asked for the removal to be visible in the file itself,
        so the words do not drift back in."""
        dictionary = _dictionary()
        self.assertIn("neutral_clinical", dictionary)
        neutral = {str(word).lower() for word in dictionary["neutral_clinical"]}
        for word in ("therapy", "patient", "condition", "trauma"):
            self.assertIn(word, neutral)


class TestTheLoaderPrefersConfigAndFallsBack(unittest.TestCase):
    """`scoring_logic.py:29-41` — the fallback branch, untested until now."""

    def test_config_wins_when_present(self):
        from src import scoring_logic

        with unittest.mock.patch.object(
                scoring_logic, "SHARED_CONFIG",
                {"clinical": {"tier_1_medical": ["symptom"],
                              "tier_2_systems": ["differentiation"],
                              "tier_3_bowen": ["emotional cutoff"]}}):
            loaded = scoring_logic.load_dictionary()
        self.assertEqual(loaded["tier_1_medical"], ["symptom"])
        self.assertEqual(loaded["tier_3_bowen_expert"], ["emotional cutoff"])

    def test_the_dictionary_file_is_used_when_config_has_no_clinical_block(self):
        from src import scoring_logic

        with unittest.mock.patch.object(scoring_logic, "SHARED_CONFIG", {}):
            loaded = scoring_logic.load_dictionary()
        # Not empty: that is the whole point of the fallback.
        self.assertTrue(loaded["tier_1_medical"])
        self.assertEqual(set(loaded["tier_1_medical"]),
                         set(_dictionary()["tier_1_medical"]))

    def test_tier_3_is_renamed_on_the_way_out(self):
        """Both files say `tier_3_bowen`; the loaded dict says
        `tier_3_bowen_expert`. A reader of either file would not guess."""
        from src import scoring_logic

        with unittest.mock.patch.object(scoring_logic, "SHARED_CONFIG", {}):
            loaded = scoring_logic.load_dictionary()
        self.assertIn("tier_3_bowen_expert", loaded)
        self.assertNotIn("tier_3_bowen", loaded)

    def test_a_missing_dictionary_file_yields_empty_tiers_not_a_crash(self):
        from src import scoring_logic

        with unittest.mock.patch.object(scoring_logic, "SHARED_CONFIG", {}), \
             unittest.mock.patch.object(scoring_logic, "DICTIONARY_PATH",
                                        "/nonexistent/clinical.json"):
            loaded = scoring_logic.load_dictionary()
        self.assertEqual(loaded, {"tier_1_medical": [], "tier_2_systems": [],
                                  "tier_3_bowen_expert": []})

    def test_an_unreadable_config_does_not_stop_the_import(self):
        """`load_shared_config` swallows everything and returns {} — which is
        correct here, but it means a corrupt config scores every page with an
        EMPTY vocabulary rather than failing. Asserted so that the behaviour is
        a decision rather than an accident."""
        from src import scoring_logic

        with unittest.mock.patch("builtins.open",
                                 side_effect=OSError("disk gone")):
            self.assertEqual(scoring_logic.load_shared_config(), {})


if __name__ == "__main__":
    unittest.main()
