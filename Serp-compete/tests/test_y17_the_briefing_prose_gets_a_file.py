"""Chunk Y17 — the briefing's prose lives in `briefing_messages.json`.

Spec: docs/review_2026-11-04/PLAN_Y17_the_briefing_prose_gets_a_file.md

Tool 1 has ten editorial text files; until this chunk Tool 2 had none and
every sentence the strategic briefing renders was a Python literal. Three
consequences were already in the code and are what these guards hold shut:

* the EEAT heuristic caveat existed in THREE wordings, one of them
  `shared_config.eeat_client_messaging.caveat`, which no module read;
* the handoff's page-relative ranks were warned about in FOUR separately
  worded places, so rewording the fact meant finding all four;
* `UNKNOWN_CELL = "—"` had a bare `"—"` duplicate beside it.
"""
import ast
import json
import os
import subprocess
import sys
import unittest

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import briefing_messages
from src.briefing_messages import Messages, MessagesUnavailable, load_messages

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "Serp-compete", "src")
MESSAGES_PATH = os.path.join(REPO, "briefing_messages.json")

#: Keys that are in the file on purpose and asked for by nothing. Each is an
#: editorial string the owner wrote that the report does not render today, kept
#: verbatim rather than deleted by a refactor — the decision whether to render
#: or drop it is the owner's. Named here so an ACCIDENTALLY unread key still
#: fails the coverage guard.
DELIBERATELY_UNREAD = {
    "eeat.positioning",
    "eeat.confidence_levels.high",
    "eeat.confidence_levels.medium",
    "eeat.confidence_levels.low",
    "positioning.framework_caption",
    "serp_overlap.framework_caption",
    "sov.framework_caption",
}


def _comment_key(dotted: str) -> bool:
    """A `_comment`-style annotation, not a message."""
    return dotted.rsplit(".", 1)[-1].startswith("_")


def _leaf_keys(node, prefix=""):
    for name, value in node.items():
        dotted = f"{prefix}{name}"
        if isinstance(value, dict):
            yield from _leaf_keys(value, dotted + ".")
        else:
            yield dotted


def _source_files():
    for name in sorted(os.listdir(SRC)):
        if name.endswith(".py"):
            yield name, open(os.path.join(SRC, name), encoding="utf-8").read()


def _sections():
    """The messages file's top-level section names.

    A message key starts with one. Without this scope the walk below also
    collects `session.get("https://api.dataforseo.com/v3/...")` — any `.get`
    on any object whose first argument happens to contain a dot.
    """
    return {name for name in load_messages() if not name.startswith("_")}


def _key_constants(node):
    """Every string constant that could be the key argument of one call.

    `db_connect` picks its key with a conditional expression
    (`m.get("…rolled_back" if rolled_back else "…committed")`), which is one
    call asking for either of two keys.
    """
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, ast.IfExp):
        return _key_constants(node.body) + _key_constants(node.orelse)
    return []


def _requested_keys():
    """Every key the code asks for, with the file it asks from.

    Keyed on the CALL, not on a receiver name: `m.get(...)`,
    `self.messages.get(...)`, `self._words.get(...)` and
    `_messages(messages).get(...)` are all the same request, and a guard that
    recognised only one of those names would pass while the others drifted.

    Returns `(exact, prefixes)`. A key composed at runtime —
    `m.get("capped.labels.%s" % label_key)` — cannot be resolved statically,
    so its literal part is returned as a prefix and the keys under it count as
    asked-for. Narrower than checking the call and wider than nothing; a key
    under no prefix and in no call is dead either way, which is what the
    coverage guard is for.
    """
    wanted = {"get", "raw", "plural"}
    sections = _sections()
    exact = {}
    prefixes = set()
    for name, text in _source_files():
        for call in (n for n in ast.walk(ast.parse(text))
                     if isinstance(n, ast.Call)):
            func = call.func
            if not isinstance(func, ast.Attribute) or func.attr not in wanted:
                continue
            if not call.args:
                continue
            arg = call.args[0]
            if isinstance(arg, (ast.BinOp, ast.JoinedStr)):
                for part in ast.walk(arg):
                    if (isinstance(part, ast.Constant)
                            and isinstance(part.value, str)
                            and part.value.split(".")[0] in sections):
                        prefixes.add(part.value.split("%")[0].split("{")[0])
                continue
            for key in _key_constants(arg):
                if "." not in key or key.split(".")[0] not in sections:
                    continue
                if func.attr == "plural":
                    exact.setdefault(key + ".one", set()).add(name)
                    exact.setdefault(key + ".many", set()).add(name)
                else:
                    exact.setdefault(key, set()).add(name)
    return exact, prefixes


def _mentioned_keys():
    """Keys named by a string literal anywhere in `src/`.

    Weaker than `_requested_keys` on purpose, and used only by the "every key
    in the file is asked for" direction: `risk_radar` holds three of its keys
    in a tuple of `(cause, key)` pairs and passes them to `get` later, which
    no call-site walk sees. A key that appears in no source file at all is
    dead whichever way it would have been passed.
    """
    sections = _sections()
    found = set()
    for _name, text in _source_files():
        for node in ast.walk(ast.parse(text)):
            if (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and "." in node.value
                    and node.value.split(".")[0] in sections):
                found.add(node.value)
    return found


