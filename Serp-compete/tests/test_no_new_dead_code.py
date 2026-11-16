"""Nothing in `src/` may be unreachable without being declared so.

Purpose: stop the dead-capability inventory growing in silence (P21).
Doc:     LEARNINGS.md → "Open risks" → the five unreachable capabilities

The rule this enforces is narrow on purpose: a function defined in `src/` whose
name appears **nowhere else** — not in another `src/` module, not in any test —
cannot run, cannot be verified, and reads to anyone browsing the code (or the
docs that name it) as a working feature. The 2026-11-16 sweep found ten such
functions; every one is listed in UNREACHABLE below with why it is there.

Deliberately NOT flagged: a function called only by tests. Those are reachable
and verified, and flagging them would make this guard noisy enough to be
deleted, which is the fate of every over-eager guard.

To add a function to `src/` that nothing calls yet, you must say so here. That
is the point: the cost of a dead capability is that someone believes it works,
and this makes the belief explicit rather than implicit.
"""
from __future__ import annotations

import ast
import os
import re
import unittest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
TEST_DIRS = [
    os.path.abspath(os.path.join(os.path.dirname(__file__))),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tests")),
]

#: Functions defined in `src/` that nothing references, with the reason each is
#: tolerated. Removing a name from this set means it either gained a caller or
#: was deleted. ADDING a name means accepting a capability that cannot run.
UNREACHABLE = {
    # `IMPLEMENTATION_PLAN_v3.md` Task 11 created this module as a declared
    # "skeleton for future" — an Ahrefs/Moz integration nobody has wired. It is
    # the one intentional entry here. Its own docstring says its tests are "to
    # be implemented", and the plan's coverage table claimed a test file that
    # does not exist until that was corrected on 2026-11-16.
    "get_domain_backlinks": "third_party_crawlers skeleton (declared future work)",
    "get_internal_links": "third_party_crawlers skeleton (declared future work)",
    "track_link_velocity": "third_party_crawlers skeleton (declared future work)",
    "batch_domain_metrics": "third_party_crawlers skeleton (declared future work)",
    "get_anchor_text": "third_party_crawlers skeleton (declared future work)",
    "get_top_linking_pages": "third_party_crawlers skeleton (declared future work)",
    "enhance_competitor_with_third_party": "third_party_crawlers skeleton",
    "export_third_party_data": "third_party_crawlers skeleton",
    # A DataForSEO SERP call for People Also Ask. Unwired, and one of the two
    # ways to restore the PAA promise FEATURE_GUIDE §6.1 made and C1 dropped —
    # at one billed call per keyword, and only after hardening (it predates
    # `post_with_retries`). See docs/handoff_contract.md §4.
    "get_serp_data": "unwired PAA fetch; see handoff_contract.md §4 before using",
    # Unreferenced by src/ AND by the tests. `update_traffic_magnet_scores`
    # would also be wrong if called: it writes two of the six score columns
    # `traffic_magnets` now carries, so the others would describe a different
    # scoring run.
    "get_run_urls": "unreferenced; deletion candidate",
    "update_traffic_magnet_scores": "unreferenced AND stale; deletion candidate",
}


def _python_files(directory):
    for root, _, files in os.walk(directory):
        if "__pycache__" in root:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(root, name)


def _definitions():
    """`{function name: [(file, lineno), …]}` for every def in `src/`."""
    found = {}
    for path in _python_files(SRC):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("__"):
                    continue
                found.setdefault(node.name, []).append(
                    (os.path.basename(path), node.lineno))
    return found


def _corpus():
    """Every `src/` and test file EXCEPT this one.

    This file names each entry of UNREACHABLE, so counting itself would make
    every declared name look referenced and the guard would report its own
    allowlist as stale — a guard defeated by its own documentation.
    """
    this_file = os.path.abspath(__file__)
    texts = []
    for directory in [SRC] + TEST_DIRS:
        if not os.path.isdir(directory):
            continue
        for path in _python_files(directory):
            if os.path.abspath(path) == this_file:
                continue
            with open(path, encoding="utf-8") as f:
                texts.append(f.read())
    return texts


