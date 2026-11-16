"""`src/strike_mapper.py` — the GSC strike list → pillar draft heading mapper.

`docs/IMPLEMENTATION_PLAN_v3.md` listed this module as "✅ Approved" with
`test_strike_mapper.py (existing)`, and `SPEC_COVERAGE_REPORT_v3.md` marked its
two rows "✅ Done". **The file did not exist**, and a coverage run on
2026-11-16 put the module at 0%. This is it, written after the module was found
to be doing three things wrong:

1. It manufactured keywords out of no data. `gsc_strike_list.md` in this repo
   holds one row — `| No data | - | - | - | - | - |` — and the parser silently
   returned five hard-coded keywords instead. `inject_headers` then wrote them
   into `pillar_north_shore_draft.md`, where those five headings still are.
   Nothing recorded that they came from an editorial list rather than Search
   Console.
2. It was not idempotent: every run re-injected every heading, into a file the
   owner edits by hand.
3. Its reframe vocabulary was a dict in Python source, against this repo's own
   rule that editorial content lives in config.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from src import strike_mapper


def _strike_list(rows):
    """A strike list file in the real format, with *rows* as its query cells."""
    header = (
        "# GSC Intelligence: The Reality Check (Strike List)\n"
        "Generated on: 2026-11-16\n\n"
        "## 🎯 Striking Distance Opportunities (Positions 11-25)\n\n"
        "| Query | Current Position | Impressions | Associated URL | "
        "Clinical Pivot | Systemic Title recommendation |\n"
        "| :--- | :--- | :--- | :--- | :--- | :--- |\n")
    body = "".join(f"| {row} | 12 | 400 | /x | pivot | title |\n" for row in rows)
    return header + body


class TestNoDataIsNotAKeyword(unittest.TestCase):
    """The finding: absence was replaced with five invented queries."""

    def test_a_no_data_row_yields_no_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strike.md")
            with open(path, "w") as f:
                f.write(_strike_list(["No data"]))
            queries, source = strike_mapper.get_top_gsc_keywords(path)
        self.assertEqual(queries, [])
        self.assertEqual(source, "none")

    def test_the_other_placeholder_forms_are_absence_too(self):
        """The old test was `parts[1] != "No data"` — exact, case-sensitive,
        and blind to the dash and empty-cell forms."""
        for placeholder in ("no data", "NO DATA", "-", "", "n/a", "None"):
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "strike.md")
                with open(path, "w") as f:
                    f.write(_strike_list([placeholder]))
                queries, source = strike_mapper.get_top_gsc_keywords(path)
            self.assertEqual(queries, [], f"{placeholder!r} was read as a query")
            self.assertEqual(source, "none")

    def test_a_missing_file_yields_no_keywords(self):
        queries, source = strike_mapper.get_top_gsc_keywords(
            "/nonexistent/strike.md")
        self.assertEqual((queries, source), ([], "none"))

    def test_real_rows_are_read_and_labelled_gsc(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strike.md")
            with open(path, "w") as f:
                f.write(_strike_list(["anxiety counselling north vancouver",
                                      "couples counselling north vancouver"]))
            queries, source = strike_mapper.get_top_gsc_keywords(path)
        self.assertEqual(queries, ["anxiety counselling north vancouver",
                                   "couples counselling north vancouver"])
        self.assertEqual(source, "gsc")

    def test_a_no_data_row_beside_real_rows_is_dropped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strike.md")
            with open(path, "w") as f:
                f.write(_strike_list(["No data", "family systems therapy bc"]))
            queries, source = strike_mapper.get_top_gsc_keywords(path)
        self.assertEqual(queries, ["family systems therapy bc"])
        self.assertEqual(source, "gsc")

    def test_the_limit_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strike.md")
            with open(path, "w") as f:
                f.write(_strike_list([f"query {n}" for n in range(12)]))
            queries, _ = strike_mapper.get_top_gsc_keywords(path, limit=3)
        self.assertEqual(len(queries), 3)


class TestInjectionIsIdempotent(unittest.TestCase):
    """Running it twice must not duplicate the headings."""

    DRAFT = ("# Pillar draft\n\n"
             "## [H2] The Anxiety Loop\n\nbody\n\n"
             f"{strike_mapper.INJECTION_POINT}\n\nlocal body\n")

    def test_the_first_run_adds_the_headings(self):
        headings = strike_mapper.headings_for(["couples counselling north vancouver"])
        updated, why = strike_mapper.plan_injection(self.DRAFT, headings)
        self.assertIsNotNone(updated)
        self.assertIn("would add 1", why)
        self.assertIn("Observing the Reciprocal Pursuit-Distance Cycle", updated)
        # The injection point survives, with the headings before it.
        self.assertIn(strike_mapper.INJECTION_POINT, updated)
        self.assertLess(updated.index("Reciprocal Pursuit-Distance"),
                        updated.index(strike_mapper.INJECTION_POINT))

    def test_the_second_run_adds_nothing(self):
        headings = strike_mapper.headings_for(["couples counselling north vancouver"])
        once, _ = strike_mapper.plan_injection(self.DRAFT, headings)
        twice, why = strike_mapper.plan_injection(once, headings)
        self.assertIsNone(twice)
        self.assertIn("already in the draft", why)

    def test_a_heading_the_owner_wrote_by_hand_counts_as_present(self):
        """The draft is hand-edited. A heading already there — without this
        tool's marker — must not be added a second time."""
        draft = self.DRAFT.replace(
            strike_mapper.INJECTION_POINT,
            "## Couples Counselling North Vancouver: Observing the Reciprocal "
            "Pursuit-Distance Cycle\n\n" + strike_mapper.INJECTION_POINT)
        headings = strike_mapper.headings_for(["couples counselling north vancouver"])
        updated, why = strike_mapper.plan_injection(draft, headings)
        self.assertIsNone(updated, why)

    def test_only_the_missing_headings_are_added(self):
        headings = strike_mapper.headings_for(
            ["couples counselling north vancouver", "family systems therapy bc"])
        partial, _ = strike_mapper.plan_injection(self.DRAFT, headings[:1])
        updated, why = strike_mapper.plan_injection(partial, headings)
        self.assertIn("would add 1 of 2", why)
        self.assertEqual(updated.count("Reciprocal Pursuit-Distance"), 1)

    def test_a_draft_without_the_injection_point_is_refused(self):
        updated, why = strike_mapper.plan_injection(
            "# Draft\n\nno anchor here\n",
            strike_mapper.headings_for(["counselling north vancouver"]))
        self.assertIsNone(updated)
        self.assertIn("injection point", why)

    def test_the_headings_carry_their_provenance(self):
        headings = strike_mapper.headings_for(["counselling north vancouver"])
        self.assertIn(strike_mapper.PROVENANCE_MARKER, headings[0])