class TestEveryKeyTheCodeAsksForExists(unittest.TestCase):
    """A message the code asks for and the file does not carry renders a
    marker in the briefing. That is the right behaviour at runtime (P2) and a
    build failure here."""

    def setUp(self):
        self.requested, self.prefixes = _requested_keys()
        # P29: the walk must be asserted to have found the thing it is about.
        self.assertGreater(len(self.requested), 100,
                           "the AST walk found almost no message requests, so "
                           "this guard is passing vacuously")
        self.assertIn("capped.labels.", self.prefixes,
                      "the composed-key arm of the walk found nothing")

    def test_every_requested_key_resolves(self):
        messages = Messages()
        missing = sorted(key for key in self.requested
                         if messages.raw(key) is None)
        self.assertEqual([], missing)

    def test_no_requested_key_resolves_to_a_container(self):
        """`m.get("eeat")` would render a dict as a marker, silently."""
        messages = Messages()
        containers = sorted(key for key in self.requested
                            if isinstance(messages.raw(key), dict))
        self.assertEqual([], containers)

    def test_every_key_in_the_file_is_asked_for(self):
        """The dead `eeat_client_messaging` entries are what an unasked-for key
        looks like: editorial text in the right kind of place that no module
        read. Three `framework_caption` entries were the same thing."""
        data = load_messages()
        mentioned = self.requested.keys() | _mentioned_keys()
        unread = sorted(
            key for key in _leaf_keys(data)
            if not _comment_key(key)
            and key not in mentioned
            and key not in DELIBERATELY_UNREAD
            and not any(key.startswith(p) for p in self.prefixes))
        self.assertEqual([], unread)

    def test_the_deliberately_unread_keys_are_all_still_there(self):
        """Listing a key as unread must not be a way to delete it."""
        messages = Messages()
        for key in sorted(DELIBERATELY_UNREAD):
            self.assertIsNotNone(messages.raw(key), key)


