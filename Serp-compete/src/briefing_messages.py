"""The words the strategic briefing prints, read from `briefing_messages.json`.

Tool 1 has ten editorial text files. Until this module Tool 2 had none, and
every sentence the briefing renders was a Python literal: the caveats, the
comparability warnings, the "why there is no number here" lines, the section
introductions. The rule both repos are built on says they do not belong there
— "if a non-developer reading the file might reasonably want to change a
value, it's editorial" — and these sentences are the hedges on the figures.
What a number does not mean, which population it was measured over, why a cell
is blank rather than zero: the owner is the person who would reword them, and
the only person who can say whether a hedge reads honestly.

Three things in the code are why this was a defect and not a preference:

* the EEAT heuristic caveat existed in THREE wordings — rendered from
  `reporting.py`, as a docstring in `eeat_scorer.py`, and in
  `shared_config.eeat_client_messaging.caveat`, which is the right place for
  it and which no module read;
* the handoff's page-relative ranks were warned about in FOUR separately
  worded places, so rewording the fact meant finding all four, and no
  de-duplication finds them because they are not duplicates;
* `UNKNOWN_CELL` had a bare `"—"` duplicate beside it.

## Two rules, because the two failures are not alike

**A missing or malformed FILE raises.** Tool 1's `report_writing_directives.yml`
degrades to no directives rather than aborting a report, and this is
deliberately the opposite. Directives are advice to a model; these sentences
are the hedges on the report's own figures, and a briefing rendered without
its caveats is a briefing that overstates every number in it, confidently and
silently. That is worse than a stopped render — the same judgement chunk Y16
made about the scoring config.

**A missing KEY renders a visible marker and is logged.** An owner part-way
through an edit gets a report that says where the hole is, not a sentence that
quietly vanished (P2). The marker is counted so the render can report "N
message(s) missing" rather than leaving it to whoever reads the log.

The file is read ONCE per render and held, which is the shape chunk Y16's cold
review arrived at: outside every per-section handler, so a failure stops the
render before the first section instead of becoming a per-section blank.

Spec: docs/review_2026-11-04/PLAN_Y17_the_briefing_prose_gets_a_file.md
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

#: The repo root — this module lives at `Serp-compete/src/`.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

#: The one definition of the path (the Y12 / Y16 rule: named once).
MESSAGES_PATH = os.path.join(PROJECT_ROOT, "briefing_messages.json")

#: Every key this PROCESS asked for and could not use, in order.
#:
#: Process-level, not per-`Messages`, because the count has to reach the one
#: place that prints it. `ReportGenerator` holds its own instance, but six
#: other consumers build a throwaway one — `ReframeEngine`, `GeoProfile`,
#: `EEATScore`, `detect_anchor_spam`, `cleanup_failure_warning`,
#: `anchor_coverage_lines` — and their markers land in the briefing or in a
#: database row while the report's own count read zero and printed nothing.
#: `README.md` and the user manual state the count as a guarantee, so the
#: ledger is where every consumer can reach it. Same shape as
#: `db_connect._CLEANUP_FAILURES`, and reset the same way, by the entry point
#: at the start of a run.
_MISSES: List[str] = []


def reset_misses() -> None:
    """Forget what earlier runs in this process could not find.

    Called by the entry point at the start of a run (`main.run_audit`), so one
    GUI session's second run does not report the first run's holes. Never
    called by a consumer: a consumer that reset it would hide the misses of
    everything built before it.
    """
    _MISSES.clear()


def misses() -> List[str]:
    """What this process could not find, as a copy."""
    return list(_MISSES)


#: What a key the file does not carry renders as. Visible in the report on
#: purpose: a sentence that silently disappears is the failure mode this file
#: exists to make impossible, and a blank line in a briefing reads as "there
#: was nothing to say here".
MISSING_MARKER = "[message missing: {key}]"


class MessagesUnavailable(RuntimeError):
    """The messages file is absent or will not parse.

    Raised rather than degraded. See the module docstring: the alternative is
    a briefing that renders every figure with none of its hedges.
    """


#: The last parse, keyed on what an edit changes: `(path, mtime_ns, size)`.
#:
#: Not a convenience. `GeoProfile` and `EEATScore` resolve a stored sentence
#: when the ROW is built, and a run builds one per audited page, so a 45 KB
#: file was being opened and parsed ten times per run and again per
#: anchor-spam detection and per reframe (measured by the cold review of
#: chunk Y17, M5).
#:
#: Keyed on the file's own mtime and size rather than on nothing, which is the
#: distinction chunk Y16 drew: a cache keyed on nothing is how an import-time
#: read became a bug, and the GUI edits these files between runs in one
#: process. An edit changes mtime, so the next read picks it up.
_PARSED: Dict[tuple, Dict[str, Any]] = {}


def load_messages(path: str = None) -> Dict[str, Any]:
    """The parsed messages file. Raises `MessagesUnavailable` if it cannot be.

    *path* is for tests. The file ships in the repo and is tracked, so an
    absent one is a broken checkout, not a configuration choice — which is why
    this does not return `{}` the way `config_io.load_config` does for an
    absent `shared_config.json`.

    Parsed once per version of the file; see `_PARSED`.
    """
    path = path or MESSAGES_PATH
    try:
        stat = os.stat(path)
        fingerprint = (os.path.abspath(path), stat.st_mtime_ns, stat.st_size)
        cached = _PARSED.get(fingerprint)
        if cached is not None:
            return cached
    except OSError:
        # Report the real reason below, where the message is written.
        fingerprint = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as exc:
        raise MessagesUnavailable(
            f"{path} is missing. The briefing's caveats and comparability "
            f"warnings live in it; rendering without them would state every "
            f"figure with none of its hedges.") from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise MessagesUnavailable(
            f"{path} could not be read: {exc}") from exc
    if not isinstance(data, dict):
        raise MessagesUnavailable(
            f"{path} does not hold an object at its top level, so it carries "
            f"no message sections.")
    if fingerprint is not None:
        _PARSED[fingerprint] = data
    return data


def forget_parsed() -> None:
    """Drop the parse cache. For tests that write a file twice in one second."""
    _PARSED.clear()


class Messages:
    """The messages of one render, held.

    Read once, outside every per-section handler, so a failure stops the
    render rather than turning into a per-section blank (the shape chunk Y16's
    cold review arrived at).
    """

    def __init__(self, data: Dict[str, Any] = None, path: str = None):
        self._data = load_messages(path) if data is None else data

    # ---- reading ---------------------------------------------------------

    def raw(self, key: str, /) -> Any:
        """The value at a dotted *key*, or `None` when it is not there.

        Does NOT record a miss: used by callers that legitimately ask whether
        an optional section is present.
        """
        node: Any = self._data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def _resolve(self, key: str, fields: dict):
        """`(text, None)` or `(None, why)`. The one resolver both policies sit on.

        `get` turns a failure into a visible marker; `prompt` turns it into
        `None`. Splitting them here keeps one definition of what "resolved"
        means (P32).
        """
        value = self.raw(key)
        if value is None:
            return None, "no such key"
        if isinstance(value, list):
            # JSON has no block scalars, so a long sentence may be a list of
            # fragments.
            value = " ".join(str(part) for part in value)
        if not isinstance(value, str):
            return None, "not a string"
        if "{" not in value:
            # No placeholders, so nothing to fill and nothing to get wrong.
            return value, None
        try:
            return value.format(**fields), None
        except (KeyError, IndexError) as exc:
            # The CALLER passed no value for a placeholder the message
            # carries, `fields` empty included — an earlier shortcut returned
            # the raw text in that case, so a caller that forgot its arguments
            # printed a literal `{domain}` into the briefing and nothing
            # counted it (P2).
            return None, f"no value for {exc}"
        except (ValueError, TypeError) as exc:
            # The MESSAGE is malformed: an unbalanced or literal brace raises
            # `ValueError: Single '{' encountered`, a bad conversion or
            # subscript a `TypeError`. The file is documented as
            # hand-editable, so a stray brace is the expected typo, and it
            # used to abort the whole render from inside `get` — after this
            # module's own docstring promised a report with one hole beats a
            # render that dies on the last section (P40/P45).
            return None, f"malformed message ({exc})"

    def prompt(self, key: str, /, **fields: Any):
        """A prompt block, or `None` when the file does not carry it.

        NOT a marker, which is the policy for everything the reader sees. A
        marker in an LLM prompt is sent to the model, paid for, and its answer
        is written into the briefing as a reframe — while nothing in the report
        says a hedge went missing, because the prompt is not rendered. The
        caller's job is to not make the call (P14).

        The miss is still recorded, so the render's count includes it.
        """
        text, why = self._resolve(key, fields)
        if text is None:
            self._miss(f"{key} ({why}; the model was not called)")
        return text

    def get(self, key: str, /, **fields: Any) -> str:
        """The message at a dotted *key*, with `{placeholders}` filled.

        A key the file does not carry renders `MISSING_MARKER` and is recorded
        (P2 — surfaced, never silently dropped). A placeholder the caller did
        not supply is also recorded rather than raising, because a report that
        renders with one hole beats a render that dies on the last section.

        *key* is POSITIONAL-ONLY, and so are `raw`'s and `plural`'s. Every
        remaining argument is a placeholder value, and a message with a
        `{key}` or `{count}` placeholder — `db_cleanup.bad_lock_timeout` has
        one — otherwise collides with the parameter name and raises
        "got multiple values for argument 'key'". One message carrying that
        placeholder found it; every future one would have found it again.
        """
        text, why = self._resolve(key, fields)
        if text is None:
            self._miss(key if why == "no such key" else f"{key} ({why})")
            return MISSING_MARKER.format(key=key)
        return text

    def plural(self, key: str, count: int, /, **fields: Any) -> str:
        """`<key>.one` when *count* is 1, `<key>.many` otherwise.

        Grammatical number is part of the sentence, so it lives in the file.
        `sov.not_measured` used to interpolate
        `{'these engines' if len(x) > 1 else 'this engine'}` — half a sentence
        in Python is still a sentence in Python.
        """
        return self.get(f"{key}.one" if count == 1 else f"{key}.many",
                        count=count, **fields)

    @property
    def missing(self) -> List[str]:
        """What THIS PROCESS could not find — see `_MISSES`.

        A property onto the module ledger rather than a per-instance list, so
        there is one definition of "what went missing" (P32) and the report's
        count covers every consumer rather than only its own keys.
        """
        return list(_MISSES)

    def _miss(self, key: str) -> None:
        _MISSES.append(key)
        logger.warning("briefing_messages.json carries no message for %r; the "
                       "report prints a marker in its place.", key)

    # ---- what the render says about its own holes -------------------------

    def shortfall_line(self) -> str:
        """The line a report carries when it printed a marker, or `""`.

        The markers are in the body already; this is the count, so the reader
        does not have to find them (P2 — "N of M", not a silent subset).
        """
        missed = self.missing
        if not missed:
            return ""
        # The count is taken before asking for the shortfall message, so a
        # missing `messages.shortfall` prints its own marker with the count of
        # everything else rather than counting itself (noted by the cold
        # review as L3 and left as the lesser of the two: a count that
        # includes the failure to report the count is harder to read than one
        # that does not).
        return self.get("messages.shortfall", count=len(missed),
                        keys=", ".join(missed))
