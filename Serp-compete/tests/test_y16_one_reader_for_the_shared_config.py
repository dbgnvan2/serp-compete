"""Chunk Y16 — one reader for `shared_config.json`.

`shared_config.json` is the editorial config both tools share: scoring
weights, penalty thresholds, position thresholds, risk signals, the database
path, the clinical vocabulary tiers. Tool 2 had **three** functions named
`load_shared_config` doing three different things with the same file, and
**five** modules each building the path to it from their own `__file__`.

Two faults followed, and the second was the serious one.

1. The same corrupt file produced three outcomes depending on which module
   read it first: `database`'s raised, `main`'s raised, and
   `scoring_logic`'s swallowed every exception and returned `{}`.

2. `scoring_logic` read the file **at import time** into module globals, and
   `WEIGHTS`, `PENALTY_CFG` and the three vocabulary tiers were derived from
   it. So a `shared_config.json` with a trailing comma meant every competitor
   in the run was scored with the Python fallback weights and an EMPTY
   clinical vocabulary — page scores of 0, a completed run, a briefing whose
   numbers reconciled with nothing the owner had configured, and nothing
   logged, because the `except Exception: pass` was the only place that could
   have said so (P40 + P16, and the same shape as the bind-time trap of
   review chunk Y4).

The guards here are consequences: a corrupt file on disk, then what a score is
computed from and what the run says about it. The import-time read needs a
guard that survives the module already being imported, so it runs in a
subprocess.

Spec: docs/review_2026-11-04/PLAN_Y16_one_reader_for_the_shared_config.md
"""
from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
PACKAGE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.abspath(os.path.join(PACKAGE_ROOT, ".."))
CONFIG = os.path.join(ROOT, "shared_config.json")

from src import scoring_logic

BROKEN = '{"technical": {"scoring_weights": {,}\n'


def _config() -> dict:
    with io.open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def _run(code: str) -> subprocess.CompletedProcess:
    """Run *code* in a fresh interpreter with the package importable."""
    environment = dict(os.environ, PYTHONPATH=PACKAGE_ROOT)
    return subprocess.run([sys.executable, "-c", code], cwd=PACKAGE_ROOT,
                          capture_output=True, text=True, timeout=180,
                          env=environment)


