"""Tests for src/competitor_mining.py — the offline keyword-gap script.

Sweep finding F7 (root fix): the module used bare `from api_clients import ...` /
`from reframe_engine import ...`, so it was UN-importable as a submodule — which silently
disabled C1/C3 (they consume `derive_brand_name` from here) through their guarded
try/except. The imports are now dual-mode (works both as `python3 src/competitor_mining.py`
and as `from src.competitor_mining import ...`). These tests lock (a) that the module
imports as `src.competitor_mining`, and (b) `derive_brand_name`'s behavior — so the run
path and the standalone script share ONE brand-derivation implementation, no inlined copy
to drift.
"""
import importlib
import os
import subprocess
import sys

import pytest


def test_f7_competitor_mining_importable_as_submodule():
    """Root F7 regression: `import src.competitor_mining` must succeed. Before the fix this
    raised `ModuleNotFoundError: No module named 'api_clients'` — the failure that silently
    disabled C1/C3."""
    mod = importlib.import_module("src.competitor_mining")
    assert hasattr(mod, "derive_brand_name")


@pytest.mark.parametrize("domain,expected", [
    ("jerichocounselling.com", "jericho"),   # 'counselling' suffix stripped
    ("bowentherapy.org", "bowen"),           # 'therapy' suffix stripped
    ("theravive.com", "theravive"),          # no suffix → domain stem
    ("SomePractice.CA", "somepractice"),     # lowercased
    (None, ""),                               # None-safe (was a crash before the fix)
    ("", ""),
])
def test_f7_derive_brand_name(domain, expected):
    """The one canonical brand-derivation used by both the offline script and the run
    path (C1 SoV / C3 branded-demand)."""
    from src.competitor_mining import derive_brand_name
    assert derive_brand_name(domain) == expected


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
