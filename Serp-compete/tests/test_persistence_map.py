"""The persistence map must describe the schema that exists.

Purpose: stop `docs/DATA_PERSISTENCE_MAP_v3.md` drifting from `database.py`.
Doc:     docs/DATA_PERSISTENCE_MAP_v3.md §1

Why this guard exists: that document was written on 2026-05-02 as a design doc
and no chunk updated it. By 2026-11-16 it listed 10 of the 22 tables that exist,
marked `market_gaps` "Active" although nothing has ever written it, and
described `semantic_audits` — the table every run reads and writes — as
"Deprecated; use traffic_magnets" while documenting the never-written
`semantic_audit_results` as a live v3 feature. Someone looking for where a
score was stored was sent to an empty table.

A schema doc nobody can trust is worse than none, and nothing in a test suite
noticed for six months. These are deliberately shallow checks — every table is
named, and a table with no writer is declared as such — because a deep
column-by-column comparison would be a second copy of the schema, which is the
failure mode this file is here to prevent, not a cure for it.
"""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
import unittest

MAP_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "docs", "DATA_PERSISTENCE_MAP_v3.md"))

#: Tables created by `_create_tables` that nothing in `src/` writes or reads.
#: They must be declared as such in §1.4 rather than listed as live, or quietly
#: left out. Removing one from this set means either it got a writer (move it
#: into the inventory) or it was dropped (remove it from the doc).
UNUSED_TABLES = {"market_gaps", "semantic_audit_results"}