class TestThereIsOneReader(unittest.TestCase):

    def test_only_config_io_defines_a_reader(self):
        """Three functions named `load_shared_config` with three different
        failure behaviours. `database.load_shared_config` keeps its name
        because every test that stubs the config patches it, but it must
        delegate rather than open the file itself."""
        definitions = []
        for name in sorted(os.listdir(SRC)):
            if not name.endswith(".py"):
                continue
            tree = ast.parse(io.open(os.path.join(SRC, name),
                                     encoding="utf-8").read())
            for node in ast.walk(tree):
                if (isinstance(node, ast.FunctionDef)
                        and node.name in ("load_shared_config",
                                          "load_config")):
                    # A body that opens a file is a reader; one that calls the
                    # reader is a delegate.
                    opens = any(
                        isinstance(sub, ast.Call)
                        and getattr(sub.func, "id", None) == "open"
                        for sub in ast.walk(node))
                    if opens:
                        definitions.append(f"{name}:{node.name}")
        # P29 — the walk asserts it found the thing it is about.
        self.assertIn("config_io.py:load_config", definitions, definitions)
        self.assertEqual(
            definitions, ["config_io.py:load_config"],
            "more than one module opens shared_config.json for itself: "
            f"{definitions}")

    def test_the_path_reaches_only_the_one_reader(self):
        """A reader does not have to be called `load_shared_config` to be a
        fourth reader: `gsc_performance` passed this path to its own
        `_load_json`, which returned `{}` for a file it could not open. So the
        test above, which looks for functions by name, passed while a module
        still read the file for itself."""
        # `exists` and `warning` do not read the file. `VelocityTracker`
        # takes the path and reads it through the one reader, which this file
        # cannot see — `test_the_velocity_tracker_delegates_its_read` is that
        # check.
        allowed = {"load_config", "exists", "warning", "VelocityTracker"}
        offenders = []
        for name in sorted(os.listdir(SRC)):
            if not name.endswith(".py") or name == "config_io.py":
                continue
            tree = ast.parse(io.open(os.path.join(SRC, name),
                                     encoding="utf-8").read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                mentions = any(
                    isinstance(arg, ast.Name)
                    and arg.id == "SHARED_CONFIG_PATH"
                    for arg in node.args)
                if not mentions:
                    continue
                callee = getattr(node.func, "attr", None) or getattr(
                    node.func, "id", None)
                if callee not in allowed:
                    offenders.append(f"{name}:{node.lineno} -> {callee}")
        self.assertEqual(
            offenders, [],
            "these modules hand shared_config.json to something other than "
            f"the one reader: {offenders}")

    def test_the_velocity_tracker_delegates_its_read(self):
        """A fifth copy of the same body: `{}` for an absent file, a raise for
        a corrupt one — `config_io.load_config`'s contract, written out
        again."""
        from src.velocity_module import VelocityTracker
        with unittest.mock.patch("src.config_io.load_config",
                                 return_value={}) as reader:
            VelocityTracker.__dict__["_load_config"](None, "/some/path.json")
        reader.assert_called_once_with("/some/path.json")

    def test_the_file_is_named_in_exactly_one_place(self):
        """Five modules each built the same path from their own `__file__`.

        Asserting that the five AGREE is not the property: they did agree —
        `abspath(join(dirname(__file__), "..", "..", "shared_config.json"))`
        and `join(PROJECT_ROOT, "shared_config.json")` resolve to the same
        string — so an equality test passes with all five definitions back in
        place. That was this guard until the cold review of Y16 found it
        vacuous for its own criterion (F4). The property is that the NAME
        appears once."""
        named_in = []
        for name in sorted(os.listdir(SRC)):
            if not name.endswith(".py"):
                continue
            source = io.open(os.path.join(SRC, name), encoding="utf-8").read()
            named_in += [name] * source.count('"shared_config.json"')
        self.assertEqual(
            named_in, ["config_io.py"],
            "`shared_config.json` is named outside config_io.py, so a module "
            f"builds its own path to it again: {named_in}")

    def test_every_module_takes_the_path_from_the_one_definition(self):
        from src import config_io, database, main, gsc_performance, orchestrator
        for module in (database, main, gsc_performance, orchestrator):
            with self.subTest(module.__name__):
                self.assertIs(module.SHARED_CONFIG_PATH,
                              config_io.SHARED_CONFIG_PATH)
        self.assertTrue(os.path.isfile(config_io.SHARED_CONFIG_PATH))

    def test_the_delegate_reads_through_the_one_reader(self):
        from src import database
        with unittest.mock.patch("src.config_io.load_config",
                                 return_value={"marker": 1}) as reader:
            self.assertEqual(database.load_shared_config(), {"marker": 1})
        reader.assert_called_once()

    def test_a_corrupt_file_raises_for_every_editorial_reader(self):
        """One rule, not three: a caller reading an editorial threshold must
        not silently score against a default."""
        from src import database, scoring_logic

        path = os.path.join(self.directory, "shared_config.json")
        io.open(path, "w", encoding="utf-8").write(BROKEN)
        with unittest.mock.patch("src.config_io.SHARED_CONFIG_PATH", path), \
                unittest.mock.patch.object(database, "SHARED_CONFIG_PATH",
                                           path):
            for label, call in (("database", database.load_shared_config),
                                ("scoring_logic", scoring_logic.shared_config),
                                ("weights", scoring_logic.weights),
                                ("penalties", scoring_logic.penalty_cfg),
                                ("vocabulary", scoring_logic.clinical_tiers)):
                with self.subTest(label):
                    with self.assertRaises(json.JSONDecodeError):
                        call()

    def test_the_lock_wait_is_the_one_named_exception(self):
        """`config_for_lock_timeout` catches and logs, because the lock wait is
        not an editorial threshold and `DatabaseManager.__init__` reads it even
        for a caller that supplied its own `db_path` (chunk Y11)."""
        from src import database

        path = os.path.join(self.directory, "shared_config.json")
        io.open(path, "w", encoding="utf-8").write(BROKEN)
        with unittest.mock.patch.object(database, "SHARED_CONFIG_PATH", path), \
                unittest.mock.patch("src.config_io.SHARED_CONFIG_PATH", path):
            with self.assertLogs(level="WARNING") as logs:
                self.assertEqual(database.config_for_lock_timeout(), {})
        self.assertTrue(any("lock" in line for line in logs.output),
                        logs.output)

    def test_an_absent_file_is_an_empty_mapping_not_a_failure(self):
        from src import config_io
        self.assertEqual(
            config_io.load_config(os.path.join(self.directory, "nope.json")),
            {})

    def setUp(self):
        import tempfile
        self.directory = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.directory,
                        ignore_errors=True)


