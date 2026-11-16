"""Map the GSC strike list onto the pillar draft's section headings.

Purpose: turn "these queries are in striking distance" into Bowen-framed H2s.
Spec:    docs/IMPLEMENTATION_PLAN_v3.md (Feature 3, "strike mapper")
Tests:   Serp-compete/tests/test_strike_mapper.py

Standalone: run it directly, it is not part of `run_audit`.

    python3 Serp-compete/src/strike_mapper.py            # dry run, prints only
    python3 Serp-compete/src/strike_mapper.py --write    # edit the draft

What this module got wrong until 2026-11-16, found by reading its own output
against `gsc_strike_list.md`:

* **It manufactured keywords out of no data.** `gsc_strike_list.md` in this repo
  contains exactly one row — `| No data | - | - | - | - | - |` — and the parser
  silently substituted five hard-coded keywords, which `inject_headers` then
  wrote into `pillar_north_shore_draft.md` as section headings. The five
  headings in that draft today are those invented keywords, and nothing in the
  draft or the console said so. This is the review's H2 class ("no data coerced
  into plausible output") inside the owner's content.
* **It was not idempotent.** Each run injected the headers again, so running it
  twice duplicated every heading in a file the owner edits by hand (P8).
* **Its editorial content lived in Python.** `CLAUDE.md`: "Editorial content
  (keyword rules, domain overrides, vocabulary) belongs in YAML/JSON config, not
  Python source." The reframe vocabulary now lives in `shared_config.json`
  under `strike_mapper`, with the constants below as the documented fallback —
  the same pattern as `reframe_engine.DEFAULT_CLINICAL_PIVOTS` and
  `brand_utils.DEFAULT_NAME_SUFFIXES`.
* **It wrote on import-and-call with no dry run.** A tool that edits a content
  file now prints what it would do unless asked to write.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional, Tuple

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GSC_STRIKE_LIST_PATH = os.path.join(ROOT_DIR, "gsc_strike_list.md")
PILLAR_DRAFT_PATH = os.path.join(ROOT_DIR, "pillar_north_shore_draft.md")

#: Where the strike list marks a row as carrying nothing. Treated as absence,
#: never as a query.
NO_DATA_MARKERS = {"no data", "-", "", "n/a", "none"}

#: Fallback only — `shared_config.json` → `strike_mapper.reframes` is the
#: editorial source of record. Mirrored here so the script still runs without
#: config, and guarded by a test so the two cannot drift.
DEFAULT_REFRAMES: Dict[str, str] = {
    "couples counselling north vancouver":
        "Observing the Reciprocal Pursuit-Distance Cycle",
    "relationship therapy north vancouver":
        "From Individual Pathology to Systemic Process",
    "anxiety clinic north vancouver":
        "Intercepting the Anxiety Loop through Differentiation",
    "marriage therapist north shore": "Defining a Self in the Marriage System",
    "family systems therapy bc":
        "The Multigenerational Transmission of Anxiety",
    "counselling north vancouver":
        "Beyond Symptoms: Focus on the Relationship System",
    "marriage counselling north vancouver":
        "Observing the Emotional System in Conflict",
    "relationship counselling north vancouver":
        "Tracing the Reciprocity in Relationship Anxiety",
}

#: The reframe used for a query with no entry of its own.
GENERIC_REFRAME = "Observing the Relationship Process"

#: Marks headings this tool wrote, so a second run can recognise its own work
#: instead of duplicating it, and so a reader can tell them from hand-written
#: ones.
PROVENANCE_MARKER = "<!-- strike-mapper -->"

INJECTION_POINT = "## [H2] Hyper-Local Support"

#: How many striking-distance queries to map. Editorial.
DEFAULT_MAX_KEYWORDS = 5


def _config(section: str = "strike_mapper") -> dict:
    try:
        from src.database import load_shared_config
    except ImportError:  # pragma: no cover - standalone use
        return {}
    try:
        return (load_shared_config().get(section) or {})
    except Exception:  # noqa: BLE001 - a config read must not break the tool
        return {}


def reframes() -> Dict[str, str]:
    """The editorial reframe vocabulary, config first."""
    configured = _config().get("reframes")
    if isinstance(configured, dict) and configured:
        return {str(k).lower(): str(v) for k, v in configured.items()}
    return dict(DEFAULT_REFRAMES)


def get_top_gsc_keywords(path: Optional[str] = None,
                         limit: Optional[int] = None) -> Tuple[List[str], str]:
    """`(queries, source)` from the GSC strike list.

    `source` is `"gsc"` when real rows were read and `"none"` when the file is
    missing, unreadable or carries no query — it is NEVER a list of keywords
    invented to stand in for data. The old version returned a hard-coded five
    in that case, and those five are in the pillar draft today.
    """
    if limit is None:
        limit = int(_config().get("max_keywords", DEFAULT_MAX_KEYWORDS))
    path = path or GSC_STRIKE_LIST_PATH
    if not os.path.exists(path):
        return [], "none"

    queries: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return [], "none"

    for line in lines:
        if "|" not in line or "Current Position" in line or "---" in line:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) <= 2:
            continue
        query = cells[1]
        # A placeholder row is absence, not a query. The old test was
        # `parts[1] != "No data"` — exact, case-sensitive, and blind to the `-`
        # and empty-cell forms the generator also writes.
        if query.lower() in NO_DATA_MARKERS:
            continue
        queries.append(query)

    return queries[:limit], ("gsc" if queries else "none")


def headings_for(queries: List[str],
                 vocabulary: Optional[Dict[str, str]] = None) -> List[str]:
    """The markdown headings for these queries, each carrying its provenance."""
    vocabulary = reframes() if vocabulary is None else vocabulary
    out = []
    for query in queries:
        reframe = vocabulary.get(query.lower(), GENERIC_REFRAME)
        out.append(f"## {query.title()}: {reframe} {PROVENANCE_MARKER}")
    return out


def plan_injection(draft: str, headings: List[str]) -> Tuple[Optional[str], str]:
    """`(new draft or None, why)` for injecting *headings* into *draft*.

    Idempotent: a heading already present is not added again. The previous
    version appended all of them on every run, duplicating every heading in a
    file the owner edits by hand.
    """
    if INJECTION_POINT not in draft:
        return None, (f"the injection point {INJECTION_POINT!r} is not in the "
                      f"draft, so there is nowhere to put the headings")

    missing = [h for h in headings if _heading_body(h) not in
               {_heading_body(line) for line in draft.splitlines()
                if line.startswith("## ")}]
    if not missing:
        return None, "every heading is already in the draft — nothing to do"

    before, after = draft.split(INJECTION_POINT, 1)
    updated = before + "\n".join(missing) + "\n\n" + INJECTION_POINT + after
    return updated, f"would add {len(missing)} of {len(headings)} heading(s)"


def _heading_body(line: str) -> str:
    """A heading without its provenance marker, for comparison."""
    return line.replace(PROVENANCE_MARKER, "").strip().rstrip(":").lower()


def inject_headers(write: bool = False, allow_fallback: bool = False,
                   strike_list: Optional[str] = None,
                   draft_path: Optional[str] = None) -> int:
    """Map the strike list onto the draft. Returns a process exit code.

    Writes nothing unless `write` is true. Refuses to invent content: when the
    strike list carries no query, it says so and stops, unless `allow_fallback`
    is set — and then it says that the headings come from the fallback
    vocabulary and not from Search Console data.
    """
    draft_path = draft_path or PILLAR_DRAFT_PATH
    queries, source = get_top_gsc_keywords(strike_list)

    if source == "none":
        if not allow_fallback:
            print("The GSC strike list carries no striking-distance query "
                  f"({strike_list or GSC_STRIKE_LIST_PATH}).")
            print("Nothing was written. Re-run the GSC step, or pass "
                  "--allow-fallback to use the editorial keyword list instead "
                  "— which is NOT Search Console data and must not be "
                  "presented as it.")
            return 1
        queries = list(reframes())[:int(
            _config().get("max_keywords", DEFAULT_MAX_KEYWORDS))]
        print("⚠️ No GSC data. Using the editorial fallback keyword list: "
              "these headings reflect the configured vocabulary, NOT measured "
              "search demand.")

    if not queries:
        print("No queries to map.")
        return 1

    if not os.path.exists(draft_path):
        print(f"❌ The pillar draft is not there: {draft_path}")
        return 1
    with open(draft_path, "r", encoding="utf-8") as f:
        draft = f.read()

    headings = headings_for(queries)
    updated, why = plan_injection(draft, headings)
    print(f"Source: {source}. {why}.")
    for heading in headings:
        print(f"  {heading}")
    if updated is None:
        return 0
    if not write:
        print("\nDry run — pass --write to edit the draft.")
        return 0
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write(updated)
    print(f"✅ Wrote {draft_path}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true",
                        help="edit the pillar draft (default: dry run)")
    parser.add_argument("--allow-fallback", action="store_true",
                        help="when the strike list has no data, use the "
                             "editorial keyword list and say so")
    args = parser.parse_args(argv)
    return inject_headers(write=args.write, allow_fallback=args.allow_fallback)


if __name__ == "__main__":
    sys.exit(main())
