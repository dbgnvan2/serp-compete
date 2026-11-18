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
(review chunk Y10).

Spec: docs/review_2026-11-04/PLAN_Y10_tool2_closes_its_handles.md
Tests: Serp-compete/tests/test_y10_tool2_closes_its_handles.py
"""

import sqlite3
from contextlib import contextmanager


@contextmanager
def connection(db_path, **kwargs):
    """A connection to *db_path*: committed on success, always closed.

    An exception inside the block rolls the transaction back and is
    re-raised, which is what the plain `with sqlite3.connect(...)` form did.
    Keyword arguments are passed to `sqlite3.connect` unchanged.
    """
    conn = sqlite3.connect(db_path, **kwargs)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
