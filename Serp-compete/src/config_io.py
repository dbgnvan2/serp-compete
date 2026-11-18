"""Read and write `shared_config.json` safely.

Purpose: the GUI edits the file every audit path reads, so the write must not
         be able to leave it half-written or rewrite its comments.
Tests:   Serp-compete/tests/test_config_io.py

Extracted from `orchestrator.py` on 2026-11-16 for two reasons. The first is
that the orchestrator is a Streamlit script — importing it runs the UI — so
nothing in it can be tested, and it is at 0% coverage. The second is that the
two functions it held each had a defect:

* **The write was not atomic.** `open(path, 'w')` truncates immediately, so a
  process killed mid-write, a full disk, or two GUI interactions racing leaves
  `shared_config.json` truncated. That used not to be a loud failure:
  `scoring_logic.load_shared_config` swallowed every exception and returned
  `{}`, so the next audit would run with **every threshold at its Python
  default and an EMPTY clinical vocabulary** — scoring every page 0 and
  reporting nothing wrong. That reader is gone: `load_config` below is the one
  reader every module uses, and it raises (review chunk Y16). The file is written to a temporary file in the same directory and
  moved into place with `os.replace`, which is atomic on POSIX and on Windows.
* **It escaped non-ASCII.** `json.dump` defaults to `ensure_ascii=True`, and
  `shared_config.json` is now full of provenance notes containing em dashes and
  arrows. The first time anyone changed the reports directory in the GUI, every
  comment in the file would have been rewritten as `\\u2014` and `\\u2192` — the
  values intact, the file valid, and the whole thing unreadable in a diff.

The GUI already does the right thing in one respect, which this preserves: it
re-reads the file and updates ONE key, rather than reconstructing the config
from its form fields. Reconstructing would delete every `_*_source` note and
every block the GUI has no field for.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict

#: The repo root — this module lives at `Serp-compete/src/`.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SHARED_CONFIG_PATH = os.path.join(PROJECT_ROOT, "shared_config.json")


def load_config(path: str = None) -> Dict[str, Any]:
    """The parsed config, or `{}` when the file is absent.

    A file that exists but cannot be parsed RAISES. This is the ONE reader of
    `shared_config.json`, and that is the one rule (review chunk Y16). There
    used to be a second policy: `scoring_logic.load_shared_config` swallowed
    the error and returned `{}`, on the argument that an abort mid-audit is
    worse than a default. It is not — the default was every threshold at its
    Python value and an EMPTY clinical vocabulary, which scored every page 0
    and reported that as a measurement. Before a write the rule matters for a
    second reason: treating a corrupt file as `{}` and then saving would
    overwrite it with the one key the GUI changed and lose everything else.

    The one named exception is `database.config_for_lock_timeout`, where the
    config is read to decide how long to wait for a lock rather than to score
    anything (review chunk Y11).
    """
    path = path or SHARED_CONFIG_PATH
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: Dict[str, Any], path: str = None) -> None:
    """Write *config* over the file, atomically, without escaping its comments.

    Refuses to write an empty mapping over a non-empty file: every caller
    arrives here having loaded the file and changed one key, so an empty
    `config` means something went wrong upstream, and the one thing worse than
    not saving a setting is erasing the config that the audit reads.
    """
    path = path or SHARED_CONFIG_PATH
    if not isinstance(config, dict):
        raise TypeError(f"config must be a mapping, got {type(config).__name__}")
    if not config and os.path.exists(path) and os.path.getsize(path) > 2:
        raise ValueError(
            "refusing to write an empty config over a non-empty "
            f"{os.path.basename(path)} — every caller loads the file and edits "
            "one key, so an empty mapping here is an upstream failure")

    directory = os.path.dirname(os.path.abspath(path)) or "."
    # Same directory as the target: os.replace is only atomic within a
    # filesystem, and /tmp is often a different one.
    handle, temporary = tempfile.mkstemp(
        dir=directory, prefix=".shared_config.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    except BaseException:
        # Leave the original file untouched, and do not leave the temp behind.
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def set_orchestrator_setting(key: str, value: Any, path: str = None) -> Dict[str, Any]:
    """Change one `orchestrator.<key>` and save. Returns the written config.

    The read-modify-write the GUI does twice, in one place — so the next
    setting added to the UI cannot reconstruct the config from form fields and
    drop every provenance note with it.
    """
    config = load_config(path)
    config.setdefault("orchestrator", {})[key] = value
    save_config(config, path)
    return config
