"""Tests for C3 / SC-5 — Branded-Demand Competitive Benchmark (src/brand_demand.py).

Covers SC-5.1 (own GSC-anchored figure distinct from volume-estimated competitors),
SC-5.2 (branded query expansion inspectable/editable via config), SC-5.3 (growth over
equal-length periods), SC-5.4 (generic brand names pruned), plus share math and DB.
"""
import pytest

from src.database import DatabaseManager
from src.brand_demand import (
    expand_branded_queries, compute_growth, compute_branded_demand,
)

CONFIG = {"branded_modifiers": ["reviews", "pricing"],
          "generic_brand_prune": ["therapy"], "growth_window_months": 2}


def _provider(vol=100, monthly=None):
    monthly = monthly if monthly is not None else []
    def provider(queries):
        return {q.lower(): {"search_volume": vol, "monthly_searches": monthly} for q in queries}
    return provider


# ── SC-5.2 branded query expansion inspectable / editable ─────────────────────

def test_sc52_expand_uses_config_modifiers():
    assert expand_branded_queries("Theravive", ["reviews", "pricing"]) == \
        ["Theravive", "Theravive reviews", "Theravive pricing"]


def test_sc52_expansion_flows_through_provider():
    seen = []
    def provider(queries):
        seen.extend(queries)
        return {q.lower(): {"search_volume": 10} for q in queries}
    compute_branded_demand({"a.com": "Acme"}, provider, CONFIG, period="2026-07")
    assert "Acme reviews" in seen and "Acme pricing" in seen   # config modifiers applied


# ── SC-5.3 growth over equal-length periods ───────────────────────────────────

def test_sc53_growth_equal_windows():
    # window=2: recent [30,40]=70 vs prior [10,20]=30 → 40/30
    assert compute_growth([10, 20, 30, 40], window=2) == round(40 / 30, 3)
    assert compute_growth([10, 20], window=2) is None          # not enough history
    assert compute_growth([0, 0, 30, 40], window=2) is None    # prior window zero → no divide


# ── SC-5.1 own (GSC-anchored) vs estimated competitor figures ─────────────────

def test_sc51_own_vs_estimated_labeling():
    rows = compute_branded_demand(
        {"a.com": "Acme", "livingsystems.ca": "Living Systems"}, _provider(100),
        CONFIG, period="2026-07", own_domain="livingsystems.ca", own_anchor=0.4)
    by_domain = {r["domain"]: r for r in rows}
    assert by_domain["livingsystems.ca"]["estimation_basis"] == "gsc_anchored"
    assert by_domain["livingsystems.ca"]["est_branded_click_share"] == 0.4
    assert by_domain["a.com"]["estimation_basis"] == "volume_estimated"
    assert by_domain["a.com"]["est_branded_click_share"] is None


# ── SC-5.4 generic brand names → pruning ──────────────────────────────────────

def test_sc54_generic_brand_pruned():
    rows = compute_branded_demand({"t.com": "therapy"}, _provider(100), CONFIG, period="2026-07")
    assert rows[0]["estimation_basis"] == "pruned_generic_brand"
    assert rows[0]["branded_search_volume"] is None            # never guessed


# ── share math + DB ───────────────────────────────────────────────────────────

def test_shares_sum_to_100():
    rows = compute_branded_demand({"a.com": "Acme", "b.com": "Bcorp"}, _provider(100),
                                  CONFIG, period="p")
    assert abs(sum(r["branded_volume_share"] for r in rows) - 100.0) < 0.5


def test_volume_unavailable_when_all_zero():
    """Sweep F2: all-zero volume (a DataForSEO outage) is labelled 'volume_unavailable',
    not rendered as genuine zero demand."""
    def zero_provider(queries):
        return {q.lower(): {"search_volume": 0} for q in queries}
    rows = compute_branded_demand({"a.com": "Acme"}, zero_provider, CONFIG, period="p")
    assert rows[0]["estimation_basis"] == "volume_unavailable"


def test_save_brand_demand_roundtrip(tmp_path):
    db = DatabaseManager(str(tmp_path / "bd.db"))
    run_id = db.create_run("c.com")
    rows = compute_branded_demand({"a.com": "Acme"}, _provider(100), CONFIG, period="2026-07")
    db.save_brand_demand(run_id, rows)
    with db._get_connection() as conn:
        n = conn.execute("SELECT COUNT(*) FROM brand_demand_bench WHERE run_id=?",
                         (run_id,)).fetchone()[0]
    assert n == 1
