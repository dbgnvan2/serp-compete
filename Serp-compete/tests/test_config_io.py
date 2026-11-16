"""`config_io` — the GUI writes the file every audit path reads.

Extracted from `orchestrator.py` on 2026-11-16. The orchestrator is a Streamlit
script, so importing it runs the UI; it is at 0% coverage and nothing in it can
be tested. These two functions were the part that could do damage, and each had
a defect:

* the write was not atomic, and a truncated `shared_config.json` is not a loud
  failure — `scoring_logic.load_shared_config` swallows it and returns `{}`, so
  the next audit runs with every threshold at its Python default and an EMPTY
  clinical vocabulary, scoring every page 0 and reporting nothing wrong;
* `json.dump` defaults to `ensure_ascii=True`, and the config is now full of
  provenance notes with em dashes and arrows in them.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from src import config_io

#: A config shaped like the real one: nested blocks, provenance notes with
#: non-ASCII in them, and a key the GUI has no field for.
SAMPLE = {
    "client": {"domain": "livingsystems.ca", "da": 35},
    "technical": {
        "_vacuum_min_medical_source":
            "editorial, uncalibrated — re-set 10 → 6 on 2026-11-15",
        "vacuum_min_medical": 6,
    },
    "clinical": {"tier_1_medical": ["symptom", "diagnosis"]},
    "orchestrator": {"reports_dir": "Serp-compete"},
}


def _config_file(tmp, payload=None):
    path = os.path.join(tmp, "shared_config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload if payload is not None else SAMPLE, f,
                  indent=2, ensure_ascii=False)
    return path


class TestTheWriteIsAtomic(unittest.TestCase):
    """A half-written config is silently catastrophic, not loudly broken."""

    def test_a_failure_mid_write_leaves_the_original_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _config_file(tmp)
            before = open(path, encoding="utf-8").read()

            # Fail after the temp file is open but before the replace.
            with patch.object(config_io.json, "dump",
                              side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    config_io.save_config({**SAMPLE, "new": 1}, path)

            self.assertEqual(open(path, encoding="utf-8").read(), before)

    def test_a_failure_mid_write_leaves_no_temporary_file_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _config_file(tmp)
            with patch.object(config_io.json, "dump",
                              side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    config_io.save_config({**SAMPLE, "new": 1}, path)
            leftovers = [n for n in os.listdir(tmp) if n != "shared_config.json"]
            self.assertEqual(leftovers, [])

    def test_the_temporary_file_is_in_the_target_directory(self):
        """`os.replace` is only atomic within one filesystem, and /tmp is
        often a different one from the repo."""
        seen = {}
        real_mkstemp = config_io.tempfile.mkstemp

        def _spy(*args, **kwargs):
            seen["dir"] = kwargs.get("dir")
            return real_mkstemp(*args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            path = _config_file(tmp)
            with patch.object(config_io.tempfile, "mkstemp", side_effect=_spy):
                config_io.save_config(SAMPLE, path)
            self.assertEqual(os.path.abspath(seen["dir"]), os.path.abspath(tmp))

    def test_the_round_trip_is_lossless(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _config_file(tmp)
            config_io.save_config(SAMPLE, path)
            self.assertEqual(config_io.load_config(path), SAMPLE)


class TestTheCommentsSurviveASave(unittest.TestCase):
    """The config is full of provenance notes with non-ASCII in them."""

    def test_an_em_dash_is_not_escaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _config_file(tmp)
            config_io.save_config(config_io.load_config(path), path)
            raw = open(path, encoding="utf-8").read()
        self.assertIn("—", raw)
        self.assertNotIn("\\u2014", raw)
        self.assertIn("→", raw)

    def test_the_file_ends_with_a_newline(self):
        """So a later diff is one line, not the whole file."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _config_file(tmp)
            config_io.save_config(SAMPLE, path)
            self.assertTrue(open(path, encoding="utf-8").read().endswith("}\n"))


class TestItRefusesToDestroyTheConfig(unittest.TestCase):

    def test_an_empty_mapping_over_a_real_file_is_refused(self):
        """Every caller loads the file and edits one key, so an empty config
        here means something failed upstream — and the one thing worse than
        losing a setting is erasing the config the audit reads."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _config_file(tmp)
            with self.assertRaises(ValueError):
                config_io.save_config({}, path)
            self.assertEqual(config_io.load_config(path), SAMPLE)

    def test_an_empty_mapping_into_a_new_file_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "shared_config.json")
            config_io.save_config({}, path)
            self.assertEqual(config_io.load_config(path), {})

    def test_a_non_mapping_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _config_file(tmp)
            for bad in ([], "config", 7, None):
                with self.assertRaises(TypeError):
                    config_io.save_config(bad, path)
            self.assertEqual(config_io.load_config(path), SAMPLE)

    def test_a_corrupt_file_raises_on_load_rather_than_reading_as_empty(self):
        """`scoring_logic.load_shared_config` swallows this and returns {},
        which is right on the scoring path. Here it must NOT: treating a
        corrupt file as empty and then saving would overwrite it with the one
        key the GUI changed and lose everything else."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "shared_config.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{ truncated")
            with self.assertRaises(json.JSONDecodeError):
                config_io.load_config(path)

    def test_a_missing_file_loads_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                config_io.load_config(os.path.join(tmp, "absent.json")), {})


