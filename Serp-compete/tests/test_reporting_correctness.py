"""Report-correctness tests for chunk C3 (C-C-02/C-M-04, C-C-07, C-C-08/C-M-05,
C-C-10, C-C-16, C-M-20).

Promotes probes/compete/probe_reporting_crossjoin.py, probe_report_truncation.py,
probe_cache_estimate_flip.py and probe_feasibility_stale.py, plus
probes/compete_method/p02 §A and §C, to behaviour tests against the real
ReportGenerator and a seeded database.

These are behaviour tests, not source greps: each one seeds the shape `main.py`
writes, renders the real briefing and Excel workbook, and asserts on what the owner
would read (TODO.md's note on `test_coverage_is_persisted…`).
"""
import os

import pandas as pd
import pytest

from src.database import DatabaseManager, magnet_thresholds
from src.reporting import ReportGenerator

FLOOR, MAX_POS = magnet_thresholds()


@pytest.fixture
def reporter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)          # keep generated .md/.xlsx out of the repo
    return ReportGenerator(str(tmp_path / "report.db"))


def _magnet(db, run_id, domain, url, keyword, medical=20, systems=0.0, traffic=100.0,
            rank=3, label="Standard", t2=0, t3=0, relevant=True, source="handoff"):
    db.save_traffic_magnet(run_id, domain, url, keyword, traffic, medical, systems,
                           label=label, keyword_source=source, keyword_relevant=relevant,
                           rank=rank, t2_count=t2, t3_count=t3)


# ── C-C-02 / C-M-04: the cross join ──────────────────────────────────────────

def test_cc02_sampled_keywords_is_not_multiplied_by_the_magnet_rows(reporter):
    """10 ranked keywords across 3 URLs + 3 audited pages reported 30 keywords: the
    LEFT JOIN against traffic_magnets had no URL condition, so every metrics row was
    replicated once per magnet row. run_11 shows 30 for almost every domain."""
    db = reporter.db
    run_id = db.create_run("client.ca")
    db.save_competitor_metrics(
        [{"domain": "comp.com", "url": f"https://comp.com/p{i % 3}",
          "keyword": f"kw{i}", "position": i + 1, "traffic": 10.0,
          "keyword_source": "handoff"} for i in range(10)], run_id=run_id)
    for j in range(3):
        _magnet(db, run_id, "comp.com", f"https://comp.com/p{j}", f"kw{j}")

    content = reporter.generate_summary("client.ca", run_id=run_id)
    summary = pd.read_excel(f"audit_results_run_{run_id}.xlsx",
                            sheet_name="Competitor Summary")
    assert int(summary.loc[0, "sampled_keywords"]) == 10      # was 30
    assert int(summary.loc[0, "pages_audited"]) == 3
    assert "total_keywords" not in summary.columns            # the inflated name is gone
    assert "sampled_keywords" in content


def test_cc02_a_domain_with_one_audited_page_is_not_special_cased(reporter):
    """The old number was keywords × magnet rows, so a 1-page domain happened to be
    right and a 3-page domain was 3x out — which is what mis-ranked the column."""
    db = reporter.db
    run_id = db.create_run("client.ca")
    for domain, pages in (("three.com", 3), ("one.com", 1)):
        db.save_competitor_metrics(
            [{"domain": domain, "url": f"https://{domain}/p{i % pages}",
              "keyword": f"{domain}-kw{i}", "position": 2, "traffic": 1.0}
             for i in range(10)], run_id=run_id)
        for j in range(pages):
            _magnet(db, run_id, domain, f"https://{domain}/p{j}", f"{domain}-kw{j}")

    reporter.generate_summary("client.ca", run_id=run_id)
    summary = pd.read_excel(f"audit_results_run_{run_id}.xlsx",
                            sheet_name="Competitor Summary").set_index("domain")
    assert int(summary.loc["three.com", "sampled_keywords"]) == 10
    assert int(summary.loc["one.com", "sampled_keywords"]) == 10


