"""Review chunk Y10 — Tool 2 closes its handles too.

`with sqlite3.connect(path) as conn:` commits but never closes; `closing(
sqlite3.connect(path))` closes but discards the commit. Tool 2 had the first
form behind `DatabaseManager._get_connection` / `VelocityModule.
_get_connection`, and two callers that took the connection bare and never
closed it at all.

Spec: docs/review_2026-11-04/PLAN_Y10_tool2_closes_its_handles.md
"""

import ast
import os
import pathlib
import sqlite3
import subprocess
import tempfile
import unittest

from src import db_connect
from src.database import DatabaseManager
from src.velocity_module import VelocityTracker

_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
_REPO_ROOT = _SRC.parent.parent


def _src_modules():
    """Every tracked module of Tool 2, plus any not committed yet.

    Driven by `git ls-files` rather than a directory walk, so a worktree
    holding another branch is not reported as an offender in this tree
    (the lesson of chunk Y9's cold review, finding 4).
    """
    # `Serp-compete/*.py` as well as `src`: `recalculate_scores.py` is an
    # entry point that constructs `DatabaseManager` against the live database,
    # and the absence claim said nothing about it (cold review, F4).
    # `:(glob)` so that `*` does not cross a directory boundary: a plain
    # pathspec would pull in `Serp-compete/tests/`, which keeps the raw form
    # on purpose to build pre-migration schemas.
    paths = [":(glob)Serp-compete/src/*.py", ":(glob)Serp-compete/*.py"]
    tracked = subprocess.run(["git", "ls-files"] + paths, cwd=_REPO_ROOT,
                             capture_output=True, text=True,
                             check=True).stdout.splitlines()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"] + paths,
        cwd=_REPO_ROOT, capture_output=True, text=True,
        check=True).stdout.splitlines()
    for line in sorted(set(tracked) | set(untracked)):
        rel = pathlib.Path(line)
        yield rel, _REPO_ROOT / rel


def _connect_calls(tree):
    """Every call that opens a connection, in any spelling of the import."""
    aliases = {"sqlite3"}
    bare = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "sqlite3":
                    aliases.add(a.asname or a.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
            for a in node.names:
                if a.name == "connect":
                    bare.add(a.asname or a.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr == "connect"
                and isinstance(func.value, ast.Name)
                and func.value.id in aliases):
            yield node
        elif isinstance(func, ast.Name) and func.id in bare:
            yield node


class TestTheHelperCommitsAndCloses(unittest.TestCase):
    """Criterion 1."""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db = tmp.name
        self.addCleanup(os.unlink, self.db)
        with db_connect.connection(self.db) as conn:
            conn.execute("CREATE TABLE t (v TEXT)")

    def _rows(self):
        with db_connect.connection(self.db) as conn:
            return conn.execute("SELECT v FROM t").fetchall()

    def test_a_write_inside_the_block_is_committed(self):
        with db_connect.connection(self.db) as conn:
            conn.execute("INSERT INTO t VALUES ('kept')")
        self.assertEqual(self._rows(), [("kept",)])

    def test_the_handle_is_closed_on_the_way_out(self):
        with db_connect.connection(self.db) as conn:
            pass
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_an_exception_rolls_the_write_back_and_still_closes(self):
        class _Boom(Exception):
            pass

        with self.assertRaises(_Boom):
            with db_connect.connection(self.db) as conn:
                conn.execute("INSERT INTO t VALUES ('lost')")
                raise _Boom()
        self.assertEqual(self._rows(), [])
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


class TestNoModuleOpensItsOwnConnection(unittest.TestCase):
    """Criterion 2."""

    def test_the_walk_sees_the_source_tree(self):
        names = {rel.name for rel, _ in _src_modules()}
        self.assertIn("database.py", names)
        self.assertIn("velocity_module.py", names)
        self.assertIn("db_connect.py", names)
        self.assertGreaterEqual(len(names), 20, sorted(names))

    def test_no_module_opens_a_connection_outside_the_helper(self):
        offenders = []
        for rel, path in _src_modules():
            if rel.name == "db_connect.py":
                continue        # the one place the pairing is written
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in _connect_calls(tree):
                offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(offenders, [], (
            "a connection opened outside db_connect.connection is committed "
            "but never closed, or closed without its commit: "
            + ", ".join(offenders)))

    def test_neither_factory_is_kept_as_an_alias(self):
        """Two doors is how one of them stays unfixed (P32).

        By AST definition, not by a call spelling: the first version of this
        test needled the source for `_get_connection()`, which an alias
        written as `def _get_connection(self): return self.connection()`
        does not contain, and it asked `hasattr` of one of the two classes
        (cold review, F1).
        """
        for cls in (DatabaseManager, VelocityTracker):
            self.assertFalse(hasattr(cls, "_get_connection"), cls.__name__)
        offenders = []
        for rel, path in _src_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == "_get_connection"):
                    offenders.append(f"{rel}:{node.lineno}")
                elif isinstance(node, ast.Assign):
                    for t in ast.walk(node):
                        if (isinstance(t, ast.Name)
                                and t.id == "_get_connection"):
                            offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(offenders, [], (
            "the old factory is back as a second door: " + ", ".join(offenders)))


