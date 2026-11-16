#!/usr/bin/env python3
"""Render a strategic briefing from fake data, so it can be READ.

Purpose: let anyone see what the briefing actually says, without API keys, a
         Google Search Console property, a Moz token or a real handoff.
Usage:   python3 tools/render_sample_briefing.py [scenario] [-o OUT_DIR]
         python3 tools/render_sample_briefing.py --list

Why this exists
---------------
The review protocol's step 4 is "regenerate the briefing and diff the
markdown". No cloud session can do it — `.env`, `competitor_history.db` and the
reference handoff are all gitignored or untracked — and on a developer machine
it costs a live run. So nobody did it, and a run of defects lived in the
rendered report with a green test suite behind them. In one evening, reading
the output of this script found:

  * `nan` printed in two tables, in exactly the cells where a value had been
    deliberately WITHHELD (`pages_audited` for a 429-blocked domain,
    `focus_score` below `positioning.min_focus_tokens`);
  * a timestamp printed in the middle of the anchor-coverage failure counts,
    because a console line iterated every key of a dict that had since gained
    three non-count keys;
  * `\\u2013` in the owner's report, from a `json.dumps` default;
  * two caveats describing behaviour the code had stopped having (`rank_absolute`
    after C-C-17 moved to `rank_group`);
  * a stored row that contradicted itself (`measured = 1, questions_total = 0`).

None of those is visible from a test suite, because a test asserts what someone
thought to assert. This is not step 4 — the numbers are invented, so there is
nothing to diff against a previous real run — but it shows every section, every
caveat and every N-of-M line as the owner will read them.

The fakes come from `Serp-compete/tests/test_main_run_coverage.py` rather than
being redefined here, so there is one definition of "a DataForSEO that 429s for
this domain". Importing a test module from a tool is unusual; duplicating five
fake clients is worse, and this repo has been bitten more than once by a second
copy of something drifting from the first.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "Serp-compete"))
sys.path.insert(0, REPO_ROOT)


def _load_fakes():
    """The end-to-end fakes, from the test module that owns them."""
    path = os.path.join(REPO_ROOT, "Serp-compete", "tests",
                        "test_main_run_coverage.py")
    spec = importlib.util.spec_from_file_location("_compete_fakes", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_compete_fakes"] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Scenario pieces
# --------------------------------------------------------------------------

def _moz_block(fakes):
    """A handoff Moz block covering every anchor-coverage state at once."""
    return {
        "generated_at": "2026-11-16T09:00:00+00:00",
        "domains": {
            # `www.` on purpose: Tool 1 writes domains as netloc.lower() with
            # the prefix kept, and the risk feed must still name the canonical
            # form the rest of the report uses (chunk X).
            f"www.{fakes.ENRICHED}": {
                "data_available": True, "status": "ok",
                "fetched_at": "2026-11-16T08:55:00+00:00",
                "anchor_texts": {"status": "ok", "truncated": False, "items": [
                    {"text": "buy backlinks cheap", "external_root_domains": 9},
                    {"text": "enriched counselling", "external_root_domains": 14},
                ]}},
            # Errored during this run.
            fakes.NO_MOZ: {"data_available": False, "status": "error",
                           "fetched_at": "2026-11-16T08:58:00+00:00",
                           "anchor_texts": {"status": "error"}},
            # Errored a month ago and re-served from Tool 1's 30-day cache.
            fakes.BLOCKED: {"data_available": False, "status": "error",
                            "fetched_at": "2026-10-18T07:00:00+00:00",
                            "anchor_texts": {"status": "error"}},
            # Errored, with no date to judge by.
            fakes.CACHED: {"data_available": False, "status": "error",
                           "anchor_texts": {"status": "error"}},
        },
    }


def _av_export(fakes):
    """An AI-visibility export covering all three engine-coverage states."""
    return {
        "schema_version": "1.0", "source_run_ts": "2026-11-16T08:00:00Z",
        "data_available": True, "client_name": "Living Systems Counselling",
        # gemini answered; perplexity reports zero answered questions; openai is
        # listed with no rows at all.
        "engines": ["gemini", "perplexity", "openai"],
        "brand_mentions": [
            {"engine": "gemini", "brand": "Living Systems Counselling",
             "mention_count": 2, "questions_total": 8, "is_client": True,
             "source": "gazetteer"},
            {"engine": "gemini", "brand": "Enriched Counselling",
             "mention_count": 6, "questions_total": 8, "is_client": False,
             "source": "gazetteer"},
            {"engine": "gemini", "brand": "SomeDirectory", "mention_count": 2,
             "questions_total": 8, "is_client": False, "source": "gazetteer"},
            {"engine": "perplexity", "brand": "Living Systems Counselling",
             "mention_count": 0, "questions_total": 0, "is_client": True,
             "source": "gazetteer"},
        ],
        "ai_citations": [
            {"engine": "gemini", "url": f"https://{fakes.ENRICHED}/couples",
             "domain": fakes.ENRICHED, "category": "competitor",
             "brand": "Enriched Counselling", "is_client": False,
             "cite_count": 4},
        ],
        "answer_sentiment": [
            {"engine": "gemini", "brand": "Enriched Counselling",
             "polarity": "positive"},
        ],
    }


def _gsc_with_findings(fakes):
    import pandas as pd

    class _Gsc(fakes._FakeGsc):
        def analyze_gaps(self):
            target_gaps = pd.DataFrame([
                {"query": "anxiety counselling north vancouver",
                 "impressions": 1480, "ctr": 0.004, "tier": "t1_medical"},
            ])
            low_hanging = pd.DataFrame([
                {"query": "couples counselling",
                 "page": "https://livingsystems.ca/couples",
                 "position": 13.2, "impressions": 640},
            ])
            return target_gaps, low_hanging, []

        def get_query_position_map(self):
            return {"couples counselling north vancouver": 13.2}

    return _Gsc()


class _DroppingMoz:
    """Page Authority 38 on the first run, 30 on later ones.

    An 8-point fall, past `risk_signals.pa_drop_min` (3), so the Fragile
    Magnet section has a real drop to report rather than being empty. Used by
    the `authority-drop` scenario.
    """

    def __init__(self, fakes, first_run_calls=4):
        self.fakes = fakes
        self.first_run_calls = first_run_calls
        self.calls = 0

    def get_url_metrics(self, urls):
        if any(self.fakes.NO_MOZ in u for u in urls):
            return []          # Moz has no record for this domain's URLs
        self.calls += 1
        pa = 38 if self.calls <= self.first_run_calls else 30
        return [{"page_authority": pa, "page": u.removeprefix("https://")}
                for u in urls]


class _DeadMoz:
    """Moz answers nothing, for every URL, all run.

    Not an empty list of metrics for one domain — a provider that is simply
    down. Used by the `total-outage` scenario, because the whole of review
    chunk C2 rests on the claim that an outage cannot render as a clean bill of
    health, and that claim is only worth anything if someone reads the briefing
    an outage produces.
    """

    def get_url_metrics(self, urls):
        return []


class _DeadDfs:
    """DataForSEO 429s every call, and returns no search volume."""

    def __init__(self):
        self.last_error = None

    def get_relevant_pages(self, domain):
        self.last_error = "HTTP 429 (rate limited)"
        return []

    def get_search_volume(self, keywords):
        # None, not 0: a provider that would not answer has not told us the
        # demand is zero (C-C-11).
        return {str(k).lower(): None for k in keywords}


SCENARIOS = {
    "minimal": "The default fixture: six handoff domains, one omitted, one "
               "429-blocked, one with no Moz record, one cache-served. No AI "
               "export, no Moz anchors, no GSC findings.",
    "total-outage": "Every external provider is down: Moz returns nothing for "
                    "every URL, DataForSEO 429s every call and reports no "
                    "search volume, every page scrape is blocked, and there is "
                    "no AI export. Nothing in the briefing may read as a clean "
                    "bill of health.",
    "full": "minimal, plus an AI-visibility export covering all three engine "
            "coverage states, a Moz anchor block with a fresh error / a cached "
            "error / an undated error / a spam anchor, GSC findings, and one "
            "site arriving as both `www.x` and `x`.",
    "authority-drop": "full, run twice, with Page Authority falling 38 → 30 "
                      "between runs so the Fragile Magnet section fires.",
}


def render(scenario: str, out_dir: str) -> list:
    fakes = _load_fakes()
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="briefing-render-")
    start = os.getcwd()
    os.chdir(work)
    try:
        return _render_in(fakes, scenario, out_dir, work)
    finally:
        os.chdir(start)


def _render_in(fakes, scenario, out_dir, work):
    config = dict(fakes.CONFIG)
    omit_path = os.path.join(work, "omitted_domains.txt")
    with open(omit_path, "w") as f:
        f.write(f"{fakes.OMITTED}\n")
    config["filtering"] = {"omitted_domains_path": omit_path}
    config["gsc_settings"] = {"date_range_days": 90, "country": "can",
                              "ctr_threshold": 0.01, "position_target_max": 20}
    config["handoff"] = {"supported_versions": ["1.1"],
                         "absolute_rank_versions": []}
    config["risk_signals"] = {**fakes.CONFIG["risk_signals"],
                              "moz_cache_tolerance_hours": 24,
                              "anchor_spam_terms": ["buy backlinks", "pbn"],
                              "anchor_spam_min_domains": 1,
                              "anchor_spam_high_share": 0.25,
                              "anchor_spam_min_anchor_reach": 5,
                              "commercial_terms": ["casino"]}
    config["sov"] = {}
    config_path = os.path.join(work, "shared_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f)

    handoff = fakes._handoff()
    if scenario in ("full", "authority-drop"):
        handoff["moz"] = _moz_block(fakes)
        # The same site in the other spelling, on a different page.
        handoff["targets"].append(
            {**fakes._target(fakes.ENRICHED, path="/anxiety",
                             keyword="anxiety counselling"),
             "domain": f"www.{fakes.ENRICHED}"})
        with open(os.path.join(work, "ai_visibility_export_20261116.json"),
                  "w") as f:
            json.dump(_av_export(fakes), f)

    handoff_path = os.path.join(work, "competitor_handoff_sample_20261116_0900.json")
    with open(handoff_path, "w") as f:
        json.dump(handoff, f)

    db_path = os.path.join(work, "sample.db")
    if scenario == "total-outage":
        # Every scrape blocked, not merely errored: a 429 from the circuit
        # breaker is the case the report must not render as "nothing to report".
        all_urls = {t["url"] for t in handoff["targets"]}
        auditor = fakes._FakeAuditor(blocked_urls=all_urls)
    else:
        auditor = fakes._FakeAuditor(
            error_urls={f"https://{fakes.NO_MOZ}/couples"},
            blocked_urls={f"https://{fakes.BLOCKED}/couples"})

    gsc = (_gsc_with_findings(fakes) if scenario in ("full", "authority-drop")
           else fakes._FakeGsc())
    if scenario == "authority-drop":
        moz = _DroppingMoz(fakes)
    elif scenario == "total-outage":
        moz = _DeadMoz()
    else:
        moz = fakes._FakeMoz()
    dfs = _DeadDfs() if scenario == "total-outage" else fakes._FakeDfs()
    runs = 2 if scenario == "authority-drop" else 1

    from src.database import DatabaseManager
    from src.reporting import ReportGenerator
    from src.velocity_module import VelocityTracker

    import src.main as main

    captured: list = []

    class _Reporter(ReportGenerator):
        def __init__(self, *a, **kw):
            super().__init__(db_path)

        def generate_summary(self, *a, **kw):
            content = super().generate_summary(*a, **kw)
            captured.append(content)
            return content

    with patch.object(main, "pre_flight_check", return_value=gsc), \
         patch.object(main, "load_shared_config", return_value=config), \
         patch.object(main, "PROJECT_ROOT", work), \
         patch.object(main, "find_latest_handoff_file", return_value=handoff_path), \
         patch.object(main, "DatabaseManager",
                      lambda *a, **kw: DatabaseManager(db_path)), \
         patch.object(main, "VelocityTracker",
                      lambda *a, **kw: VelocityTracker(config_path)), \
         patch.object(main, "DataForSEOClient", lambda *a, **kw: dfs), \
         patch.object(main, "MozClient", lambda *a, **kw: moz), \
         patch.object(main, "SemanticAuditor", lambda *a, **kw: auditor), \
         patch.object(main, "ReframeEngine", lambda *a, **kw: fakes._FakeReframe()), \
         patch.object(main, "GeoProfiler", MagicMock()), \
         patch.object(main, "EEATScorer", MagicMock()), \
         patch.object(main, "ClusterDetector", MagicMock()), \
         patch.object(main, "ReportGenerator", _Reporter):
        for _ in range(runs):
            main.run_audit()

    written = []
    for index, content in enumerate(captured, 1):
        suffix = f"_run{index}" if len(captured) > 1 else ""
        target = os.path.join(out_dir, f"sample_briefing_{scenario}{suffix}.md")
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        written.append(target)
    return written


def main_cli(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", nargs="?", default="full",
                        choices=sorted(SCENARIOS))
    parser.add_argument("-o", "--out-dir", default="sample_briefings",
                        help="where to write the markdown (default: "
                             "./sample_briefings)")
    parser.add_argument("--list", action="store_true",
                        help="describe the scenarios and exit")
    args = parser.parse_args(argv)

    if args.list:
        for name in sorted(SCENARIOS):
            print(f"{name}\n    {SCENARIOS[name]}\n")
        return 0

    out_dir = os.path.abspath(args.out_dir)
    written = render(args.scenario, out_dir)
    if not written:
        print("No briefing was produced — run_audit returned before reporting.",
              file=sys.stderr)
        return 1
    print("\nThe numbers below are INVENTED. Read the wording, the caveats and "
          "the N-of-M lines, not the figures.")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