class TestTheScoresAreReadWhenTheyAreUsed(unittest.TestCase):
    """The import-time read, checked in a fresh interpreter: a test that
    imports the module in this process would pass either way, because the
    module is already imported."""

    def test_importing_scoring_logic_does_not_read_the_config(self):
        code = (
            "import builtins, os\n"
            "opened = []\n"
            "real = builtins.open\n"
            "def spy(path, *a, **k):\n"
            "    opened.append(str(path))\n"
            "    return real(path, *a, **k)\n"
            "builtins.open = spy\n"
            "from src import scoring_logic\n"
            "builtins.open = real\n"
            "hits = [p for p in opened if 'shared_config.json' in p]\n"
            "print('HITS', hits)\n"
            "assert not hits, hits\n")
        result = _run(code)
        self.assertEqual(result.returncode, 0,
                         f"importing scoring_logic read the config: "
                         f"{result.stdout}\n{result.stderr}")

    def test_a_corrupt_config_stops_the_score_rather_than_defaulting_it(self):
        """It used to complete the run: the weights fell back to the Python
        literals and the vocabulary to the empty set, so every page scored 0
        and the briefing reported it as a measurement."""
        code = (
            "import json, os, tempfile\n"
            "from src import config_io\n"
            "handle, path = tempfile.mkstemp(suffix='.json')\n"
            "os.write(handle, b'{\"technical\": {,}')\n"
            "os.close(handle)\n"
            "config_io.SHARED_CONFIG_PATH = path\n"
            "from src import scoring_logic\n"
            "try:\n"
            "    scoring_logic.calculate_weighted_score(5, 4, 0, 100)\n"
            "except json.JSONDecodeError:\n"
            "    print('RAISED')\n"
            "else:\n"
            "    raise AssertionError('scored against the Python defaults')\n"
            "finally:\n"
            "    os.unlink(path)\n")
        result = _run(code)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")
        self.assertIn("RAISED", result.stdout)

    def test_an_edited_config_changes_the_next_score_in_the_same_process(self):
        """The GUI edits this file while the process that reads it is running.
        With the config in module globals, editing it and re-running inside one
        Streamlit process changed nothing (P16)."""
        code = (
            "import json, os, tempfile\n"
            "from src import config_io, scoring_logic\n"
            "handle, path = tempfile.mkstemp(suffix='.json')\n"
            "os.close(handle)\n"
            "config_io.SHARED_CONFIG_PATH = path\n"
            "def write(t3):\n"
            "    with open(path, 'w') as f:\n"
            "        json.dump({'technical': {'scoring_weights': "
            "{'tier_2_systems': 0.5, 'tier_3_bowen': t3}}}, f)\n"
            "write(2.0)\n"
            "first, _ = scoring_logic.calculate_weighted_score(0, 0, 1)\n"
            "write(5.0)\n"
            "second, _ = scoring_logic.calculate_weighted_score(0, 0, 1)\n"
            "os.unlink(path)\n"
            "print('SCORES', first, second)\n"
            "assert (first, second) == (2.0, 5.0), (first, second)\n")
        result = _run(code)
        self.assertEqual(result.returncode, 0,
                         f"{result.stdout}\n{result.stderr}")

    def test_a_caller_holding_the_config_is_not_made_to_re_read_it(self):
        """P25 — one config→argument mapping, as `position_thresholds` and
        `magnet_thresholds` already do."""
        from src import scoring_logic

        config = {"technical": {"scoring_weights": {"tier_3_bowen": 7.0},
                                "penalty_thresholds": {}}}
        with unittest.mock.patch("src.config_io.load_config") as reader:
            score, _label = scoring_logic.calculate_weighted_score(
                0, 0, 1, config=config)
        reader.assert_not_called()
        self.assertEqual(score, 7.0)

    def test_the_vocabulary_is_read_when_the_analyser_is_built(self):
        """`SemanticAuditor` took the three tiers from module globals, so the
        vocabulary a run scored with was whatever the file said when the
        process started.

        This was two assertions over `semantic.py`'s source text —
        `"TIER_1_MEDICAL" not in source` and `"clinical_tiers()" in source`.
        Both hold if the import-time read comes back as
        `TIERS = clinical_tiers()` at module level, which is the same defect
        under another name (P19; Y16 cold review, F5). The consequence is
        cheap to test instead: build two analysers either side of a changed
        file and look at the vocabulary each one holds."""
        marker_one = {"clinical": {"tier_1_medical": ["zzmarkerone"],
                                   "tier_2_systems": [], "tier_3_bowen": []}}
        marker_two = {"clinical": {"tier_1_medical": ["zzmarkertwo"],
                                   "tier_2_systems": [], "tier_3_bowen": []}}
        from src.semantic import SemanticAuditor
        with unittest.mock.patch("src.config_io.load_config",
                                 return_value=marker_one):
            first = SemanticAuditor()
        with unittest.mock.patch("src.config_io.load_config",
                                 return_value=marker_two):
            second = SemanticAuditor()
        self.assertIn("zzmarkerone", first.medical_terms)
        self.assertNotIn("zzmarkertwo", first.medical_terms)
        self.assertIn("zzmarkertwo", second.medical_terms,
                      "the second analyser was built after the file changed "
                      "and still holds the first vocabulary, so the read is "
                      "not happening when the analyser is built")