class TestARealRunReleasesItsHandles(unittest.TestCase):
    """Criteria 3 and 4 — the quantity the bug is about, at a real call site.

    Chunk Y9's cold review established that a guard on the shape of the call
    cannot stand in for this: it passes while the code is shaped right and
    leaking through a spelling the walk does not know (P30).
    """

    @staticmethod
    def _eeat_score():
        from src.eeat_scorer import EEATScore

        return EEATScore(
            url="https://example.ca/page", scored_at="2026-11-18T00:00:00+00:00",
            experience_signals={}, expertise_signals={},
            authoritativeness_signals={}, trustworthiness_signals={},
            scores={"experience": 0.5}, score_confidence="low")

    @staticmethod
    def _cluster_result():
        from src.cluster_detector import ClusterResult

        return ClusterResult(
            domain="example.ca", pages_analyzed=2, internal_link_graph={},
            hub_candidates=[], cluster_signal="insufficient_data",
            resolution_caveat="test")

    @unittest.skipUnless(os.path.isdir("/dev/fd"),
                         "no /dev/fd to count open handles on")
    def test_a_sequence_of_writes_and_reads_leaves_no_handle_open(self):
        """Every converted site, not only `DatabaseManager`.

        The first version of this test drove `DatabaseManager` alone, which is
        the least leaky third of the change: the two writers that took the
        connection bare and never closed it ran per URL and per domain inside
        the audit loop, and `VelocityTracker` has four sites of its own (cold
        review, F2 — measured at 57 extra descriptors per 50 iterations in the
        pre-fix shape).
        """
        from src.cluster_detector import ClusterDetector
        from src.eeat_scorer import EEATScorer

        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(os.path.join(tmp, "competitor_history.db"))
            config = os.path.join(tmp, "shared_config.json")
            with open(config, "w", encoding="utf-8") as f:
                f.write('{"technical": {"database_path": "velocity.db"}}')
            velocity = VelocityTracker(config)
            eeat, clusters = EEATScorer({}), ClusterDetector({})
            score, result = self._eeat_score(), self._cluster_result()
            # One of everything first, so table creation and any one-off
            # migration is not counted as a leak.
            run_id = db.create_run("warm.ca")
            eeat.save_to_database(db, run_id, score)
            clusters.save_to_database(db, run_id, result)
            velocity.save_market_snapshot("warm.ca", "u", "k", 1, 2, 3, 4,
                                          run_id=run_id)
            velocity.get_market_alerts(run_id)

            before = len(os.listdir("/dev/fd"))
            for i in range(50):
                run_id = db.create_run(f"c{i}.ca")
                db.save_anchor_coverage(run_id, {"total": 1},
                                        detected_at="2026-11-18")
                db.get_anchor_coverage(run_id)
                eeat.save_to_database(db, run_id, score)
                clusters.save_to_database(db, run_id, result)
                velocity.save_market_snapshot(f"c{i}.ca", "u", "k", 1, 2, 3, 4,
                                              run_id=run_id)
                velocity.get_market_alerts(run_id)
            self.assertEqual(len(os.listdir("/dev/fd")), before)

    def test_the_write_is_still_committed_through_the_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(os.path.join(tmp, "competitor_history.db"))
            run_id = db.create_run("example.ca")
            with db.connection() as conn:
                rows = conn.execute(
                    "SELECT client_domain FROM runs WHERE id = ?",
                    (run_id,)).fetchall()
            self.assertEqual(rows, [("example.ca",)])


if __name__ == "__main__":
    unittest.main()