class TestAMalformedFileStopsTheRender(unittest.TestCase):
    """The opposite of Tool 1's `report_writing_directives.yml`, on purpose.

    Directives are advice to a model; these sentences are the hedges on the
    report's own figures, and a briefing rendered without its caveats states
    every number in it as fact. That is worse than a stopped render — the same
    judgement chunk Y16 made about the scoring config.
    """

    def test_an_absent_file_raises(self):
        with self.assertRaises(MessagesUnavailable):
            load_messages(os.path.join(REPO, "no_such_messages_file.json"))

    def test_a_file_that_will_not_parse_raises(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as handle:
            handle.write("{not json")
            path = handle.name
        try:
            with self.assertRaises(MessagesUnavailable):
                load_messages(path)
        finally:
            os.unlink(path)

    def test_a_file_that_is_not_an_object_raises(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as handle:
            handle.write('["a list of sentences"]')
            path = handle.name
        try:
            with self.assertRaises(MessagesUnavailable):
                load_messages(path)
        finally:
            os.unlink(path)

    def test_the_report_generator_does_not_swallow_it(self):
        """The read is in `__init__`, outside every per-section handler, so a
        broken file stops the render before the first section rather than
        becoming a per-section blank (the shape Y16's cold review arrived
        at)."""
        from unittest.mock import patch

        from src.reporting import ReportGenerator

        with patch("src.briefing_messages.load_messages",
                   side_effect=MessagesUnavailable("broken")):
            with patch("src.reporting.DatabaseManager"), \
                 patch("src.reporting.load_shared_config", return_value={}):
                with self.assertRaises(MessagesUnavailable):
                    ReportGenerator()


class TestAMissingKeyIsVisibleAndCounted(unittest.TestCase):
    """An owner part-way through an edit gets a report that says where the hole
    is, not a sentence that quietly vanished."""

    def setUp(self):
        # The ledger is process-level, so that the report's count covers the
        # six consumers that build a throwaway `Messages` (cold review H2).
        # Each test therefore starts from empty, the way the entry point does.
        briefing_messages.reset_misses()

    tearDown = setUp

    def test_a_missing_key_renders_its_marker(self):
        messages = Messages(data={})
        rendered = messages.get("eeat.score_caveat")
        self.assertIn("eeat.score_caveat", rendered)
        self.assertIn("message missing", rendered)

    def test_a_missing_key_is_recorded(self):
        messages = Messages(data={})
        messages.get("eeat.score_caveat")
        self.assertEqual(["eeat.score_caveat"], messages.missing)

    def test_a_missing_placeholder_is_recorded_not_raised(self):
        messages = Messages(data={"x": {"y": "needs {a}"}})
        rendered = messages.get("x.y")
        self.assertIn("message missing", rendered)
        self.assertEqual(1, len(messages.missing))

    def test_raw_does_not_record_a_miss(self):
        """Callers legitimately ask whether an optional section is present."""
        messages = Messages(data={})
        self.assertIsNone(messages.raw("anything.at.all"))
        self.assertEqual([], messages.missing)

    def test_the_shortfall_line_counts_them(self):
        messages = Messages()
        self.assertEqual("", messages.shortfall_line())
        messages.get("no.such.key")
        line = messages.shortfall_line()
        self.assertIn("no.such.key", line)
        self.assertIn("1", line)

    def test_the_report_appends_the_shortfall_line(self):
        """Called on the real method, not read out of the source: a text guard
        passed while the append was reachable only when `if False`. Found by
        this chunk's own mutation gate."""
        from src.reporting import ReportGenerator

        holder = ReportGenerator.__new__(ReportGenerator)
        holder.messages = Messages()
        self.assertEqual([], holder.shortfall_lines())
        holder.messages.get("no.such.key")
        lines = holder.shortfall_lines()
        self.assertEqual(1, len(lines))
        self.assertIn("no.such.key", lines[0])

    def test_the_shortfall_line_is_asked_for_after_the_sections(self):
        """It counts what the sections could not find, so it has to be last,
        and it has to reach the file."""
        import inspect

        from src.reporting import ReportGenerator

        source = inspect.getsource(ReportGenerator.generate_summary)
        self.assertLess(source.index("self.shortfall_lines()"),
                        source.index("join(report)"))

    def test_the_key_argument_is_positional_only(self):
        """`db_cleanup.bad_lock_timeout` carries a `{key}` placeholder, which
        collided with the parameter name and raised "got multiple values for
        argument 'key'". Every future message with that placeholder would have
        found it again."""
        messages = Messages(data={"a": {"b": "{key} and {count}"}})
        self.assertEqual("x and 2", messages.get("a.b", key="x", count=2))


class TestOneFactIsWordedOnce(unittest.TestCase):
    """The handoff's page-relative ranks were warned about in four separately
    worded places, each citing the same finding. They are not literal
    duplicates, so no de-duplication tool finds them."""

    def setUp(self):
        self.data = load_messages()
        self.citation = self.data["rank_semantics"]["finding_citation"]

    def test_the_citation_is_spelled_out_in_exactly_one_key(self):
        carriers = sorted(key for key in _leaf_keys(self.data)
                          if not _comment_key(key)
                          and self.citation in str(_resolve(self.data, key)))
        self.assertEqual(["rank_semantics.finding_citation"], carriers)

    def test_every_warning_about_it_interpolates_that_key(self):
        for key in ("rank_semantics.page_relative",
                    "magnets.rank_filter_inoperative",
                    "serp_overlap.asymmetric_warning",
                    "positioning.authority_inflated_warning"):
            self.assertIn("{citation}", _resolve(self.data, key), key)

    def test_the_rendered_warnings_all_name_the_finding(self):
        """The interpolation is only worth having if the callers pass it."""
        import inspect

        from src.reporting import ReportGenerator

        source = inspect.getsource(ReportGenerator.generate_summary)
        del source
        text = open(os.path.join(SRC, "reporting.py"), encoding="utf-8").read()
        # Parsed calls, not a substring count: the same string in a comment
        # satisfies `text.count(...)`, which is the shape this chunk's own
        # LEARNINGS entry says the mutation gate walked through (cold review,
        # M6).
        passing = 0
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "citation":
                    continue
                value = kw.value
                if (isinstance(value, ast.Call)
                        and isinstance(value.func, ast.Attribute)
                        and value.func.attr == "get"
                        and value.args
                        and isinstance(value.args[0], ast.Constant)
                        and value.args[0].value
                        == "rank_semantics.finding_citation"):
                    passing += 1
        self.assertEqual(
            4, passing,
            "the four warnings about the page-relative rank convention are "
            "run coverage, the magnet filter, the SERP-overlap cells and the "
            "positioning axis; one of them has stopped citing the finding")

    def test_the_unknown_cell_is_visible(self):
        """`test_report_rendering.py` compares the render against this same
        configured value, so an `icons.unknown_cell` set to `""` would satisfy
        every one of those assertions while the cells rendered blank — which
        is the thing the em dash exists to prevent (cold review, M7)."""
        from src.reporting import unknown_cell

        cell = unknown_cell()
        self.assertTrue(cell.strip(),
                        "an empty unknown-cell marker is indistinguishable "
                        "from a rendering fault, and makes every assertion "
                        "that looks for it pass trivially")

    def test_the_em_dash_has_one_home(self):
        """`UNKNOWN_CELL` had a bare duplicate of itself in the cluster
        table bypassing the constant entirely."""
        from src.reporting import unknown_cell

        self.assertEqual(self.data["icons"]["unknown_cell"], unknown_cell())
        text = open(os.path.join(SRC, "reporting.py"), encoding="utf-8").read()
        bare = [node.lineno for node in ast.walk(ast.parse(text))
                if isinstance(node, ast.Constant) and node.value == "—"]
        self.assertEqual([], bare,
                         "a bare em-dash literal is back in reporting.py; the "
                         "cell reads `icons.unknown_cell`. (A comment that "
                         "quotes the cell is not a second home for it, so this "
                         "reads the parsed constants, not the file text.)")


class TestTheRecordedDuplicatesDoNotGrow(unittest.TestCase):
    """Two claims are each still worded more than once, on purpose, and the
    decision is recorded rather than quietly reversed (cold review, M9).

    * the EEAT heuristic caveat went from FOUR wordings to THREE, not to one:
      the long rendered `eeat.caveat`, the short `eeat.row_caveat` stored on
      every score row, and the `eeat_scorer` module docstring, which is
      written for whoever reads the module and is not report output. The
      fourth, `shared_config.eeat_client_messaging.caveat`, was read by
      nothing and is gone;
    * three sections carry a `framework_caption` that restates their own
      rendered `intro` at greater length. Both wordings moved into this file
      verbatim; rewriting the report's editorial content is the owner's call,
      not the migration's, so the captions stay unread and named.

    What these guards stop is a FOURTH home appearing — which is how the
    original defect was built, one reasonable addition at a time.
    """

    #: The fingerprint of the EEAT claim: whatever the wording, it says the
    #: scores are not Google's model.
    EEAT_CLAIM = "eeat model"

    #: The three sections whose caption restates their intro. A fourth is a
    #: new instance of the defect, not a continuation of this decision.
    CAPTIONED = {"positioning", "serp_overlap", "sov"}

    def setUp(self):
        self.data = load_messages()

    def test_the_eeat_caveat_has_exactly_two_message_keys(self):
        carriers = sorted(key for key in _leaf_keys(self.data)
                          if not _comment_key(key)
                          and self.EEAT_CLAIM in str(
                              _resolve(self.data, key)).lower())
        self.assertEqual(["eeat.caveat", "eeat.row_caveat"], carriers,
                         "the EEAT heuristic caveat is worded in the long "
                         "rendered line and in the short caveat stored on "
                         "every score row; a third key carrying the same "
                         "claim is the defect returning")

    def test_the_only_python_home_for_it_is_a_docstring(self):
        """A docstring is written for whoever reads the module. A rendered
        sentence is not, and `_prose_literals` would catch one — this names
        the module that is allowed to repeat the claim at all."""
        homes = []
        for name, text in _source_files():
            tree = ast.parse(text)
            in_docstring = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                    if ast.get_docstring(node, clean=False) and node.body:
                        in_docstring.add(node.body[0].lineno)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and self.EEAT_CLAIM in node.value.lower()):
                    homes.append((name, node.lineno in in_docstring))
        self.assertEqual([("eeat_scorer.py", True)], homes)

    def test_no_fourth_section_gains_a_framework_caption(self):
        carriers = {name for name, section in self.data.items()
                    if isinstance(section, dict)
                    and "framework_caption" in section}
        self.assertEqual(self.CAPTIONED, carriers)

    def test_each_captioned_section_still_renders_its_intro(self):
        """The caption is the unread one of the pair. If a section lost its
        `intro` the duplication would have resolved itself the wrong way —
        by the longer, unrendered wording becoming the only one."""
        for name in sorted(self.CAPTIONED):
            self.assertIn("intro", self.data[name], name)
            self.assertIn(f"{name}.framework_caption", DELIBERATELY_UNREAD)


def _resolve(data, dotted):
    node = data
    for part in dotted.split("."):
        node = node[part]
    return node


class TestTheWordsStillMatchTheCodeThatComparesThem(unittest.TestCase):
    """Some of these values are ALSO compared against — in SQL, in the magnet
    filter, in the database. Moving the label out of Python is safe; letting it
    drift from the value the comparison uses is not. The same shape as Tool 1's
    `feasibility_messages.yml` statuses."""

    def test_the_surface_level_depth_word_is_the_stored_value(self):
        data = load_messages()
        self.assertEqual("Surface-Level", data["systemic_depth"]["surface"])
        text = open(os.path.join(SRC, "reporting.py"), encoding="utf-8").read()
        self.assertIn('systemic_label = "Surface-Level"', text)

    def test_every_systemic_depth_state_has_a_word(self):
        import inspect

        from src.reporting import ReportGenerator

        source = inspect.getsource(ReportGenerator.generate_summary)
        data = load_messages()["systemic_depth"]
        states = [k for k in data if not k.startswith("_")]
        self.assertEqual(
            sorted(states),
            sorted(["bowen", "none", "not_recorded", "surface", "systems",
                    "trace"]))
        for state in states:
            self.assertIn(f'systemic_depth.{state}"', source, state)

    def test_the_feasibility_margin_comes_from_the_knob_that_decides_it(self):
        """The sentence said "client DA + 5" while the knob was
        `technical.feasibility_threshold`, which `check_feasibility` reads. The
        prose now interpolates it."""
        from src.analysis import feasibility_threshold

        intro = load_messages()["feasibility"]["intro"]
        self.assertIn("{threshold}", intro)
        rendered = Messages().get("feasibility.intro",
                                  threshold=f"{feasibility_threshold():g}")
        self.assertIn(f"{feasibility_threshold():g}", rendered)

    def test_the_action_queue_cap_is_one_number(self):
        """`15` was a literal in the prose and in the `.head(15)` beside it,
        so the sentence could say "top 15" while the slice took another
        number. The number is a THRESHOLD, so it is in `shared_config.json`
        beside its two siblings and the sentence interpolates it; it spent one
        afternoon in the messages file, read with `raw()`, where an owner
        deleting the key reverted to a hardcoded 15 in silence (cold review
        M2)."""
        import inspect

        from src.reporting import ReportGenerator

        self.assertIsNone(Messages().raw("serp_overlap.action_queue_row_cap"),
                          "a threshold does not belong in the file of words")
        with open(os.path.join(REPO, "shared_config.json"),
                  encoding="utf-8") as handle:
            configured = json.load(handle)["serp_overlap"][
                "action_queue_row_cap"]
        self.assertIsInstance(configured, int)

        source = inspect.getsource(ReportGenerator.generate_summary)
        slices = [node for node in ast.walk(ast.parse(source.lstrip()))
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "head"]
        by_cap = [node for node in slices
                  if node.args and isinstance(node.args[0], ast.Name)
                  and node.args[0].id == "row_cap"]
        self.assertEqual(2, len(by_cap),
                         "both action queues slice by the cap")
        self.assertEqual(
            [], [node.args[0].value for node in slices
                 if node.args and isinstance(node.args[0], ast.Constant)
                 and node.args[0].value == 15],
            "an action queue slices by a literal 15 again")

        holder = ReportGenerator.__new__(ReportGenerator)
        holder.messages = Messages()
        holder.config = {"serp_overlap": {"action_queue_row_cap": configured}}
        self.assertEqual(configured, holder.action_queue_row_cap())

    def test_an_unusable_cap_falls_back_and_says_so(self):
        """A cap of 0 would print an empty action queue, which reads as "no
        keywords qualify" rather than "the cap is wrong"."""
        from src.reporting import ReportGenerator

        holder = ReportGenerator.__new__(ReportGenerator)
        holder.messages = Messages()
        default = ReportGenerator.DEFAULT_ACTION_QUEUE_ROW_CAP

        holder.config = {}
        self.assertEqual(default, holder.action_queue_row_cap())
        for bad in (0, -5, "lots", None, [3]):
            holder.config = {"serp_overlap": {"action_queue_row_cap": bad}}
            if bad is None:
                self.assertEqual(default, holder.action_queue_row_cap())
                continue
            with self.assertLogs(level="WARNING") as logged:
                self.assertEqual(default, holder.action_queue_row_cap(), bad)
            self.assertIn("action_queue_row_cap", "".join(logged.output))

    def test_the_truncation_note_quotes_the_cap_it_was_given(self):
        """Called with a cap of the test's own choosing, so a note that
        hardcodes the number fails. As a closure over the render's `row_cap`
        it was reachable only through a full render and no guard saw it."""
        from src.reporting import ReportGenerator

        holder = ReportGenerator.__new__(ReportGenerator)
        holder.messages = Messages()
        self.assertEqual("", holder.action_queue_note(7, 7))
        note = holder.action_queue_note(40, 7)
        self.assertIn("7", note)
        self.assertIn("40", note)
        self.assertNotIn("15", note)


class TestTheFileIsReadOncePerRender(unittest.TestCase):
    """The read is outside every per-section handler and happens once. A
    per-section read is both wasteful and the shape that turns "I cannot parse
    my own messages" into a per-section blank."""

    def test_the_report_generator_holds_it(self):
        import inspect

        from src.reporting import ReportGenerator

        self.assertIn("self.messages = Messages()",
                      inspect.getsource(ReportGenerator.__init__))

    def test_the_sections_do_not_construct_their_own(self):
        text = open(os.path.join(SRC, "reporting.py"), encoding="utf-8").read()
        tree = ast.parse(text)
        constructions = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "Messages"]
        self.assertGreater(len(constructions), 0)
        for node in constructions:
            self.assertLess(
                node.lineno,
                _function_line(tree, "generate_summary"),
                "a section builds its own Messages at line %d" % node.lineno)

    def test_no_construction_sits_inside_a_handler(self):
        """A read inside a `try` is how a configuration failure became a
        per-item status in chunk Y16.

        Every module that builds a `Messages`, found by walking `src/` rather
        than by a list: the first version of this guard named two files and
        the pattern was in two others, including an `except` body it would not
        have looked in either (cold review, M5). `db_connect` is the one
        allowed exception and says why in its own source: it is the only
        module that catches `MessagesUnavailable` and degrades.
        """
        allowed = {"db_connect.py"}
        offenders = {}
        builders = 0
        for name, text in _source_files():
            tree = ast.parse(text)
            constructions = [
                node for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Messages"]
            if constructions:
                builders += 1
            if name in allowed:
                continue
            inside = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                # `handlers` as well as `body`: `db_connect` built one inside
                # an `except`, which the first version of this guard missed.
                for stmt in list(node.body) + [
                        s for h in node.handlers for s in h.body]:
                    for inner in ast.walk(stmt):
                        if (isinstance(inner, ast.Call)
                                and isinstance(inner.func, ast.Name)
                                and inner.func.id == "Messages"):
                            inside.add(inner.lineno)
            if inside:
                offenders[name] = sorted(inside)
        self.assertGreater(builders, 2, "the walk found almost no builders")
        self.assertEqual({}, offenders)

    def test_a_row_building_module_resolves_its_words_once(self):
        """`GeoProfile` and `EEATScore` resolve a stored sentence when the ROW
        is built, and a run builds one per audited page. That was ten opens
        and ten parses of a 45 KB file per run (cold review, M5)."""
        script = (
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "import builtins\n"
            "real = builtins.open\n"
            "count = []\n"
            "def counting(path, *a, **k):\n"
            "    if str(path).endswith('briefing_messages.json'):\n"
            "        count.append(path)\n"
            "    return real(path, *a, **k)\n"
            "builtins.open = counting\n"
            "from src.geo_profiler import GeoProfile\n"
            "for _ in range(10):\n"
            "    GeoProfile(url='u', profiled_at='t',\n"
            "               extractability_tier='Strong', signals={},\n"
            "               present_signals=[], why_cited='w')\n"
            "print(len(count))\n" % os.path.join(REPO, "Serp-compete"))
        out = subprocess.run([sys.executable, "-c", script], cwd=REPO,
                             capture_output=True, text=True)
        self.assertEqual("1", out.stdout.strip(), out.stderr)

    def test_an_edited_file_is_re_read(self):
        """The parse is cached on the file's own mtime and size, not on
        nothing: the GUI edits these files between runs in one process, and a
        cache keyed on nothing is how chunk Y16's import-time read became a
        bug."""
        import tempfile
        import time

        briefing_messages.forget_parsed()
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as handle:
            handle.write('{"a": {"b": "first"}}')
            path = handle.name
        try:
            self.assertEqual("first", Messages(path=path).get("a.b"))
            time.sleep(0.01)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"a": {"b": "second"}}')
            self.assertEqual("second", Messages(path=path).get("a.b"))
        finally:
            os.unlink(path)
            briefing_messages.forget_parsed()

    def test_fifty_lookups_do_not_re_read(self):
        """A held instance answers from its own dict.

        This is the weak half of the property — see
        `test_a_render_reads_the_file_once` for the one that renders. The cold
        review found the previous single guard named the render and tested
        this (M5).
        """
        script = (
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "import builtins\n"
            "real = builtins.open\n"
            "count = []\n"
            "def counting(path, *a, **k):\n"
            "    if str(path).endswith('briefing_messages.json'):\n"
            "        count.append(path)\n"
            "    return real(path, *a, **k)\n"
            "builtins.open = counting\n"
            "from src.briefing_messages import Messages\n"
            "m = Messages()\n"
            "for _ in range(50):\n"
            "    m.get('eeat.intro')\n"
            "print(len(count))\n" % os.path.join(REPO, "Serp-compete"))
        out = subprocess.run([sys.executable, "-c", script], cwd=REPO,
                             capture_output=True, text=True)
        self.assertEqual("1", out.stdout.strip(), out.stderr)