class TestTheFallbacksSayWhatTheDocumentSays(unittest.TestCase):
    """Several Python fallbacks mirror `shared_config.json`'s own values. Each
    must be verbatim equal to the file's, or "degrades to the documented
    default" degrades to a different number than the document."""

    def test_the_scoring_weights_match(self):
        from src import scoring_logic
        self.assertEqual(
            scoring_logic.DEFAULT_WEIGHTS,
            _config()["technical"]["scoring_weights"])

    def test_the_penalty_fallbacks_match(self):
        from src import scoring_logic
        declared = _config()["technical"]["penalty_thresholds"]
        for key, value in scoring_logic.DEFAULT_PENALTY_CFG.items():
            with self.subTest(key):
                self.assertEqual(value, declared[key])
        self.assertEqual(scoring_logic.DEFAULT_TIER_1_MAX_DENSITY,
                         declared["tier_1_max_density_per_1000"])
        self.assertEqual(scoring_logic.DEFAULT_TIER_1_MIN_HITS,
                         declared["tier_1_min_hits"])

    def test_a_config_with_no_weights_block_yields_the_documented_defaults(self):
        """The accessor's contract: a config that says nothing returns the
        documented numbers, not an empty mapping that every call site then has
        to carry its own copy of the default for."""
        from src import scoring_logic
        self.assertEqual(scoring_logic.weights({}),
                         scoring_logic.DEFAULT_WEIGHTS)
        self.assertEqual(scoring_logic.weights({"technical": {}}),
                         scoring_logic.DEFAULT_WEIGHTS)
        self.assertEqual(scoring_logic.penalty_cfg({}),
                         scoring_logic.DEFAULT_PENALTY_CFG)

    def test_the_position_thresholds_match(self):
        from src import database
        declared = _config()["technical"]["position_thresholds"]
        for key, value in database.DEFAULT_POSITION_THRESHOLDS.items():
            with self.subTest(key):
                self.assertEqual(value, declared[key])

    def test_the_magnet_and_vacuum_fallbacks_match(self):
        from src import database
        technical = _config()["technical"]
        self.assertEqual(database.DEFAULT_VACUUM_MIN_MEDICAL,
                         technical["vacuum_min_medical"])
        self.assertEqual(database.DEFAULT_MAGNET_MAX_POSITION,
                         technical["magnet_max_position"])

    def test_the_volatility_trigger_fallback_matches(self):
        from src import database
        self.assertEqual(database.DEFAULT_VOLATILITY_MIN_SHIFT,
                         _config()["risk_signals"]["volatility_min_shift"])


