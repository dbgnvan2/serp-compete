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

import logging
import sqlite3
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
        logger.warning(
            "shared_config.json %s.%s is %r, which is not a positive number "
            "of seconds; using the documented default %s.",
            section_name, key, raw, DEFAULT_LOCK_TIMEOUT_SECONDS)
        return DEFAULT_LOCK_TIMEOUT_SECONDS
    return seconds


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
        logger.exception(
            "Could not %s the connection to %s. The original outcome of the "
            "block stands; this is a failure of the cleanup, not of the work.",
            what, db_path)


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
        _safely(conn.rollback, "roll back", db_path)
        raise
    finally:
        _safely(conn.close, "close", db_path)
