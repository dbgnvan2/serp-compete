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

import pandas as pd

from src.briefing_messages import Messages
from src.reporting import md_table, unknown_cell


class TestMissingValuesAreStatedNotPrintedAsNan(unittest.TestCase):

    def test_a_nan_renders_as_the_unknown_marker(self):
        df = pd.DataFrame([{"domain": "blocked.ca", "pages_audited": float("nan")}])
        rendered = md_table(df, index=False)
        self.assertNotIn("nan", rendered)
        self.assertIn(unknown_cell(), rendered)

    def test_a_none_renders_as_the_unknown_marker(self):
        df = pd.DataFrame([{"domain": "x.ca", "focus_score": None}])
        rendered = md_table(df, index=False)
        self.assertNotIn("None", rendered)
        self.assertIn(unknown_cell(), rendered)

    def test_real_values_are_untouched(self):
        df = pd.DataFrame([{"domain": "x.ca", "authority_score": 35,
                            "focus_score": 100.0}])
        rendered = md_table(df, index=False)
        self.assertIn("35", rendered)
        self.assertIn("100", rendered)

    def test_a_zero_is_not_treated_as_missing(self):
        """The distinction the whole chunk-C2 effort was about: 0 is a measured
        value and must not render as unknown."""
        df = pd.DataFrame([{"domain": "x.ca", "t2_count": 0, "t3_count": float("nan")}])
        rendered = md_table(df, index=False)
        self.assertRegex(rendered, r"\|\s*0\s*\|")
        self.assertIn(unknown_cell(), rendered)

    def test_a_mixed_column_renders_both(self):
        df = pd.DataFrame([{"domain": "a.ca", "pages_audited": 2},
                           {"domain": "b.ca", "pages_audited": float("nan")}])
        rendered = md_table(df, index=False)
        self.assertNotIn("nan", rendered)
        self.assertIn("2", rendered)
        self.assertIn(unknown_cell(), rendered)

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
        df = pd.DataFrame([{"domain": "x.ca", "focus_score": float("nan")}])
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
        self.assertIn(unknown_cell(), rendered)

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
        self.assertIn(unknown_cell(), rendered)

    def test_a_negative_whole_number_is_preserved(self):
        """Drift columns are signed, and int() truncates toward zero."""
        df = pd.DataFrame([{"domain": "a.ca", "drift": -3.0},
                           {"domain": "b.ca", "drift": None}])
        rendered = md_table(df, index=False)
        self.assertIn("-3", rendered)
        self.assertNotIn("-3.0", rendered)


class TestNothingScoredStillSaysSo(unittest.TestCase):
    """The third case the magnet section never handled.

    `reporting` had two branches: magnets found, and "none of the N audited
    page(s) met the magnet definition". The second branch's own comment says
    the reader "cannot otherwise tell it from 'nothing was audited'" — and when
    nothing WAS audited, both branches were skipped and the whole section
    vanished. A reader seeing no Traffic Magnets heading cannot tell "no
    competitor page qualified" from "no competitor page could be read", and
    this is the report's primary action list.

    Found by rendering the `total-outage` scenario — every provider down, every
    scrape blocked — and reading it.
    """

    @staticmethod
    def _briefing(scenario):
        import os
        import sys
        import tempfile

        tool_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", "tools"))
        if tool_dir not in sys.path:
            sys.path.insert(0, tool_dir)
        import render_sample_briefing

        start = os.getcwd()
        with tempfile.TemporaryDirectory() as out:
            try:
                written = render_sample_briefing.render(scenario, out)
            finally:
                os.chdir(start)
            with open(written[-1], encoding="utf-8") as f:
                return f.read()

    def test_a_total_outage_still_renders_the_magnet_section(self):
        content = self._briefing("total-outage")
        self.assertIn("Identified 'Traffic Magnets'", content)
        self.assertIn("No page could be scored this run", content)
        # …and it must not be readable as a finding about the competitors.
        self.assertIn("not a finding that competitors have no Traffic Magnets",
                      content)

    def test_a_total_outage_does_not_point_at_a_section_that_is_absent(self):
        """The SERP Overlap note said it "folds in the Systemic Vacuum list
        above" unconditionally, and in this run there is no such list."""
        content = self._briefing("total-outage")
        self.assertNotIn("Systemic Vacuum list above", content)
        # The rest of that sentence must survive.
        self.assertIn("Competitor positions are SERP-measured", content)

    def test_the_cross_reference_is_kept_when_the_list_is_there(self):
        content = self._briefing("minimal")
        self.assertIn("Systemic Vacuums", content)
        self.assertIn("Folds in the Systemic Vacuum list above", content)

    def test_a_total_outage_names_what_could_not_be_measured(self):
        """The whole point of chunk C2: an outage cannot read as a clean run."""
        content = self._briefing("total-outage")
        self.assertIn("Page Authority measured for 0 of", content)
        self.assertIn("Page Authority was unmeasured", content)
        self.assertIn("Blocked by the 429 circuit breaker", content)
        self.assertNotRegex(content, r"\|\s*nan\s*\|")