def _function_line(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node.lineno
    raise AssertionError("no function %r" % name)


class TestTheProseIsOutOfPython(unittest.TestCase):
    """The migration itself, checked rather than trusted: a reader-facing
    sentence left behind in Python is the state the project rule forbids — "do
    not leave old hardcoded content in place while new content moves to
    config"."""

    #: A string literal this long, outside a docstring, is prose until shown
    #: otherwise. SQL is excluded by keyword, not by length.
    PROSE_LENGTH = 70

    def _prose_literals(self, name):
        """Reader-facing string literals left in *name*.

        Three kinds of long literal are excluded, each for a stated reason:

        * **docstrings** — written for whoever reads the module;
        * **log lines** (the first argument of a `logging`/`logger` call, and
          anything carrying a `%s`-style placeholder) — written for whoever is
          watching the run, not for the briefing. Tool 1 draws the same line:
          `gsc_messages.yml` holds that section's report lines while the
          `logging.warning` calls beside them are Python literals;
        * **SQL**, by keyword.

        And one named exemption, `db_connect.FALLBACK_*`: see M4 in the cold
        review and the comment above those two constants. They are said from
        inside an `except` and from an `atexit` hook, where asking a file that
        may be the thing that is broken turns a warning into a failure.
        """
        text = open(os.path.join(SRC, name), encoding="utf-8").read()
        tree = ast.parse(text)
        log_lines = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            target = getattr(func, "attr", getattr(func, "id", ""))
            if target not in ("debug", "info", "warning", "error",
                              "exception", "critical", "print"):
                continue
            for arg in node.args:
                for part in ast.walk(arg):
                    if isinstance(part, ast.Constant):
                        log_lines.add(id(part))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None and node.body:
                    docstrings.add(node.body[0].lineno)
        out = []
        exempt = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if not any(n.startswith("FALLBACK_") for n in names):
                continue
            for part in ast.walk(node.value):
                if isinstance(part, ast.Constant):
                    exempt.add(id(part))
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str):
                continue
            if (node.lineno in docstrings or id(node) in log_lines
                    or id(node) in exempt):
                continue
            value = " ".join(node.value.split())
            if "%s" in value or "%r" in value or "%d" in value:
                # A format string for a log call reached by a name this walk
                # does not recognise. Excluded by the same reason as above.
                continue
            if len(value) < self.PROSE_LENGTH:
                continue
            if any(word in value for word in (
                    "SELECT ", "FROM ", "WHERE ", "GROUP BY", "ORDER BY",
                    "INSERT INTO", "INSERT OR REPLACE", "UPDATE ",
                    "DELETE FROM", "CREATE TABLE", "ALTER TABLE",
                    "VALUES (")):
                continue
            out.append((node.lineno, value[:90]))
        return out

    def test_the_two_exempt_fallbacks_are_the_only_ones(self):
        """The exemption is a named pair, not a door. Both are in
        `db_connect`, both are said where asking a file that may itself be
        broken would turn a warning into a failure (cold review, M4)."""
        names = []
        for name, text in _source_files():
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Assign):
                    names += [f"{name}:{t.id}" for t in node.targets
                              if isinstance(t, ast.Name)
                              and t.id.startswith("FALLBACK_")]
        self.assertEqual(
            ["db_connect.py:FALLBACK_BAD_LOCK_TIMEOUT",
             "db_connect.py:FALLBACK_CLEANUP_WARNING"], sorted(names))

    def test_the_report_renderer_carries_no_prose(self):
        self.assertEqual([], self._prose_literals("reporting.py"))

    def test_the_modules_the_report_renders_from_carry_none_either(self):
        """`risk_radar`, `db_connect` and `geo_profiler` render into this
        report, and leaving their sentences in Python while `reporting.py`'s
        moved is the half-migrated state the rule names (P5).

        `gsc_performance` and `competitor_mining` write standalone markdown
        reports of their own rather than into the briefing, and were not in
        this list when the chunk was first built — so every sentence of
        `gsc_strike_list.md`, `gsc_strategic_gap.md` and
        `competitor_keyword_gaps.md` stayed in Python, two of them near-
        identical rewordings of keys that had moved. Added by the cold review
        (M8)."""
        for name in ("risk_radar.py", "db_connect.py", "geo_profiler.py",
                     "reframe_engine.py", "eeat_scorer.py",
                     "gsc_performance.py", "competitor_mining.py"):
            self.assertEqual([], self._prose_literals(name), name)


