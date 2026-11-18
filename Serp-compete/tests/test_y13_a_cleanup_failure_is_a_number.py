"""Chunk Y13 — a cleanup failure is a number, not a line on stderr (Tool 2).

Tool 2's audit opens and closes a connection inside its per-domain loop, so a
`close()` that fails once has usually failed every time, each one holding a
file handle open. Chunk Y11 stopped that failure replacing the exception that
caused it; it still went only to the log.

Spec: docs/review_2026-11-04/PLAN_Y13_a_cleanup_failure_is_a_number.md
"""

import ast
import io
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import pytest

from src.reporting import ReportGenerator

from src import db_connect


_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "src")


class _CleanupFails:
    """A connection proxy whose `rollback` or `close` raises.

    `sqlite3.Connection` is a C type, so a failing cleanup cannot be patched
    onto a real one.
    """

    def __init__(self, conn, failing):
        self._conn = conn
        self._failing = failing

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def rollback(self):
        if self._failing == "rollback":
            raise sqlite3.OperationalError("disk I/O error")
        return self._conn.rollback()

    def close(self):
        if self._failing == "close":
            raise sqlite3.OperationalError("disk I/O error")
        return self._conn.close()


def _connecting_with_failing_cleanup(failing):
    real = sqlite3.connect

    def connect(*args, **kwargs):
        return _CleanupFails(real(*args, **kwargs), failing)
    return mock.patch.object(db_connect.sqlite3, "connect",
                             side_effect=connect)


class _TallyIsolation(unittest.TestCase):

    def setUp(self):
        self._before = db_connect.cleanup_failures()
        db_connect.reset_cleanup_failures()

    def tearDown(self):
        db_connect.reset_cleanup_failures()
        db_connect._CLEANUP_FAILURES.update(self._before)

    def _db(self):
        return os.path.join(tempfile.mkdtemp(), "t.db")


class TestAFailedCleanupIsCounted(_TallyIsolation):

    def test_a_failing_close_is_counted_every_time_it_fails(self):
        db_path = self._db()
        with _connecting_with_failing_cleanup("close"):
            for _ in range(3):
                with db_connect.connection(db_path) as conn:
                    conn.execute("CREATE TABLE IF NOT EXISTS t (a)")
        self.assertEqual(db_connect.cleanup_failure_count(), 3)

    def test_a_failing_rollback_is_counted_as_its_own_step(self):
        db_path = self._db()
        with _connecting_with_failing_cleanup("rollback"):
            with self.assertRaises(ValueError):
                with db_connect.connection(db_path) as conn:
                    conn.execute("CREATE TABLE t (a)")
                    raise ValueError("the caller's own failure")
        self.assertEqual(db_connect.cleanup_failures(),
                         {("roll back", db_path): 1})

    def test_a_clean_run_counts_nothing_and_warns_about_nothing(self):
        db_path = self._db()
        with db_connect.connection(db_path) as conn:
            conn.execute("CREATE TABLE t (a)")
        self.assertEqual(db_connect.cleanup_failure_count(), 0)
        self.assertIsNone(db_connect.cleanup_failure_warning())

    def test_the_tally_can_be_reset_for_the_next_run(self):
        db_connect._CLEANUP_FAILURES[("close", "/x.db")] = 4
        db_connect.reset_cleanup_failures()
        self.assertEqual(db_connect.cleanup_failure_count(), 0)


