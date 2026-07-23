"""C4 / SC-6 — SERP Overlap & Differentiation Gap (the wired who-ranks-where matrix).

Purpose: Over the keywords the client and/or a tracked competitor ranks for, classify
         each into a strategic cell — shared_commodity / shared_defensible /
         exclusive_self / exclusive_competitor / absent (+ self_unknown when the
         client's own positions are unavailable) — from competitor SERP positions
         (competitor_metrics) plus the client's own GSC positions, and wire the
         previously-unwired AnalysisEngine keyword-intersection gap + feasibility.
Spec:    suite_enhancement_spec_v1.md#C4 (SC-6) — see compete-spec.md#C4.
Tests:   tests/test_serp_overlap.py

Design notes:
    * Pure logic (data in → data out); the DB/GSC glue lives in run_audit and calls
      analyze_serp_overlap with already-fetched data (mirrors src/enrichment.py).
    * Case-insensitive join. Competitor SERP keywords are uncontrolled casing while
      GSC always lowercases; every join key (competitor positions, client positions,
      volumes, the AnalysisEngine sets) is normalized with _norm_kw so the same
      keyword can't split into two misclassified rows.
    * Honest absence. self_position comes from first-party GSC. When the client's GSC
      positions are UNAVAILABLE for the whole run (fetch failed / no session → an
      empty map), self-presence is UNKNOWN, not False — the rows are marked
      self_unknown and the exclusive_self / exclusive_competitor claims are withheld
      (an unknown must never be rendered as a definitive "you're absent"). Per-keyword
      absence (the client has GSC data but not for this keyword) is still a real False.
    * "Ranks top-N" is symmetric for the client and competitors (a page-2 client is
      not "present"); the raw GSC position is retained (self_position) for transparency.
    * commodity_score is a LOCAL overlap-density proxy — a strategic framing, not a
      measured index (themed-statistic rule). Upgrade path: serp-discover D4.
    * Scope: the keyword universe is "who ranked" (competitors' + the client's GSC
      keywords). A keyword no one ranks for has no source row here, so the `absent`
      cell is currently only reachable if a target-keyword universe is later plumbed in.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from src.analysis import AnalysisEngine

CELL_SHARED_COMMODITY = "shared_commodity"
CELL_SHARED_DEFENSIBLE = "shared_defensible"
CELL_EXCLUSIVE_SELF = "exclusive_self"
CELL_EXCLUSIVE_COMPETITOR = "exclusive_competitor"
CELL_ABSENT = "absent"
CELL_SELF_UNKNOWN = "self_unknown"  # client GSC positions unavailable this run

DEFAULT_TOP_N = 10
DEFAULT_COMMODITY_HIGH_OVERLAP = 3
LOCAL_ESTIMATION_BASIS = "local_overlap_density"


def _norm_kw(keyword: Any) -> str:
    """Canonical join key for a keyword: whitespace-collapsed, lower-cased."""
    return re.sub(r"\s+", " ", str(keyword or "").strip()).lower()


def _normalize_positions(competitor_positions: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    """Merge competitor positions under a normalized keyword, keeping the best
    (lowest) position per domain across casings."""
    out: Dict[str, Dict[str, int]] = {}
    for kw, domains in (competitor_positions or {}).items():
        bucket = out.setdefault(_norm_kw(kw), {})
        for domain, pos in (domains or {}).items():
            if pos is None:
                continue
            if domain not in bucket or pos < bucket[domain]:
                bucket[domain] = pos
    return out


def _normalize_client(client_positions: Dict[str, int]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for kw, pos in (client_positions or {}).items():
        if pos is None:
            continue
        key = _norm_kw(kw)
        if key not in out or pos < out[key]:
            out[key] = pos
    return out


def classify_cell(self_present: Optional[bool], n_competitors: int,
                  commodity_high: bool) -> str:
    """Deterministic cell classification (SC-6.1 / SC-6.2).

    Args:
        self_present:   True/False if the client's presence is known (ranks top-N or
                        not); None when the client's GSC positions are UNAVAILABLE.
        n_competitors:  count of tracked competitors ranking in the top-N.
        commodity_high: the SERP is at/above the high-overlap commodity threshold.

    SC-6.2: exclusive_self is returned only when NO competitor ranks in the top-N.
    When self_present is None, self-relative cells are withheld (self_unknown / absent).
    """
    if self_present is None:  # GSC positions unavailable — do not assert presence/absence
        return CELL_SELF_UNKNOWN if n_competitors >= 1 else CELL_ABSENT
    if self_present and n_competitors >= 1:
        if n_competitors >= 2 and commodity_high:
            return CELL_SHARED_COMMODITY
        return CELL_SHARED_DEFENSIBLE
    if self_present:            # and n_competitors == 0
        return CELL_EXCLUSIVE_SELF
    if n_competitors >= 1:      # and not self_present
        return CELL_EXCLUSIVE_COMPETITOR
    return CELL_ABSENT


def build_overlap_rows(competitor_positions: Dict[str, Dict[str, int]],
                       client_positions: Dict[str, int],
                       config: Dict[str, Any], snapshot_date: str,
                       gap_keywords: Optional[Set[str]] = None,
                       keyword_volumes: Optional[Dict[str, float]] = None,
                       client_positions_available: bool = True) -> List[Dict[str, Any]]:
    """Build one classified overlap row per ranked keyword. Deterministic.

    competitor_positions: {keyword: {domain: best_position}} (from competitor_metrics).
    client_positions:     {keyword: client_gsc_position} (the client's own GSC rank).
    client_positions_available: False when the whole GSC map is missing (fetch failed
        / no session) — self-presence is then UNKNOWN for every keyword, not False.
    """
    top_n = int(config.get("top_n", DEFAULT_TOP_N))
    commodity_high_overlap = int(config.get("commodity_high_overlap",
                                            DEFAULT_COMMODITY_HIGH_OVERLAP))
    gap_keywords = {_norm_kw(k) for k in (gap_keywords or set())}
    comp = _normalize_positions(competitor_positions)
    client = _normalize_client(client_positions)
    volumes = {_norm_kw(k): float(v or 0.0) for k, v in (keyword_volumes or {}).items()}
    config_ref = f"top_n={top_n};commodity_high_overlap={commodity_high_overlap}"

    rows: List[Dict[str, Any]] = []
    for kw in sorted(set(comp) | set(client)):
        comp_top = {d: p for d, p in comp.get(kw, {}).items() if p <= top_n}
        n_comp = len(comp_top)
        raw_self = client.get(kw)
        if not client_positions_available:
            self_present: Optional[bool] = None
        else:
            self_present = raw_self is not None and raw_self <= top_n
        rows.append({
            "keyword": kw,
            "snapshot_date": snapshot_date,
            "competitors_ranking": dict(sorted(comp_top.items(), key=lambda kv: (kv[1], kv[0]))),
            "self_position": raw_self,      # raw GSC position (may exceed top_n) or None
            "overlap_count": n_comp,
            "commodity_score": float(n_comp),  # local overlap-density proxy
            "keyword_volume": volumes.get(kw, 0.0),
            "cell": classify_cell(self_present, n_comp, n_comp >= commodity_high_overlap),
            "config_ref": config_ref,
            "estimation_basis": LOCAL_ESTIMATION_BASIS,
            "all_competitor_gap": kw in gap_keywords,
        })
    return rows


def rollup_by_cell(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    """Sum each row's keyword_volume into its cell (SC-6.3).

    Every keyword contributes to exactly one cell, so the sum of the cell rollups
    equals the sum of the member keyword volumes — no double-count, no drop.
    """
    rollup: Dict[str, float] = {}
    for row in rows:
        rollup[row["cell"]] = rollup.get(row["cell"], 0.0) + float(row.get("keyword_volume", 0.0) or 0.0)
    return rollup


def compute_analysis_gap(client_domain: str,
                         competitor_keywords: Dict[str, Set[str]],
                         client_keywords: Set[str]) -> Set[str]:
    """Wire the previously-unwired AnalysisEngine.find_keyword_intersection (SC-6.4):
    the keywords ALL tracked competitors rank for but the client does not. Normalizes
    both sides so casing can't hide a real client keyword from the difference."""
    engine = AnalysisEngine(client_domain)
    comp_norm = {d: {_norm_kw(k) for k in kws} for d, kws in (competitor_keywords or {}).items()}
    client_norm = {_norm_kw(k) for k in (client_keywords or set())}
    return engine.find_keyword_intersection(comp_norm, client_norm)


def feasibility_by_competitor(client_domain: str, client_da: int,
                              competitor_das: Dict[str, int]) -> Dict[str, Dict[str, Any]]:
    """Wire AnalysisEngine.check_feasibility per competitor (client_da vs each
    competitor_da). Degrades to {} when a competitor's DA is unknown."""
    engine = AnalysisEngine(client_domain)
    out: Dict[str, Dict[str, Any]] = {}
    for domain, da in (competitor_das or {}).items():
        if da is None:
            continue
        out[domain] = {**engine.check_feasibility(int(client_da or 0), int(da)),
                       "competitor_da": int(da)}
    return out


def analyze_serp_overlap(competitor_positions: Dict[str, Dict[str, int]],
                         client_positions: Dict[str, int],
                         competitor_keywords: Dict[str, Set[str]],
                         client_keywords: Set[str], client_domain: str,
                         client_da: int, competitor_das: Dict[str, int],
                         config: Dict[str, Any], snapshot_date: str,
                         keyword_volumes: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Orchestrate C4: the classified matrix + AnalysisEngine gap/feasibility + the
    per-cell volume rollup + action queues. Pure — the caller persists rows via
    db.save_serp_overlap and feasibility via db.save_competitor_feasibility.
    """
    # An entirely empty client map means we could not read the client's GSC positions
    # this run — treat self-presence as UNKNOWN, never as blanket absence (Finding 1).
    client_positions_available = bool(client_positions)
    gap_keywords = compute_analysis_gap(client_domain, competitor_keywords, client_keywords)
    rows = build_overlap_rows(competitor_positions, client_positions, config,
                              snapshot_date, gap_keywords, keyword_volumes,
                              client_positions_available)
    return {
        "rows": rows,
        "rollup": rollup_by_cell(rows),
        "gap_keywords": sorted(gap_keywords),
        "feasibility": feasibility_by_competitor(client_domain, client_da, competitor_das),
        "client_positions_available": client_positions_available,
        # exclusive_competitor is only assertable when self-presence is known
        "action_exclusive_competitor": [r["keyword"] for r in rows
                                        if r["cell"] == CELL_EXCLUSIVE_COMPETITOR],
        "action_shared_commodity": [r["keyword"] for r in rows
                                    if r["cell"] == CELL_SHARED_COMMODITY],
    }