class TestTheThreeFailuresTheGateFoundUnguarded(unittest.TestCase):
    """Three of the cold review's own fixes had no consequence test, which the
    mutation gate reported as vacuous: reverting them failed nothing.

    All three are about a failure that must NOT propagate — a typo in a
    hand-edited file, a prompt block the file does not carry, and the one
    module that is allowed to degrade when the file cannot be read at all.
    """

    def setUp(self):
        briefing_messages.reset_misses()

    tearDown = setUp

    def test_a_stray_brace_renders_a_marker_rather_than_aborting(self):
        """`str.format` raises `ValueError: Single '{' encountered` on an
        unbalanced brace. The file is documented as hand-editable, so that is
        the expected typo, and it used to abort the whole render from inside
        `get` — after this module's docstring promised that a report with one
        hole beats a render that dies on its last section (M3)."""
        messages = Messages(data={"a": {"b": "a { stray brace"}})
        rendered = messages.get("a.b")
        self.assertIn("message missing", rendered)
        self.assertIn("a.b", rendered)
        self.assertEqual(1, len(messages.missing))
        self.assertIn("malformed message", messages.missing[0])

    def test_a_prompt_block_the_file_lacks_stops_the_call(self):
        """`prompt()` returns `None` and the engine returns `generated: False`
        without calling the model. With `get`'s policy instead, the marker
        would be sent as the prompt, paid for, and the answer written into the
        briefing as a reframe while nothing in the report said a hedge was
        missing (H1)."""
        from unittest import mock

        from src.reframe_engine import ReframeEngine

        data = json.loads(json.dumps(load_messages()))
        del data["reframes"]["prompt"]["body"]
        engine = ReframeEngine(messages=Messages(data=data))
        engine.client = mock.MagicMock()

        out = engine.generate_bowen_reframe("couples counselling",
                                            "https://example.com/x", 4)

        self.assertFalse(out["generated"])
        self.assertEqual({}, out["usage"])
        engine.client.chat.completions.create.assert_not_called()
        self.assertTrue(any("reframes.prompt.body" in key
                            for key in Messages(data=data).missing),
                        "the miss was not recorded, so the report's count "
                        "does not include a reframe that was never attempted")

    def test_the_cleanup_warning_degrades_when_the_file_cannot_be_read(self):
        """`db_connect` is the one module allowed to degrade: its two
        sentences are said from inside an `except` and from an `atexit` hook,
        where asking a file that may itself be the broken thing turns a
        warning into a failure (M4)."""
        from unittest import mock

        from src import db_connect

        with mock.patch("src.briefing_messages.Messages",
                        side_effect=MessagesUnavailable("gone")):
            db_connect._CLEANUP_FAILURES[(db_connect.CLOSE, "/a.db")] = 1
            try:
                warning = db_connect.cleanup_failure_warning()
            finally:
                db_connect.reset_cleanup_failures()

        self.assertIn("1 database cleanup step(s) failed", warning)
        self.assertIn("built-in wording", warning)


