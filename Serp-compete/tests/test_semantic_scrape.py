"""`SemanticAuditor.scrape_content` — the failure paths, and the metadata.

Coverage on 2026-11-16 had `semantic.py` at 67%, and the largest uncovered
block was every error branch of `scrape_content`: the 429 → `blocked` path, the
HTTPError → `error` path and the catch-all. Those branches produce the
`extraction_status` that `main.run_audit`, `gsc_performance.analyze_gaps` and
`infiltrator.collect` all branch on to decide whether a page may be SCORED. If
one of them returned the wrong status, a 403 body would be counted as prose in
three places at once — which is the defect that was live in `infiltrator` until
the same day.

The metadata extraction was likewise untested, and it feeds the EEAT and GEO
verdicts.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import requests as _requests

from src.semantic import (DEFAULT_STOCK_IMAGE_HOSTS, SemanticAuditor,
                          stock_image_hosts)

#: Built once: `spacy.load` is slow, and the scrape path does not touch it.
AUDITOR = None


def setUpModule():
    global AUDITOR
    AUDITOR = SemanticAuditor()


class _Response:
    def __init__(self, status_code=200, text="", raise_for=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode()
        self._raise_for = raise_for

    def raise_for_status(self):
        if self._raise_for is not None:
            raise self._raise_for


def _http_error(status):
    error = _requests.exceptions.HTTPError(f"{status} error")
    error.response = _Response(status_code=status)
    return error


class _Session:
    """A `requests.Session` that answers the target URL and the warm-up.

    `scrape_content` makes two calls: a best-effort warm-up GET of the site
    root (C-C-18 gave it its own guard) and then the page itself. Only the
    second one is what these tests are about, so the warm-up always succeeds
    quietly.
    """

    def __init__(self, response=None, exception=None, target="/page"):
        self.response = response
        self.exception = exception
        self.target = target
        self.requested = []

    def get(self, url, **_kwargs):
        self.requested.append(url)
        if not url.endswith(self.target):
            return _Response(200, "<html><body>warm-up</body></html>")
        if self.exception is not None:
            raise self.exception
        return self.response


class TestTheFailureStatuses(unittest.TestCase):
    """Three downstream modules decide whether to SCORE a page from this."""

    def _scrape(self, response=None, exception=None):
        session = _Session(response, exception)
        with patch("src.semantic.requests.Session", return_value=session):
            return AUDITOR.scrape_content("https://rival.ca/page")

    def test_a_429_is_blocked_not_error(self):
        """`blocked` and `error` are different facts: a 429 is the circuit
        breaker and the report names those domains separately."""
        page = self._scrape(_Response(429, raise_for=_http_error(429)))
        self.assertEqual(page.extraction_status, "blocked")
        self.assertEqual(page.http_status, 429)
        self.assertEqual(page.first_500_words, "")
        self.assertIn("429", " ".join(page.extraction_errors))

    def test_a_403_is_an_error_with_its_status_kept(self):
        page = self._scrape(_Response(403, raise_for=_http_error(403)))
        self.assertEqual(page.extraction_status, "error")
        self.assertEqual(page.http_status, 403)

    def test_a_500_is_an_error(self):
        page = self._scrape(_Response(500, raise_for=_http_error(500)))
        self.assertEqual(page.extraction_status, "error")
        self.assertEqual(page.http_status, 500)

    def test_a_timeout_is_an_error_not_an_empty_page(self):
        page = self._scrape(exception=_requests.exceptions.Timeout("too slow"))
        self.assertEqual(page.extraction_status, "error")
        self.assertEqual(page.first_500_words, "")

    def test_a_connection_error_is_an_error(self):
        page = self._scrape(
            exception=_requests.exceptions.ConnectionError("reset"))
        self.assertEqual(page.extraction_status, "error")

    def test_an_unexpected_exception_is_still_an_error_page(self):
        """`scrape_content` must never raise: one bad page would abort a run
        part-way and leave the audit half-written."""
        page = self._scrape(exception=ValueError("something odd"))
        self.assertEqual(page.extraction_status, "error")
        self.assertIn("something odd", " ".join(page.extraction_errors))

    def test_every_failure_path_still_returns_the_url_and_a_timestamp(self):
        """The caller records the attempt, so these must be populated even on
        the paths that carry no content."""
        for response, exception in (
                (_Response(429, raise_for=_http_error(429)), None),
                (_Response(403, raise_for=_http_error(403)), None),
                (None, _requests.exceptions.Timeout("t")),
        ):
            page = self._scrape(response, exception)
            self.assertEqual(page.url, "https://rival.ca/page")
            self.assertTrue(page.fetched_at, "no fetched_at on a failure path")
            self.assertEqual(page.outline, [])
            self.assertEqual(page.full_text_word_count, 0)

    def test_a_failure_carries_empty_metadata_not_a_missing_key(self):
        """`eeat_scorer` and `geo_profiler` index into this dict."""
        page = self._scrape(_Response(429, raise_for=_http_error(429)))
        self.assertIsInstance(page.metadata, dict)
        for key in ("title", "image_count", "likely_original_images_count"):
            self.assertIn(key, page.metadata)

    def test_a_good_page_is_complete_and_carries_its_text(self):
        html = ("<html><head><title>Couples counselling</title></head>"
                "<body><h1>Anxiety</h1><p>" + "word " * 60 + "</p></body></html>")
        page = self._scrape(_Response(200, html))
        self.assertEqual(page.extraction_status, "complete")
        self.assertEqual(page.http_status, 200)
        self.assertGreater(page.scoring_word_count, 0)
        self.assertEqual(page.metadata["title"], "Couples counselling")


class TestStockImageHostsComeFromConfig(unittest.TestCase):
    """One list, read by both consumers.

    It was a literal set inside `_extract_metadata` while `eeat_scorer` read
    `shared_config.json → stock_image_hosts`, so editing that key changed the
    EEAT stock-image penalty and left `likely_original_images_count` alone —
    one visible knob controlling half of what it appears to (C-C-14).
    """

    def test_the_config_key_is_what_is_read(self):
        import json
        import os

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with open(os.path.join(root, "shared_config.json")) as f:
            configured = json.load(f)["stock_image_hosts"]
        self.assertEqual(stock_image_hosts(),
                         frozenset(h.lower() for h in configured))

    def test_the_fallback_matches_the_config(self):
        import json
        import os

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with open(os.path.join(root, "shared_config.json")) as f:
            configured = json.load(f)["stock_image_hosts"]
        self.assertEqual(DEFAULT_STOCK_IMAGE_HOSTS,
                         frozenset(h.lower() for h in configured))

    def test_eeat_scorer_reads_the_same_key(self):
        """The two consumers must agree, or one page has two stock-image
        verdicts depending on which module is asked."""
        import json
        import os

        from src.eeat_scorer import EEATScorer

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with open(os.path.join(root, "shared_config.json")) as f:
            config = json.load(f)
        scorer = EEATScorer(config)
        self.assertEqual(set(scorer.stock_image_hosts), set(stock_image_hosts()))

    def test_an_empty_config_list_falls_back_rather_than_counting_everything(self):
        """An empty list would make every image "original"."""
        with patch("src.database.load_shared_config",
                   return_value={"stock_image_hosts": []}):
            self.assertEqual(stock_image_hosts(), DEFAULT_STOCK_IMAGE_HOSTS)

    def test_a_broken_config_read_falls_back(self):
        with patch("src.database.load_shared_config",
                   side_effect=OSError("no config")):
            self.assertEqual(stock_image_hosts(), DEFAULT_STOCK_IMAGE_HOSTS)


class TestImageAttribution(unittest.TestCase):
    """`likely_original_images_count` is an EEAT input."""

    def _metadata(self, html):
        session = _Session(_Response(200, html))
        with patch("src.semantic.requests.Session", return_value=session):
            return AUDITOR.scrape_content("https://rival.ca/page").metadata

    def test_a_stock_image_is_not_counted_as_original(self):
        meta = self._metadata(
            '<html><body><img src="https://shutterstock.com/a.jpg">'
            '<p>text</p></body></html>')
        self.assertEqual(meta["image_count"], 1)
        self.assertEqual(meta["likely_original_images_count"], 0)

    def test_a_self_hosted_image_is_counted_as_original(self):
        meta = self._metadata(
            '<html><body><img src="https://rival.ca/wp/photo.jpg">'
            '<p>text</p></body></html>')
        self.assertEqual(meta["likely_original_images_count"], 1)

    def test_a_mixed_case_stock_host_is_still_stock(self):
        """Host names are case-insensitive, and `IStockPhoto.com` in a src
        attribute used to count as the practice's own photography."""
        meta = self._metadata(
            '<html><body><img src="https://IStockPhoto.com/a.jpg">'
            '<p>text</p></body></html>')
        self.assertEqual(meta["likely_original_images_count"], 0)

    def test_a_relative_src_is_counted_in_the_total_but_has_no_host(self):
        meta = self._metadata(
            '<html><body><img src="/images/photo.jpg"><p>text</p></body></html>')
        self.assertEqual(meta["image_count"], 1)
        # No netloc to judge, so it contributes no host and no original count.
        self.assertEqual(meta["likely_original_images_count"], 0)
        self.assertEqual(meta["image_hosts"], [])

    def test_an_img_with_no_src_is_counted_once_and_judged_not_at_all(self):
        meta = self._metadata('<html><body><img><p>text</p></body></html>')
        self.assertEqual(meta["image_count"], 1)
        self.assertEqual(meta["likely_original_images_count"], 0)


