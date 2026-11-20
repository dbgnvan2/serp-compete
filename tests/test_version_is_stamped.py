"""The version is written once, and the record of it cannot drift.

Before v1.5.0 neither tool had a version, so a briefing named its run and
its client but not the build that produced it. These tests hold three
things: the number has one home, `CHANGELOG.md`'s newest entry names that
same number, and the briefing's header reads it through
`briefing_messages.json` rather than carrying a literal.
"""
import json
import os
import re
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "Serp-compete")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from src import _version  # noqa: E402

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def _without_comments(body):
    """Code only. A version NAMED in a comment explains why a line is the way
    it is; a version used as data is a copy that can go stale, and only the
    second is a defect."""
    return "\n".join(line.split("#", 1)[0] for line in body.splitlines())


class TestTheNumberHasOneHome(unittest.TestCase):

    def test_version_is_a_semver_string(self):
        self.assertRegex(_version.__version__, SEMVER)

    def test_no_other_module_declares_its_own_version(self):
        offenders = []
        for root, dirs, files in os.walk(SRC):
            dirs[:] = [d for d in dirs
                       if d not in {"venv", ".git", "__pycache__", "data"}]
            for name in files:
                if not name.endswith(".py") or name == "_version.py":
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8", errors="replace") as fh:
                    if re.search(r"^__version__\s*=", fh.read(), re.M):
                        offenders.append(os.path.relpath(path, REPO))
        self.assertEqual(offenders, [], f"a second version lives in {offenders}")


class TestTheChangelogNamesThisVersion(unittest.TestCase):

    def test_newest_entry_is_the_current_version(self):
        entries = re.findall(r"^## \[(\d+\.\d+\.\d+)\]",
                             _read("CHANGELOG.md"), re.M)
        self.assertTrue(entries, "CHANGELOG.md has no `## [x.y.z]` entry")
        self.assertEqual(
            entries[0], _version.__version__,
            f"CHANGELOG.md names {entries[0]!r} but _version.py says "
            f"{_version.__version__!r} — bump both or neither")


class TestTheReadmeNamesThisVersion(unittest.TestCase):
    """The README states the version in prose, which is a copy. Checked
    rather than trusted: nothing else would notice it going stale."""

    def test_readme_names_the_current_version(self):
        found = re.findall(r"\*\*v(\d+\.\d+\.\d+)\*\*", _read("README.md"))
        self.assertTrue(found, "README.md names no version")
        self.assertEqual(found[0], _version.__version__)


class TestTheBriefingHeaderCarriesIt(unittest.TestCase):

    def test_the_heading_has_words_in_the_messages_file(self):
        headings = json.loads(_read("briefing_messages.json"))["headings"]
        self.assertIn("tool_version", headings)
        self.assertIn("{version}", headings["tool_version"])

    def test_the_heading_sits_before_the_executive_summary(self):
        """Render order: the build is part of the header, not a footnote."""
        keys = list(json.loads(_read("briefing_messages.json"))["headings"])
        self.assertLess(keys.index("tool_version"),
                        keys.index("executive_summary"))

    def test_reporting_renders_it_from_the_version_module(self):
        body = _read("Serp-compete", "src", "reporting.py")
        self.assertIn("from src._version import __version__", body)
        self.assertIn('m.get("headings.tool_version", version=__version__)',
                      body)
        self.assertEqual(
            re.findall(r"\bv\d+\.\d+\.\d+\b", _without_comments(body)), [])

    def test_the_mismatch_warning_is_not_placed_by_a_fixed_index(self):
        """The header grew a line in v1.5.0; a literal index moved the
        warning below it instead of above the executive summary."""
        body = _read("Serp-compete", "src", "reporting.py")
        self.assertNotIn("report.insert(4, mismatch_line)", body)
        self.assertIn("report.insert(_at, mismatch_line)", body)


if __name__ == "__main__":
    unittest.main()
