"""Chunk Y12 — one database, named once. The Tool 2 half.

Spec: docs/review_2026-11-04/PLAN_Y12_one_database_named_once.md

Tool 1 held the database name as a literal at 24 sites, every one of them
relative to the current working directory. Tool 2 had already fixed the body
of that fault in `ReportGenerator`, but `load_db_path`'s config-absent branch
still returned the bare name: run a reader from another directory with no
`shared_config.json` present and SQLite created a new empty database beside
the caller instead of reporting that the history was missing (P16/P2). The
branch that bypasses the resolution is the branch that has the bug.
"""
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from src import database  # noqa: E402


@contextmanager
def _cwd(path):
    before = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(before)


class TestThePathIsAlwaysAbsolute(unittest.TestCase):

    def test_an_absent_config_still_gives_a_path_outside_the_cwd(self):
        """The fault. With no config, the name was returned bare, so the
        database SQLite opened depended on where the command was run."""
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as elsewhere:
            missing = os.path.join(root, "shared_config.json")
            with mock.patch.object(database, "SHARED_CONFIG_PATH", missing), \
                    _cwd(elsewhere):
                resolved = database.load_db_path()
        self.assertTrue(os.path.isabs(resolved))
        self.assertEqual(resolved,
                         os.path.join(root, database.DEFAULT_DATABASE_NAME))
        self.assertNotEqual(os.path.dirname(resolved), elsewhere)

    def test_a_configured_relative_name_resolves_against_the_config(self):
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as elsewhere:
            config_path = os.path.join(root, "shared_config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write('{"technical": {"database_path": "hist.db"}}')
            with mock.patch.object(database, "SHARED_CONFIG_PATH", config_path), \
                    _cwd(elsewhere):
                resolved = database.load_db_path()
        self.assertEqual(resolved, os.path.join(root, "hist.db"))

    def test_a_configured_absolute_name_is_used_as_given(self):
        with tempfile.TemporaryDirectory() as root:
            config_path = os.path.join(root, "shared_config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write('{"technical": {"database_path": "/var/x/h.db"}}')
            with mock.patch.object(database, "SHARED_CONFIG_PATH", config_path):
                self.assertEqual(database.load_db_path(), "/var/x/h.db")

    def test_a_tilde_is_expanded(self):
        """`~/serp/hist.db` is a home-relative path, not a directory called
        `~` under the config: unexpanded it resolves beside the config file."""
        with tempfile.TemporaryDirectory() as root:
            config_path = os.path.join(root, "shared_config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write('{"technical": {"database_path": "~/hist.db"}}')
            with mock.patch.object(database, "SHARED_CONFIG_PATH", config_path):
                self.assertEqual(
                    database.load_db_path(),
                    os.path.join(os.path.expanduser("~"), "hist.db"))

    def test_a_value_that_is_not_a_path_is_reported_not_used(self):
        """P2: a blank or non-string value is somebody's mistake, and
        resolving it silently would hide it."""
        for bad in ("", "   ", 7, None, []):
            with self.subTest(bad=bad):
                with tempfile.TemporaryDirectory() as root:
                    config_path = os.path.join(root, "shared_config.json")
                    import json
                    with open(config_path, "w", encoding="utf-8") as handle:
                        json.dump({"technical": {"database_path": bad}}, handle)
                    with mock.patch.object(database, "SHARED_CONFIG_PATH",
                                           config_path):
                        with self.assertLogs(level="WARNING") as logs:
                            resolved = database.load_db_path()
                self.assertEqual(os.path.basename(resolved),
                                 database.DEFAULT_DATABASE_NAME)
                self.assertIn("database_path", "".join(logs.output))

    def test_an_absent_config_is_reported_not_assumed(self):
        """P2: a run with no config is a run on defaults, and the database it
        landed on is the thing worth knowing. The fix made the path
        deterministic; without a report, a briefing of zero competitors still
        comes back with nothing saying the config was never found."""
        with tempfile.TemporaryDirectory() as root:
            missing = os.path.join(root, "shared_config.json")
            with mock.patch.object(database, "SHARED_CONFIG_PATH", missing):
                with self.assertLogs(level="WARNING") as logs:
                    resolved = database.load_db_path()
        message = "".join(logs.output)
        self.assertIn(resolved, message)
        self.assertIn("shared_config.json", message)

    def test_a_malformed_technical_block_is_reported_not_raised(self):
        """The guard checked the leaf and not the section, so `"technical":
        null` was an AttributeError from a `.get` on None while a blank leaf
        got the designed warning (P5)."""
        for bad in (None, [], "technical", 3):
            with self.subTest(bad=bad):
                with tempfile.TemporaryDirectory() as root:
                    config_path = os.path.join(root, "shared_config.json")
                    resolved = database.resolve_db_path(
                        {"technical": bad}, config_path)
                self.assertEqual(resolved,
                                 os.path.join(root, database.DEFAULT_DATABASE_NAME))

    def test_a_config_that_is_not_a_block_at_all_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as root:
            config_path = os.path.join(root, "shared_config.json")
            for bad in (None, [], "x"):
                with self.subTest(bad=bad):
                    self.assertEqual(
                        database.resolve_db_path(bad, config_path),
                        os.path.join(root, database.DEFAULT_DATABASE_NAME))


class TestOneResolverForTheWholeRepo(unittest.TestCase):
    """P5/P32 — the chunk is named "one database, named once", and the repo
    held two hand-rolled resolvers of `technical.database_path` with two
    different default names. A config with the key deleted sent the competitor
    rows to one file and the velocity reads to the other, with no warning
    either side."""

    def test_the_velocity_tracker_resolves_through_the_same_function(self):
        import json
        from src import velocity_module
        with tempfile.TemporaryDirectory() as root:
            config_path = os.path.join(root, "shared_config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump({"technical": {}}, handle)   # the key deleted
            tracker = velocity_module.VelocityTracker(config_path)
            self.assertEqual(
                tracker.db_path,
                database.resolve_db_path({"technical": {}}, config_path))
            self.assertEqual(os.path.basename(tracker.db_path),
                             database.DEFAULT_DATABASE_NAME)

    def test_no_module_carries_the_database_name_as_a_second_literal(self):
        """P4/P32: one home for the name. A second literal is how the two
        resolvers came to disagree in the first place."""
        import glob
        import re
        src = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "src")
        pattern = re.compile(r"""['"]competitor_history\.db['"]""")
        offenders = []
        for path in sorted(glob.glob(os.path.join(src, "*.py"))):
            for lineno, line in enumerate(
                    open(path, encoding="utf-8").read().splitlines(), 1):
                if not pattern.search(line):
                    continue
                if line.strip().startswith("DEFAULT_DATABASE_NAME ="):
                    continue
                offenders.append(f"{os.path.basename(path)}:{lineno}")
        self.assertEqual(offenders, [])

    def test_the_walk_would_see_a_literal_if_one_were_there(self):
        """P21: the single allowed literal must be the one it found."""
        source = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "src", "database.py"),
            encoding="utf-8").read()
        self.assertIn('DEFAULT_DATABASE_NAME = "competitor_history.db"', source)


if __name__ == "__main__":
    unittest.main()
