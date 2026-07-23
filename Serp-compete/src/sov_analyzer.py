"""C1 / SC-3 — AI Answer Share-of-Voice vs Competitors.

Purpose: When someone asks the AI engines a category question, whose brand and sources
         come back — the client's or its competitors'? This CONSUMES serp-discover's
         AI-visibility export (brand_mentions + ai_citations + answer_sentiment) and
         computes per-engine mention/citation share + per-competitor sentiment. It does
         NOT probe any engine (the single AI-probe runner lives in serp-discover) — it
         adds only the comparative layer, from the competitors already in scope.
Spec:    suite_enhancement_spec_v1.md#C1 (SC-3) — see compete-spec.md#C1.
Tests:   tests/test_sov_analyzer.py

Design notes:
    * Pure over the stored export — adding/removing a competitor recomputes shares from
      the SAME file, no re-probe (SC-3.3).
    * Consumer selection contract (locked in Phase 0): pick the newest export whose
      data_available is true by its in-file source_run_ts, never by filename.
    * Per-competitor sentiment uses only that competitor's own answer_sentiment rows
      (SC-3.4) — sentiment is aggregated per (engine, brand), never globally.
    * Shares within an engine sum to ~100% (entities not matched to the client or a
      tracked competitor fall into "other") — SC-3.1.
"""
from __future__ import annotations

import glob
import json
import os
import re
from typing import Any, Dict, List, Optional

POLARITY_SCORE = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}


def _norm(name: Any) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip()).lower()


# ---------------------------------------------------------------------------
# Locate + load the export (honours the Phase-0 selection contract)
# ---------------------------------------------------------------------------

def find_av_export(project_root: str, config: Dict[str, Any]) -> Optional[str]:
    """Return the path to the AI-visibility export to consume, or None.

    Precedence: explicit `sov.export_path`; else auto-discover
    `ai_visibility_export_*.json` in the repo root and in a sibling
    `serp-discover/output/`, choosing the newest export whose `data_available` is
    true by its in-file `source_run_ts` (falling back to the newest file).
    """
    sov_cfg = config.get("sov", {}) or {}
    explicit = sov_cfg.get("export_path")
    if explicit and os.path.exists(explicit):
        return explicit
    candidates = glob.glob(os.path.join(project_root, "ai_visibility_export_*.json"))
    candidates += glob.glob(os.path.join(
        project_root, "..", "serp-discover", "output", "ai_visibility_export_*.json"))
    if not candidates:
        return None
    available: List[tuple] = []
    newest_path, newest_mtime = None, -1.0
    for path in candidates:
        mtime = os.path.getmtime(path)
        if mtime > newest_mtime:
            newest_path, newest_mtime = path, mtime
        data = load_av_export(path)
        if data and data.get("data_available") and data.get("source_run_ts"):
            available.append((data["source_run_ts"], path))
    if available:
        return max(available)[1]
    return newest_path


