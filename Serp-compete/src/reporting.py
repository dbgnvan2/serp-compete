import os

import pandas as pd
from src.database import DatabaseManager, load_shared_config, magnet_sql, magnet_thresholds
import datetime

from src.risk_radar import anchor_caveat_lines, anchor_data_unreadable


#: What an unknown value reads as in a rendered markdown table. An em dash,
#: not an empty cell: a blank is indistinguishable from a rendering fault, and
#: the briefing's whole convention is that absence is stated.
UNKNOWN_CELL = "—"


def md_table(df, **kwargs) -> str:
    """`df.to_markdown` with missing values rendered as `—` rather than `nan`.

    Purpose: stop a float artefact appearing in the owner's tables.
    Tests:   Serp-compete/tests/test_report_rendering.py

    Found by rendering a briefing and reading it (2026-11-16): the Competitor
    Ranking Summary printed `pages_audited` as `nan` for the two domains whose
    pages errored or were blocked, and the Barbell table printed `focus_score`
    as `nan` for the three domains whose focus was deliberately WITHHELD for
    too small a sample. The withholding was correct and the `quadrant` column
    said `insufficient_data` beside it — but the number next to it read as a
    broken calculation, which is the opposite of the point: this report's
    convention is that an unmeasured thing says so.

    Only display is affected. The Excel sheets keep the real NaN/None so the
    columns stay numeric and sortable, and nothing downstream parses this
    string.
    """
    if df is None:
        return ""
    # Work on a copy: filling in place would put the em dash into the frame the
    # Excel writer gets, where it must stay a real NULL so the column keeps its
    # type.
    out = df.copy()
    for column in out.columns:
        series = out[column]
        if not pd.api.types.is_float_dtype(series):
            continue
        present = series.dropna()
        # A count column holding one NULL becomes float64, so `pages_audited`
        # rendered as "1.0" and "2.0" once the NULLs were filled. Whole numbers
        # are printed as whole numbers; genuinely fractional columns
        # (medical_per_1000, shares) are left alone.
        if not present.empty and (present == present.round()).all():
            out[column] = series.map(
                lambda v: UNKNOWN_CELL if pd.isna(v) else str(int(v)))
    # `fillna` on a numeric column upcasts to object, which is what we want for
    # display.
    return out.fillna(UNKNOWN_CELL).to_markdown(**kwargs)


def gsc_pull_note(config) -> str:
    """The line that states which Google Search Console pull a section used.

    Purpose: stop a figure from this tool being read beside a figure from
             serp-discover as though both described the same traffic.
    Spec:    docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md §3 Chunk X
             (GSC bullet); docs/handoff_contract.md §GSC
    Tests:   Serp-compete/tests/test_handoff_contract.py::TestGscPullIsStated

    serp-discover pulls 90 days, all devices, global; this tool pulls the
    `gsc_settings.date_range_days` window with a `gsc_settings.country` filter
    so the client's own positions come from the same market as the Canada-scoped
    DataForSEO snapshot. Neither report said which pull it was.

    The values are read from the keys `GSCManager.fetch_performance_data` reads,
    not restated here, so this line cannot drift from the request that was
    actually made. A function rather than inline text for the same reason
    `anchor_caveat_lines` is one: the decision is then testable without
    standing up a whole report.
    """
    settings = ((config or {}).get("gsc_settings", {}) or {})
    try:
        days = int(settings.get("date_range_days", 90))
    except (TypeError, ValueError):
        days = 90
    country = str(settings.get("country", "can") or "").strip().lower()
    return (
        f"_Pull: last {days} days, "
        + (f"country `{country}`" if country else "no country filter")
        + ", all devices, query × page. "
        + ("The country filter matches the DataForSEO SERP snapshot, which is a "
           "Canada snapshot, so the two are comparable. " if country else
           "No country filter, so this is global traffic and is NOT comparable "
           "with the Canada-scoped DataForSEO SERP snapshot. ")
        + "serp-discover pulls GSC over its own window; figures from the two "
          "reports are comparable only where both state the same window and "
          "filter._")