class TestTheDeadConfigStringsAreGone(unittest.TestCase):
    """`eeat_client_messaging` and three `framework_caption` entries were
    editorial reader-facing text in `shared_config.json` that no module read.
    They are in the messages file now, and gone from there, so there is one
    home per sentence."""

    def setUp(self):
        with open(os.path.join(REPO, "shared_config.json"),
                  encoding="utf-8") as handle:
            self.config = json.load(handle)

    def test_the_eeat_block_is_gone_from_the_config(self):
        self.assertNotIn("eeat_client_messaging", self.config)

    def test_no_section_keeps_an_unread_framework_caption(self):
        carriers = sorted(name for name, block in self.config.items()
                          if isinstance(block, dict)
                          and "framework_caption" in block)
        self.assertEqual([], carriers)

    def test_the_third_eeat_wording_moved_too(self):
        """The plan counted three wordings of the EEAT heuristic caveat and
        there were four: the rendered sentence, the module docstring, the
        unread config entry, and a dataclass default stored on every score
        row. This chunk's own prose guard found the fourth."""
        from src.eeat_scorer import EEATScore

        self.assertEqual(Messages().raw("eeat.row_caveat"),
                         EEATScore.__dataclass_fields__[
                             "caveat"].default_factory())

    def test_the_stored_extractability_caveat_moved_too(self):
        from src.geo_profiler import GeoProfile

        self.assertEqual(Messages().raw("extractability.profile_caveat"),
                         GeoProfile.__dataclass_fields__[
                             "caveat"].default_factory())

    def test_the_owners_words_were_not_lost(self):
        messages = Messages()
        self.assertIn("not Google's proprietary EEAT model",
                      messages.get("eeat.caveat"))
        self.assertIn("barbell is a strategic framing",
                      messages.get("positioning.framework_caption"))

    def test_the_reframe_fallback_went_to_its_siblings_instead(self):
        """`strike_mapper.generic_reframe` is a member of the reframe
        vocabulary, which has been in `shared_config.json` since an earlier
        migration — not a sentence the briefing renders."""
        from src import strike_mapper

        self.assertIn("generic_reframe", self.config["strike_mapper"])
        self.assertEqual(self.config["strike_mapper"]["generic_reframe"],
                         strike_mapper.generic_reframe())
        self.assertIsNone(Messages().raw("strike_mapper.generic_reframe"))

    def test_the_idempotency_markers_stayed_in_python(self):
        """`PROVENANCE_MARKER` and `INJECTION_POINT` are byte-matched against
        what earlier runs wrote into a file the owner hand-edits. Moving either
        duplicates headings, which is the bug that module already had once."""
        from src import strike_mapper

        self.assertEqual("<!-- strike-mapper -->",
                         strike_mapper.PROVENANCE_MARKER)
        self.assertIsNone(Messages().raw("strike_mapper.provenance_marker"))


