"""Chunk Y11 — a failing cleanup is not the diagnosis, and the lock wait is chosen.

Spec: docs/review_2026-11-04/PLAN_Y11_a_rollback_is_not_the_diagnosis.md

The Tool 2 half. Tool 1's guards are
`tests/test_y11_a_rollback_is_not_the_diagnosis.py` in `serp-discover`; the
helper is the same in both repos, and the two faults were in both:

* `conn.rollback()` and `conn.close()` were unguarded, so an exception from
  either replaced the exception the caller needed to see — and on the clean
  path, a failing `close()` after a successful `commit()` turned a durable
  write into a reported failure.
* `sqlite3.connect`'s `timeout` — the wait for another writer's lock — was
  left at its default of 5.0, a number nobody chose and nobody could change,
  while the Streamlit orchestrator and an audit write the same file.
"""
import json
import logging
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from src import database, db_connect, velocity_module  # noqa: E402


class _CleanupFails:
    """A connection proxy whose `rollback` or `close` raises.

    `sqlite3.Connection` is a C type with read-only attributes, so the failing
    cleanup cannot be patched onto a real one. Everything else is delegated, so
    the commit, the execute and the transaction are the real database's.
    """

    def __init__(self, conn, failing, error=None):
        self._conn = conn
        self._failing = failing
        self._error = error or sqlite3.OperationalError("disk I/O error")

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def rollback(self):
        if self._failing == "rollback":
            raise self._error
        return self._conn.rollback()

    def close(self):
        if self._failing == "close":
            raise self._error
        return self._conn.close()

    def really_close(self):
        self._conn.close()


def _connecting_with_failing_cleanup(failing, error=None):
    real = sqlite3.connect

    def connect(*args, **kwargs):
        return _CleanupFails(real(*args, **kwargs), failing, error)
    return mock.patch.object(db_connect.sqlite3, "connect", side_effect=connect)