def load_av_export(path: Optional[str]) -> Optional[Dict[str, Any]]:
    """Load the export JSON; None on missing/unreadable file (never raises)."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


# ---------------------------------------------------------------------------
# Share-of-voice computation (pure)
# ---------------------------------------------------------------------------

def _classify(is_client: bool, domain: Optional[str], competitor_domains: set) -> str:
    if is_client:
        return "client"
    if domain and domain.lower() in competitor_domains:
        return "competitor"
    return "other"


def compute_sov(export: Optional[Dict[str, Any]], competitor_domains: List[str],
                snapshot_date: str, competitor_brands: Optional[List[str]] = None) -> Dict[str, Any]:
    """Per-engine mention/citation share + per-competitor sentiment from the export.

    Returns {data_available, rows, gaps}. `rows` are per (engine, entity) with a
    mention or citation share (entity_type 'brand' or 'domain'); `gaps` are the
    "cited-but-you're-not" list (a competitor domain an engine cites while the client
    is absent). data_available False (empty rows) when the export is missing/empty.

    A mentioned competitor is matched by its brand→domain (from citations) OR directly
    by `competitor_brands` (its display name) — so a competitor that's mentioned but
    never cited is still classified 'competitor', not hidden in "other".
    """
    if not export or not export.get("data_available"):
        return {"data_available": False, "rows": [], "gaps": []}

    competitor_set = {_norm_domain(d) for d in (competitor_domains or [])}
    competitor_brand_set = {_norm(b) for b in (competitor_brands or []) if _norm(b)}
    mentions = export.get("brand_mentions", []) or []
    citations = export.get("ai_citations", []) or []
    sentiment = export.get("answer_sentiment", []) or []
    engines = export.get("engines", []) or []

    # brand -> registrable-ish domain (from citations, which carry both)
    brand_to_domain: Dict[str, str] = {}
    for c in citations:
        if c.get("brand") and c.get("domain"):
            brand_to_domain.setdefault(_norm(c["brand"]), _norm_domain(c["domain"]))

    # per-competitor sentiment: aggregate polarity per (engine, brand) — SC-3.4
    sent_agg: Dict[tuple, List[float]] = {}
    for s in sentiment:
        key = (s.get("engine"), _norm(s.get("brand")))
        bucket = sent_agg.setdefault(key, [0.0, 0])
        bucket[0] += POLARITY_SCORE.get(_norm(s.get("polarity")), 0.0)
        bucket[1] += 1

    rows: List[Dict[str, Any]] = []
    gaps: List[Dict[str, Any]] = []
    for engine in engines:
        eng_mentions = [m for m in mentions if m.get("engine") == engine]
        eng_citations = [c for c in citations if c.get("engine") == engine]
        total_mentions = sum(int(m.get("mention_count") or 0) for m in eng_mentions)
        total_cites = sum(int(c.get("cite_count") or 0) for c in eng_citations)
        client_cited = any(c.get("is_client") for c in eng_citations)

        for m in eng_mentions:
            nb = _norm(m.get("brand"))
            domain = brand_to_domain.get(nb)
            if m.get("is_client"):
                category = "client"
            elif (domain and domain in competitor_set) or (nb in competitor_brand_set):
                category = "competitor"       # matched by cited domain OR brand name
            else:
                category = "other"
            count = int(m.get("mention_count") or 0)
            qt = int(m.get("questions_total") or 0)
            s = sent_agg.get((engine, nb))
            rows.append({
                "engine": engine, "snapshot_date": snapshot_date, "entity": m.get("brand"),
                "entity_type": "brand", "is_client": bool(m.get("is_client")), "category": category,
                "mention_share": round(100.0 * count / total_mentions, 2) if total_mentions else 0.0,
                "citation_share": None,
                "presence_rate": round(count / qt, 3) if qt else 0.0,
                "avg_sentiment": round(s[0] / s[1], 3) if s and s[1] else None,
            })

        for c in eng_citations:
            domain = _norm_domain(c.get("domain"))
            category = _classify(bool(c.get("is_client")), domain, competitor_set)
            count = int(c.get("cite_count") or 0)
            rows.append({
                "engine": engine, "snapshot_date": snapshot_date, "entity": c.get("domain"),
                "entity_type": "domain", "is_client": bool(c.get("is_client")), "category": category,
                "mention_share": None,
                "citation_share": round(100.0 * count / total_cites, 2) if total_cites else 0.0,
                "presence_rate": None, "avg_sentiment": None,
            })
            if category == "competitor" and not client_cited:
                gaps.append({"engine": engine, "domain": c.get("domain"), "cite_count": count})

    return {"data_available": True, "rows": rows, "gaps": gaps}


def _norm_domain(domain: Any) -> str:
    """Lower-cased, www-stripped domain — matches serp-discover's citation domain form."""
    return str(domain or "").strip().lower().removeprefix("www.")
