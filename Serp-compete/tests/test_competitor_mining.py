"""Tests for src/competitor_mining.py — the offline keyword-gap script.

Sweep finding F7 (root fix): the module used bare `from api_clients import ...` /
`from reframe_engine import ...`, so it was UN-importable as a submodule — which silently
disabled C1/C3 (they consume `derive_brand_name` from here) through their guarded
try/except. The imports are now dual-mode (works both as `python3 src/competitor_mining.py`
and as `from src.competitor_mining import ...`). These tests lock (a) that the module
imports as `src.competitor_mining`, and (b) that it re-exports the ONE canonical
`derive_brand_name` (now in src/brand_utils.py) — so the run path and the standalone script
share a single implementation, no inlined copy to drift. Full behavior of the brand function
lives in test_brand_utils.py.
"""
import importlib
import os
import subprocess
import sys


def test_f7_competitor_mining_importable_as_submodule():
    """Root F7 regression: `import src.competitor_mining` must succeed. Before the fix this
    raised `ModuleNotFoundError: No module named 'api_clients'` — the failure that silently
    disabled C1/C3."""
    mod = importlib.import_module("src.competitor_mining")
    assert hasattr(mod, "derive_brand_name")


def test_f7_derive_brand_name_is_reexport_of_canonical():
    """competitor_mining must re-export the SAME brand_utils.derive_brand_name object (so
    existing `from src.competitor_mining import derive_brand_name` callers keep working and
    no duplicate copy can drift). Behavior itself is covered in test_brand_utils.py."""
    from src.competitor_mining import derive_brand_name
    from src.brand_utils import derive_brand_name as canonical
    assert derive_brand_name is canonical                       # same object, not a fork
    assert derive_brand_name("jerichocounselling.com") == "jericho"


def test_f7_standalone_fallback_import_branch():
    """Lock the OTHER dual-mode branch: run the module the way the offline script is invoked
    (`python3 src/competitor_mining.py`), i.e. with `src/` as cwd and no `src` package on the
    path — so `from src.…` fails and the `except ImportError` fallback (bare imports) MUST
    resolve. Without a test, someone could 'tidy' the try/except to a single `from src.…` and
    silently break the standalone script (only orchestrator.py's subprocess call would fail)."""
    src_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    proc = subprocess.run(
        [sys.executable, "-c",
         "import competitor_mining as m; print(m.derive_brand_name('jerichocounselling.com'))"],
        cwd=src_dir, env={**os.environ, "PYTHONPATH": ""},  # cleared → `src` pkg not reachable
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr    # fallback branch resolved the bare imports
    assert proc.stdout.strip() == "jericho"