class TestTheCorruptFileStopsTheRunRatherThanThePage(unittest.TestCase):
    """The cold review of this chunk found the new raise swallowed one layer
    below where it was guarded (F1, high).

    `SemanticAuditor._scoring_window_words` read the config, and the call sat
    inside `scrape_content`'s `try` / `except Exception`. So a config that
    could not be parsed at the moment a page was scraped did NOT stop the run:
    every page came back `http_status=0, extraction_status="error"`, `main.py`
    wrote a market snapshot with `rank`/`systems_score`/`medical_score` all
    NULL for every URL, printed "Skipping unreadable page", and continued — a
    persisted "we could not read this page" that was actually "I could not
    read my own config" (P1 + P2 + P11 + P40). `calculate_weighted_score`,
    where the guard below this one fires, was never reached on the run path.

    The trigger is the case the per-call read was introduced for: the GUI edits
    this file while the process that reads it is running.
    """

    def test_a_corrupt_config_stops_the_analyser_being_built(self):
        from src.semantic import SemanticAuditor
        with unittest.mock.patch(
                "src.config_io.load_config",
                side_effect=json.JSONDecodeError("Expecting value", "{", 1)):
            with self.assertRaises(json.JSONDecodeError):
                SemanticAuditor()

    def test_nothing_reads_the_config_once_the_analyser_is_built(self):
        """The read must be outside every per-page handler, which means it
        happens once, here, and not again while pages are being scored."""
        from src.semantic import SemanticAuditor
        with unittest.mock.patch("src.config_io.load_config",
                                 return_value=_config()):
            auditor = SemanticAuditor()
        with unittest.mock.patch("src.config_io.load_config",
                                 side_effect=AssertionError(
                                     "the config was read again after the "
                                     "analyser was built")) as reader:
            auditor.analyze_text("a short page about families")
            _ = auditor.stock_image_hosts
            _ = auditor.scoring_window_words
        reader.assert_not_called()

    def test_the_window_the_analyser_holds_is_the_configured_one(self):
        """`self.scoring_window_words = None` slices a word list to its full
        length, so a mutation that stopped the window being read at all was
        near-harmless to the scrape and nothing asserted the value (the one
        vacuous result in this chunk's mutation gate)."""
        from src.semantic import SemanticAuditor
        config = _config()
        config["technical"] = dict(config["technical"], scoring_window_words=7)
        with unittest.mock.patch("src.config_io.load_config",
                                 return_value=config):
            auditor = SemanticAuditor()
        self.assertEqual(auditor.scoring_window_words, 7)

    def test_the_scrape_handler_does_not_wrap_a_config_read(self):
        """A structural check on top of the two consequences: the call that
        caused F1 is gone from the scrape path, so a future edit cannot put
        the read back inside the handler without this failing."""
        source = io.open(os.path.join(SRC, "semantic.py"),
                         encoding="utf-8").read()
        tree = ast.parse(source)
        scrape = [node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "scrape_content"]
        self.assertEqual(len(scrape), 1, "scrape_content not found (P29)")
        readers = {"shared_config", "load_config", "load_shared_config",
                   "clinical_tiers", "load_dictionary", "weights",
                   "penalty_cfg", "_scoring_window_words",
                   "stock_image_hosts"}
        called = set()
        for node in ast.walk(scrape[0]):
            if isinstance(node, ast.Call):
                func = node.func
                name = (func.attr if isinstance(func, ast.Attribute)
                        else getattr(func, "id", None))
                if name in readers:
                    called.add(name)
        self.assertEqual(
            called, set(),
            "scrape_content calls a config reader, and its `except Exception` "
            f"turns a config failure into an unreadable PAGE: {sorted(called)}")