def _live_schema():
    """Every table a fresh database actually gets, including velocity's."""
    import json

    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "schema.db")
        config_path = os.path.join(tmp, "shared_config.json")
        with open(config_path, "w") as f:
            json.dump({"technical": {"database_path": db_path},
                       "risk_signals": {}}, f)

        from src.database import DatabaseManager
        from src.velocity_module import VelocityTracker

        DatabaseManager(db_path)
        # market_history lives in velocity_module, not database.py — a reader of
        # the doc does not care which module created it.
        VelocityTracker(config_path)

        with sqlite3.connect(db_path) as conn:
            return {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")}


def _documented_tables(text):
    """Table names the map mentions in backticks, including struck-through ones.

    Deliberately broad — it also catches column and function names — so it can
    only be used to ask "is this table mentioned anywhere?", never "is this
    name a table?". For the latter, use :func:`_inventory_rows`.
    """
    return set(re.findall(r"~?~?`([a-z_][a-z0-9_]*)`~?~?", text))


def _inventory_section(text):
    """§1, where the map states what the schema is."""
    return text.split("## 2. The original v3 design")[0]


def _inventory_rows(text):
    """`{table name: its row}` for every row of §1's tables.

    The table name is the FIRST backticked name in the row, because that is the
    row's "Table" column; later cells hold column names.
    """
    rows = {}
    for line in _inventory_section(text).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("|---"):
            continue
        first_cell = stripped.strip("|").split("|")[0]
        match = re.search(r"~?~?`([a-z_][a-z0-9_]*)`~?~?", first_cell)
        if match:
            rows[match.group(1)] = stripped
    return rows


class TestPersistenceMapMatchesTheSchema(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(MAP_PATH, encoding="utf-8") as f:
            cls.text = f.read()
        cls.live = _live_schema()
        cls.documented = _documented_tables(cls.text)

    def test_every_table_that_exists_is_named_in_the_map(self):
        missing = sorted(self.live - self.documented)
        self.assertEqual(missing, [], (
            "These tables exist in a fresh database and are not mentioned in "
            "docs/DATA_PERSISTENCE_MAP_v3.md. Add them to §1 — a schema doc "
            f"that omits tables sends readers to the wrong place: {missing}"))

    def test_the_map_does_not_describe_tables_that_do_not_exist(self):
        """Every row of §1 must name a table a fresh database really has.

        Reads the rows' first column only — the "Table" column — so a column
        name in backticks in a later cell cannot trip it.
        """
        phantom = sorted(set(_inventory_rows(self.text)) - self.live)
        self.assertEqual(phantom, [], (
            "The §1 inventory has a row for each of these, but a fresh database "
            f"has no such table: {phantom}"))

    def test_the_unused_tables_are_declared_unused(self):
        """A documented table implies a place to look for data (P21)."""
        section = self.text.split("### 1.4")[1].split("\n## ")[0]
        for table in sorted(UNUSED_TABLES):
            self.assertIn(table, section, (
                f"`{table}` is created but never written, and §1.4 is where the "
                f"map says so. If it now has a writer, move it into the "
                f"inventory and drop it from UNUSED_TABLES here."))

    def test_the_unused_tables_really_have_no_writer(self):
        """The mirror of the test above: if one of these gains a writer, the
        doc's §1.4 becomes a lie and this is what catches it."""
        src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        sources = []
        for name in os.listdir(src):
            if name.endswith(".py"):
                with open(os.path.join(src, name), encoding="utf-8") as f:
                    sources.append(f.read())
        joined = "\n".join(sources)
        for table in sorted(UNUSED_TABLES):
            self.assertNotRegex(
                joined, rf"INSERT(?:\s+OR\s+\w+)?\s+INTO\s+{table}\b",
                f"`{table}` now has a writer, so docs/DATA_PERSISTENCE_MAP_v3.md "
                f"§1.4 ('created but never used') is out of date.")

    def test_the_live_tables_are_not_called_deprecated(self):
        """The specific error this guard was written for: `semantic_audits` and
        `competitor_metrics` are read and written on every run, and the map
        called both deprecated for six months."""
        rows = _inventory_rows(self.text)
        for table in ("semantic_audits", "competitor_metrics"):
            self.assertIn(table, rows, f"no §1 inventory row for `{table}`")
            self.assertIn("Active", rows[table], (
                f"`{table}` is written and read on every run but its inventory "
                f"row does not say Active: {rows[table]}"))


if __name__ == "__main__":
    unittest.main()


class TestTheGuardCanActuallyFail(unittest.TestCase):
    """A guard that cannot fail is worse than none (the repo's own rule).

    Each case feeds the helpers the doctored text that the real failure would
    produce, so the detection logic is exercised rather than trusted.
    """

    def test_a_missing_table_is_detected(self):
        live = {"runs", "brand_new_table"}
        documented = _documented_tables("the map mentions `runs` and nothing else")
        self.assertEqual(sorted(live - documented), ["brand_new_table"])

    def test_a_phantom_table_row_is_detected(self):
        doctored = ("## 1. Table inventory\n"
                    "| Table | Purpose |\n|---|---|\n"
                    "| `table_that_never_existed` | something | \n"
                    "## 2. The original v3 design\n")
        self.assertIn("table_that_never_existed", _inventory_rows(doctored))

    def test_a_column_name_in_a_later_cell_is_not_read_as_a_table(self):
        """The first version of this guard flagged 35 column names as phantom
        tables, which would have made it useless noise."""
        doctored = ("## 1. Table inventory\n"
                    "| Table | Key columns |\n|---|---|\n"
                    "| `runs` | `run_id`, `client_domain` |\n"
                    "## 2. The original v3 design\n")
        self.assertEqual(list(_inventory_rows(doctored)), ["runs"])

    def test_a_live_table_marked_deprecated_is_detected(self):
        doctored = ("## 1. Table inventory\n"
                    "| Table | Purpose | Status |\n|---|---|---|\n"
                    "| `semantic_audits` | scores | Deprecated |\n"
                    "## 2. The original v3 design\n")
        self.assertNotIn("Active", _inventory_rows(doctored)["semantic_audits"])

    def test_the_section_split_survives_a_markdown_table(self):
        """`.split("---")` truncated §1.4 at the table's own `|---|` separator,
        so the declaration test passed on text it had never seen."""
        doctored = ("### 1.4 Created but never used\n"
                    "| Table | Reality |\n|---|---|\n"
                    "| `market_gaps` | never written |\n"
                    "\n## 3. Next section\n")
        section = doctored.split("### 1.4")[1].split("\n## ")[0]
        self.assertIn("market_gaps", section)