class TestTheEeatDashesAreDashesNotNan(unittest.TestCase):
    """The mixed case is the realistic one, and it was the broken one.

    The section rendered each dimension with
    `f"{x:.1f}" if x is not None else "—"`. pandas reads a SQL NULL as NaN in a
    numeric column, and `NaN is not None` is True — so a page whose dimension
    could not be computed printed "nan" beside the pages that could. It only
    looked right when EVERY value was NULL, because the column is then dtype
    object and the values really are None.

    Found by rendering the section for the first time: the test fixture
    MagicMocks `EEATScorer`, so this table had never appeared in any rendered
    briefing.
    """

    def test_a_mixed_column_renders_the_unknown_marker(self):
        series = pd.Series([0.55, float("nan")])
        rendered = series.apply(lambda x: f"{x:.1f}" if pd.notna(x) else unknown_cell())
        self.assertEqual(list(rendered), ["0.6", unknown_cell()])

    def test_the_old_logic_is_what_produced_nan(self):
        """Kept as the evidence: `is not None` passes NaN straight through."""
        series = pd.Series([0.55, float("nan")])
        old = series.apply(lambda x: f"{x:.1f}" if x is not None else unknown_cell())
        self.assertEqual(list(old), ["0.6", "nan"])

    def test_the_deep_render_shows_real_eeat_scores(self):
        """The whole section, end to end, with the REAL EEATScorer.

        Also guards the fixture: the test CONFIG has no `eeat_weights`, so
        before the renderer started from the repo's own config this table was
        four columns of dashes — a property of the fixture, which is exactly
        what makes a rendered sample misleading.
        """
        content = TestNothingScoredStillSaysSo._briefing("deep")
        self.assertIn("EEAT Competitive Analysis", content)
        self.assertNotRegex(content, r"\|\s*nan\s*\|")
        # A real composite, to one decimal place.
        self.assertRegex(content, r"\|\s*0\.\d\s*\|")
        # …and no "could not be computed" banner, because they were.
        self.assertNotIn("No EEAT composite could be computed", content)

    def test_the_deep_render_shows_the_sections_the_fixture_mocks_away(self):
        """EEAT, Extractability and Cluster are MagicMocked in the default
        fixture, so none of them had ever been rendered."""
        content = TestNothingScoredStillSaysSo._briefing("deep")
        for heading in ("EEAT Competitive Analysis",
                        "Extractability signals",
                        "Internal Linking Cluster Analysis"):
            self.assertIn(heading, content, f"{heading} did not render")


