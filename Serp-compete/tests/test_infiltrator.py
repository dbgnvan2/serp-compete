"""`src/infiltrator.py` — the standalone fragility list.

`compete-spec.md`#C3 documents this as a live implementation producing
`infil_report.md`. A coverage run on 2026-11-16 put it at **0%**, and giving it
tests found that it scored pages it had never read and treated unmeasured
traffic as low traffic.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src import infiltrator


@dataclass
class _Page:
    """Enough of `ScrapedPage` to exercise the guard."""
    url: str = "https://x.ca/a"
    extraction_status: str = "complete"


class _Auditor:
    def __init__(self, pages: Dict[str, Any], scores: Dict[str, Any] = None):
        self.pages = pages
        self.scores = scores or {"medical_score": 20, "systems_score": 0.0}
        self.scored: List[str] = []

    def scrape_content(self, url):
        return self.pages.get(url)

    def analyze_text(self, content):
        self.scored.append(getattr(content, "url", str(content)))
        return dict(self.scores)


class _Dfs:
    def __init__(self, pages_by_domain):
        self.pages_by_domain = pages_by_domain

    def get_top_pages(self, domain, limit=20):
        return self.pages_by_domain.get(domain, [])[:limit]


def _entry(url, etv=None, volume=None):
    page: Dict[str, Any] = {"url": url}
    if etv is not None:
        page["metrics"] = {"organic": {"etv": etv}}
    if volume is not None:
        page["keyword_data"] = {"keyword_info": {"search_volume": volume}}
    return page


class TestABlockedPageIsNotScored(unittest.TestCase):
    """The guard was `if not content:` — and `ScrapedPage` is a dataclass.

    A dataclass instance with no `__bool__` is always truthy, so a page whose
    fetch was blocked or errored passed the guard and had its 403 body counted
    as prose. `main.py` has branched on `extraction_status` since chunk C2
    (C-C-09); this module never did.
    """

    def _run(self, status):
        url = "https://rival.ca/page"
        auditor = _Auditor({url: _Page(url=url, extraction_status=status)})
        dfs = _Dfs({"rival.ca": [_entry(url, etv=4000)]})
        rows, coverage = infiltrator.Infiltrator(auditor, dfs).collect(["rival.ca"])
        return rows, coverage, auditor

    def test_a_blocked_page_is_not_scored(self):
        rows, coverage, auditor = self._run("blocked")
        self.assertEqual(rows, [])
        self.assertEqual(auditor.scored, [], "a blocked page was scored")
        self.assertEqual(coverage["unreadable"], 1)
        self.assertEqual(coverage["scored"], 0)

    def test_an_errored_page_is_not_scored(self):
        rows, coverage, auditor = self._run("error")
        self.assertEqual(rows, [])
        self.assertEqual(auditor.scored, [])
        self.assertEqual(coverage["unreadable"], 1)

    def test_a_complete_page_is_scored(self):
        rows, coverage, auditor = self._run("complete")
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(auditor.scored), 1)
        self.assertEqual(coverage["unreadable"], 0)

    def test_a_partial_page_is_scored(self):
        """`partial` means some content was extracted — it is data."""
        rows, _coverage, auditor = self._run("partial")
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(auditor.scored), 1)

    def test_a_none_from_the_scraper_is_not_scored(self):
        url = "https://rival.ca/page"
        auditor = _Auditor({})          # scrape_content returns None
        dfs = _Dfs({"rival.ca": [_entry(url, etv=4000)]})
        rows, coverage = infiltrator.Infiltrator(auditor, dfs).collect(["rival.ca"])
        self.assertEqual(rows, [])
        self.assertEqual(coverage["unreadable"], 1)

    def test_a_plain_string_still_works(self):
        """The pre-dataclass contract: a truthy string is content."""
        self.assertTrue(infiltrator._readable("some page text"))
        self.assertFalse(infiltrator._readable(""))


class TestUnmeasuredTrafficIsNotLowTraffic(unittest.TestCase):
    """`est_traffic` fell back to 0, and 0 > 500 is False.

    So a page whose traffic DataForSEO did not report was classified
    `Standard` — not fragile — on the strength of a number nobody measured.
    """

    def test_a_page_with_no_traffic_figure_reads_as_unmeasured(self):
        self.assertIsNone(infiltrator.page_traffic({"url": "https://x.ca"}))

    def test_etv_is_preferred(self):
        self.assertEqual(
            infiltrator.page_traffic(_entry("u", etv=1200, volume=50)), 1200)

    def test_search_volume_is_the_fallback(self):
        self.assertEqual(infiltrator.page_traffic(_entry("u", volume=50)), 50)

    def test_a_measured_zero_is_zero_not_unknown(self):
        """0 from the provider is a measurement. It must not become None."""
        self.assertEqual(infiltrator.page_traffic(_entry("u", etv=0)), 0.0)

    def test_an_unparseable_figure_is_unknown(self):
        self.assertIsNone(infiltrator.page_traffic(
            {"url": "u", "metrics": {"organic": {"etv": "lots"}}}))

    def test_unmeasured_traffic_is_classified_as_such(self):
        self.assertEqual(infiltrator.classify_fragility(None, 0.0, 500),
                         infiltrator.TRAFFIC_UNMEASURED)

    def test_a_measured_zero_is_classified_standard(self):
        self.assertEqual(infiltrator.classify_fragility(0.0, 0.0, 500),
                         infiltrator.STANDARD)

    def test_high_traffic_and_no_systems_is_fragile(self):
        self.assertEqual(infiltrator.classify_fragility(4000, 0.0, 500),
                         infiltrator.HIGH_FRAGILITY)

    def test_high_traffic_with_systems_language_is_not_fragile(self):
        self.assertEqual(infiltrator.classify_fragility(4000, 2.5, 500),
                         infiltrator.STANDARD)

    def test_the_boundary_is_exclusive(self):
        """`> threshold`, as the original was, so 500 exactly is not fragile."""
        self.assertEqual(infiltrator.classify_fragility(500, 0.0, 500),
                         infiltrator.STANDARD)
        self.assertEqual(infiltrator.classify_fragility(501, 0.0, 500),
                         infiltrator.HIGH_FRAGILITY)

    def test_an_unknown_systems_score_is_not_a_zero(self):
        self.assertEqual(infiltrator.classify_fragility(4000, None, 500),
                         infiltrator.TRAFFIC_UNMEASURED)


class TestTheThresholdIsConfigured(unittest.TestCase):
    """It was the literal `est_traffic > 500` (P4)."""

    def test_the_config_key_exists_and_is_read(self):
        import json

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with open(os.path.join(root, "shared_config.json")) as f:
            configured = json.load(f)["infiltrator"]["fragility_min_traffic"]
        self.assertEqual(infiltrator.fragility_min_traffic(), float(configured))

    def test_the_fallback_matches_the_config(self):
        import json

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with open(os.path.join(root, "shared_config.json")) as f:
            configured = json.load(f)["infiltrator"]["fragility_min_traffic"]
        self.assertEqual(infiltrator.DEFAULT_FRAGILITY_MIN_TRAFFIC, configured)


class TestTheReportStatesItsCoverage(unittest.TestCase):
    """An empty table must not read as "nothing is fragile" (P2)."""

    def test_an_all_blocked_run_says_nothing_was_scored(self):
        markdown = infiltrator.render(
            [], {"pages_seen": 8, "scored": 0, "unreadable": 8, "domains": 2})
        self.assertIn("scored 0 of 8 page(s)", markdown)
        self.assertIn("8 could not be read", markdown)
        self.assertIn("No page was scored this run", markdown)
        self.assertIn("not a page without fragility", markdown)

    def test_a_clean_run_with_no_fragile_pages_says_that_instead(self):
        markdown = infiltrator.render(
            [], {"pages_seen": 8, "scored": 8, "unreadable": 0, "domains": 2})
        self.assertIn("No page met the fragility definition", markdown)
        self.assertNotIn("could not be read", markdown)

    def test_unmeasured_traffic_is_called_out(self):
        markdown = infiltrator.render(
            [{"domain": "x.ca", "url": "https://x.ca/a", "traffic": None,
              "medical": 3, "bowen": 0.0,
              "fragility": infiltrator.TRAFFIC_UNMEASURED}],
            {"pages_seen": 1, "scored": 1, "traffic_unmeasured": 1, "domains": 1})
        self.assertIn("had no traffic figure", markdown)
        self.assertIn("rather than as not", markdown)
        # …and the cell is an em dash, never a 0.
        self.assertIn("| — |", markdown)

    def test_the_threshold_is_stated_with_its_provenance(self):
        markdown = infiltrator.render([], {"pages_seen": 0, "scored": 0,
                                           "domains": 0}, threshold=500)
        self.assertIn("500 estimated monthly visits", markdown)
        self.assertIn("editorial and uncalibrated", markdown)

    def test_fragile_pages_sort_first(self):
        rows = [
            {"domain": "a.ca", "url": "u1", "traffic": 100, "medical": 1,
             "bowen": 0.0, "fragility": infiltrator.STANDARD},
            {"domain": "b.ca", "url": "u2", "traffic": 900, "medical": 9,
             "bowen": 0.0, "fragility": infiltrator.HIGH_FRAGILITY},
        ]
        auditor = _Auditor({"u1": _Page(url="u1"), "u2": _Page(url="u2")})
        dfs = _Dfs({"a.ca": [_entry("u1", etv=100)],
                    "b.ca": [_entry("u2", etv=900)]})
        collected, _ = infiltrator.Infiltrator(auditor, dfs).collect(["a.ca", "b.ca"])
        self.assertEqual(collected[0]["fragility"], infiltrator.HIGH_FRAGILITY)
        del rows


class TestItWritesWhereItIsTold(unittest.TestCase):

    def test_the_report_is_written_and_returned(self):
        url = "https://rival.ca/page"
        auditor = _Auditor({url: _Page(url=url)})
        dfs = _Dfs({"rival.ca": [_entry(url, etv=4000)]})
        tool = infiltrator.Infiltrator(auditor, dfs)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "infil.md")
            markdown = tool.run_infiltration(["rival.ca"], output_path=out)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(f.read(), markdown)
        self.assertIn("High Fragility", markdown)

    def test_an_entry_with_no_url_is_counted_not_crashed_on(self):
        """It used to format `est_traffic` with `:.0f` in that branch, which
        raises on None."""
        auditor = _Auditor({})
        dfs = _Dfs({"rival.ca": [{"metrics": {"organic": {"etv": 10}}}, {}]})
        rows, coverage = infiltrator.Infiltrator(auditor, dfs).collect(["rival.ca"])
        self.assertEqual(rows, [])
        self.assertEqual(coverage["no_url"], 2)


if __name__ == "__main__":
    unittest.main()