def test_cc02_avg_pos_is_unchanged_by_the_fix(reporter):
    """The replication factor was uniform per domain, so avg_pos was already right;
    the fix must not move it."""
    db = reporter.db
    run_id = db.create_run("client.ca")
    db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": f"kw{i}",
          "position": i + 1, "traffic": 1.0} for i in range(10)], run_id=run_id)
    _magnet(db, run_id, "comp.com", "https://comp.com/a", "kw0")
    reporter.generate_summary("client.ca", run_id=run_id)
    summary = pd.read_excel(f"audit_results_run_{run_id}.xlsx",
                            sheet_name="Competitor Summary")
    assert summary.loc[0, "avg_pos"] == pytest.approx(5.5)


# ── C-C-07: truncation ───────────────────────────────────────────────────────

def _seed_wide_run(db, run_id, competitors=15, pages=3):
    """15 competitors × 3 pages — the real handoff's shape."""
    with db._get_connection() as conn:
        for i in range(competitors * pages):
            domain = f"{chr(97 + i // pages)}comp.com"
            url = f"https://{domain}/p{i % pages}"
            conn.execute(
                "INSERT INTO eeat_scores (run_id, url, scored_at, experience_score, "
                "expertise_score, authoritativeness_score, trustworthiness_score, "
                "score_confidence) VALUES (?,?,?,?,?,?,?,?)",
                (run_id, url, "t", 0.5, None, 0.2, 0.9, "medium"))
            conn.execute(
                "INSERT INTO geo_profiles (run_id, url, profiled_at, extractability_tier,"
                " question_heading_count, present_signals, why_cited) VALUES (?,?,?,?,?,?,?)",
                (run_id, url, "t", "Weak", 0, "[]", "why"))
        conn.commit()
    for i in range(competitors * pages):
        domain = f"{chr(97 + i // pages)}comp.com"
        _magnet(db, run_id, domain, f"https://{domain}/p{i % pages}", f"kw{i}",
                medical=12, systems=0.0, traffic=0.0, label="Surface-Level")


def test_cc07_excel_carries_every_row_while_the_markdown_is_capped(reporter):
    """`LIMIT 30` / `LIMIT 20` truncated the markdown AND the sheet identically, with
    no "N of M" anywhere — and FEATURE_GUIDE §8.2 calls the sheet the full export."""
    db = reporter.db
    run_id = db.create_run("client.ca")
    _seed_wide_run(db, run_id)
    db.save_competitor_metrics(
        [{"domain": "acomp.com", "url": "https://acomp.com/p0", "keyword": "kw0",
          "position": 2, "traffic": 1.0}], run_id=run_id)

    content = reporter.generate_summary("client.ca", run_id=run_id)
    book = pd.ExcelFile(f"audit_results_run_{run_id}.xlsx")
    assert len(book.parse("EEAT Scores")) == 45
    assert len(book.parse("GEO Extractability")) == 45
    assert len(book.parse("Traffic Magnets")) == 45
    # …and the markdown says what it is showing.
    assert "Showing the first 30 of 45 scored page(s)" in content
    assert "Showing the first 30 of 45 profiled page(s)" in content
    assert "Showing the first 20 of 45 qualifying page(s)" in content


