"""The compete-spec comparison layer (C4/C2/C1/C3/C6), extracted from run_audit.

Purpose: Run the five comparison features on the audit's persisted data — SERP overlap
         (SC-6), barbell positioning (SC-4), AI share-of-voice (SC-3), branded-demand
         benchmark (SC-5), and reputation-risk radar (SC-8). Each is independently
         guarded so one failure can't abort the others or the audit.
Spec:    suite_enhancement_spec_v1.md#C1/#C2/#C3/#C4/#C6
Tests:   tests/test_comparison_features.py

Why a module: previously these five blocks lived inline in run_audit(), so the
"assembly" (which reads inputs, calls the tested compute functions, and persists) had
NO test — deleting a save() failed nothing (sweep finding F7 / P21). Extracting them
here makes the wiring unit-testable with a seeded DB + fake GSC/DataForSEO clients.
Returns a summary of what each feature produced (for logging + the smoke test).
"""
from __future__ import annotations

import datetime
import os
from typing import Any, Dict


def _derive_brand_name(domain: str) -> str:
    """Brand stub from a domain ('jerichocounselling.com' -> 'jericho'). Mirrors
    competitor_mining.derive_brand_name, inlined so this run-path module does NOT import
    that standalone script — whose bare `from api_clients import ...` (should be
    `from src.api_clients`) makes it un-importable as a submodule and would silently
    disable C1/C3 via the guarded try/except. (Adjacent bug flagged, not swept.)"""
    name = str(domain or "").split(".")[0]
    for suffix in ("counselling", "counseling", "therapy", "counselor", "counsellor", "psychology"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.lower()


def run_comparison_features(db: Any, run_id: int, shared_config: Dict[str, Any],
                            client_domain: str, competitor_keywords: Dict[str, Any],
                            gsc: Any, dfs_client: Any, project_root: str) -> Dict[str, Any]:
    """Run C4/C2/C1/C3/C6 and persist their outputs. Never raises — each feature is
    guarded so a failure degrades to an empty section, never a broken audit."""
    from src.serp_overlap import analyze_serp_overlap
    from src.positioning import compute_positioning, classify_query_tiers
    from src.sov_analyzer import find_av_export, load_av_export, compute_sov
    from src.brand_demand import compute_branded_demand
    from src.risk_radar import compute_risk_signals

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    client_da = shared_config.get("client", {}).get("da", 0)
    domains = list(competitor_keywords.keys())
    summary: Dict[str, Any] = {}

    # Client's own GSC positions — shared by C4 (overlap) and C2 (positioning).
    # get_query_position_map catches its own fetch errors (returns {}).
    client_positions = gsc.get_query_position_map() if gsc else {}

    # C4 / SC-6: SERP Overlap & Differentiation Gap.
    try:
        overlap = analyze_serp_overlap(
            competitor_positions=db.get_competitor_positions(run_id),
            client_positions=client_positions, competitor_keywords=competitor_keywords,
            client_keywords=set(client_positions.keys()), client_domain=client_domain,
            client_da=client_da, competitor_das=db.get_competitor_das(),
            config=shared_config.get("serp_overlap", {}), snapshot_date=today,
            keyword_volumes=db.get_keyword_volumes(run_id))
        db.save_serp_overlap(run_id, overlap["rows"])
        db.save_competitor_feasibility(run_id, client_da, overlap["feasibility"])
        summary["overlap_rows"] = len(overlap["rows"])
        if not overlap["client_positions_available"]:
            print("   ⚠️ SERP overlap: client GSC positions unavailable this run — "
                  "self-presence UNKNOWN; exclusive-competitor/self claims withheld.")
        print(f"   🗺️  SERP overlap: {len(overlap['rows'])} keywords classified — "
              f"{len(overlap['action_exclusive_competitor'])} exclusive-competitor, "
              f"{len(overlap['action_shared_commodity'])} shared-commodity, "
              f"{len(overlap['gap_keywords'])} all-competitor gaps; "
              f"{len(overlap['feasibility'])} competitors scored for feasibility.")
    except Exception as overlap_err:  # noqa: BLE001
        print(f"⚠️ SERP overlap analysis skipped: {overlap_err}")

    # C2 / SC-4: Barbell Positioning Diagnostic (client always plotted).
    try:
        comp_inputs = db.get_positioning_inputs(run_id)
        client_med, client_sys = classify_query_tiers(
            list(client_positions.keys()), shared_config.get("clinical", {}))
        client_inputs = {
            # None (not client_da's 0 default) when client.da is absent — compute_authority
            # EXCLUDES a missing DA and renormalizes, never counts it as a zero score.
            "moz_da": shared_config.get("client", {}).get("da"),
            "top10_count": sum(1 for p in client_positions.values() if p <= 10),
            "medical_total": client_med, "systems_total": client_sys}
        pos_rows = compute_positioning(comp_inputs, client_domain, client_inputs,
                                       shared_config.get("positioning", {}))
        db.save_positioning(run_id, pos_rows, computed_at=today)
        summary["positioning_rows"] = len(pos_rows)
        quads: Dict[str, int] = {}
        for r in pos_rows:
            quads[r["quadrant"]] = quads.get(r["quadrant"], 0) + 1
        print("   🧭 Positioning: " + ", ".join(f"{q}: {n}" for q, n in sorted(quads.items())))
    except Exception as pos_err:  # noqa: BLE001
        print(f"⚠️ Positioning analysis skipped: {pos_err}")

    # C1 / SC-3: AI Answer Share-of-Voice — CONSUME serp-discover's export (no probing).
    try:
        export_path = find_av_export(project_root, shared_config)
        sov = compute_sov(load_av_export(export_path), competitor_domains=domains,
                          snapshot_date=today,
                          competitor_brands=[_derive_brand_name(d) for d in domains])
        summary["sov_available"] = sov["data_available"]
        if sov["data_available"]:
            db.save_sov(run_id, sov["rows"])
            summary["sov_rows"] = len(sov["rows"])
            print(f"   📣 AI Share-of-Voice: {len(sov['rows'])} entity rows, "
                  f"{len(sov['gaps'])} cited-but-you're-not gaps "
                  f"(from {os.path.basename(export_path) if export_path else '?'}).")
        else:
            print("   ℹ️ AI Share-of-Voice: no serp-discover AI-visibility export found — skipped.")
    except Exception as sov_err:  # noqa: BLE001
        print(f"⚠️ AI Share-of-Voice analysis skipped: {sov_err}")

    # C3 / SC-5: Branded-Demand Competitive Benchmark.
    try:
        brand_by_domain = {d: _derive_brand_name(d) for d in domains}
        client_brands = shared_config.get("client", {}).get("brand_names") or []
        brand_by_domain[client_domain] = (client_brands[0] if client_brands
                                          else _derive_brand_name(client_domain))
        bd_rows = compute_branded_demand(
            brand_by_domain, dfs_client.get_search_volume, shared_config.get("branded_demand", {}),
            period=datetime.datetime.now().strftime("%Y-%m"),
            own_domain=client_domain, own_anchor=None)
        db.save_brand_demand(run_id, bd_rows)
        summary["branded_rows"] = len(bd_rows)
        print(f"   💷 Branded demand: {len(bd_rows)} brands benchmarked.")
    except Exception as bd_err:  # noqa: BLE001
        print(f"⚠️ Branded-demand benchmark skipped: {bd_err}")

    # C6 / SC-8: Reputation-Risk Radar (pattern detections, not confirmed penalties).
    try:
        series_by_domain = {d: db.get_visibility_series(d) for d in domains}
        series_by_domain[client_domain] = db.get_visibility_series(client_domain)
        risk_rows = compute_risk_signals(
            volatility_alerts=db.get_volatility_alerts(run_id), series_by_domain=series_by_domain,
            parasite_candidates=db.get_parasite_candidates(run_id),
            own_domain=client_domain, config=shared_config.get("risk_signals", {}))
        db.save_risk_signals(run_id, risk_rows, detected_at=today)
        summary["risk_rows"] = len(risk_rows)
        own_risks = sum(1 for r in risk_rows if r["is_own_site"])
        print(f"   🚨 Reputation risk: {len(risk_rows)} signals ({own_risks} own-site).")
    except Exception as risk_err:  # noqa: BLE001
        print(f"⚠️ Reputation-risk radar skipped: {risk_err}")

    return summary