class TestSchemaExtractionSurvivesBadJson(unittest.TestCase):
    """A rival's malformed JSON-LD must not cost us the whole page."""

    def _metadata(self, html):
        session = _Session(_Response(200, html))
        with patch("src.semantic.requests.Session", return_value=session):
            return AUDITOR.scrape_content("https://rival.ca/page").metadata

    def test_malformed_json_ld_does_not_fail_the_scrape(self):
        meta = self._metadata(
            '<html><body><script type="application/ld+json">{not json,}'
            '</script><p>text</p></body></html>')
        self.assertIsInstance(meta, dict)

    def test_valid_json_ld_types_are_picked_up(self):
        meta = self._metadata(
            '<html><body><script type="application/ld+json">'
            '{"@type": "FAQPage"}</script><p>text</p></body></html>')
        self.assertIn("FAQPage", str(meta.get("schema_types", "")))

    def test_an_empty_script_tag_does_not_fail_the_scrape(self):
        meta = self._metadata(
            '<html><body><script type="application/ld+json"></script>'
            '<p>text</p></body></html>')
        self.assertIsInstance(meta, dict)


if __name__ == "__main__":
    unittest.main()


class TestJsonLdSurvivesBoilerplateStripping(unittest.TestCase):
    """The regression this file was written to find.

    `_strip_boilerplate` (C-M-19, 2026-11-15) decomposes every `<script>` so
    none of it reaches the scored text window. It runs BEFORE
    `_extract_metadata`, so from that date until 2026-11-16 no page's JSON-LD
    was ever found, and every schema signal was permanently False:

      geo_profiler: has_faq_schema, has_article_schema,
                    has_localbusiness_schema, has_person_schema, has_org_schema
      eeat_scorer:  schema_author_type_person, schema_organization_present

    Two owner-facing composites were degraded for every competitor, by a change
    in a third place, with a green suite.
    """

    FULL_SCHEMA = (
        '<html><head><title>T</title>'
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"FAQPage",'
        '"mainEntity":[{"@type":"Question","name":"What is anxiety?"}]}'
        '</script>'
        '<script type="application/ld+json">'
        '{"@type":"Organization","name":"Rival Counselling"}'
        '</script>'
        '</head><body><nav><a href="/menu">Menu</a></nav>'
        '<p>' + "body word " * 40 + '</p></body></html>')

    def _page(self, html):
        session = _Session(_Response(200, html))
        with patch("src.semantic.requests.Session", return_value=session):
            return AUDITOR.scrape_content("https://rival.ca/page")

    def test_the_schema_types_are_found(self):
        meta = self._page(self.FULL_SCHEMA).metadata
        types = str(meta.get("schema_types", ""))
        self.assertIn("FAQPage", types)
        self.assertIn("Organization", types)

    def test_the_schema_json_does_not_enter_the_scored_text(self):
        """Leaving the blocks in the soup would have been the easy fix, and it
        would have counted `schema.org` and every schema property as prose."""
        page = self._page(self.FULL_SCHEMA)
        self.assertNotIn("schema.org", page.scoring_text)
        self.assertNotIn("mainEntity", page.scoring_text)
        self.assertNotIn("@type", page.scoring_text)
        self.assertIn("body", page.scoring_text)

    def test_the_boilerplate_is_still_stripped(self):
        page = self._page(self.FULL_SCHEMA)
        self.assertNotIn("Menu", page.scoring_text)

    @staticmethod
    def _config():
        import json
        import os

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        with open(os.path.join(root, "shared_config.json")) as f:
            return json.load(f)

    def test_the_geo_profiler_sees_the_schema(self):
        """The consumer, not just the metadata dict: five of its signals."""
        from src.geo_profiler import GeoProfiler

        page = self._page(self.FULL_SCHEMA)
        profile = GeoProfiler(self._config()).profile_page(page)
        self.assertTrue(profile.signals.get("has_faq_schema"),
                        "geo_profiler did not see the FAQPage schema")
        self.assertTrue(profile.signals.get("has_org_schema"),
                        "geo_profiler did not see the Organization schema")
        self.assertIn("FAQPage", " ".join(profile.present_signals))

    def test_the_eeat_scorer_sees_the_organization_schema(self):
        from src.eeat_scorer import EEATScorer

        page = self._page(self.FULL_SCHEMA)
        score = EEATScorer(self._config()).score_page(page)
        self.assertTrue(
            score.authoritativeness_signals["schema_organization_present"],
            "eeat_scorer did not see the Organization schema")

    def test_a_page_with_no_schema_still_reports_false_not_an_error(self):
        page = self._page('<html><body><p>' + "word " * 30 + '</p></body></html>')
        self.assertIsInstance(page.metadata.get("schema_types"), list)
        self.assertEqual(page.metadata["schema_types"], [])
