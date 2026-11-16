"""A rendered table must not print `nan`.

Purpose: an unmeasured value says so; it does not leak a float artefact.
Spec:    docs/FEATURE_GUIDE.md §9 ("a missing number is NULL, not zero")
Found:   by rendering a briefing through the test fakes and reading it
         (2026-11-16), which is as close to the review protocol's "regenerate
         the report and diff it" step as a cloud session can get — it has no
         `.env`, no history database and no reference handoff.

What was in that rendered briefing:

- the Competitor Ranking Summary printed `pages_audited` as `nan` for the two
  domains whose pages errored or were blocked by the 429 circuit breaker;
- the Barbell table printed `focus_score` as `nan` for the three domains whose
  focus was deliberately WITHHELD for too small a sample.

The withholding was right, and the `quadrant` column said `insufficient_data`
next to it — but a reader sees `nan` and reads a broken calculation, which is
exactly backwards for a report whose convention is that absence is stated. The
chunk-C2 work made the data layer honest about NULL; this makes the rendering
layer honest about it too.
"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.reporting import UNKNOWN_CELL, md_table


class TestMissingValuesAreStatedNotPrintedAsNan(unittest.TestCase):

    def test_a_nan_renders_as_the_unknown_marker(self):
        df = pd.DataFrame([{"domain": "blocked.ca", "pages_audited": np.nan}])
        rendered = md_table(df, index=False)
        self.assertNotIn("nan", rendered)
        self.assertIn(UNKNOWN_CELL, rendered)

    def test_a_none_renders_as_the_unknown_marker(self):
        df = pd.DataFrame([{"domain": "x.ca", "focus_score": None}])
        rendered = md_table(df, index=False)
        self.assertNotIn("None", rendered)
        self.assertIn(UNKNOWN_CELL, rendered)

    def test_real_values_are_untouched(self):
        df = pd.DataFrame([{"domain": "x.ca", "authority_score": 35,
                            "focus_score": 100.0}])
        rendered = md_table(df, index=False)
        self.assertIn("35", rendered)
        self.assertIn("100", rendered)

    def test_a_zero_is_not_treated_as_missing(self):
        """The distinction the whole chunk-C2 effort was about: 0 is a measured
        value and must not render as unknown."""
        df = pd.DataFrame([{"domain": "x.ca", "t2_count": 0, "t3_count": np.nan}])
        rendered = md_table(df, index=False)
        self.assertRegex(rendered, r"\|\s*0\s*\|")
        self.assertIn(UNKNOWN_CELL, rendered)

    def test_a_mixed_column_renders_both(self):
        df = pd.DataFrame([{"domain": "a.ca", "pages_audited": 2},
                           {"domain": "b.ca", "pages_audited": np.nan}])
        rendered = md_table(df, index=False)
        self.assertNotIn("nan", rendered)
        self.assertIn("2", rendered)
        self.assertIn(UNKNOWN_CELL, rendered)

    def test_an_empty_frame_does_not_raise(self):
        self.assertIsInstance(md_table(pd.DataFrame(), index=False), str)

    def test_none_instead_of_a_frame_does_not_raise(self):
        self.assertEqual(md_table(None), "")

    def test_every_report_table_goes_through_this_helper(self):
        """A single table rendered the raw way reintroduces the defect, and it
        would only surface in a briefing nobody reads until after it is sent."""
        import inspect
        import re

        from src import reporting

        source = inspect.getsource(reporting)
        # Strip this helper's own body and docstrings mentioning to_markdown.
        helper = inspect.getsource(reporting.md_table)
        source = source.replace(helper, "")
        offenders = re.findall(r"^.*\.to_markdown\(.*$", source, flags=re.M)
        self.assertEqual(offenders, [], (
            "These render a table without md_table, so a missing value would "
            f"print as `nan`: {offenders}"))


class TestTheExcelPathKeepsRealNulls(unittest.TestCase):
    """Display-only. The workbook must keep NaN so its columns stay numeric."""

    def test_md_table_does_not_mutate_the_caller_s_frame(self):
        df = pd.DataFrame([{"domain": "x.ca", "focus_score": np.nan}])
        md_table(df, index=False)
        self.assertTrue(pd.isna(df.loc[0, "focus_score"]),
                        "md_table filled the caller's frame in place, so the "
                        "Excel sheet would carry the em dash as data")


if __name__ == "__main__":
    unittest.main()


class TestWholeNumbersStayWholeNumbers(unittest.TestCase):
    """A count column with one NULL in it becomes float64.

    The first version of this helper filled the NULLs and left the rest as
    floats, so `pages_audited` rendered as "1.0" and "2.0" — a cosmetic
    regression introduced while fixing a cosmetic defect.
    """

    def test_an_integral_column_with_a_null_prints_integers(self):
        df = pd.DataFrame([{"domain": "a.ca", "pages_audited": 2},
                           {"domain": "b.ca", "pages_audited": None}])
        rendered = md_table(df, index=False)
        self.assertIn("| 2 ", rendered)
        self.assertNotIn("2.0", rendered)
        self.assertIn(UNKNOWN_CELL, rendered)

    def test_a_genuinely_fractional_column_keeps_its_decimals(self):
        df = pd.DataFrame([{"domain": "a.ca", "medical_per_1000": 12.4},
                           {"domain": "b.ca", "medical_per_1000": None}])
        rendered = md_table(df, index=False)
        self.assertIn("12.4", rendered)

    def test_a_column_of_all_nulls_does_not_raise(self):
        df = pd.DataFrame([{"domain": "a.ca", "words": None},
                           {"domain": "b.ca", "words": None}])
        rendered = md_table(df, index=False)
        self.assertNotIn("nan", rendered)
        self.assertIn(UNKNOWN_CELL, rendered)

    def test_a_negative_whole_number_is_preserved(self):
        """Drift columns are signed, and int() truncates toward zero."""
        df = pd.DataFrame([{"domain": "a.ca", "drift": -3.0},
                           {"domain": "b.ca", "drift": None}])
        rendered = md_table(df, index=False)
        self.assertIn("-3", rendered)
        self.assertNotIn("-3.0", rendered)