class TestOneRuleInsideSemanticToo(unittest.TestCase):
    """F2 (medium): `semantic.py` held two opposite policies for this file,
    280 lines apart and inside the same `try`. `stock_image_hosts` swallowed
    every exception with the rule written out — "a config read must not break
    a scrape" — while the scoring-window read raised. Pick one: it raises, and
    it is read when the analyser is built, so there is no scrape to break."""

    def test_the_stock_image_hosts_read_raises_like_every_other(self):
        from src import semantic
        with unittest.mock.patch(
                "src.config_io.load_config",
                side_effect=json.JSONDecodeError("Expecting value", "{", 1)):
            with self.assertRaises(json.JSONDecodeError):
                semantic.stock_image_hosts()

    def test_a_configured_list_is_used_and_an_absent_one_degrades(self):
        from src import semantic
        self.assertEqual(semantic.stock_image_hosts({"stock_image_hosts": ["A.COM"]}),
                         frozenset({"a.com"}))
        self.assertEqual(semantic.stock_image_hosts({}),
                         semantic.DEFAULT_STOCK_IMAGE_HOSTS)

    def test_no_config_read_in_this_module_sits_inside_a_handler(self):
        """The structural form of the same rule, for the whole module rather
        than `scrape_content` alone: a config read inside a `try` whose
        handler returns a fallback is the policy this chunk removed."""
        tree = ast.parse(io.open(os.path.join(SRC, "semantic.py"),
                                 encoding="utf-8").read())
        readers = {"shared_config", "load_config", "load_shared_config",
                   "clinical_tiers", "load_dictionary", "weights",
                   "penalty_cfg", "stock_image_hosts"}
        tries = [node for node in ast.walk(tree) if isinstance(node, ast.Try)]
        self.assertTrue(tries, "no try blocks found in semantic.py (P29)")
        swallowed = []
        for block in tries:
            for body_node in block.body:
                for node in ast.walk(body_node):
                    if not isinstance(node, ast.Call):
                        continue
                    func = node.func
                    name = (func.attr if isinstance(func, ast.Attribute)
                            else getattr(func, "id", None))
                    if name in readers:
                        swallowed.append(f"line {node.lineno}: {name}()")
        self.assertEqual(
            swallowed, [],
            "a config read sits inside a try block, so its failure becomes "
            f"whatever that handler returns: {swallowed}")