def unreachable_names(defs, texts):
    """The names in `defs` that `texts` never mentions outside their own `def`.

    Separated from the file walking so the can-fail test below can drive it
    with synthetic input instead of asserting a tautology.
    """
    out = set()
    for name, places in defs.items():
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        hits = sum(len(pattern.findall(text)) for text in texts)
        # Every definition contributes one textual hit for its own `def` line.
        if hits - len(places) <= 0:
            out.add(name)
    return out


class TestNoNewDeadCode(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.defs = _definitions()
        cls.texts = _corpus()
        cls.unreachable = unreachable_names(cls.defs, cls.texts)

    def test_no_undeclared_unreachable_function(self):
        undeclared = sorted(self.unreachable - set(UNREACHABLE))
        detail = "; ".join(
            f"{name} ({', '.join(f'{f}:{l}' for f, l in self.defs[name])})"
            for name in undeclared)
        self.assertEqual(undeclared, [], (
            "These functions are defined in src/ and referenced nowhere — not by "
            "another src module, not by any test. Wire one, delete it, or add it "
            "to UNREACHABLE in this file with the reason. A capability nobody can "
            f"reach still reads as a working feature (P21): {detail}"))

    def test_the_declared_list_has_no_stale_entries(self):
        """The mirror: a declared entry that is now referenced must be removed
        from the list, or the list stops meaning anything."""
        stale = sorted(set(UNREACHABLE) - self.unreachable)
        self.assertEqual(stale, [], (
            "These are listed as unreachable but something references them now. "
            f"Remove them from UNREACHABLE: {stale}"))

    def test_every_declared_entry_still_exists(self):
        """A name left in the list after the function was deleted would hide a
        real unreachable function behind a stale allowance."""
        missing = sorted(set(UNREACHABLE) - set(self.defs))
        self.assertEqual(missing, [], (
            "These are listed as unreachable but no longer exist in src/. "
            f"Remove them from UNREACHABLE: {missing}"))

    def test_a_new_unreferenced_function_is_detected(self):
        """A guard that cannot fail is worse than none."""
        defs = {"freshly_added_helper": [("newmodule.py", 10)]}
        texts = ["def freshly_added_helper(x):\n    return x\n"]
        self.assertEqual(unreachable_names(defs, texts), {"freshly_added_helper"})

    def test_a_function_with_one_caller_is_not_flagged(self):
        defs = {"used_helper": [("a.py", 3)]}
        texts = ["def used_helper(x):\n    return x\n",
                 "from src.a import used_helper\n"]
        self.assertEqual(unreachable_names(defs, texts), set())

    def test_a_function_called_only_by_a_test_is_not_flagged(self):
        """Reachable and verified. Flagging these would make the guard noisy
        enough to be deleted, which is the fate of every over-eager guard."""
        defs = {"tested_helper": [("a.py", 3)]}
        texts = ["def tested_helper(x):\n    return x\n",      # the src module
                 "assert tested_helper(1) == 1\n"]              # a test
        self.assertEqual(unreachable_names(defs, texts), set())

    def test_a_substring_match_is_not_counted_as_a_reference(self):
        """`\\b` anchors matter: without them `get_run` would be 'referenced'
        by every mention of `get_run_urls`."""
        defs = {"get_run": [("a.py", 3)]}
        texts = ["def get_run(self):\n    pass\n", "db.get_run_urls(run_id)\n"]
        self.assertEqual(unreachable_names(defs, texts), {"get_run"})

    def test_this_file_is_excluded_from_the_corpus(self):
        """Naming the allowlist entries here must not make them look used."""
        self.assertNotIn("UNREACHABLE", "\n".join(self.texts))


if __name__ == "__main__":
    unittest.main()