class TestTheExcelWorkbookIsNotTheMarkdown(unittest.TestCase):
    """USER_MANUAL: "**The Excel sheets always carry every row**".

    Nothing had ever opened the workbook. Checking it found that the EEAT
    display formatting ran **in place on the frame the Excel writer gets**, so
    four float64 columns were exported as TEXT — "0.6" and "—" — and the
    workbook's scores could not be sorted, charted or averaged, with an em dash
    sitting in a numeric column. The markdown wants strings; the sheet wants
    numbers and real NULLs.
    """

    @staticmethod
    def _workbook_and_markdown():
        import glob
        import os
        import sys
        import tempfile

        tool_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", "tools"))
        if tool_dir not in sys.path:
            sys.path.insert(0, tool_dir)
        import render_sample_briefing

        # The renderer runs the audit inside a temp working directory and the
        # workbook lands there, so it is captured on the way past.
        captured = {}
        original = render_sample_briefing._render_in

        def _spy(fakes, scenario, out_dir, work):
            captured["work"] = work
            return original(fakes, scenario, out_dir, work)

        start = os.getcwd()
        render_sample_briefing._render_in = _spy
        try:
            with tempfile.TemporaryDirectory() as out:
                written = render_sample_briefing.render("deep", out)
                with open(written[-1], encoding="utf-8") as f:
                    markdown = f.read()
                books = glob.glob(os.path.join(captured["work"], "*.xlsx"))
                frames = {}
                path = None
                if books:
                    # Copied out: `work` is a temp directory that goes away.
                    path = os.path.join(out, os.path.basename(books[0]))
                    import shutil
                    shutil.copy(books[0], path)
                    book = pd.ExcelFile(path)
                    for sheet in book.sheet_names:
                        frames[sheet] = book.parse(sheet)
                    # …and again, outside the `with`, so the file survives.
                    kept = tempfile.mkdtemp()
                    path = os.path.join(kept, os.path.basename(books[0]))
                    shutil.copy(books[0], path)
                return frames, markdown, path
        finally:
            render_sample_briefing._render_in = original
            os.chdir(start)

    @classmethod
    def setUpClass(cls):
        cls.frames, cls.markdown, cls.workbook_path = cls._workbook_and_markdown()

    def test_the_workbook_was_written_with_its_sheets(self):
        self.assertTrue(self.frames, "no workbook was produced")
        for sheet in ("Competitor Summary", "Traffic Magnets", "EEAT Scores"):
            self.assertIn(sheet, self.frames)

    def test_the_eeat_scores_reach_excel_as_numbers(self):
        """The defect: formatted in place, so the sheet got text.

        Checked on the RAW CELL TYPES, not on a pandas frame. The first version
        of this test asserted `is_numeric_dtype` on `read_excel`'s output and
        passed even with the defect restored, because pandas parses the string
        "0.6" back into a float on the way in — the stored cell is text, and
        the reader hides it. openpyxl reports what is actually in the file.
        """
        from openpyxl import load_workbook

        book = load_workbook(self.workbook_path)
        sheet = book["EEAT Scores"]
        headers = [cell.value for cell in next(sheet.iter_rows(max_row=1))]
        wanted = ("experience_score", "expertise_score",
                  "authoritativeness_score", "trustworthiness_score")
        for column in wanted:
            self.assertIn(column, headers)
            index = headers.index(column)
            cells = [row[index] for row in
                     sheet.iter_rows(min_row=2, max_row=sheet.max_row)]
            self.assertTrue(cells, f"no data rows for {column}")
            for cell in cells:
                self.assertIn(
                    cell.data_type, ("n",),
                    f"{column} row {cell.row} is stored as "
                    f"{cell.data_type!r} ({cell.value!r}) rather than a number "
                    f"— the owner cannot sort, chart or average the column")

    def test_the_em_dash_is_not_in_the_workbook(self):
        """It is a rendering marker for the markdown, not data."""
        for sheet, frame in self.frames.items():
            as_text = frame.astype(str)
            self.assertFalse(
                (as_text == unknown_cell()).any().any(),
                f"the '{unknown_cell()}' display marker reached the {sheet} sheet")

    def test_the_markdown_still_shows_the_dash(self):
        """The fix must not have removed the marker from the report."""
        self.assertIn("EEAT Competitive Analysis", self.markdown)


class TestTheMagnetFilterSaysWhenItIsNotInForce(unittest.TestCase):
    """The `rank ≤ 10` half of the magnet definition is currently a no-op.

    `_MAGNET_PREDICATE` compares against the handoff's `rank`, and
    serp-discover stores SerpAPI's per-page `position` without a pagination
    offset (H1 / D-C-01). In its 3-page mode the ranks run 1..9, 1..10, 1..10,
    so a result at true position 25 carries a rank of 5 and passes. Against the
    committed reference run's distribution the filter admits **29 of 29**
    results, true positions 1 through 29.

    The coverage block already warned that the rank COLUMN is page-relative.
    That is not the same statement: this is the list the owner acts on, it is
    roughly three times longer than its own definition implies, and some of the
    pages in it are on page 2 or 3 of the SERP. The Systemic Vacuums and the
    gpt-4o reframe targets share the predicate and inherit it.
    """

    def test_the_reference_distribution_admits_everything(self):
        """The arithmetic the warning asserts, so the claim is checkable."""
        ranks = list(range(1, 10)) + list(range(1, 11)) + list(range(1, 11))
        admitted = [position for position, rank
                    in enumerate(ranks, start=1) if rank <= 10]
        self.assertEqual(len(admitted), len(ranks))
        self.assertEqual(max(admitted), 29)

    def test_the_magnet_section_carries_the_qualification(self):
        content = TestNothingScoredStillSaysSo._briefing("deep")
        self.assertIn("Identified 'Traffic Magnets'", content)
        self.assertIn("criterion is not in force", content)
        self.assertIn("NOT as", content)
        # It must name what the list actually is.
        self.assertIn("clear the medical floor and the relevance test", content)
        # …and that the vacuums and reframes inherit it.
        self.assertIn("share this filter", content)

    def test_the_warning_is_absent_once_the_ranks_are_absolute(self):
        """It is driven by `handoff.absolute_rank_versions`, so listing the
        version serp-discover ships after D1 retires it with no code change."""
        import json
        import os
        import sys
        import tempfile
        from unittest.mock import patch

        tool_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", "tools"))
        if tool_dir not in sys.path:
            sys.path.insert(0, tool_dir)
        import render_sample_briefing

        original = render_sample_briefing._render_in

        def _absolute(fakes, scenario, out_dir, work):
            # Patch the config the run is given, after the tool assembles it.
            real_json_dump = json.dump

            def _spy(obj, handle, **kwargs):
                if isinstance(obj, dict) and "handoff" in obj:
                    obj["handoff"]["absolute_rank_versions"] = ["1.1"]
                return real_json_dump(obj, handle, **kwargs)

            with patch.object(json, "dump", side_effect=_spy):
                return original(fakes, scenario, out_dir, work)

        start = os.getcwd()
        render_sample_briefing._render_in = _absolute
        try:
            with tempfile.TemporaryDirectory() as out:
                written = render_sample_briefing.render("minimal", out)
                with open(written[-1], encoding="utf-8") as f:
                    content = f.read()
        finally:
            render_sample_briefing._render_in = original
            os.chdir(start)

        self.assertNotIn("criterion is not in force", content)
        self.assertNotIn("page-relative", content)


