"""db_connect.py — one way to open the SQLite database and close it again.

`with sqlite3.connect(path) as conn:` commits on a clean exit and rolls back
on an exception, but it never closes the connection: the handle is released
whenever the object happens to be collected. `with closing(sqlite3.connect(
path)) as conn:` is the opposite trap — it closes the handle and discards the
commit, because `closing` does not run the connection's own `__exit__`, so
every write inside the block is rolled back by the close.

This module does both, once, so no call site has to pair them. It is the same
helper Tool 1 (`serp-discover`) got in review chunk Y9; Tool 2 had the same
class of site one level further in, behind `DatabaseManager._get_connection`
(review chunk Y10). Review chunk Y11 fixed the two things that first version
got wrong, in both repos: a failing rollback or close no longer replaces the
exception that caused it, and the lock wait is a configured number rather
than sqlite3's undeclared default.

Spec: docs/review_2026-11-04/PLAN_Y11_a_rollback_is_not_the_diagnosis.md
Tests: Serp-compete/tests/test_y10_tool2_closes_its_handles.py,
       Serp-compete/tests/test_y11_a_rollback_is_not_the_diagnosis.py
"""

import atexit
import logging
import sqlite3
import sys
from contextlib import contextmanager

logger = logging.getLogger(__name__)

#: sqlite3's own default for `connect(timeout=)`, named here because it was
#: being used without being chosen. It is how long a writer waits for another
#: writer's lock before raising `database is locked`. It matters in this repo
#: because the Streamlit orchestrator and an audit write the same file.
DEFAULT_LOCK_TIMEOUT_SECONDS = 5.0

#: Where the wait is configured in `shared_config.json`.
LOCK_TIMEOUT_KEY = ("technical", "db_lock_timeout_seconds")


def lock_timeout_from_config(config) -> float:
    """The configured SQLite lock wait, in seconds, from a loaded config.

    A non-positive, non-numeric or boolean value is reported and the
    documented default used: zero would make every concurrent write fail at
    once, and a wait that could be switched off is not a wait. The same rule
    Tool 1 applies through `timeouts.seconds_from_config`; this repo has no
    such module, so the rule is here, once, rather than at the two gateways
    that need it.
    """
    section_name, key = LOCK_TIMEOUT_KEY
    section = (config or {}).get(section_name) if isinstance(config, dict) else None
    if not isinstance(section, dict) or key not in section:
        return DEFAULT_LOCK_TIMEOUT_SECONDS
    raw = section[key]
    try:
        if isinstance(raw, bool):
            raise ValueError("boolean")
        seconds = float(raw)
        if not 0 < seconds < float("inf"):
            raise ValueError("not a positive number")
    except (TypeError, ValueError):
        logger.warning("%s", _words(
            "db_cleanup.bad_lock_timeout",
            FALLBACK_BAD_LOCK_TIMEOUT, section=section_name, key=key,
            raw=raw, default=DEFAULT_LOCK_TIMEOUT_SECONDS))
        return DEFAULT_LOCK_TIMEOUT_SECONDS
    return seconds


#: Said when `briefing_messages.json` itself cannot be read. These are the ONLY
#: two sentences in this repo with a Python fallback, and the reason is the
#: place they are said from, not the sentence: one is inside the `except` of a
#: misconfigured lock timeout and the other runs from an `atexit` hook. The
#: loader raises on an unreadable file, deliberately — a briefing without its
#: caveats states every figure as fact — but raising HERE turns a warning about
#: a bad config value into a failure of the database path, and raising from
#: `atexit` is swallowed as "Error in atexit._run_exitfuncs", which loses the
#: chunk-Y13 guarantee that a cleanup failure is always reported, exactly when
#: something else is already broken (cold review of Y17, M4).
FALLBACK_BAD_LOCK_TIMEOUT = (
    "{section}.{key} is {raw}, which is not a number of seconds; waiting "
    "{default} for another writer's lock. (briefing_messages.json could not "
    "be read, so this is the built-in wording.)")

FALLBACK_CLEANUP_WARNING = (
    "{failures} database cleanup step(s) failed ({detail}). "
    "(briefing_messages.json could not be read, so this is the built-in "
    "wording; the figures this run wrote are unaffected by the cleanup.)")


def _words(key, fallback, /, *, messages=None, **fields):
    """A message, or *fallback* when the messages file cannot be read.

    Only for the two call sites above. Everywhere else an unreadable file
    stops the render, which is the point of the loader's contract.

    *key* and *fallback* are positional-only and *messages* keyword-only for
    the reason `Messages.get` is: `db_cleanup.bad_lock_timeout` carries a
    `{key}` placeholder, and any ordinary parameter of that name collides with
    it ("got multiple values for argument 'key'"). Found twice now, once in
    each class of helper.
    """
    try:
        from src.briefing_messages import Messages, MessagesUnavailable
    except ImportError:          # pragma: no cover - defensive
        return fallback.format(**fields)
    try:
        return (messages or Messages()).get(key, **fields)
    except MessagesUnavailable:
        logger.warning("briefing_messages.json could not be read, so the "
                       "built-in wording is used for %r.", key)
        return fallback.format(**fields)


