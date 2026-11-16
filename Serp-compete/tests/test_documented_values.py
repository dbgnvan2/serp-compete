"""A threshold quoted in the docs must be the value the code uses.

Purpose: stop the docs stating one number while `shared_config.json` holds
         another. Spec: owner decision 7 (provenance), FEATURE_GUIDE §9.

Why: `docs/USER_MANUAL.md` told the owner a Traffic Magnet needs
`medical_score >= technical.vacuum_min_medical (10)` and showed
`"vacuum_min_medical": 10` in its config example, 24 lines above a paragraph
correctly explaining that the value had been **re-set to 6**. One document,
three statements, two of them wrong. The number matters: it is the floor that
decides which competitor pages appear as magnets, vacuums and reframe targets,
so an owner tuning against the documented 10 would be reasoning about a filter
that admits a different set of pages.

The check is deliberately conservative — it only complains when a line
references a config key AND quotes a number AND none of the numbers on that
line is the live value. A line that explains a threshold without quoting a
figure (the robust way to write one) is never flagged.

`docs/review_2026-11-04/` is excluded: those files are a dated record of
findings, and several quote the pre-fix values on purpose. Correcting them
would destroy the audit trail they exist to be.
"""
from __future__ import annotations

import json
import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONFIG_PATH = os.path.join(ROOT, "shared_config.json")

#: Directories whose .md files are historical records, not current claims.
EXCLUDED_DIRS = {
    os.path.join("docs", "review_2026-11-04"),
    os.path.join("docs", "tool2_review_bundle"),
}

#: Files that describe a design as it was proposed, not as it shipped. They
#: carry their own "this is not the current schema" banners.
EXCLUDED_FILES = {
    os.path.join("docs", "IMPLEMENTATION_PLAN_v3.md"),
    "RECONCILIATION_CHANGES.md",
    "sc7-yt-spec.md",
    "sc7-yt-phase1-plan.md",
    "compete-spec.md",
    "compete-spec-plan.md",
    "suite_enhancement_spec_SERPCOMPETE_v1.md",
}

#: Keys too short or too common to match reliably in prose ("da" matches every
#: "data"; "top_n" and "rank" appear constantly). Checking them would produce
#: noise, and a noisy guard gets deleted.
MIN_KEY_LENGTH = 12

#: Lines quoting a figure that is deliberately not the config value, with why.
#: Keep this empty if you can; an entry here is a line the guard cannot help.
ALLOWED_EXCEPTIONS: set = set()