class TestEveryEntryPointSaysItSomehow(_TallyIsolation):
    """Only `run_audit` renders the tally into an artefact; `recalculate_scores`
    and the other scripts open the database through the same helper and write
    no briefing, so the exit hook is their floor (P5, the cold review of this
    chunk)."""

    def test_a_script_with_no_briefing_still_says_it_at_exit(self):
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 1
        said = []
        with mock.patch.object(db_connect, "report_cleanup_failures",
                               side_effect=lambda **kw: said.append(1)):
            db_connect._report_cleanup_failures_at_exit()
        self.assertEqual(said, [1])

    def test_the_exit_hook_does_not_repeat_what_was_reported(self):
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 1
        db_connect.report_cleanup_failures(printer=lambda line: None)
        again = []
        with mock.patch.object(db_connect, "report_cleanup_failures",
                               side_effect=lambda **kw: again.append(1)):
            db_connect._report_cleanup_failures_at_exit()
        self.assertEqual(again, [], "the tally was reported twice")

    def test_the_exit_hook_is_registered_at_import(self):
        """P29 — the two tests above call the hook directly, which does not
        prove it runs in production. `atexit`'s registry is not readable, so
        this asserts the module-level registration itself."""
        tree = ast.parse(io.open(os.path.join(_SRC, "db_connect.py"),
                                 encoding="utf-8").read())
        registered = [n for n in tree.body
                      if isinstance(n, ast.Expr)
                      and isinstance(n.value, ast.Call)
                      and isinstance(n.value.func, ast.Attribute)
                      and n.value.func.attr == "register"
                      and n.value.args
                      and isinstance(n.value.args[0], ast.Name)
                      and n.value.args[0].id
                      == "_report_cleanup_failures_at_exit"]
        self.assertEqual(len(registered), 1)


class TestTheTallyBecomesASentence(_TallyIsolation):

    def test_the_warning_carries_the_count_and_the_step(self):
        db_connect._CLEANUP_FAILURES[("close", "/a.db")] = 3
        db_connect._CLEANUP_FAILURES[("roll back", "/a.db")] = 1
        text = db_connect.cleanup_failure_warning()
        self.assertIn("4 database cleanup step(s) failed", text)
        self.assertIn("3 x close", text)
        self.assertIn("1 x roll back", text)

    def test_the_same_step_on_two_databases_is_one_number(self):
        db_connect._CLEANUP_FAILURES[("close", "/a.db")] = 1
        db_connect._CLEANUP_FAILURES[("close", "/b.db")] = 2
        self.assertIn("3 x close", db_connect.cleanup_failure_warning())

    def test_a_failed_close_says_the_runs_figures_still_stand(self):
        """A close fails after the commit, so the data is durable."""
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 1
        text = db_connect.cleanup_failure_warning()
        self.assertIn("writes were committed and its figures stand", text)
        self.assertNotIn("abandoned its transaction", text)

    def test_a_failed_rollback_does_not_claim_the_figures_stand(self):
        """A counted rollback means a block raised and its transaction was
        abandoned. The first version told that reader their figures stood,
        which is the opposite of what happened (P6, this chunk's cold
        review). The path is live: `run_audit` catches the GSC step's
        exceptions and carries on."""
        db_connect._CLEANUP_FAILURES[(db_connect.ROLL_BACK, "/a.db")] = 1
        text = db_connect.cleanup_failure_warning()
        self.assertIn("abandoned its transaction", text)
        self.assertNotIn("writes were committed and its figures stand", text)

    def test_the_sentence_has_the_placeholders_it_needs(self):
        """Tool 1 keeps these words in `serp_vocab.yml` under `db_cleanup`;
        chunk Y17 gave this repo `briefing_messages.json`, which holds the same
        section, so the sentence is no longer a Python constant here. This test
        cannot see the other repo — it checks the shape this one needs,
        asserted on the PLACEHOLDERS rather than the prose, so rewording the
        sentence in the file does not break it."""
        from src.briefing_messages import Messages

        warning = Messages().raw("db_cleanup.warning")
        self.assertIsNotNone(warning, "db_cleanup.warning is missing")
        self.assertIn("{failures}", warning)
        self.assertIn("{detail}", warning)
        self.assertIn("{consequence}", warning)
        item = Messages().raw("db_cleanup.detail_item")
        self.assertIsNotNone(item, "db_cleanup.detail_item is missing")
        self.assertIn("{count}", item)
        self.assertIn("{what}", item)


