"""`tools/render_sample_briefing.py` must keep working.

It reuses the fakes defined in `test_main_run_coverage.py` rather than
redefining five fake API clients. That is the right trade — a second copy of
"a DataForSEO that 429s for this domain" would drift from the first — but it
makes the tool depend on names in a test module, which nothing would otherwise
stop anyone renaming. This is that stop.

Only the `minimal` scenario is exercised: `full` and `authority-drop` run the
same code path with more fixtures (and `authority-drop` runs the audit twice),
so running them here would cost seconds of suite time to re-cover the same
plumbing. What is asserted is that the tool runs, writes a briefing, and that
briefing is a briefing.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

TOOL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                        "tools"))


def _tool():
    if TOOL_DIR not in sys.path:
        sys.path.insert(0, TOOL_DIR)
    import render_sample_briefing

    return render_sample_briefing


class TestTheRendererRuns(unittest.TestCase):

    def test_it_writes_a_briefing_that_looks_like_one(self):
        tool = _tool()
        start = os.getcwd()
        with tempfile.TemporaryDirectory() as out:
            try:
                written = tool.render("minimal", out)
            finally:
                # `render` restores the cwd itself; this guards the assertion
                # below from a failure part-way through leaving the suite in a
                # temp directory that is about to be deleted.
                os.chdir(start)
            self.assertEqual(len(written), 1)
            with open(written[0], encoding="utf-8") as f:
                content = f.read()

        self.assertIn("Strategic Briefing", content)
        self.assertIn("## Executive Summary", content)
        # The coverage block is what makes the artifact worth reading.
        self.assertIn("Run coverage", content)
        # And the thing the tool exists to catch must not be in it.
        self.assertNotRegex(content, r"\|\s*nan\s*\|")

    def test_the_cwd_is_restored(self):
        """The renderer chdirs into a temp directory to run the audit. Leaving
        the process there would break every later test that uses a relative
        path, in a way that looks like an unrelated failure."""
        tool = _tool()
        before = os.getcwd()
        with tempfile.TemporaryDirectory() as out:
            tool.render("minimal", out)
        self.assertEqual(os.getcwd(), before)

    def test_every_scenario_is_selectable_and_described(self):
        """`--list` is the only documentation of what the scenarios contain."""
        tool = _tool()
        self.assertEqual(set(tool.SCENARIOS),
                         {"minimal", "full", "authority-drop", "total-outage", "deep"})
        for name, description in tool.SCENARIOS.items():
            self.assertTrue(description.strip(), f"{name} has no description")

    def test_the_fakes_it_borrows_still_exist(self):
        """The tool reaches into the end-to-end test module for its fakes. If
        one is renamed there, the tool breaks and nothing else notices."""
        tool = _tool()
        fakes = tool._load_fakes()
        for name in ("CONFIG", "ENRICHED", "NO_ENRICHMENT", "NO_MOZ", "BLOCKED",
                     "CACHED", "OMITTED", "_handoff", "_target", "_FakeAuditor",
                     "_FakeDfs", "_FakeMoz", "_FakeGsc", "_FakeReframe"):
            self.assertTrue(hasattr(fakes, name),
                            f"test_main_run_coverage.{name} is gone, so "
                            f"tools/render_sample_briefing.py cannot run")


if __name__ == "__main__":
    unittest.main()