class TestAnUnreadableVocabularyIsNotAnEmptyOne(unittest.TestCase):
    """F6 (medium): the `clinical_dictionary.json` fallback was
    `except Exception: pass` followed by three empty lists. Reached whenever
    the config parses but its `clinical` block is absent — one GUI edit away,
    since the block is editorial — and the dictionary file is then unreadable.
    Every page then scored medical 0 / t2 0 / t3 0, label `Standard`, the run
    completed and reported that as a measurement, and nothing was logged."""

    def _with_dictionary(self, text):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "clinical_dictionary.json")
        io.open(path, "w", encoding="utf-8").write(text)
        return unittest.mock.patch.object(scoring_logic, "DICTIONARY_PATH", path)

    def test_a_corrupt_dictionary_file_raises(self):
        with self._with_dictionary("{ truncated"):
            with self.assertRaises(json.JSONDecodeError):
                scoring_logic.load_dictionary({})

    def test_a_readable_dictionary_file_is_still_the_fallback(self):
        with self._with_dictionary(json.dumps({"tier_1_medical": ["zzdict"]})):
            self.assertEqual(scoring_logic.load_dictionary({})["tier_1_medical"],
                             ["zzdict"])

    def test_no_vocabulary_anywhere_is_logged_rather_than_silent(self):
        missing = os.path.join(tempfile.mkdtemp(), "absent.json")
        with unittest.mock.patch.object(scoring_logic, "DICTIONARY_PATH", missing):
            with self.assertLogs("src.scoring_logic", level="WARNING") as logged:
                tiers = scoring_logic.load_dictionary({})
        self.assertEqual(tiers, {"tier_1_medical": [], "tier_2_systems": [],
                                 "tier_3_bowen_expert": []})
        self.assertIn("No clinical vocabulary", "\n".join(logged.output))


class TestOneScoreComesFromOneRead(unittest.TestCase):
    """F8 (medium): the vocabulary was frozen when the analyser was built
    while the weights, penalties and window were read per call. One run holds
    one analyser, so after a mid-run edit a single `analyze_text` combined the
    old vocabulary with the new weights and nothing recorded which version
    produced the score."""

    def test_the_score_is_computed_with_the_config_the_analyser_holds(self):
        from src import semantic
        with unittest.mock.patch("src.config_io.load_config",
                                 return_value=_config()):
            auditor = semantic.SemanticAuditor()
        with unittest.mock.patch("src.semantic.calculate_weighted_score",
                                 return_value=(0.0, "Standard")) as scorer:
            auditor.analyze_text("a short page about families")
        self.assertIs(scorer.call_args.kwargs["config"], auditor.config,
                      "the score was computed from a different read of the "
                      "config than the vocabulary was")


class TestTheRemainingMirroredFallbacks(unittest.TestCase):
    """F7 (medium): the sweep was complete along one axis — the fallbacks
    `scoring_logic` and `database` declare — and reported as complete. Three
    more Python literals mirror a `shared_config.json` value."""

    def setUp(self):
        self.technical = _config()["technical"]

    def test_the_scoring_window_fallback_matches(self):
        from src import semantic
        self.assertEqual(semantic.DEFAULT_SCORING_WINDOW_WORDS,
                         self.technical["scoring_window_words"])

    def test_the_feasibility_threshold_fallback_matches(self):
        from src import analysis
        self.assertEqual(analysis.DEFAULT_FEASIBILITY_THRESHOLD,
                         self.technical["feasibility_threshold"])

    def test_the_lock_timeout_fallback_matches_the_file_not_a_literal(self):
        """`tests/test_y11_*` asserts this against the literal `5.0`, so the
        constant and the file could still drift from each other."""
        from src import db_connect
        self.assertEqual(db_connect.DEFAULT_LOCK_TIMEOUT_SECONDS,
                         self.technical["db_lock_timeout_seconds"])


class TestTheReadIsCheapEnoughToDoEveryTime(unittest.TestCase):
    """The plan asked for a measurement rather than an assumption about
    whether eleven reads per run need a cache. They do not: a cache keyed on
    nothing is how the import-time read became a bug, and the GUI edits this
    file while the process that reads it is running."""

    def test_one_read_is_well_under_a_millisecond(self):
        import time
        from src import config_io
        start = time.perf_counter()
        for _ in range(50):
            config_io.load_config()
        each_ms = (time.perf_counter() - start) * 1000 / 50
        self.assertLess(each_ms, 5.0, f"one read took {each_ms:.3f} ms over "
                                      f"{os.path.getsize(CONFIG)} bytes")


if __name__ == "__main__":
    unittest.main()