class TestTheFormatContractStayedInPython(unittest.TestCase):
    """Not everything reader-facing is editorial. The workbook's sheet names
    and column headers are a contract consumers and tests read by name, and
    Tool 1's rule is explicit that they are never renamed.

    `Traffic Magnets` is both an Excel sheet name and a report heading, which
    is why this is checked at the `sheet_name=` argument rather than by
    looking for the words: the heading moved to `headings.magnets` and the
    sheet name must not follow it.
    """

    def test_every_sheet_name_is_a_literal(self):
        text = open(os.path.join(SRC, "reporting.py"), encoding="utf-8").read()
        names = [node for node in ast.walk(ast.parse(text))
                 if isinstance(node, ast.Call)
                 for kw in node.keywords
                 if kw.arg == "sheet_name"
                 for node in [kw.value]]
        self.assertGreater(len(names), 10,
                           "the walk found almost no sheet names")
        composed = [ast.dump(node)[:60] for node in names
                    if not isinstance(node, ast.Constant)]
        self.assertEqual([], composed,
                         "a sheet name is being composed rather than written "
                         "out; the workbook's names are a contract")

    def test_the_sheet_names_are_the_ones_consumers_read(self):
        text = open(os.path.join(SRC, "reporting.py"), encoding="utf-8").read()
        for sheet in ("Competitor Summary", "Traffic Magnets", "EEAT Scores",
                      "GEO Extractability", "AI Share-of-Voice"):
            self.assertIn(f"sheet_name='{sheet}'", text, sheet)


class TestTheFileItselfIsWellFormed(unittest.TestCase):
    def test_it_parses_and_holds_an_object(self):
        self.assertIsInstance(load_messages(), dict)

    def test_the_path_is_named_once(self):
        """The Y12 / Y16 rule: one definition of the path to a file."""
        hits = [name for name, text in _source_files()
                if '"briefing_messages.json"' in text]
        self.assertEqual(["briefing_messages.py"], hits)

    def test_the_marker_names_the_key_it_could_not_find(self):
        self.assertIn("{key}", briefing_messages.MISSING_MARKER)

    def test_a_list_value_is_joined_rather_than_rendered_as_a_list(self):
        """JSON has no block scalars, so a long sentence may be written as a
        list of fragments."""
        messages = Messages(data={"a": {"b": ["one", "two"]}})
        self.assertEqual("one two", messages.get("a.b"))

    def test_plural_picks_the_form_by_count(self):
        messages = Messages(data={"a": {"b": {"one": "{count} thing",
                                              "many": "{count} things"}}})
        self.assertEqual("1 thing", messages.plural("a.b", 1))
        self.assertEqual("3 things", messages.plural("a.b", 3))

    def test_the_sov_sentences_have_both_forms(self):
        """Four grammatical-number switches lived inside two f-strings:
        `{'these engines' if len(x) > 1 else 'this engine'}`. Half a sentence
        in Python is still a sentence in Python."""
        data = load_messages()["sov"]
        for key in ("not_measured", "coverage_unknown"):
            self.assertEqual({"one", "many"}, set(data[key]))
            self.assertIn("this engine", data[key]["one"])
            self.assertIn("these engines", data[key]["many"])


class TestTheCallSitesUseTheReaders(unittest.TestCase):
    """A reader that returns the configured value proves nothing on its own:
    the call site can still hold the literal beside it. Each of these patches
    the reader and looks at what the caller produced."""

    def test_the_reframe_heading_uses_the_configured_fallback(self):
        """`test_strike_mapper.py` asserts `generic_reframe()` returns the
        config value, which a hardcoded call site passes unchanged. Found
        vacuous by this chunk's mutation gate."""
        from unittest.mock import patch

        from src import strike_mapper

        with patch.object(strike_mapper, "generic_reframe",
                          return_value="A Configured Reframe"):
            headings = strike_mapper.headings_for(["a query"], vocabulary={})
        self.assertIn("A Configured Reframe", headings[0])