class TestTheVocabularyLivesInConfig(unittest.TestCase):
    """CLAUDE.md: editorial content belongs in config, not Python source."""

    def test_the_config_block_exists_and_is_what_the_module_reads(self):
        import json

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with open(os.path.join(root, "shared_config.json")) as f:
            configured = json.load(f)["strike_mapper"]["reframes"]
        self.assertEqual(strike_mapper.reframes(),
                         {k.lower(): v for k, v in configured.items()})

    def test_the_python_fallback_matches_the_config(self):
        """A fallback that drifts makes the same query map to two different
        reframes depending on whether config loaded (P4)."""
        import json

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with open(os.path.join(root, "shared_config.json")) as f:
            configured = json.load(f)["strike_mapper"]["reframes"]
        self.assertEqual({k.lower(): v for k, v in configured.items()},
                         {k.lower(): v for k, v in
                          strike_mapper.DEFAULT_REFRAMES.items()})

    def test_an_unmapped_query_gets_the_generic_reframe(self):
        heading = strike_mapper.headings_for(["something nobody mapped"])[0]
        self.assertIn(strike_mapper.GENERIC_REFRAME, heading)

    def test_the_vocabulary_lookup_is_case_insensitive(self):
        heading = strike_mapper.headings_for(
            ["Couples Counselling North Vancouver"])[0]
        self.assertIn("Observing the Reciprocal Pursuit-Distance Cycle", heading)


class TestItWritesNothingByAccident(unittest.TestCase):
    """It edits a content file the owner maintains by hand."""

    def _draft(self, tmp):
        path = os.path.join(tmp, "pillar.md")
        with open(path, "w") as f:
            f.write(TestInjectionIsIdempotent.DRAFT)
        return path

    def test_no_gsc_data_writes_nothing_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            strike = os.path.join(tmp, "strike.md")
            with open(strike, "w") as f:
                f.write(_strike_list(["No data"]))
            draft = self._draft(tmp)
            before = open(draft).read()
            code = strike_mapper.inject_headers(write=True, strike_list=strike,
                                                draft_path=draft)
            self.assertEqual(code, 1)
            self.assertEqual(open(draft).read(), before)

    def test_the_fallback_must_be_asked_for_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            strike = os.path.join(tmp, "strike.md")
            with open(strike, "w") as f:
                f.write(_strike_list(["No data"]))
            draft = self._draft(tmp)
            code = strike_mapper.inject_headers(
                write=True, allow_fallback=True, strike_list=strike,
                draft_path=draft)
            self.assertEqual(code, 0)
            self.assertIn(strike_mapper.PROVENANCE_MARKER, open(draft).read())

    def test_a_dry_run_leaves_the_draft_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            strike = os.path.join(tmp, "strike.md")
            with open(strike, "w") as f:
                f.write(_strike_list(["couples counselling north vancouver"]))
            draft = self._draft(tmp)
            before = open(draft).read()
            code = strike_mapper.inject_headers(strike_list=strike,
                                                draft_path=draft)
            self.assertEqual(code, 0)
            self.assertEqual(open(draft).read(), before)

    def test_a_missing_draft_is_reported_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            strike = os.path.join(tmp, "strike.md")
            with open(strike, "w") as f:
                f.write(_strike_list(["couples counselling north vancouver"]))
            missing = os.path.join(tmp, "not-there.md")
            code = strike_mapper.inject_headers(write=True, strike_list=strike,
                                                draft_path=missing)
            self.assertEqual(code, 1)
            self.assertFalse(os.path.exists(missing))

    def test_writing_twice_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            strike = os.path.join(tmp, "strike.md")
            with open(strike, "w") as f:
                f.write(_strike_list(["couples counselling north vancouver"]))
            draft = self._draft(tmp)
            strike_mapper.inject_headers(write=True, strike_list=strike,
                                         draft_path=draft)
            once = open(draft).read()
            strike_mapper.inject_headers(write=True, strike_list=strike,
                                         draft_path=draft)
            self.assertEqual(open(draft).read(), once)
            self.assertEqual(once.count("Reciprocal Pursuit-Distance"), 1)


if __name__ == "__main__":
    unittest.main()