def _config_values():
    """`{key: {every value that key has anywhere in the config}}`."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    values: dict = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if isinstance(value, dict):
                walk(value)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                values.setdefault(key, set()).add(float(value))

    walk(config)
    return {k: v for k, v in values.items() if len(k) >= MIN_KEY_LENGTH}


def _markdown_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in {".git", "node_modules", "__pycache__", "venv"}]
        relative_dir = os.path.relpath(dirpath, ROOT)
        if any(relative_dir == d or relative_dir.startswith(d + os.sep)
               for d in EXCLUDED_DIRS):
            continue
        for name in sorted(filenames):
            if not name.endswith(".md"):
                continue
            relative = os.path.normpath(os.path.join(relative_dir, name))
            if relative in EXCLUDED_FILES:
                continue
            yield relative, os.path.join(dirpath, name)


def _numbers_after(text, key):
    """Bare numbers appearing after `key` on this line.

    Excluded, because none of them is a threshold value:

    - parts of a longer token, so `2026-11-15` and `1.1` do not match;
    - section references — `§3.3` and `§9` are cross-references, and reading
      the `3.3` of "see the §3.3 caveat" as a quoted value for
      `max_audit_pages_per_domain` was this guard's first false positive;
    - numbered cross-references in prose — "open decision 8", "chunk C4",
      "finding 2", "Phase 1". These documents are full of them, and the second
      false positive was "open decision 8" read as a value.
    """
    tail = text.split(key, 1)[1] if key in text else ""
    tail = re.sub(r"§\s*\d+(?:\.\d+)*", " ", tail)
    tail = re.sub(
        r"\b(?:decision|decisions|chunk|chunks|finding|findings|section|sections"
        r"|step|steps|gap|gaps|part|parts|phase|phases|task|tasks|revision"
        r"|table|figure|rev|v)\s+[A-Za-z-]*\d+(?:\.\d+)*",
        " ", tail, flags=re.IGNORECASE)
    return {float(n) for n in re.findall(r"(?<![\w.\-])(\d+(?:\.\d+)?)(?![\w.\-])", tail)}


def disagreements(config_values, files):
    """Lines that reference a key and quote only non-live numbers."""
    found = []
    for relative, path in files:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        for line_no, line in enumerate(lines, 1):
            for key, live in config_values.items():
                # The key must be referenced AS a key — in backticks or as a
                # quoted JSON key — optionally dotted (`technical.key`). Bare
                # prose mentions are not worth the false positives.
                if not re.search(rf'[`"](?:[a-z_]+\.)*{re.escape(key)}[`"]', line):
                    continue
                quoted = _numbers_after(line, key)
                if not quoted:
                    continue          # explains the key without quoting a figure
                if live & quoted:
                    continue          # the live value is on the line
                found.append((relative, line_no, key, sorted(live),
                              sorted(quoted), line.strip()))
    return found


class TestDocumentedValuesMatchTheConfig(unittest.TestCase):

    def test_no_document_quotes_a_stale_threshold(self):
        problems = [p for p in disagreements(_config_values(), _markdown_files())
                    if f"{p[0]}:{p[1]}" not in ALLOWED_EXCEPTIONS]
        detail = "\n".join(
            f"  {relative}:{line_no} — `{key}` is {live} in shared_config.json "
            f"but this line quotes {quoted}\n    {line[:160]}"
            for relative, line_no, key, live, quoted, line in problems)
        self.assertEqual(problems, [], (
            "These lines quote a threshold that is not the configured value. "
            "Either the doc is stale or the config changed without the doc. "
            "Prefer explaining a threshold WITHOUT quoting the figure — a line "
            f"that names the key and no number never goes stale:\n{detail}"))


class TestTheGuardCanActuallyFail(unittest.TestCase):
    """A guard that cannot fail is worse than none."""

    def _check(self, line, config_values=None):
        import tempfile

        config_values = config_values or {"vacuum_min_medical": {6.0}}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "doc.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(line + "\n")
            return disagreements(config_values, [("doc.md", path)])

    def test_a_stale_quoted_value_is_detected(self):
        self.assertTrue(self._check("`vacuum_min_medical` is 10 by default"))

    def test_the_live_value_passes(self):
        self.assertFalse(self._check("`vacuum_min_medical` is 6 by default"))

    def test_a_json_example_is_checked_too(self):
        """The USER_MANUAL's stale value was in a JSON block, not prose."""
        self.assertTrue(self._check('  "vacuum_min_medical": 10,'))

    def test_a_dotted_reference_is_checked(self):
        """`technical.vacuum_min_medical` is how the manual writes it, and the
        first version of this guard missed exactly that form."""
        self.assertTrue(self._check(
            "`medical_score` >= `technical.vacuum_min_medical` (10)"))

    def test_explaining_a_key_without_a_number_is_not_flagged(self):
        self.assertFalse(self._check(
            "`vacuum_min_medical` is the minimum medical score a page must reach"))

    def test_a_date_is_not_read_as_a_value(self):
        self.assertFalse(self._check(
            "`vacuum_min_medical` is 6, editorial and uncalibrated, 2026-11-15"))

    def test_a_bare_prose_mention_is_not_flagged(self):
        """Without backticks there is no reliable way to tell a key reference
        from an English sentence, and guessing produces the noise that gets a
        guard deleted."""
        self.assertFalse(self._check("the vacuum_min_medical was 10 once"))


if __name__ == "__main__":
    unittest.main()


class TestSectionReferencesAreNotValues(unittest.TestCase):
    """`§3.3` is a cross-reference, not a figure — the first false positive."""

    def test_a_section_reference_is_ignored(self):
        self.assertEqual(
            _numbers_after("bounded by `max_audit_pages_per_domain` (§3.3)",
                           "max_audit_pages_per_domain"),
            set())

    def test_a_plain_section_number_is_ignored(self):
        self.assertEqual(
            _numbers_after("see `vacuum_min_medical` in §9", "vacuum_min_medical"),
            set())

    def test_a_real_value_beside_a_section_reference_still_counts(self):
        self.assertEqual(
            _numbers_after("`vacuum_min_medical` is 6 (§9)", "vacuum_min_medical"),
            {6.0})


class TestNumberedCrossReferencesAreNotValues(unittest.TestCase):
    """"open decision 8" is a pointer, not a threshold — false positive #2."""

    def test_a_decision_reference_is_ignored(self):
        self.assertEqual(
            _numbers_after("bounded by `max_audit_pages_per_domain`; "
                           "see open decision 8", "max_audit_pages_per_domain"),
            set())

    def test_a_chunk_reference_is_ignored(self):
        self.assertEqual(
            _numbers_after("`vacuum_min_medical` was re-set by chunk C4",
                           "vacuum_min_medical"),
            set())

    def test_a_real_value_beside_a_cross_reference_still_counts(self):
        self.assertEqual(
            _numbers_after("`vacuum_min_medical` is 6, per decision 3",
                           "vacuum_min_medical"),
            {6.0})

    def test_a_stale_value_beside_a_cross_reference_is_still_caught(self):
        """The case that matters: the exclusions must not become a way for a
        stale figure to hide behind a citation."""
        self.assertEqual(
            _numbers_after("`vacuum_min_medical` is 10, per decision 3",
                           "vacuum_min_medical"),
            {10.0})