#: The words for the tally below live in `briefing_messages.json` under
#: `db_cleanup` (chunk Y17). Tool 1 keeps the same sentence in `serp_vocab.yml`
#: under `db_cleanup`; until Y17 this repo had no editorial text file at all,
#: so the wording was four constants here and the two repos had to be changed
#: together with nothing but a comment saying so.
#:
#: WHICH consequence the sentence may claim stays in Python, because it is a
#: fact about what failed rather than a choice of words: a failed `close` comes
#: after the commit, so the writes are durable, while a failed `roll back`
#: means a block raised and its transaction was abandoned, which is not "the
#: figures stand" (the cold review of chunk Y13, P6).
#: The step name `_safely` records for a rollback, so the consequence can be
#: chosen by what actually failed rather than by a string literal repeated in
#: two places (P32).
ROLL_BACK = "roll back"
CLOSE = "close"

#: How many times each cleanup step failed in this process, keyed by
#: `(what, db_path)`. One log line per occurrence is not the same fact as
#: "this happened 437 times", and only the second is actionable: the audit
#: opens and closes a connection inside its per-domain loop, so a `close()`
#: that fails once has usually failed every time, each one holding a file
#: handle open (P2, review chunk Y13).
_CLEANUP_FAILURES: dict = {}
_REPORTED = False


def cleanup_failures() -> dict:
    """A copy of this process's tally, keyed by `(what, db_path)`."""
    return dict(_CLEANUP_FAILURES)


def cleanup_failure_count() -> int:
    """How many cleanup steps failed in this process, in total."""
    return sum(_CLEANUP_FAILURES.values())


def reset_cleanup_failures() -> None:
    """Start a fresh tally, and let it be reported again.

    Clearing the tally without clearing "already reported" would leave a
    second run in the same process unable to report at exit — which the test
    suite, running both in one process, is exactly the case for.
    """
    global _REPORTED
    _CLEANUP_FAILURES.clear()
    _REPORTED = False


def cleanup_failure_warning(messages=None):
    """The reader-facing sentence for this process's tally, or None.

    *messages* is the render's already-loaded `Messages` (P25). With none it
    reads the file now — this is called from an `atexit` hook and from
    callers that have no report in hand.
    """
    if not _CLEANUP_FAILURES:
        return None
    # Steps, not paths: "3 x close" is the actionable fact.
    by_step: dict = {}
    for (what, _db_path), count in _CLEANUP_FAILURES.items():
        by_step[what] = by_step.get(what, 0) + count
    detail = ", ".join(
        _words("db_cleanup.detail_item", "{count} x {what}",
               messages=messages, count=count, what=what)
        for what, count in sorted(by_step.items()))
    consequence = _words("db_cleanup.consequence_rolled_back"
                         if ROLL_BACK in by_step
                         else "db_cleanup.consequence_committed",
                         "", messages=messages)
    return _words("db_cleanup.warning", FALLBACK_CLEANUP_WARNING,
                  messages=messages, failures=cleanup_failure_count(),
                  detail=detail, consequence=consequence)


def report_cleanup_failures(printer=None) -> str | None:
    """Print the tally once, wherever a run ends, and return what was printed.

    Every entry point in this repo opens the database through `connection`, so
    every one of them can accumulate a tally; only `run_audit` reports it in
    its artefact. This is the floor for the rest: called from `run_audit`'s
    `finally` and registered at exit, so an abort, an early return, or a
    script with no briefing at all still says it happened rather than leaving
    it in the log (P5/P2, the cold review of this chunk). Marked reported, so
    the exit hook does not repeat what a caller already printed.
    """
    global _REPORTED
    warning = cleanup_failure_warning()
    _REPORTED = True
    if not warning:
        return None
    (printer or (lambda line: print(line, file=sys.stderr)))(
        f"\u26a0\ufe0f {warning}.")
    return warning


def _report_cleanup_failures_at_exit() -> None:
    """Say it on the way out if nothing else did."""
    if _CLEANUP_FAILURES and not _REPORTED:
        report_cleanup_failures()


atexit.register(_report_cleanup_failures_at_exit)


def _safely(cleanup, what: str, db_path) -> None:
    """Run one cleanup step so it cannot replace the caller's exception.

    A failing `rollback()` or `close()` is a second fact, not the diagnosis:
    raising from here turns the `IntegrityError` that says which write was
    wrong into an `OperationalError` from the cleanup, and on the clean path
    turns a committed, durable write into a reported failure (review chunk
    Y11). `Exception`, not `BaseException`, so a `KeyboardInterrupt` during
    cleanup still reaches the user.
    """
    try:
        cleanup()
    except Exception:
        try:
            key = (what, str(db_path))
            _CLEANUP_FAILURES[key] = _CLEANUP_FAILURES.get(key, 0) + 1
        except Exception:
            key = None
        logger.exception(
            "Could not %s the connection to %s (%s time(s) in this run). The "
            "original outcome of the block stands; this is a failure of the "
            "cleanup, not of the work.",
            what, db_path, _CLEANUP_FAILURES.get(key, "an uncounted"))


@contextmanager
def connection(db_path, **kwargs):
    """A connection to *db_path*: committed on success, always closed.

    An exception inside the block rolls the transaction back and is
    re-raised, which is what the plain `with sqlite3.connect(...)` form did.
    Keyword arguments are passed to `sqlite3.connect` unchanged; a caller that
    names its own `timeout` is honoured, and the two gateway classes pass the
    configured wait.
    """
    conn = sqlite3.connect(db_path, **kwargs)
    try:
        yield conn
        conn.commit()
    except BaseException:
        _safely(conn.rollback, ROLL_BACK, db_path)
        raise
    finally:
        _safely(conn.close, CLOSE, db_path)