class TestTheBarbellSaysItsAuthorityIsOverstated(unittest.TestCase):
    """The same root cause as the magnet filter, in the section that gives a
    verdict rather than a list.

    `top10_count` is `MIN(position) <= 10` over the handoff keywords, and that
    position restarts at 1 on every SERP page (H1 / D-C-01). So every handoff
    keyword counts as a top-10 ranking, and with the default weights
    (moz_da 0.7 / top10 0.3) and `top10_saturation` 10, a domain with ten or
    more of them saturates the component whatever its real positions.
    """

    def test_the_inflation_crosses_the_quadrant_threshold(self):
        """The arithmetic the warning asserts, so the claim is checkable."""
        from src.positioning import compute_authority

        config = {"authority_weights": {"moz_da": 0.7, "top10": 0.3},
                  "top10_saturation": 10}
        # A domain with Moz DA 30 and NO genuine top-10 ranking, holding 12
        # handoff keywords.
        honest = compute_authority(30, 0, config)
        as_computed = compute_authority(30, 12, config)
        self.assertEqual(honest, 30.0)
        self.assertEqual(as_computed, 51.0)
        # `positioning.authority_threshold` is 50, so the inflation moves it
        # from one side of the quadrant boundary to the other.
        self.assertLess(honest, 50)
        self.assertGreater(as_computed, 50)

    def test_the_section_carries_the_qualification(self):
        content = TestNothingScoredStillSaysSo._briefing("deep")
        self.assertIn("Barbell Positioning Diagnostic", content)
        self.assertIn("authority axis is overstated", content)
        self.assertIn("upper bounds", content)
        # It must say what top10_count really counts.
        self.assertIn('"handoff keywords", not "top-10 rankings"', content)


class TestTheOverlapCellsSayTheyAreSkewed(unittest.TestCase):
    """The asymmetry: competitor positions page-relative, the client's absolute.

    `build_overlap_rows` filters competitor positions on `p <= top_n`, where a
    handoff-sourced position restarts at 1 on every SERP page, and filters the
    client's GSC position, which is absolute. Competitors pass the top-10 test
    at any true position; the client passes only if genuinely in the top 10.
    """

    def test_a_keyword_nobody_wins_is_reported_as_a_content_gap(self):
        """The demonstration the warning cites, so the claim is checkable."""
        from src.serp_overlap import build_overlap_rows

        config = {"top_n": 10, "commodity_high_overlap": 3}
        # Rivals at TRUE positions 14, 22 and 27 — handoff ranks 4, 2 and 7
        # after the per-page reset. The client is at a true GSC position of 12,
        # i.e. the CLOSEST of the four to the top 10.
        rows = build_overlap_rows(
            {"couples counselling": {"a.ca": 4, "b.ca": 2, "c.ca": 7}},
            {"couples counselling": 12},
            config, "2026-11-16", client_positions_available=True)
        row = rows[0]
        self.assertEqual(row["cell"], "exclusive_competitor")
        self.assertEqual(row["overlap_count"], 3)
        self.assertEqual(row["self_position"], 12)

    def test_the_section_carries_the_qualification(self):
        content = TestNothingScoredStillSaysSo._briefing("deep")
        self.assertIn("SERP Overlap", content)
        self.assertIn("top-10 test is asymmetric", content)
        self.assertIn("exclusive_self", content)
        # It must name the mixed-scale problem in the competitor column too.
        self.assertIn("mixes scales", content)