def test_cc07_every_competitor_reaches_the_excel_sheets(reporter):
    """`ORDER BY url LIMIT 30` showed the alphabetically-first ~10 of 15 competitors
    and dropped the rest without a word."""
    db = reporter.db
    run_id = db.create_run("client.ca")
    _seed_wide_run(db, run_id)
    db.save_competitor_metrics(
        [{"domain": "acomp.com", "url": "https://acomp.com/p0", "keyword": "kw0",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    reporter.generate_summary("client.ca", run_id=run_id)

    sheet = pd.ExcelFile(f"audit_results_run_{run_id}.xlsx").parse("GEO Extractability")
    domains = {u.split("/")[2] for u in sheet["url"]}
    assert len(domains) == 15
    assert "ocomp.com" in domains        # the last competitor alphabetically


def test_cc07_the_vacuum_list_comes_from_the_full_magnet_set(reporter):
    """The vacuums were a subset of the 20 magnet rows that survived an `est_traffic
    DESC` sort with heavy ties — an arbitrary subset of an arbitrary subset."""
    db = reporter.db
    run_id = db.create_run("client.ca")
    _seed_wide_run(db, run_id)
    db.save_competitor_metrics(
        [{"domain": "acomp.com", "url": "https://acomp.com/p0", "keyword": "kw0",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    content = reporter.generate_summary("client.ca", run_id=run_id)
    assert "Showing the first 30 of 45 vacuum(s)" in content


# ── C-C-08 / C-M-05: tier counts, not estimates ──────────────────────────────

def test_cc08_cached_scores_carry_the_real_tier_counts(tmp_path):
    """The cache path estimated `t3 = systems_score / 2.0 if >= 2.0`, so a page with
    four generic Tier-2 words (score 2.0) came back as "one Tier-3 term"."""
    db = DatabaseManager(str(tmp_path / "cache.db"))
    run_id = db.create_run("client.ca")
    db.save_semantic_audit("https://comp.com/a", 5, 2.0, run_id=run_id,
                           label="Standard", t2_count=4, t3_count=0)
    cached = db.was_audited_recently("https://comp.com/a")
    assert cached["t2_count"] == 4
    assert cached["t3_count"] == 0          # NOT 1.0, as the estimate produced


def test_cc08_a_legacy_cached_row_reports_unknown_counts(tmp_path):
    """A row written before the counts existed must say "unknown", so the caller
    cannot silently treat it as zero — or re-derive it from the weighted score."""
    db = DatabaseManager(str(tmp_path / "legacy.db"))
    run_id = db.create_run("client.ca")
    with db._get_connection() as conn:
        conn.execute("INSERT INTO semantic_audits (run_id, url, medical_score, "
                     "systems_score, systemic_label) VALUES (?,?,?,?,?)",
                     (run_id, "https://comp.com/a", 5, 2.0, "Standard"))
        conn.commit()
    cached = db.was_audited_recently("https://comp.com/a")
    assert cached["t2_count"] is None and cached["t3_count"] is None


def test_cc08_market_position_is_withheld_when_tier_counts_are_incomplete(tmp_path):
    """Probe `probe_cache_estimate_flip.py`: the estimate flipped `market_position`
    between a fresh run and a cached re-run of the SAME unchanged page. Withholding
    the label is the honest answer; inventing counts is not."""
    db = DatabaseManager(str(tmp_path / "pos.db"))
    db.tag_competitor_position("fresh.com", 5, 12, 0, 0, tier_counts_complete=True)
    assert db.get_competitor_metadata("fresh.com")["market_position"] == "Generalist"

    db.tag_competitor_position("cached.com", 5, 0, 0, 0, tier_counts_complete=False)
    position = db.get_competitor_metadata("cached.com")["market_position"]
    assert position == "Not classified (incomplete tier counts)"
    assert position != "Direct Systemic"       # what the estimate produced


def test_cc08_volume_scaler_still_fires_without_tier_counts(tmp_path):
    """It rests on traffic and the medical count, neither of which is affected."""
    db = DatabaseManager(str(tmp_path / "vs.db"))
    db.tag_competitor_position("vol.com", 20, 0, 0, 1500, tier_counts_complete=False)
    assert db.get_competitor_metadata("vol.com")["market_position"] == "Volume Scaler"


# ── C-M-05: systemic_depth bands ─────────────────────────────────────────────

@pytest.mark.parametrize("t2,t3,label,expected", [
    (0, 1, "Standard", "Bowen (Tier 3 present)"),
    (5, 0, "Standard", "Systems (Tier 2 only)"),
    (1, 0, "Surface-Level", "Surface-Level"),
    (1, 0, "Standard", "Trace (1-2 Tier 2 terms)"),
    (0, 0, "Standard", "None detected"),
])
def test_cm05_depth_bands_read_the_tier_counts(reporter, t2, t3, label, expected):
    """"High" used to mean `systems_score > 0`, so one occurrence of "relationship"
    (score 0.5) read as high systemic depth; and "Medical" compared a RAW Tier-1
    count with a ×2.0/×0.5-weighted systems score."""
    db = reporter.db
    run_id = db.create_run("client.ca")
    db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    _magnet(db, run_id, "comp.com", "https://comp.com/a", "kw", medical=20,
            systems=float(t3 * 2 + t2 * 0.5), label=label, t2=t2, t3=t3)

    reporter.generate_summary("client.ca", run_id=run_id)
    summary = pd.read_excel(f"audit_results_run_{run_id}.xlsx",
                            sheet_name="Competitor Summary")
    assert summary.loc[0, "systemic_depth"] == expected


def test_cm05_a_page_with_unrecorded_counts_reads_not_recorded(reporter):
    db = reporter.db
    run_id = db.create_run("client.ca")
    db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    db.save_traffic_magnet(run_id, "comp.com", "https://comp.com/a", "kw", 1.0, 20, 0.0,
                           label="Standard", keyword_source="handoff",
                           keyword_relevant=True, rank=3)   # no tier counts
    reporter.generate_summary("client.ca", run_id=run_id)
    summary = pd.read_excel(f"audit_results_run_{run_id}.xlsx",
                            sheet_name="Competitor Summary")
    assert summary.loc[0, "systemic_depth"] == "Not recorded"


# ── C-C-10: feasibility is this run's competitors ────────────────────────────

def test_cc10_feasibility_excludes_domains_this_run_did_not_audit(tmp_path):
    """`competitors` is domain-keyed and overwritten in place, so the unscoped read
    listed competitors that are not in this run's handoff at all, with DA values of
    unknown age — while `get_positioning_inputs` beside it was already run-scoped."""
    db = DatabaseManager(str(tmp_path / "feas.db"))
    db.save_competitor_summary("old-run-only.com", 60)
    db.save_competitor_summary("current.com", 30)
    run_id = db.create_run("client.ca")
    db.save_competitor_metrics(
        [{"domain": "current.com", "url": "https://current.com/a", "keyword": "kw",
          "position": 3, "traffic": 1.0}], run_id=run_id)

    assert db.get_competitor_das(run_id) == {"current.com": 30}
    # The unscoped read is gone: `run_id` is required, so no caller can reintroduce
    # the stale set (P22).
    with pytest.raises(TypeError):
        db.get_competitor_das()


def test_cc10_the_feasibility_table_matches_positioning(tmp_path):
    """The two sections read the same column and used to disagree about which
    competitors exist."""
    from src.serp_overlap import analyze_serp_overlap
    db = DatabaseManager(str(tmp_path / "feas2.db"))
    db.save_competitor_summary("old-run-only.com", 60)
    db.save_competitor_summary("current.com", 30)
    run_id = db.create_run("client.ca")
    db.save_competitor_metrics(
        [{"domain": "current.com", "url": "https://current.com/a", "keyword": "kw",
          "position": 3, "traffic": 1.0}], run_id=run_id)
    out = analyze_serp_overlap(db.get_competitor_positions(run_id), {"kw": 4},
                               {"current.com": {"kw"}}, {"kw"}, "client.ca", 35,
                               db.get_competitor_das(run_id), {}, "2026-11-15")
    db.save_competitor_feasibility(run_id, 35, out["feasibility"])
    with db._get_connection() as conn:
        domains = {r[0] for r in conn.execute(
            "SELECT domain FROM competitor_feasibility WHERE run_id=?",
            (run_id,)).fetchall()}
    assert domains == {"current.com"}
    assert set(db.get_positioning_inputs(run_id)) == domains


# ── C-C-16 / C-M-20: the report names its input, and its labels mean something ──

def test_cc16_the_briefing_header_names_the_handoff_it_read(reporter):
    db = reporter.db
    run_id = db.create_run("client.ca")
    db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    content = reporter.generate_summary(
        "client.ca", run_id=run_id,
        run_coverage={"handoff_file": "/outputs/competitor_handoff_couples_20260502_1634.json",
                      "domains_in_handoff": 1, "domains_audited": 1,
                      "pa_measured": 1, "pa_total": 1})
    assert "**Handoff:** competitor_handoff_couples_20260502_1634.json" in content


def test_cc16_a_run_without_recorded_coverage_says_so(reporter):
    db = reporter.db
    run_id = db.create_run("client.ca")
    db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    content = reporter.generate_summary("client.ca", run_id=run_id)
    assert "**Handoff:** not recorded for this run" in content


def test_cc16_reports_dir_is_honoured(tmp_path, monkeypatch):
    """The GUI wrote `orchestrator.reports_dir` into shared_config.json and nothing
    read it, so reports kept landing in Serp-compete/ while "Previous Reports"
    browsed elsewhere."""
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "briefings"
    rg = ReportGenerator(str(tmp_path / "dir.db"))
    rg.output_dir = str(out_dir)
    run_id = rg.db.create_run("client.ca")
    rg.db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    rg.generate_summary("client.ca", run_id=run_id)
    assert (out_dir / f"strategic_briefing_run_{run_id}.md").exists()
    assert (out_dir / f"audit_results_run_{run_id}.xlsx").exists()
    assert not (tmp_path / f"strategic_briefing_run_{run_id}.md").exists()


def test_cm20_the_volatility_sign_convention_is_stated(reporter):
    db = reporter.db
    run1, run2 = db.create_run("client.ca"), db.create_run("client.ca")
    for run_id, position in ((run1, 4), (run2, 9)):
        db.save_competitor_metrics(
            [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
              "position": position, "traffic": 1.0}], run_id=run_id)
    content = reporter.generate_summary("client.ca", run_id=run2)
    assert "## 📉 Volatility Alerts" in content
    assert "positive = moved **DOWN**" in content or "**positive = moved DOWN**" in content


def test_cm20_the_overlap_figure_is_named_best_rival_etv(reporter):
    """It is MAX(competitor_metrics.traffic) — the best-ranking rival's DataForSEO
    ETV — and it was labelled "Volume by cell (est. traffic)" and stored in a column
    called `keyword_volume`."""
    db = reporter.db
    run_id = db.create_run("client.ca")
    db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    db.save_serp_overlap(run_id, [{
        "keyword": "kw", "snapshot_date": "2026-11-15", "competitors_ranking": {},
        "self_position": 5, "overlap_count": 1, "commodity_score": 1.0,
        "best_rival_etv": 450.0, "cell": "shared_commodity",
        "all_competitor_gap": False, "config_ref": "x",
        "estimation_basis": "local"}])
    content = reporter.generate_summary("client.ca", run_id=run_id)
    assert "Best-rival ETV by cell" in content
    assert "not search volume, not your traffic" in content
    sheet = pd.ExcelFile(f"audit_results_run_{run_id}.xlsx").parse("SERP Overlap")
    assert "best_rival_etv" in sheet.columns
    assert "keyword_volume" not in sheet.columns
    assert float(sheet.loc[0, "best_rival_etv"]) == 450.0


# ── C-M-20: the Executive Summary states fresh vs cached vs blocked ──────────

def test_cm20_coverage_block_states_blocked_cached_and_incomplete(reporter):
    """"the console already has the numbers" — a reader of the .md could not tell a
    blocked domain from one with nothing to report, nor cached figures from fresh."""
    db = reporter.db
    run_id = db.create_run("client.ca")
    db.save_competitor_metrics(
        [{"domain": "comp.com", "url": "https://comp.com/a", "keyword": "kw",
          "position": 2, "traffic": 1.0}], run_id=run_id)
    content = reporter.generate_summary(
        "client.ca", run_id=run_id,
        run_coverage={"handoff_file": "h.json", "domains_in_handoff": 4,
                      "domains_audited": 3, "pa_measured": 2, "pa_total": 3,
                      "blocked_domains": ["blocked.ca"],
                      "cached_domains": ["cached.ca"],
                      "incomplete_tier_domains": ["cached.ca"],
                      "skipped_domains": [("omit.ca", "on the omit list")],
                      "universe": {"handoff": 4, "enrichment_kept": 2,
                                   "enrichment_dropped_brand": 1,
                                   "enrichment_dropped_irrelevant": 7}})
    assert "Blocked by the 429 circuit breaker" in content and "blocked.ca" in content
    assert "Served at least one page from the 7-day semantic cache" in content
    assert "cached.ca" in content
    assert "Tier counts incomplete" in content
    assert "audited 3 of 4 handoff domain(s)" in content