class ReportGenerator:
    def __init__(self, db_path: str = None):
        # None, not a literal: DatabaseManager falls through to load_db_path(),
        # which reads shared_config technical.database_path. The literal
        # default short-circuited that and opened a CWD-relative
        # competitor_history.db — a DIFFERENT file from the one the audit
        # writes — so every section read a stale database, and the anchor
        # coverage this class now reads from the DB was never found (P6/P16).
        self.db = DatabaseManager(db_path)
        # The magnet / vacuum definition is editorial config (C-M-02), and the
        # report must render the same definition the audit wrote with rather than
        # re-inventing thresholds of its own (P4).
        self.config = load_shared_config()
        self.vacuum_min_medical, self.magnet_max_position = magnet_thresholds(self.config)
        # C-C-16: honour `orchestrator.reports_dir`. The GUI wrote the setting into
        # shared_config.json and nothing read it, so new reports kept landing in
        # Serp-compete/ while "Previous Reports" browsed somewhere else.
        orchestrator_cfg = self.config.get("orchestrator", {}) or {}
        self.output_dir = orchestrator_cfg.get("reports_dir") or "."
        # C-C-07: display caps for the MARKDOWN only; the Excel sheets get the full
        # frame. Editorial, display-only (shared_config `reporting.*`).
        reporting_cfg = self.config.get("reporting", {}) or {}
        self.markdown_row_cap = int(reporting_cfg.get("markdown_row_cap", 30))
        self.magnet_row_cap = int(reporting_cfg.get("magnet_markdown_row_cap", 20))
        self.t2_depth_min = int(reporting_cfg.get("systems_depth_min_t2", 3))

    def _geo_citation_check(self, conn, run_id: int, df_geo) -> str:
        """Do the Strong-tier domains actually get cited? (C-M-14)

        The serp-discover AI-visibility export is the ONE thing in this system that
        records real citations, and the extractability section never looked at it. When
        this run consumed an export (`sov_daily` carries citation_share per entity),
        the tiers are checked against it: a Strong-tier page on a domain no engine
        cited is the honest counter-evidence to a structural heuristic, and it is
        better for the owner to see that than to be told the structure is "why"
        anything happens.
        """
        try:
            cited = {row[0] for row in conn.execute(
                "SELECT DISTINCT entity FROM sov_daily "
                "WHERE run_id = ? AND citation_share IS NOT NULL AND citation_share > 0",
                (run_id,)).fetchall() if row[0]}
        except Exception:  # noqa: BLE001 - an optional cross-check, never fatal
            cited = set()
        if not cited:
            return ("_No AI-visibility export was consumed this run, so no page here "
                    "can be checked against a real citation._")
        strong = df_geo[df_geo["extractability_tier"] == "Strong"]
        if strong.empty:
            return ("_No Strong-tier pages this run, so there is nothing to check "
                    "against the citation data._")
        from src.brand_utils import normalise_domain
        cited_norm = {normalise_domain(entity) for entity in cited}
        strong_domains = {normalise_domain(str(url).split("/")[2])
                          for url in strong["url"] if str(url).count("/") >= 2}
        confirmed = sorted(strong_domains & cited_norm)
        unconfirmed = sorted(strong_domains - cited_norm)
        return (f"_Checked against the AI-visibility export: of the Strong-tier "
                f"domains, {len(confirmed)} of {len(strong_domains)} were actually "
                f"cited by an engine"
                + (f" ({', '.join(confirmed)})" if confirmed else "")
                + (f"; not cited: {', '.join(unconfirmed)}" if unconfirmed else "")
                + ". A Strong tier with no citation is evidence against the "
                  "heuristic, not against the page._")

    def _capped(self, df, cap: int, label: str):
        """(display frame, "showing N of M" note) — C-C-07.

        A LIMIT in the SQL truncated the markdown AND the Excel sheet identically and
        said nothing: the EEAT and GEO sections showed the alphabetically-first ~10
        competitors of 15 and the Excel sheet, which is supposed to be the full
        export, was cut to the same 30 rows.
        """
        total = len(df)
        if total <= cap:
            return df, f"_{total} {label}._"
        return (df.head(cap),
                f"_Showing the first {cap} of {total} {label} — the full set is in "
                f"the Excel workbook._")

    def generate_summary(self, client_domain: str, expected_competitors: list = None, run_id: int = None, reframes: list = None, token_usage: dict = None, market_alerts: list = None, gsc_findings: dict = None, run_coverage: dict = None):
        """
        Generate a Markdown report summarizing the audit findings for a specific run.

        `run_coverage` (C-C-03 / C-C-12) carries what the console used to keep to
        itself: how many handoff domains were audited, which were skipped and why,
        which had no Moz authority figure, and how the keyword universe was
        assembled. Optional, so an old caller still works — but then the briefing
        says the coverage was not recorded rather than implying full coverage.
        """
        if run_id is None:
            run_id = self.db.get_latest_run_id()
            
        if not run_id:
            print("No runs found in database.")
            return

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        handoff_name = (run_coverage or {}).get("handoff_file")
        report = [
            f"# Serp-comp Strategic Briefing (Run ID: {run_id})",
            f"**Client:** {client_domain}",
            f"**Date:** {timestamp}",
            # C-C-16: name the input. Two handoffs in the project root differ only by
            # timestamp, and the briefing used to be silent about which one it read.
            f"**Handoff:** {os.path.basename(handoff_name) if handoff_name else 'not recorded for this run'}",
            "\n## Executive Summary",
            "This report identifies strategic openings where competitors rely on the 'Medical Model' and provides automated Bowen-based reframes."
        ]

        # Run coverage, in the artefact rather than only in the console (P2).
        if run_coverage:
            skipped = run_coverage.get("skipped_domains") or []
            report.append(
                f"\n**Run coverage:** audited "
                f"{run_coverage.get('domains_audited', 0)} of "
                f"{run_coverage.get('domains_in_handoff', 0)} handoff domain(s); "
                f"Page Authority measured for {run_coverage.get('pa_measured', 0)} of "
                f"{run_coverage.get('pa_total', 0)} audited URL(s).")
            if skipped:
                report.append("**Skipped domains:** "
                              + "; ".join(f"{d} — {r}" for d, r in skipped) + ".")
            unmeasured = run_coverage.get("unmeasured_pa_domains") or []
            if unmeasured:
                report.append(
                    "> ⚠️ **Page Authority was unmeasured** for "
                    + ", ".join(unmeasured)
                    + ". The `avg PA > 50` high-authority filter could not be applied "
                      "to them, and their authority figures are NULL (unknown), not 0.")
            enrichment_failures = run_coverage.get("enrichment_failures") or []
            if enrichment_failures:
                report.append(
                    "> ℹ️ **Keyword enrichment was unavailable** for "
                    + "; ".join(f"{d} ({r})" for d, r in enrichment_failures)
                    + ". Those domains were audited on their handoff targets only.")
            blocked = run_coverage.get("blocked_domains") or []
            if blocked:
                report.append(
                    "> 🛑 **Blocked by the 429 circuit breaker** (remaining pages not "
                    "audited): " + ", ".join(blocked) + ".")
            cached = run_coverage.get("cached_domains") or []
            if cached:
                report.append(
                    "> ⚡ **Served at least one page from the 7-day semantic cache:** "
                    + ", ".join(cached)
                    + ". Their scores are as fresh as that cached scrape, not as this run.")
            incomplete = run_coverage.get("incomplete_tier_domains") or []
            if incomplete:
                report.append(
                    "> ℹ️ **Tier counts incomplete** for " + ", ".join(incomplete)
                    + " (pages cached before the counts were persisted), so their "
                      "`market_position` classification is withheld this run.")
            universe = run_coverage.get("universe") or {}
            if universe:
                report.append(
                    f"**Keyword universe:** {universe.get('handoff', 0)} handoff "
                    f"target(s); {universe.get('enrichment_kept', 0)} enrichment "
                    f"keyword(s) kept, "
                    f"{universe.get('enrichment_dropped_brand', 0)} dropped as the "
                    f"competitor's own brand and "
                    f"{universe.get('enrichment_dropped_irrelevant', 0)} as off-topic.")
            # Chunk X (rank semantics / H1): serp-discover stores SerpAPI's
            # per-page `position` verbatim and concatenates paginated pages
            # without an offset, so the handoff's ranks restart at 1 on every
            # page. Until its chunk D1 lands and bumps `schema_version`, a
            # "rank 2" in this report may be the second result of page 3.
            if run_coverage.get("rank_semantics_error"):
                report.append(
                    f"> ⚠️ **The handoff's rank convention could not be determined** "
                    f"({run_coverage['rank_semantics_error']}), so whether the `rank` "
                    f"column holds an absolute SERP position or serp-discover's "
                    f"per-page one is unknown for this run. Treat it as page-relative "
                    f"until checked — that is what every shipped handoff version "
                    f"carries.")
            elif run_coverage.get("rank_is_absolute") is False:
                report.append(
                    f"> ⚠️ **Handoff ranks are page-relative.** This handoff is "
                    f"schema v{run_coverage.get('handoff_version') or '?'}, which "
                    f"carries serp-discover's per-page SERP `position` rather than an "
                    f"absolute one (review finding H1 / D-C-01, open on the "
                    f"serp-discover side). Several targets can therefore share a rank, "
                    f"and a rank of 2 may be the second result of page 3. Read the "
                    f"`rank` column below as \"where on its SERP page\", not as a "
                    f"market position; `handoff.absolute_rank_versions` in "
                    f"`shared_config.json` is what retires this warning.")
        else:
            report.append("\n_Run coverage was not recorded for this run — how many "
                          "handoff domains were audited, skipped or unmeasured is "
                          "unknown here, not zero._")

        # Initialize dataframes for later use in Excel export
        df_eeat = pd.DataFrame()
        df_clusters = pd.DataFrame()
        df_metrics = pd.DataFrame()
        df_magnets = pd.DataFrame()
        df_geo = pd.DataFrame()
        df_overlap = pd.DataFrame()
        df_feasibility = pd.DataFrame()
        df_positioning = pd.DataFrame()
        df_sov = pd.DataFrame()
        df_brand = pd.DataFrame()
        df_risk = pd.DataFrame()

        if gsc_findings:
            report.append("\n## 📈 Internal GSC Performance Gaps")
            report.append("Analysis of our own site's performance in Google Search Console.")
            report.append(gsc_pull_note(self.config))


            target_gaps = gsc_findings.get("target_gaps")
            if target_gaps is not None and not target_gaps.empty:
                report.append("\n### High Impression / Low CTR Gaps")
                report.append("These internal keywords are being seen but not clicked. Reframe the Meta Titles with systemic depth.")
                report.append(md_table(target_gaps[['query', 'impressions', 'ctr', 'tier']],
                                       index=False))

            low_hanging = gsc_findings.get("low_hanging")
            if low_hanging is not None and not low_hanging.empty:
                report.append("\n### Low-Hanging Fruit (Page 2 Targets)")
                report.append("Internal pages ranking in positions 11-20. A systemic boost could push them to Page 1.")
                report.append(md_table(
                    low_hanging[['query', 'page', 'position', 'impressions']],
                    index=False))

            mismatches = gsc_findings.get("mismatches")
            if mismatches:
                report.append("\n### Clinical Mismatches")
                report.append("Detected instances where our Systems-heavy pages are being found via Medical Model queries.")
                report.append(md_table(pd.DataFrame(mismatches), index=False))

        if token_usage:
            report.append("\n## 💰 AI Token Usage")
            report.append(f"- **Prompt Tokens:** {token_usage.get('prompt_tokens', 0)}")
            report.append(f"- **Completion Tokens:** {token_usage.get('completion_tokens', 0)}")
            report.append(f"- **Total Tokens:** {token_usage.get('total_tokens', 0)}")

        with self.db._get_connection() as conn:
            # 1. Volatility Alerts
            volatility = self.db.get_volatility_alerts(run_id)
            if volatility:
                report.append("\n## 📉 Volatility Alerts")
                # C-M-20: the sign convention was never stated, and in SERP positions
                # a bigger number is worse — the opposite of most metrics.
                report.append("_`shift` is the change in the domain's average "
                              "position since the previous run: **positive = moved "
                              "DOWN** (worse), negative = moved up. Averaged over the "
                              "keywords both runs measured._")
                df_vol = pd.DataFrame(volatility)
                report.append(md_table(df_vol, index=False))

            # Spec 4: Fragile Magnets — ONE authority-drift detector (C-C-05 / C-M-06).
            # There used to be two, under two headings, for the same event:
            # `database.get_feasibility_drift` (drift < -2, per URL) and
            # `VelocityTracker.get_market_alerts` (da_drift < 0, unscoped). The first
            # is gone; this is the survivor, run-scoped and thresholded.
            if market_alerts:
                report.append("\n## 🚩 Expert Alerts: Fragile Magnets (authority drift)")
                threshold = next((a.get('pa_drop_min') for a in market_alerts
                                  if a.get('pa_drop_min') is not None), None)
                report.append(
                    "Competitor pages whose Moz Page Authority fell measurably between "
                    "this run and the previous run that saw the same page"
                    + (f", by at least {threshold:g} point(s) "
                       f"(`risk_signals.pa_drop_min`, editorial and uncalibrated)"
                       if threshold is not None else "")
                    + ". _A page whose authority was not measured in both runs is "
                      "absent from this list — unknown, not unchanged._")
                for alert in market_alerts:
                    if alert['type'] == 'Fragile Magnet':
                        rank_drift = alert.get('rank_drift')
                        rank_note = ("rank unchanged" if rank_drift == 0
                                     else (f"rank drift {rank_drift}" if rank_drift is not None
                                           else "rank not measured in both runs"))
                        report.append(
                            f"- **{alert['domain']}** ({alert['keyword']}): Page Authority "
                            f"drift {alert['da_drift']:g}, {rank_note}. "
                            f"**Strategic Advice:** {alert['advice']}")
                    else:
                        report.append(f"- **{alert['type']}**: {alert['domain']} ({alert['keyword']})")

            # Revision 3: Competitor Overview with Market Position & Systemic Depth.
            #
            # C-C-02 / C-M-04: `total_keywords` used to be
            # SUM(CASE WHEN m.keyword IS NOT NULL ...) over a LEFT JOIN against
            # traffic_magnets with no URL condition — a cross product. Each metrics
            # row was multiplied by the number of magnet rows for the domain, so a
            # domain with 10 ranked keywords and 3 audited pages reported 30
            # keywords (run_11 shows 30 for almost every domain, 21 = 7×3, 27 = 9×3)
            # and `competitor_mining.get_top_domains` sorted competitors by it. The
            # magnet aggregates now come from a per-domain subquery, and the keyword
            # count is COUNT(DISTINCT m.keyword).
            df_metrics = pd.read_sql_query('''
                SELECT m.domain,
                       COUNT(DISTINCT m.url) as top_pages,
                       COUNT(DISTINCT m.keyword) as sampled_keywords,
                       AVG(m.position) as avg_pos,
                       tm.pages_audited,
                       tm.max_med,
                       tm.max_sys,
                       tm.max_t3,
                       tm.t2_total,
                       tm.tier_counts_known,
                       tm.has_surface,
                       meta.market_position,
                       meta.strategy as recommended_strategy
                FROM competitor_metrics m
                LEFT JOIN competitor_metadata meta ON m.domain = meta.domain
                LEFT JOIN (
                    SELECT domain,
                           COUNT(*) as pages_audited,
                           MAX(medical_score) as max_med,
                           MAX(systems_score) as max_sys,
                           MAX(COALESCE(t3_count, 0)) as max_t3,
                           SUM(COALESCE(t2_count, 0)) as t2_total,
                           MIN(CASE WHEN t2_count IS NULL OR t3_count IS NULL
                                    THEN 0 ELSE 1 END) as tier_counts_known,
                           MAX(CASE WHEN systemic_label = "Surface-Level" THEN 1 ELSE 0 END) as has_surface
                    FROM traffic_magnets
                    WHERE run_id = ?
                    GROUP BY domain
                ) tm ON tm.domain = m.domain
                WHERE m.run_id = ?
                GROUP BY m.domain
            ''', conn, params=(run_id, run_id))

            def get_systemic_depth(row):
                """C-M-05: depth from the TIER COUNTS, not from a comparison of a raw
                medical count with a weighted systems score.

                The old bands were: `systems_score > 0 AND label != 'Surface-Level'`
                → "High" (so one occurrence of "relationship", score 0.5, read as
                high systemic depth); then `max_med > max_sys` → "Medical", comparing
                a raw Tier-1 count with a ×2.0/×0.5-weighted score, so two medical
                words beat three Tier-2 words. The manual tells the owner to pick
                targets with this column.
                """
                if not row.get('tier_counts_known'):
                    return "Not recorded"
                if (row.get('max_t3') or 0) >= 1:
                    return "Bowen (Tier 3 present)"
                if (row.get('t2_total') or 0) >= self.t2_depth_min:
                    return "Systems (Tier 2 only)"
                if row.get('has_surface') == 1:
                    return "Surface-Level"
                if (row.get('t2_total') or 0) > 0:
                    return "Trace (1-2 Tier 2 terms)"
                return "None detected"

            if not df_metrics.empty:
                df_metrics['systemic_depth'] = df_metrics.apply(get_systemic_depth, axis=1)
                # Reorder columns to include systemic_depth
                cols = ['domain', 'top_pages', 'sampled_keywords', 'pages_audited',
                        'avg_pos', 'systemic_depth', 'market_position',
                        'recommended_strategy']
                df_metrics = df_metrics[cols]


            if expected_competitors:
                found_domains = df_metrics['domain'].tolist()
                missing = [d for d in expected_competitors if d not in found_domains]
                if missing:
                    report.append("\n### ⚠️ Missing Data Alert")
                    report.append(f"No ranking data found for: {', '.join(missing)}")

            if not df_metrics.empty:
                report.append("\n## Competitor Ranking Summary")
                report.append(
                    "_`sampled_keywords` is the number of DISTINCT keywords this run "
                    "audited for the domain — its handoff targets plus any enrichment "
                    "keywords that passed the relevance filter — not the keywords it "
                    "ranks for in total. `pages_audited` is how many of its pages were "
                    "scored (capped by `technical.max_audit_pages_per_domain`). "
                    "`avg_pos` averages whatever each keyword's source measured: the "
                    # C-C-17 changed the enrichment rank to `rank_group`, the
                    # organic position; this caveat still named `rank_absolute`,
                    # so the report described a scale it had stopped using.
                    "handoff rank for a handoff keyword, DataForSEO's `rank_group` "
                    "for an enrichment one. `systemic_depth` reads the Tier-2/Tier-3 "
                    "counts; `Not recorded` means a cached page predates those counts._")
                report.append(md_table(df_metrics, index=False))
                # C-M-01: say where this run's keywords came from. `handoff` =
                # Tool 1 measured the URL ranking for it; `ranked_keywords` = a
                # DataForSEO enrichment keyword that passed the relevance filter;
                # `unlabelled` = written before provenance was recorded.
                sources = self.db.keyword_source_counts(run_id)
                if sources:
                    report.append(
                        "\n**Keyword provenance:** "
                        + ", ".join(f"{src}: {n}" for src, n in sorted(sources.items()))
                        + ". `handoff` keywords are what Serp-Discover measured ranking; "
                          "`ranked_keywords` are DataForSEO enrichment keywords kept only "
                          "when they are in the handoff set or carry a clinical term, and "
                          "never when they contain the competitor's own brand token.")

            # 2b. EEAT Scores (Gap 3 enhancement).
            # C-C-07: no LIMIT in the SQL — the Excel sheet gets every row and the
            # markdown is capped for readability with a "showing N of M" line.
            # Ordered by confidence tier, then url: `ORDER BY url LIMIT 30` meant the
            # section showed the alphabetically-first ~10 competitors of 15.
            df_eeat = pd.read_sql_query('''
                SELECT url, score_confidence, experience_score, expertise_score,
                       authoritativeness_score, trustworthiness_score
                FROM eeat_scores
                WHERE run_id = ?
                ORDER BY
                    CASE score_confidence
                        WHEN 'high' THEN 0 WHEN 'medium' THEN 1
                        WHEN 'low' THEN 2 ELSE 3 END, url
            ''', conn, params=(run_id,))

            if not df_eeat.empty:
                report.append("\n## EEAT Competitive Analysis (Heuristic)")
                report.append("Experience, Expertise, Authoritativeness, and Trustworthiness heuristic scores.")
                # C-M-12: 1 dp, not 2. These composites are weighted sums of
                # BOOLEANS — trustworthiness can only take the values
                # {0, .3, .4, .6, .7, 1.0}, and 0.4 of it is the scheme of the URL
                # DataForSEO returned — so a second decimal place implies a
                # resolution the inputs do not have.
                # pd.notna, not `is not None`: pandas reads a SQL NULL as NaN
                # in a numeric column, and `NaN is not None` is True — so a
                # page whose dimension could not be computed printed "nan"
                # beside the pages that could. It only looked right when EVERY
                # value was NULL (the column is then dtype object and the
                # values really are None), which is why the mixed case — one
                # competitor's Domain Authority unmeasured, the realistic one —
                # was the broken one. Same defect as the SoV presence_rate
                # line, found the same day by rendering the section.
                #
                # Formatted on a COPY. `df_eeat` is the frame the Excel writer
                # gets (line ~1096), and formatting in place turned four
                # float64 columns into TEXT — "0.6" and "—" — so the workbook's
                # EEAT scores could not be sorted, charted or averaged, and the
                # em dash sat in a numeric column. The markdown wants strings;
                # the sheet wants numbers and real NULLs. Same reason `md_table`
                # fills a copy.
                display_eeat = df_eeat.copy()
                for col in ['experience_score', 'expertise_score', 'authoritativeness_score', 'trustworthiness_score']:
                    display_eeat[col] = display_eeat[col].apply(
                        lambda x: f"{x:.1f}" if pd.notna(x) else UNKNOWN_CELL)
                # A table of dashes with no stated cause is the failure mode
                # this report exists to avoid. The usual cause is an absent
                # `eeat_weights` block: EEATScorer then has nothing to weight
                # with and correctly computes nothing, silently.
                _dimensions = ['experience_score', 'expertise_score',
                               'authoritativeness_score', 'trustworthiness_score']
                if all((display_eeat[col] == UNKNOWN_CELL).all()
                       for col in _dimensions):
                    report.append(
                        "> ⚠️ **No EEAT composite could be computed for any page.** The "
                        "signals below were read, but the scores were not: check that "
                        "`eeat_weights` is present in `shared_config.json` — without it "
                        "there is nothing to weight the signals with, and the scorer "
                        "returns unknown for every dimension. This is not a finding "
                        "about the competitors.")
                report.append(
                    "_Each score is a weighted sum of BOOLEAN signals, so it moves in "
                    "steps, not continuously — trustworthiness, for example, can only "
                    "be 0, 0.3, 0.4, 0.6, 0.7 or 1.0, and 0.4 of it is simply whether "
                    "the URL is https. `score_confidence` is now **signal coverage** "
                    "(the share of weighted signals that could be read at all), and it "
                    "is capped below `high` whenever one of the four composites could "
                    "not be computed — it used to read `high` for every page that "
                    "loaded. Authoritativeness uses the domain's Moz Domain Authority; "
                    "it was being given the individual URL's Page Authority._")
                disp_eeat, eeat_note = self._capped(display_eeat, self.markdown_row_cap,
                                                    "scored page(s)")
                report.append(eeat_note)
                report.append(md_table(disp_eeat, index=False))
                report.append("\n_Note: These scores are heuristic proxies based on SEO industry conventions, not Google's proprietary EEAT model._")

            # 2c. Cluster Analysis (Gap 4 enhancement)
            df_clusters = pd.read_sql_query('''
                SELECT domain, pages_analysed, cluster_signal, avg_in_degree, max_in_degree
                FROM cluster_results
                WHERE run_id = ?
                ORDER BY domain
            ''', conn, params=(run_id,))

            if not df_clusters.empty:
                report.append("\n## Internal Linking Cluster Analysis")
                report.append("Detection of hub pages and linking patterns within competitor sites.")
                df_clusters['avg_in_degree'] = df_clusters['avg_in_degree'].apply(lambda x: f"{x:.2f}" if x is not None else "—")
                report.append(md_table(df_clusters, index=False))
                report.append("\n_Note: Analysis based on N≤3 scraped pages per domain. Full site structure not visible._")

            # 3. Traffic Magnets with Systemic Label.
            # C-M-02 (owner decision 2, 2026-11-14): the documented definition is now
            # implemented rather than the section renamed — a magnet ranks well on a
            # handed-over keyword (handoff rank <= magnet_max_position), uses medical
            # language (medical_score >= vacuum_min_medical), and its keyword passed the
            # relevance test. The predicate lives in database.magnet_sql so the magnet
            # table, the vacuum list and the reframe query cannot drift apart.
            floor, max_pos = self.vacuum_min_medical, self.magnet_max_position
            # C-C-07: the full magnet frame. `LIMIT 20` truncated the Excel sheet
            # identically to the markdown, and the Systemic-Vacuum list was then a
            # subset of that truncated set — with est_traffic ties (DataForSEO `etv`
            # 0 is common) deciding arbitrarily which 20 survived.
            df_magnets = pd.read_sql_query(
                magnet_sql(), conn, params=(run_id, floor, max_pos))
            # C-M-19: length-normalise for display. Derived here rather than stored
            # twice, from the count and the window that produced it.
            if not df_magnets.empty:
                df_magnets = df_magnets.rename(columns={"scoring_window_words": "words"})
                df_magnets["medical_per_1000"] = [
                    (round(1000.0 * float(med) / float(words), 1)
                     if words else None)
                    for med, words in zip(df_magnets["medical_score"], df_magnets["words"])]
            audited_pages = self.db.count_audited_pages(run_id)
            # Whether a Systemic Vacuum list was actually rendered. The SERP
            # Overlap section says it "folds in the Systemic Vacuum list above",
            # and in a run where nothing could be scored that pointed at a
            # section which is not there (found by rendering the total-outage
            # scenario).
            vacuums_rendered = False
            magnet_filter_note = (
                f"_Filter: handoff rank ≤ {max_pos}, medical_score ≥ {floor} "
                f"(`technical.vacuum_min_medical`, editorial and uncalibrated), and the "
                f"keyword is in the handoff set or carries a clinical term and not the "
                f"competitor's own brand token. `est_traffic` is DataForSEO's estimated "
                f"monthly visits for that keyword×position, 0 when it was not measured. "
                f"`medical_score` is a COUNT of Tier-1 terms and `medical_per_1000` the "
                f"same count per 1000 scored words (`words` is the window it was counted "
                f"over) — the count alone meant different things in a short page and a "
                f"long one._")

            if not df_magnets.empty:
                disp_magnets, magnet_note = self._capped(
                    df_magnets, self.magnet_row_cap, "qualifying page(s)")
                report.append("\n## Identified 'Traffic Magnets'")
                report.append(f"{len(df_magnets)} of {audited_pages} audited page(s) "
                              f"meet the magnet definition. {magnet_note}")
                report.append(magnet_filter_note)
                report.append(md_table(disp_magnets, index=False))

                # Spec 2: Highlight Systemic Vacuums — the magnets with no systemic
                # language. Same predicate as the reframe targets, by construction.
                vacuums = df_magnets[(df_magnets['systems_score'] == 0) | (df_magnets['systemic_label'] == 'Surface-Level')]
                vacuums_rendered = not vacuums.empty
                if not vacuums.empty:
                    disp_vacuums, vacuum_note = self._capped(
                        vacuums, self.markdown_row_cap, "vacuum(s)")
                    report.append("\n### ⚡ Strategic Targets: Systemic Vacuums")
                    report.append("These competitors rank on a handed-over keyword using medical language and show no real systemic framing. They are our **primary targets** for content reframing.")
                    report.append(vacuum_note)
                    for _, v in disp_vacuums.iterrows():
                        label_str = f" [{v['systemic_label']}]" if v['systemic_label'] != 'Standard' else ""
                        report.append(
                            f"- **{v['domain']}** ({v['primary_keyword']} — "
                            f"{v['keyword_source']}, rank {v['rank']}): Medical Score "
                            f"{v['medical_score']}, Systems Score {v['systems_score']}{label_str}")
            elif audited_pages:
                # Absence stated, not implied: 100 audited pages and no magnet is a
                # fact about the filter, and the reader cannot otherwise tell it from
                # "nothing was audited" (P2).
                report.append("\n## Identified 'Traffic Magnets'")
                report.append(f"None of the {audited_pages} audited page(s) met the "
                              f"magnet definition this run.")
                report.append(magnet_filter_note)
            else:
                # …and the third case, which the branch above names but did not
                # handle: NOTHING was scored, so the section used to vanish
                # entirely. A reader seeing no Traffic Magnets heading cannot
                # tell "no competitor page qualified" from "no competitor page
                # could be read", and this is the report's primary action list.
                # Found by rendering the total-outage scenario and reading it
                # (tools/render_sample_briefing.py).
                report.append("\n## Identified 'Traffic Magnets'")
                report.append(
                    "**No page could be scored this run**, so there is nothing to "
                    "qualify or to rule out. This is not a finding that competitors "
                    "have no Traffic Magnets — see the run coverage in the Executive "
                    "Summary for which domains were blocked, skipped or unmeasured.")

            # 3b. GEO / Extractability — Why Competitors Get Cited (SC-1)
            df_geo = pd.read_sql_query('''
                SELECT url, extractability_tier, question_heading_count,
                       present_signals, why_cited
                FROM geo_profiles
                WHERE run_id = ?
                ORDER BY
                    CASE extractability_tier
                        WHEN 'Strong' THEN 0 WHEN 'Moderate' THEN 1
                        WHEN 'Weak' THEN 2 ELSE 3 END, url
            ''', conn, params=(run_id,))

            if not df_geo.empty:
                # C-M-14: the section used to be headed "Why Competitors Get Cited"
                # and told the owner these structures are *why* rivals get cited,
                # while nothing here checks whether any page is cited by anything.
                report.append("\n## Extractability signals (structural, unvalidated)")
                report.append("Structural features associated with being quoted by AI answer engines "
                              "(FAQ schema, question-shaped headings, credentialed authorship, "
                              "freshness). **Nothing in this section measures citations** — it reads "
                              "page structure and nothing else. Treat it as a build checklist, not as "
                              "an explanation of why a rival is cited.")
                report.append(self._geo_citation_check(conn, run_id, df_geo))
                # C-C-07: capped for display only (tier order, then url); the sheet
                # carries all of them.
                disp_geo, geo_note = self._capped(df_geo, self.markdown_row_cap,
                                                  "profiled page(s)")
                report.append(geo_note)
                for _, g in disp_geo.iterrows():
                    report.append(f"- **{g['url']}** — _{g['extractability_tier']}_: {g['why_cited']}")
                report.append("\n_Heuristic structural proxies for AI citability, not measured citations. "
                              "Answer-first placement and FAQ-answers-in-HTML are not yet measured._")

            # 3c. SERP Overlap & Differentiation Gap (C4 / SC-6)
            df_overlap = pd.read_sql_query('''
                SELECT keyword, cell, self_position, overlap_count, commodity_score,
                       best_rival_etv, all_competitor_gap, estimation_basis,
                       competitors_ranking_json
                FROM serp_overlap
                WHERE run_id = ?
                ORDER BY overlap_count DESC, keyword
            ''', conn, params=(run_id,))

            if not df_overlap.empty:
                report.append("\n## SERP Overlap & Differentiation Gap")
                report.append("Where you and tracked competitors collide on shared SERPs "
                              "(AI-absorption risk) vs. where you're uniquely present "
                              "(defensible). Cells: `shared_commodity` / `shared_defensible` / "
                              "`exclusive_self` / `exclusive_competitor` / `absent`. "
                              "_'Commodity' is a local overlap-density proxy — a strategic "
                              "framing, not a measured index._")
                # If the client's GSC positions were unavailable this run, self-presence
                # is UNKNOWN — say so loudly rather than imply "you're absent".
                if 'self_unknown' in set(df_overlap['cell']):
                    report.append("\n> ⚠️ **Client GSC positions were unavailable this run** — "
                                  "self-presence is UNKNOWN for these keywords (shown as "
                                  "`self_unknown`); exclusive-competitor / exclusive-self "
                                  "classifications are withheld to avoid a false 'you're absent'.")
                counts = df_overlap['cell'].value_counts().to_dict()
                report.append("\n**Cell distribution:** "
                              + ", ".join(f"{cell}: {n}" for cell, n in sorted(counts.items())))
                # C-M-20: this is not a search volume and not your traffic. It is
                # MAX(competitor_metrics.traffic) per keyword — the best-ranking
                # RIVAL's DataForSEO ETV — summed per cell.
                vol = df_overlap.groupby('cell')['best_rival_etv'].sum().to_dict()
                report.append("**Best-rival ETV by cell** (summed DataForSEO estimated "
                              "monthly visits of the best-ranking competitor per "
                              "keyword — not search volume, not your traffic): "
                              + ", ".join(f"{cell}: {int(v)}" for cell, v in sorted(vol.items())))
                excl = df_overlap[df_overlap['cell'] == 'exclusive_competitor']
                if not excl.empty:
                    n = len(excl)
                    report.append("\n### ⚔️ Action queue — exclusive-competitor (rivals rank, you're absent)"
                                  + (f"  _(top 15 of {n})_" if n > 15 else ""))
                    for _, r in excl.head(15).iterrows():
                        gap = " — **every tracked rival ranks**" if r['all_competitor_gap'] else ""
                        report.append(f"- **{r['keyword']}** ({int(r['overlap_count'])} rivals in top-N){gap}")
                comm = df_overlap[df_overlap['cell'] == 'shared_commodity']
                if not comm.empty:
                    n = len(comm)
                    report.append("\n### 🔁 Action queue — shared-commodity (differentiate or deprioritize)"
                                  + (f"  _(top 15 of {n})_" if n > 15 else ""))
                    for _, r in comm.head(15).iterrows():
                        report.append(f"- **{r['keyword']}** (you + {int(r['overlap_count'])} rivals; commoditized SERP)")
                report.append(
                    "\n_"
                    + ("Folds in the Systemic Vacuum list above (not duplicated). "
                       if vacuums_rendered else "")
                    + "Competitor positions are SERP-measured; self_position is "
                      "first-party GSC (see estimation_basis in the Excel sheet)._")

            # 3d. Competitor Feasibility (C4 / SC-6: check_feasibility, surfaced)
            df_feasibility = pd.read_sql_query('''
                SELECT domain, competitor_da, feasible, suggestion
                FROM competitor_feasibility
                WHERE run_id = ?
                ORDER BY feasible DESC, domain
            ''', conn, params=(run_id,))

            if not df_feasibility.empty:
                report.append("\n### 🎯 Competitor Feasibility (your DA vs. each competitor)")
                report.append("Whether a systemic counter-page can realistically compete, from "
                              "the Domain Authority gap (feasible when client DA + 5 ≥ competitor DA).")
                df_feasibility['feasible'] = df_feasibility['feasible'].apply(
                    lambda x: "✅" if x else "❌")
                report.append(md_table(df_feasibility, index=False))

            # 3e. Barbell Positioning Diagnostic (C2 / SC-4)
            df_positioning = pd.read_sql_query('''
                SELECT domain, is_client, authority_score, focus_score, quadrant,
                       rationale_json
                FROM positioning WHERE run_id = ?
                ORDER BY is_client DESC,
                    CASE quadrant WHEN 'authoritative' THEN 0 WHEN 'niche_owner' THEN 1
                        WHEN 'middle' THEN 2 WHEN 'emerging' THEN 3 ELSE 4 END, domain
            ''', conn, params=(run_id,))

            if not df_positioning.empty:
                report.append("\n## Barbell Positioning Diagnostic")
                report.append("Each domain on an **authority** (Moz DA + top-10 ranking count, "
                              "the same formula for you and competitors) vs. **focus** "
                              "(medical/systems tier-identity concentration) 2×2. "
                              "_Barbell framing: winners are large-and-authoritative "
                              "(`authoritative`) or small-and-niche (`niche_owner`); the "
                              "undifferentiated `middle` is the danger zone. `emerging` / "
                              "`insufficient_data` = too little signal to place, never silently "
                              "`middle`. Rivals with avg PA > 50 are filtered upstream, so an "
                              "empty `authoritative` quadrant does not mean none exist._")
                quad_counts = df_positioning['quadrant'].value_counts().to_dict()
                report.append("\n**Quadrant distribution:** "
                              + ", ".join(f"{q}: {n}" for q, n in sorted(quad_counts.items())))
                disp = df_positioning.copy()
                disp['domain'] = disp.apply(
                    lambda r: f"⭐ {r['domain']} (you)" if r['is_client'] else r['domain'], axis=1)
                # C-M-10: print the counts the focus figure came from, and the floor
                # it had to clear, so a quadrant can be checked rather than trusted.
                import json as _json

                def _rationale(row, key, default=""):
                    try:
                        return _json.loads(row['rationale_json'] or "{}").get(key, default)
                    except (TypeError, ValueError):
                        return default

                disp['tier_tokens'] = df_positioning.apply(
                    lambda r: _rationale(r, 'tier_tokens_total'), axis=1)
                disp['top10_count'] = df_positioning.apply(
                    lambda r: _rationale(r, 'top10_count'), axis=1)
                disp['authority_basis'] = df_positioning.apply(
                    lambda r: _rationale(r, 'authority_basis', 'unknown'), axis=1)
                report.append(md_table(
                    disp[['domain', 'authority_score', 'focus_score',
                          'quadrant', 'top10_count', 'tier_tokens',
                          'authority_basis']], index=False))
                floors = {str(_rationale(r, 'min_focus_tokens', '')) for _, r in
                          df_positioning.iterrows()} - {''}
                if floors:
                    report.append(
                        f"\n_`tier_tokens` is the unweighted Tier-1 + Tier-2/3 term "
                        f"count the focus figure was computed from; below "
                        f"{sorted(floors)[0]} (`positioning.min_focus_tokens`) focus is "
                        f"withheld and the domain reads `insufficient_data` rather than "
                        f"being placed on a handful of generic tokens. `top10_count` is "
                        f"over the handoff's keywords — the same universe for you and "
                        f"for competitors._")
                mid = df_positioning[df_positioning['quadrant'] == 'middle']
                if not mid.empty:
                    report.append("\n⚠️ **Danger zone (undifferentiated middle):** "
                                  + ", ".join(mid['domain'].tolist()) + ".")

            # 3f. Competitive AI Share-of-Voice (C1 / SC-3)
            df_sov = pd.read_sql_query('''
                SELECT engine, entity, entity_type, is_client, category,
                       mention_share, citation_share, presence_rate, avg_sentiment,
                       cited_gap
                FROM sov_daily WHERE run_id = ?
            ''', conn, params=(run_id,))

            # Chunk X: which engines actually answered. serp-discover writes
            # brand-mention rows for an engine that answered nothing (D-C-05 /
            # D-C-11), so those engines are now dropped from `sov_daily` rather
            # than published at 0% share — and an engine missing from the table
            # has to be named, or "not measured" reads as "measured, absent".
            sov_coverage = self.db.get_sov_coverage(run_id)
            # `measured` is three-valued. False = the export says this engine
            # answered nothing. None = the export carried no brand-mention rows
            # for it, which could be "asked, nothing matched" or "never ran" —
            # the two are indistinguishable from the file, so they get separate
            # wording rather than being collapsed.
            sov_unmeasured = [c["engine"] for c in sov_coverage
                              if c["measured"] is False]
            sov_unknown = [c["engine"] for c in sov_coverage
                           if c["measured"] is None]

            if not df_sov.empty:
                report.append("\n## Competitive AI Share-of-Voice")
                report.append("When the AI engines answer category questions, whose brand and "
                              "sources come back. Consumed from serp-discover's AI-visibility "
                              "probes (not re-probed here). _Rolling snapshots — LLM answers vary._")
                if sov_unmeasured:
                    report.append(
                        f"\n_Not measured this run: {', '.join(sorted(sov_unmeasured))} — "
                        f"the export carried no answered questions for "
                        f"{'these engines' if len(sov_unmeasured) > 1 else 'this engine'}, so "
                        f"{'they are' if len(sov_unmeasured) > 1 else 'it is'} excluded from "
                        f"the shares below rather than shown at 0%. Absence here is not "
                        f"evidence that the engine does not name these brands._")
                if sov_unknown:
                    report.append(
                        f"\n_Coverage unknown: {', '.join(sorted(sov_unknown))} — the "
                        f"export listed "
                        f"{'these engines' if len(sov_unknown) > 1 else 'this engine'} "
                        f"but carried no brand mentions for "
                        f"{'them' if len(sov_unknown) > 1 else 'it'}, which from the "
                        f"export alone could mean the questions were asked and no "
                        f"tracked brand came back, or that the engine did not run. "
                        f"Not counted either way._")
                for engine in sorted(df_sov['engine'].dropna().unique()):
                    eng = df_sov[df_sov['engine'] == engine]
                    report.append(f"\n### {engine}")
                    brands = eng[eng['entity_type'] == 'brand']
                    men = brands[brands['category'] != 'other']
                    men = men.sort_values('mention_share', ascending=False).head(10)
                    if not men.empty:
                        # C-M-17: `presence_rate` is the quantity the guide describes
                        # ("whose brand the models return") — named in k of n answers —
                        # and it was computed and never printed. `mention_share` is a
                        # share of all brand mentions, including "other".
                        report.append("**Mention share** (share of all brand mentions "
                                      "this engine made) **and presence** (the share of "
                                      "answers the brand was named in): " + ", ".join(
                            f"{r['entity']}{' (you)' if r['is_client'] else ''} "
                            f"{(r['mention_share'] or 0):.0f}%"
                            # pd.notna, not `is not None`: a SQL NULL arrives
                            # from pandas as NaN, which IS not None and would
                            # have rendered "named in nan% of answers". A brand
                            # row can now carry NULL here — the export gave no
                            # question count for it (Chunk X).
                            + (f" / named in {r['presence_rate'] * 100:.0f}% of answers"
                               if pd.notna(r['presence_rate']) else "")
                            for _, r in men.iterrows()))
                    # …and the remainder, so the shares visibly sum to 100.
                    other_share = brands[brands['category'] == 'other']['mention_share'].sum()
                    if other_share:
                        other_names = sorted(
                            brands[brands['category'] == 'other']['entity'].dropna().unique())
                        report.append(
                            f"**Other brands (not you, not a tracked competitor):** "
                            f"{other_share:.0f}% of mentions"
                            + (f" — {', '.join(other_names[:8])}" if other_names else "")
                            + ". A tracked rival that is mentioned but never cited used "
                              "to land here and be filtered out of the line above.")
                    gap_rows = eng[eng['cited_gap'] == 1]   # single source: the persisted flag
                    if not gap_rows.empty:
                        report.append("⚔️ **Cited but you're not:** "
                                      + ", ".join(sorted(gap_rows['entity'].dropna().unique())))

            # 3g. Branded-Demand Benchmark (C3 / SC-5)
            df_brand = pd.read_sql_query('''
                SELECT domain, brand, branded_search_volume, branded_volume_share,
                       branded_growth, est_branded_click_share, estimation_basis,
                       queries
                FROM brand_demand_bench WHERE run_id = ?
                ORDER BY branded_search_volume DESC
            ''', conn, params=(run_id,))

            if not df_brand.empty:
                report.append("\n## Branded-Demand Benchmark")
                report.append("Brand-search demand, you vs competitors, estimated from public "
                              "search volume for each practice's **display brand** (e.g. "
                              "\"Lavender Counselling\", not the bare stem \"lavender\"). "
                              "_Competitor figures are volume-estimated (not click-measured); "
                              "the exact query strings are in the `queries` column of the "
                              "Branded Demand Excel sheet — see `estimation_basis`._")
                n_unavailable = int((df_brand['estimation_basis'] == 'volume_unavailable').sum())
                if n_unavailable:
                    # C-C-11: this used to be an all-or-nothing caveat, because a
                    # per-brand provider failure was stored as 0 volume and a 0.00%
                    # share. Now each unmeasured brand is NULL and says so.
                    report.append(f"\n> ⚠️ **{n_unavailable} of {len(df_brand)} brand(s) could not "
                                  f"be measured this run** — the search-volume source did not "
                                  f"answer for them (likely a DataForSEO outage). Their volume is "
                                  f"unknown, not zero, and they are excluded from the share "
                                  f"denominator.")
                n_ambiguous = int((df_brand['estimation_basis'] == 'ambiguous_brand').sum())
                if n_ambiguous:
                    report.append(f"\n> ⚠️ **{n_ambiguous} brand name(s) are ambiguous** — the bare "
                                  f"stem's search volume swamps the practice name's "
                                  f"(`branded_demand.ambiguous_brand_ratio`), so the demand cannot "
                                  f"be attributed to the practice. Their share and growth are "
                                  f"withheld and they are excluded from the share denominator.")
                disp = df_brand.copy()
                disp['brand'] = disp.apply(
                    lambda r: (f"⭐ {r['brand']} (you)" if r['domain'] == client_domain
                               else r['brand']), axis=1)   # own row identifiable regardless of anchor
                # `queries` is Excel-only: one row can carry seven query strings, which
                # would make the markdown table unreadable.
                report.append(md_table(disp.drop(columns=['queries']), index=False))

            # 3h. Reputation-Risk Radar (C6 / SC-8)
            df_risk = pd.read_sql_query('''
                SELECT domain, is_own_site, signal_type, severity, evidence_json
                FROM risk_signal WHERE run_id = ?
                ORDER BY is_own_site DESC,
                    CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, domain
            ''', conn, params=(run_id,))

            # Read from the DB, like every other section reads its own data,
            # rather than being handed it by the caller. That is what makes an
            # OLD run's report able to say what could not be read; a threaded
            # parameter only ever describes the run happening right now.
            risk_coverage = self.db.get_anchor_coverage(run_id)
            if not risk_coverage:
                # {} means the run predates the table — flagged explicitly so
                # an old report cannot read as a clean bill of health (P6).
                risk_coverage = {"unrecorded": True}
            unreadable = anchor_data_unreadable(risk_coverage)
            if not df_risk.empty or unreadable:
                report.append("\n## Reputation-Risk Radar")
                report.append("Patterns Google is known to penalize — visibility cliffs, off-topic "
                              "commercial subfolders (site-reputation abuse), ranking volatility, "
                              "and paid-link/PBN footprints in inbound anchor text. "
                              "_**Pattern detections, not confirmed Google penalties.**_")
                # C-C-06 / C-M-07: say why a cliff may be absent. The series is now
                # per RUN (not per calendar day) and normalised by how many keywords
                # were measured, and it is withheld entirely below
                # `risk_signals.cliff_min_sample` — so "no visibility cliff" must not
                # be readable as "we looked and the visibility held".
                cliff_floor = (self.config.get("risk_signals", {}) or {}).get("cliff_min_sample")
                if cliff_floor:
                    report.append(
                        f"\n_`visibility_cliff` is computed per RUN from every ranked "
                        f"keyword of that run, as the share in the top 10, and only for "
                        f"domains with at least {cliff_floor} measured keywords in two or "
                        f"more runs (`risk_signals.cliff_min_sample`). Below that the "
                        f"signal is withheld, not reported as stable._")
                report.extend(anchor_caveat_lines(
                    df_risk['signal_type'].tolist() if not df_risk.empty else [],
                    risk_coverage))
                if df_risk.empty:
                    report.append("_No risk signals detected in this run._")
                own = df_risk[df_risk['is_own_site'] == 1]
                if not own.empty:
                    report.append("\n### ⚠️ Own-site warnings")
                    for _, r in own.iterrows():
                        report.append(f"- **{r['signal_type']}** ({r['severity']}) on "
                                      f"{r['domain']}: {r['evidence_json']}")
                comp = df_risk[df_risk['is_own_site'] == 0]
                if not comp.empty:
                    report.append("\n### 🔎 Competitor risk signals (opportunity intel)")
                    report.append(md_table(comp[['domain', 'signal_type', 'severity']],
                                           index=False))
                    for _, r in comp[comp['signal_type'] == 'anchor_text_spam'].iterrows():
                        report.append(f"- **{r['domain']}** anchor-text evidence: "
                                      f"{r['evidence_json']}")

            # 3i. YouTube Presence (SC-7-YT Phase 1). is_client is derived by domain match
            # (the branded-demand precedent), so the table carries no is_client column.
            df_yt = pd.read_sql_query('''
                SELECT domain, has_channel, handle, channel_title, subscriber_count,
                       last_upload_date, uploads_recent, match_confidence, check_status
                FROM yt_channel_presence WHERE run_id = ?
                ORDER BY CASE check_status WHEN 'confirmed' THEN 0 WHEN 'candidate' THEN 1
                         WHEN 'none_found' THEN 2 ELSE 3 END, subscriber_count DESC
            ''', conn, params=(run_id,))

            if not df_yt.empty:
                report.append("\n## YouTube Presence")
                report.append("Which of your competitors run a YouTube channel, and how active — "
                              "from the official YouTube **Data API** (a sanctioned metadata check, "
                              "**not** scraping). _`confirmed` = the domain appears in the channel's "
                              "About or the handle equals the domain stem; `candidate` = a name-only "
                              "match **awaiting your confirmation** (see `TEST_RUN_CHECKLIST.md`); "
                              "`none_found` = **none matched by a name search of the top 3 results** "
                              "— not a measured 'no channel'; `error` = couldn't check this run "
                              "(retryable). `channel?` reads `?` for both, because neither is "
                              "evidence that the practice has no channel._")
                disp = df_yt.copy()
                disp['channel?'] = disp['has_channel'].apply(
                    lambda v: '✓' if v == 1 else ('✗' if v == 0 else '?'))
                disp['domain'] = disp['domain'].apply(
                    lambda d: f"⭐ {d} (you)" if d == client_domain else d)
                cols = ['domain', 'channel?', 'handle', 'channel_title', 'subscriber_count',
                        'last_upload_date', 'uploads_recent', 'match_confidence', 'check_status']
                report.append(md_table(disp[cols], index=False))
                n_cand = int((df_yt['check_status'] == 'candidate').sum())
                if n_cand:
                    report.append(f"\n> ℹ️ **{n_cand} candidate channel(s)** matched by name only — "
                                  "confirm identity before treating as the competitor's channel, "
                                  "then seed `youtube_presence.channel_map` so future runs cost 1 "
                                  "quota unit instead of ~100.")
                n_err = int((df_yt['check_status'] == 'error').sum())
                if n_err:
                    report.append(f"\n> ⚠️ **{n_err} check(s) errored** this run (quota/network) — "
                                  "retryable, not recorded as 'no channel'.")

            # 4. Strategic Openings & Reframes
            if reframes:
                report.append("\n## 🎯 Automated Bowen Reframes")
                report.append("_AI-drafted scaffolds for the Systemic Vacuums above. Each "
                              "carries its own provenance line; People-Also-Ask context "
                              "appears only on the legacy `market_analysis` path, because "
                              "the Tool 1 handoff carries no PAA field._")
                for r in reframes:
                    report.append(f"\n### Reframe: {r['keyword']}")
                    report.append(f"**Target URL:** {r['url']}")
                    if r.get('paa'):
                        report.append(f"**User Anxieties (PAA):** {', '.join(r['paa'][:5])}")
                    report.append("\n" + r['reframe'])
                    report.append("\n---")

        # Output paths — `orchestrator.reports_dir` when the GUI set one (C-C-16),
        # else the working directory as before.
        out_dir = self.output_dir or "."
        if out_dir not in (".", ""):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as exc:
                print(f"⚠️ Reports directory {out_dir} unusable ({exc}) — "
                      f"writing to the working directory instead.")
                out_dir = "."
        md_path = os.path.join(out_dir, f"strategic_briefing_run_{run_id}.md")
        excel_path = os.path.join(out_dir, f"audit_results_run_{run_id}.xlsx")

        report_content = "\n".join(report)
        with open(md_path, "w") as f:
            f.write(report_content)
        
        # Excel Export
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            with self.db._get_connection() as conn:
                if not df_metrics.empty:
                    df_metrics.to_excel(writer, sheet_name='Competitor Summary', index=False)
                if not df_magnets.empty:
                    df_magnets.to_excel(writer, sheet_name='Traffic Magnets', index=False)
                if not df_eeat.empty:
                    df_eeat.to_excel(writer, sheet_name='EEAT Scores', index=False)
                if not df_clusters.empty:
                    df_clusters.to_excel(writer, sheet_name='Cluster Analysis', index=False)
                if not df_geo.empty:
                    df_geo.to_excel(writer, sheet_name='GEO Extractability', index=False)
                if not df_overlap.empty:
                    df_overlap.to_excel(writer, sheet_name='SERP Overlap', index=False)
                if not df_feasibility.empty:
                    df_feasibility.to_excel(writer, sheet_name='Feasibility', index=False)
                if not df_positioning.empty:
                    df_positioning.to_excel(writer, sheet_name='Positioning', index=False)
                if not df_sov.empty:
                    df_sov.to_excel(writer, sheet_name='AI Share-of-Voice', index=False)
                if not df_brand.empty:
                    df_brand.to_excel(writer, sheet_name='Branded Demand', index=False)
                if not df_risk.empty:
                    df_risk.to_excel(writer, sheet_name='Reputation Risk', index=False)
                if not df_yt.empty:
                    df_yt.to_excel(writer, sheet_name='YouTube Presence', index=False)
                if reframes:
                    df_reframes = pd.DataFrame([{"keyword": r['keyword'], "url": r['url'], "reframe": r['reframe'][:500]} for r in reframes])
                    df_reframes.to_excel(writer, sheet_name='Automated Reframes', index=False)
                if token_usage:
                    df_usage = pd.DataFrame([token_usage])
                    df_usage.to_excel(writer, sheet_name='AI Usage Stats', index=False)

        print(f"Strategic Briefing generated: {excel_path} (and {md_path})")
        return report_content