class TestTheTallyReachesTheBriefing:
    """A real `run_audit` against fakes, through the harness
    `test_main_run_coverage.py` already uses: the briefing is the artefact, so
    the test reads the markdown rather than the source (the cold review of
    this chunk: the first version asserted AST dumps while a harness that
    runs the real thing was already in the repo)."""

    def test_the_coverage_block_carries_the_cleanup_warning(
            self, tmp_path, monkeypatch):
        from tests.test_main_run_coverage import (
            _FakeAuditor, _prepare, _run_audit_with_fakes, NO_MOZ, BLOCKED)
        config, config_path, db_path, handoff_path = _prepare(
            tmp_path, monkeypatch)
        auditor = _FakeAuditor(error_urls={f"https://{NO_MOZ}/couples"},
                               blocked_urls={f"https://{BLOCKED}/couples"})
        # A cleanup that failed mid-run: injected into the tally the audit
        # reads, not simulated by patching the reader.
        real_reset = db_connect.reset_cleanup_failures

        def reset_then_fail():
            real_reset()
            db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, db_path)] = 7
        with mock.patch.object(db_connect, "reset_cleanup_failures",
                               side_effect=reset_then_fail):
            markdowns = _run_audit_with_fakes(
                tmp_path, db_path, config, config_path, handoff_path, auditor)
        db_connect.reset_cleanup_failures()
        assert markdowns, "the audit produced no briefing"
        assert "**Database cleanup:**" in markdowns[-1]
        assert "7 database cleanup step(s) failed" in markdowns[-1]

    def test_a_clean_run_says_nothing_about_cleanup(
            self, tmp_path, monkeypatch):
        from tests.test_main_run_coverage import (
            _FakeAuditor, _prepare, _run_audit_with_fakes)
        config, config_path, db_path, handoff_path = _prepare(
            tmp_path, monkeypatch)
        markdowns = _run_audit_with_fakes(
            tmp_path, db_path, config, config_path, handoff_path,
            _FakeAuditor())
        assert markdowns
        assert "Database cleanup" not in markdowns[-1]

    def test_a_failure_after_the_briefing_still_reaches_the_console(
            self, tmp_path, monkeypatch, capsys):
        """The briefing's snapshot is taken before the report generator's own
        database reads, so `run_audit` reports the final tally in a `finally`
        — an abort and the report's own phase are both covered (the cold
        review of this chunk)."""
        from tests.test_main_run_coverage import (
            _FakeAuditor, _prepare, _run_audit_with_fakes)
        config, config_path, db_path, handoff_path = _prepare(
            tmp_path, monkeypatch)

        real_summary = ReportGenerator.generate_summary

        def summary_then_fail(self, *a, **kw):
            content = real_summary(self, *a, **kw)
            db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, db_path)] = 4
            return content
        with mock.patch.object(ReportGenerator, "generate_summary",
                               summary_then_fail):
            _run_audit_with_fakes(tmp_path, db_path, config, config_path,
                                  handoff_path, _FakeAuditor())
        db_connect.reset_cleanup_failures()
        out = capsys.readouterr()
        assert "4 database cleanup step(s) failed" in (out.out + out.err)

    def test_an_abort_before_the_briefing_still_reports(
            self, tmp_path, monkeypatch, capsys):
        import src.main as main
        db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 2

        def fail():
            db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 3
            raise RuntimeError("the run's own failure")
        with mock.patch.object(main, "pre_flight_check", side_effect=fail):
            with pytest.raises(RuntimeError):
                main.run_audit()
        db_connect.reset_cleanup_failures()
        out = capsys.readouterr()
        assert "3 database cleanup step(s) failed" in (out.out + out.err)


class TestTheAuditWiresItUp(unittest.TestCase):
    """What the consequence tests above cannot show: that the read is not
    moved back to where `run_coverage` is built, which is before the audit's
    last domain."""

    def test_the_tally_is_read_after_the_domain_loop(self):
        source = io.open(os.path.join(_SRC, "main.py"),
                         encoding="utf-8").read()
        lines = source.splitlines()
        def line_of(fragment):
            for i, line in enumerate(lines, start=1):
                if fragment in line:
                    return i
            raise AssertionError(f"not found: {fragment}")
        built = line_of('run_coverage = {')
        read = line_of('run_coverage["db_cleanup"] = db_connect')
        self.assertGreater(read, built,
                           "the tally is read where run_coverage is built, so "
                           "a failure in the last domains is not in it")


if __name__ == "__main__":
    unittest.main()