class TestTheOrchestratorSettingHelper(unittest.TestCase):
    """The read-modify-write the GUI does, in one place."""

    def test_it_changes_one_key_and_keeps_everything_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _config_file(tmp)
            config_io.set_orchestrator_setting("reports_dir", "/new/place", path)
            written = config_io.load_config(path)
        self.assertEqual(written["orchestrator"]["reports_dir"], "/new/place")
        # Everything the GUI has no field for must survive — including the
        # provenance notes and the clinical vocabulary.
        self.assertEqual(written["technical"], SAMPLE["technical"])
        self.assertEqual(written["clinical"], SAMPLE["clinical"])
        self.assertEqual(written["client"], SAMPLE["client"])

    def test_it_creates_the_orchestrator_block_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = {k: v for k, v in SAMPLE.items() if k != "orchestrator"}
            path = _config_file(tmp, payload)
            config_io.set_orchestrator_setting("handoff_source_dir", "/in", path)
            written = config_io.load_config(path)
        self.assertEqual(written["orchestrator"], {"handoff_source_dir": "/in"})
        self.assertEqual(written["technical"], SAMPLE["technical"])

    def test_two_settings_in_turn_both_persist(self):
        """The GUI writes them from two different tabs."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _config_file(tmp)
            config_io.set_orchestrator_setting("reports_dir", "/r", path)
            config_io.set_orchestrator_setting("handoff_source_dir", "/h", path)
            written = config_io.load_config(path)
        self.assertEqual(written["orchestrator"],
                         {"reports_dir": "/r", "handoff_source_dir": "/h"})


class TestTheRealConfigSurvivesARoundTrip(unittest.TestCase):
    """The strongest form of the comment test: the actual file."""

    def test_the_repos_own_config_round_trips_byte_for_byte(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        real = os.path.join(root, "shared_config.json")
        with open(real, encoding="utf-8") as f:
            original = f.read()

        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "shared_config.json")
            with open(copy, "w", encoding="utf-8") as f:
                f.write(original)
            config_io.save_config(config_io.load_config(copy), copy)
            with open(copy, encoding="utf-8") as f:
                rewritten = f.read()

        self.assertEqual(rewritten, original, (
            "saving the repo's own shared_config.json changes it. The GUI does "
            "exactly this on any settings change, so the diff would be the "
            "whole file"))


if __name__ == "__main__":
    unittest.main()


class TestTheOrchestratorCanActuallyImportThis(unittest.TestCase):
    """`run_gui.sh` does `streamlit run Serp-compete/src/orchestrator.py`.

    That puts the SCRIPT's directory (`src/`) on `sys.path`, not
    `Serp-compete/` — so `from src.config_io import …` raises
    `ModuleNotFoundError: No module named 'src'` there. Extracting these
    functions introduced exactly that break, and nothing in the suite could
    have caught it: importing `orchestrator` runs the Streamlit UI, so no test
    imports it.

    This executes the orchestrator's REAL import statements, read from the
    file, under the `streamlit run` path — without running the UI body. It is
    the lesson from `competitor_mining`'s dual-mode imports, which the repo's
    own LEARNINGS records as "assert the import in a test, don't trust that the
    class merely exists".
    """

    ORCHESTRATOR = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "src", "orchestrator.py"))

    def _import_statements(self):
        """Every top-level `import` / `from … import` in the orchestrator."""
        import ast

        with open(self.ORCHESTRATOR, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        out = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                out.append(node)
            elif isinstance(node, ast.Try):
                # The dual-mode guard is a Try at module level.
                if all(isinstance(inner, (ast.Import, ast.ImportFrom))
                       for inner in node.body):
                    out.append(node)
        return out

    def test_the_imports_resolve_with_only_src_on_the_path(self):
        import ast
        import subprocess
        import sys

        statements = self._import_statements()
        self.assertTrue(statements, "no import statements found")
        source = "\n".join(ast.unparse(node) for node in statements)

        # `streamlit` is a GUI-only dependency that `run_gui.sh` installs on
        # demand, so it is not in this environment. Stubbed, because what is
        # under test is whether the REPO's own imports resolve — not whether
        # Streamlit is installed.
        script = "\n".join([
            "import sys, types",
            'sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))',
            # Exactly what `streamlit run <path>` does: the script's directory
            # goes on sys.path, and nothing else from this repo.
            f"sys.path.insert(0, {os.path.dirname(self.ORCHESTRATOR)!r})",
            source,
            'print("ok")',
        ])

        result = subprocess.run([sys.executable, "-c", script],
                                capture_output=True, text=True,
                                cwd=os.path.dirname(os.path.dirname(
                                    os.path.dirname(self.ORCHESTRATOR))))
        self.assertEqual(result.returncode, 0, (
            "the orchestrator's imports do not resolve under `streamlit run`, "
            "so the GUI would fail at startup:\n" + result.stderr))

    def test_the_helpers_are_among_what_it_imports(self):
        """So the test above is actually exercising them."""
        import ast

        names = set()
        for node in self._import_statements():
            for inner in (node.body if isinstance(node, ast.Try) else [node]):
                if isinstance(inner, ast.ImportFrom):
                    names.update(alias.name for alias in inner.names)
        self.assertIn("load_config", names)
        self.assertIn("set_orchestrator_setting", names)