class TestACleanupFailureDoesNotReplaceTheDiagnosis(unittest.TestCase):

    def _db(self):
        return os.path.join(tempfile.mkdtemp(), "t.db")

    def test_a_failing_rollback_leaves_the_blocks_exception_intact(self):
        db_path = self._db()
        with _connecting_with_failing_cleanup("rollback"):
            with self.assertRaises(ValueError) as caught:
                with db_connect.connection(db_path):
                    raise ValueError("the real diagnosis")
        self.assertEqual(str(caught.exception), "the real diagnosis")

    def test_a_failing_close_leaves_the_blocks_exception_intact(self):
        db_path = self._db()
        with _connecting_with_failing_cleanup("close"):
            with self.assertRaises(ValueError) as caught:
                with db_connect.connection(db_path):
                    raise ValueError("the real diagnosis")
        self.assertEqual(str(caught.exception), "the real diagnosis")

    def test_a_failing_close_does_not_fail_a_committed_write(self):
        """The commit has already succeeded, so the row is on disk; raising
        from `close()` would make the caller record the write as failed."""
        db_path = self._db()
        with db_connect.connection(db_path) as conn:
            conn.execute("CREATE TABLE t (x)")
        with _connecting_with_failing_cleanup("close"):
            with db_connect.connection(db_path) as conn:
                conn.execute("INSERT INTO t VALUES (1)")
            conn.really_close()
        with db_connect.connection(db_path) as conn:
            self.assertEqual(conn.execute("SELECT x FROM t").fetchall(), [(1,)])

    def test_a_cleanup_failure_is_logged_not_swallowed(self):
        db_path = self._db()
        with self.assertLogs(db_connect.logger, level=logging.ERROR) as logged:
            with _connecting_with_failing_cleanup("rollback"):
                with self.assertRaises(ValueError):
                    with db_connect.connection(db_path):
                        raise ValueError("the real diagnosis")
        joined = "\n".join(logged.output)
        self.assertIn("roll back", joined)
        self.assertIn("disk I/O error", joined)

    def test_an_interrupt_during_cleanup_still_reaches_the_user(self):
        """`_safely` catches `Exception`, not `BaseException`: a Ctrl-C while
        the rollback runs is the user."""
        db_path = self._db()
        with _connecting_with_failing_cleanup("rollback", KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                with db_connect.connection(db_path):
                    raise ValueError("overtaken by the interrupt")


class TestTheLockWaitIsRead(unittest.TestCase):

    def test_an_absent_key_leaves_the_documented_default(self):
        for config in ({}, None, {"technical": {}}, {"technical": "nonsense"}):
            with self.subTest(config=config):
                self.assertEqual(db_connect.lock_timeout_from_config(config),
                                 db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS)

    def test_the_default_is_sqlite3s_own_so_the_change_is_not_a_behaviour_change(self):
        self.assertEqual(db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS, 5.0)

    def test_a_configured_wait_is_used(self):
        self.assertEqual(db_connect.lock_timeout_from_config(
            {"technical": {"db_lock_timeout_seconds": 12.5}}), 12.5)

    def test_a_non_positive_or_non_numeric_wait_is_refused_and_reported(self):
        for value in (0, -3, "soon", True, [5]):
            with self.subTest(value=value):
                with self.assertLogs(db_connect.logger, level=logging.WARNING):
                    resolved = db_connect.lock_timeout_from_config(
                        {"technical": {"db_lock_timeout_seconds": value}})
                self.assertEqual(resolved,
                                 db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS)


class TestTheGatewaysPassTheConfiguredWait(unittest.TestCase):
    """Consequence, not inspection: another connection holds the write lock,
    and the wait before `database is locked` is the configured number."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.db_path = os.path.join(self.directory, "t.db")

    def _hold_the_write_lock(self):
        holder = sqlite3.connect(self.db_path, timeout=0.05)
        holder.execute("BEGIN EXCLUSIVE")
        self.addCleanup(holder.close)

    def _blocked_write_seconds(self, manager):
        started = time.monotonic()
        with self.assertRaises(sqlite3.OperationalError):
            with manager.connection() as conn:
                conn.execute("INSERT INTO runs (client_domain) VALUES ('x')")
        return time.monotonic() - started

    def test_database_manager_waits_the_configured_time(self):
        short = database.DatabaseManager(
            self.db_path, config={"technical": {"db_lock_timeout_seconds": 0.2}})
        long = database.DatabaseManager(
            self.db_path, config={"technical": {"db_lock_timeout_seconds": 1.4}})
        self._hold_the_write_lock()
        # Derived from the two configured numbers, not a floor picked to pass
        # (P29): 1.4 - 0.2 is 1.2, and half of that is a wide margin for a
        # loaded machine while still failing a gateway that ignores the config.
        self.assertGreater(self._blocked_write_seconds(long)
                           - self._blocked_write_seconds(short), 0.6)

    def test_velocity_tracker_waits_the_configured_time(self):
        def tracker(seconds):
            path = os.path.join(tempfile.mkdtemp(), "shared_config.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"technical": {"database_path": self.db_path,
                                         "db_lock_timeout_seconds": seconds}},
                          handle)
            return velocity_module.VelocityTracker(path)

        short, long = tracker(0.2), tracker(1.4)
        self.assertEqual(short.lock_timeout, 0.2)
        self.assertEqual(long.lock_timeout, 1.4)
        holder = sqlite3.connect(self.db_path, timeout=0.05)
        holder.execute("BEGIN EXCLUSIVE")
        self.addCleanup(holder.close)

        def blocked(instance):
            started = time.monotonic()
            with self.assertRaises(sqlite3.OperationalError):
                with instance.connection() as conn:
                    conn.execute(
                        "INSERT INTO market_history (domain) VALUES ('x')")
            return time.monotonic() - started

        self.assertGreater(blocked(long) - blocked(short), 0.6)

    def test_both_gateways_read_the_wait_from_the_one_rule(self):
        """Not a second validator at each gateway (P32)."""
        with mock.patch.object(db_connect, "lock_timeout_from_config",
                               return_value=3.25) as rule:
            manager = database.DatabaseManager(self.db_path, config={})
        self.assertEqual(manager.lock_timeout, 3.25)
        rule.assert_called_once()


class TestAnUnreadableConfigDoesNotFailConstruction(unittest.TestCase):
    """`DatabaseManager.__init__` reads the config for the wait even when the
    caller supplied its own `db_path`, and `load_shared_config` raises on a
    corrupt file — so without a tolerant read this chunk would newly fail
    construction for a caller that never reads the config at all (P34, cold
    review of chunk Y11). The file's real readers still raise where they
    are."""

    def test_a_corrupt_shared_config_gives_the_default_wait_and_a_warning(self):
        broken = os.path.join(tempfile.mkdtemp(), "shared_config.json")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with mock.patch.object(database, "SHARED_CONFIG_PATH", broken):
            with self.assertLogs(level=logging.WARNING):
                self.assertEqual(database.config_for_lock_timeout(), {})
            manager = database.DatabaseManager(
                os.path.join(tempfile.mkdtemp(), "t.db"))
        self.assertEqual(manager.lock_timeout,
                         db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS)

    def test_the_editorial_readers_still_raise_on_a_corrupt_file(self):
        """The tolerant read is for the wait alone: a caller reading a scoring
        threshold must not silently score against a default."""
        broken = os.path.join(tempfile.mkdtemp(), "shared_config.json")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with mock.patch.object(database, "SHARED_CONFIG_PATH", broken):
            with self.assertRaises(Exception):
                database.load_shared_config()


class TestTheShippedConfigCarriesTheKey(unittest.TestCase):

    def test_shared_config_has_the_key_and_the_documented_default(self):
        """A setting nobody can find is not configurable (P4). The shipped
        value is sqlite3's own default, so adding the key changed no
        behaviour."""
        with open(database.SHARED_CONFIG_PATH, encoding="utf-8") as handle:
            shipped = json.load(handle)
        section, key = db_connect.LOCK_TIMEOUT_KEY
        self.assertEqual(shipped[section][key],
                         db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS)
        self.assertIn(f"_{key}_source", shipped[section],
                      "every threshold in this file records where it came from")


if __name__ == "__main__":
    unittest.main()