def test_a_rendered_briefing_carries_its_markers_and_their_count(
        tmp_path, monkeypatch):
    """The whole contract, through one real render.

    The two guards this replaces read `generate_summary`'s source, and the
    mutation gate walked through both: a `report.extend(...)` inside a comment
    still satisfies a `source.index(...)`. This renders a briefing against a
    messages file with one key removed and reads the markdown.
    """
    from unittest.mock import patch

    from src import briefing_messages
    from tests.test_main_run_coverage import (_FakeAuditor, _prepare,
                                              _run_audit_with_fakes)

    config, config_path, db_path, handoff_path = _prepare(tmp_path, monkeypatch)

    whole = briefing_messages.load_messages()
    removed = "executive_summary.intro"
    section, key = removed.split(".")
    holed = {name: (dict(block) if isinstance(block, dict) else block)
             for name, block in whole.items()}
    assert key in holed[section]
    del holed[section][key]

    with patch.object(briefing_messages, "load_messages", return_value=holed):
        rendered = _run_audit_with_fakes(tmp_path, db_path, config, config_path,
                                         handoff_path, _FakeAuditor())
    # The harness captures one markdown per run.
    markdown = "\n".join(rendered)

    assert f"[message missing: {removed}]" in markdown, (
        "a key the file does not carry must be visible in the briefing, not a "
        "sentence that quietly vanished")
    assert "1 report message(s) could not be found" in markdown, (
        "the render must count its own markers (P2), and the count must reach "
        "the markdown rather than only the log")
    assert removed in markdown.rsplit("could not be found", 1)[1], (
        "the count must name the key it could not find"
    )


class TestTheLedgerIsTheProcessNotTheInstance(unittest.TestCase):
    """`shortfall_line` is called by the report, so a miss recorded by any
    other consumer's throwaway instance has to reach it (cold review, H2).

    This is the mechanism; the end-to-end test below is one consumer walked
    through a real run. The mechanism is tested separately because which
    consumers a given run reaches depends on the data — a run with no anchor
    spam never asks for the anchor-spam caveat, so an end-to-end test alone
    cannot cover all six.
    """

    def setUp(self):
        briefing_messages.reset_misses()

    tearDown = setUp

    def test_one_consumers_miss_is_in_anothers_count(self):
        throwaway = Messages()
        throwaway.get("geo_profiler.asked.for.nothing")
        report = Messages()
        self.assertIn("geo_profiler.asked.for.nothing",
                      report.shortfall_line())

    def test_the_count_covers_every_consumer(self):
        for consumer in ("a.one", "b.two", "c.three"):
            Messages().get(consumer)
        line = Messages().shortfall_line()
        self.assertIn("3", line)
        for consumer in ("a.one", "b.two", "c.three"):
            self.assertIn(consumer, line)

    def test_a_reset_is_what_separates_two_runs(self):
        """The GUI runs twice in one process; the second briefing must count
        its own holes. `main.run_audit` resets, the way it already resets the
        cleanup tally (chunk Y13)."""
        Messages().get("first.run.hole")
        briefing_messages.reset_misses()
        self.assertEqual("", Messages().shortfall_line())

    def test_the_entry_point_resets_it(self):
        source = open(os.path.join(SRC, "main.py"), encoding="utf-8").read()
        tree = ast.parse(source)
        run_audit = next(node for node in ast.walk(tree)
                         if isinstance(node, ast.FunctionDef)
                         and node.name == "run_audit")
        calls = [node for node in ast.walk(run_audit)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "reset_misses"]
        self.assertEqual(1, len(calls),
                         "run_audit must forget the previous run's holes")


@pytest.mark.parametrize("removed", [
    # reporting.py's own key — the only consumer whose misses the count saw
    # before the cold review.
    "executive_summary.intro",
    # Asked for by `anchor_coverage_lines`, which `comparison_features` calls
    # with no `messages` of its own — one of the six consumers that built a
    # throwaway `Messages` whose misses the report's count could not see
    # (cold review, H2). Its own output goes to the console, so the only place
    # a hole in it can be reported is the report's count.
    "risk_radar.console_coverage",
])
def test_a_hole_in_any_consumers_key_is_counted(tmp_path, monkeypatch, removed):
    """One render, one key removed, wherever that key is asked from.

    The ledger is process-level for this reason: `shortfall_line` is called by
    the report, and before the fix it could only see what the report itself
    had asked for.
    """
    from unittest.mock import patch

    from src import briefing_messages
    from tests.test_main_run_coverage import (_FakeAuditor, _prepare,
                                              _run_audit_with_fakes)

    config, config_path, db_path, handoff_path = _prepare(tmp_path, monkeypatch)

    whole = briefing_messages.load_messages()
    section, key = removed.split(".", 1)
    holed = {name: (dict(block) if isinstance(block, dict) else block)
             for name, block in whole.items()}
    assert key in holed[section], f"{removed} is not in the shipped file"
    del holed[section][key]

    briefing_messages.reset_misses()
    with patch.object(briefing_messages, "load_messages", return_value=holed):
        rendered = _run_audit_with_fakes(tmp_path, db_path, config, config_path,
                                         handoff_path, _FakeAuditor())
    markdown = "\n".join(rendered)
    briefing_messages.reset_misses()

    assert "could not be found" in markdown, (
        f"a hole in {removed} was not counted in the briefing; the ledger "
        f"does not reach the consumer that asks for it")
    assert removed in markdown.rsplit("could not be found", 1)[1], (
        f"the count did not name {removed}")


def test_a_render_reads_the_file_once(tmp_path, monkeypatch):
    """Counted across a real run, not across fifty lookups on a held dict.

    The guard this replaces named the render and tested a dict (cold review,
    M5): the real answer was ten opens and ten parses, one per audited page,
    because `GeoProfile` resolves a stored sentence when the row is built.
    """
    from tests.test_main_run_coverage import (_FakeAuditor, _prepare,
                                              _run_audit_with_fakes)

    config, config_path, db_path, handoff_path = _prepare(tmp_path, monkeypatch)

    opens = []
    real_open = open

    def counting(path, *args, **kwargs):
        if str(path).endswith("briefing_messages.json"):
            opens.append(str(path))
        return real_open(path, *args, **kwargs)

    import builtins
    monkeypatch.setattr(builtins, "open", counting)
    _run_audit_with_fakes(tmp_path, db_path, config, config_path,
                          handoff_path, _FakeAuditor())
    monkeypatch.undo()

    assert len(opens) <= 1, (
        f"the messages file was opened {len(opens)} times in one run; it is "
        f"parsed once per version of the file")


if __name__ == "__main__":
    unittest.main()
