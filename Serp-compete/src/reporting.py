import pandas as pd
from src.database import DatabaseManager, load_shared_config, magnet_sql, magnet_thresholds
import datetime

from src.risk_radar import anchor_caveat_lines, anchor_data_unreadable


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
        report = [
            f"# Serp-comp Strategic Briefing (Run ID: {run_id})",
            f"**Client:** {client_domain}",
            f"**Date:** {timestamp}",
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
            universe = run_coverage.get("universe") or {}
            if universe:
                report.append(
                    f"**Keyword universe:** {universe.get('handoff', 0)} handoff "
                    f"target(s); {universe.get('enrichment_kept', 0)} enrichment "
                    f"keyword(s) kept, "
                    f"{universe.get('enrichment_dropped_brand', 0)} dropped as the "
                    f"competitor's own brand and "
                    f"{universe.get('enrichment_dropped_irrelevant', 0)} as off-topic.")
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
            
            target_gaps = gsc_findings.get("target_gaps")
            if target_gaps is not None and not target_gaps.empty:
                report.append("\n### High Impression / Low CTR Gaps")
                report.append("These internal keywords are being seen but not clicked. Reframe the Meta Titles with systemic depth.")
                report.append(target_gaps[['query', 'impressions', 'ctr', 'tier']].to_markdown(index=False))

            low_hanging = gsc_findings.get("low_hanging")
            if low_hanging is not None and not low_hanging.empty:
                report.append("\n### Low-Hanging Fruit (Page 2 Targets)")
                report.append("Internal pages ranking in positions 11-20. A systemic boost could push them to Page 1.")
                report.append(low_hanging[['query', 'page', 'position', 'impressions']].to_markdown(index=False))

            mismatches = gsc_findings.get("mismatches")
            if mismatches:
                report.append("\n### Clinical Mismatches")
                report.append("Detected instances where our Systems-heavy pages are being found via Medical Model queries.")
                report.append(pd.DataFrame(mismatches).to_markdown(index=False))

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
                df_vol = pd.DataFrame(volatility)
                report.append(df_vol.to_markdown(index=False))

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

            # Revision 3: Competitor Overview with Market Position & Systemic Depth
            df_metrics = pd.read_sql_query('''
                SELECT m.domain, 
                       COUNT(DISTINCT m.url) as top_pages, 
                       SUM(CASE WHEN m.keyword IS NOT NULL AND m.keyword != "" THEN 1 ELSE 0 END) as total_keywords, 
                       AVG(m.position) as avg_pos,
                       MAX(tm.medical_score) as max_med,
                       MAX(tm.systems_score) as max_sys,
                       MAX(CASE WHEN tm.systemic_label = "Surface-Level" THEN 1 ELSE 0 END) as has_surface,
                       MAX(CASE WHEN tm.systems_score > 0 AND tm.systemic_label != "Surface-Level" THEN 1 ELSE 0 END) as has_expert,
                       meta.market_position,
                       meta.strategy as recommended_strategy
                FROM competitor_metrics m
                LEFT JOIN competitor_metadata meta ON m.domain = meta.domain
                LEFT JOIN traffic_magnets tm ON m.run_id = tm.run_id AND m.domain = tm.domain
                WHERE m.run_id = ?
                GROUP BY m.domain
            ''', conn, params=(run_id,))

            def get_systemic_depth(row):
                # Safety check for None values
                max_med = row['max_med'] if row['max_med'] is not None else 0
                max_sys = row['max_sys'] if row['max_sys'] is not None else 0
                
                if row['has_expert'] == 1:
                    return "High"
                if row['has_surface'] == 1:
                    return "Surface"
                if max_med > max_sys:
                    return "Medical"
                if max_sys > 0:
                    return "Systems"
                return "Unknown"

            if not df_metrics.empty:
                df_metrics['systemic_depth'] = df_metrics.apply(get_systemic_depth, axis=1)
                # Reorder columns to include systemic_depth
                cols = ['domain', 'top_pages', 'total_keywords', 'avg_pos', 'systemic_depth', 'market_position', 'recommended_strategy']
                df_metrics = df_metrics[cols]


            if expected_competitors:
                found_domains = df_metrics['domain'].tolist()
                missing = [d for d in expected_competitors if d not in found_domains]
                if missing:
                    report.append("\n### ⚠️ Missing Data Alert")
                    report.append(f"No ranking data found for: {', '.join(missing)}")

            if not df_metrics.empty:
                report.append("\n## Competitor Ranking Summary")
                report.append(df_metrics.to_markdown(index=False))
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

            # 2b. EEAT Scores (Gap 3 enhancement)
            df_eeat = pd.read_sql_query('''
                SELECT url, score_confidence, experience_score, expertise_score,
                       authoritativeness_score, trustworthiness_score
                FROM eeat_scores
                WHERE run_id = ?
                ORDER BY url
                LIMIT 30
            ''', conn, params=(run_id,))

            if not df_eeat.empty:
                report.append("\n## EEAT Competitive Analysis (Heuristic)")
                report.append("Experience, Expertise, Authoritativeness, and Trustworthiness heuristic scores.")
                # Format numeric columns to 2 decimals
                for col in ['experience_score', 'expertise_score', 'authoritativeness_score', 'trustworthiness_score']:
                    df_eeat[col] = df_eeat[col].apply(lambda x: f"{x:.2f}" if x is not None else "—")
                report.append(df_eeat.to_markdown(index=False))
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
                report.append(df_clusters.to_markdown(index=False))
                report.append("\n_Note: Analysis based on N≤3 scraped pages per domain. Full site structure not visible._")

            # 3. Traffic Magnets with Systemic Label.
            # C-M-02 (owner decision 2, 2026-11-14): the documented definition is now
            # implemented rather than the section renamed — a magnet ranks well on a
            # handed-over keyword (handoff rank <= magnet_max_position), uses medical
            # language (medical_score >= vacuum_min_medical), and its keyword passed the
            # relevance test. The predicate lives in database.magnet_sql so the magnet
            # table, the vacuum list and the reframe query cannot drift apart.
            floor, max_pos = self.vacuum_min_medical, self.magnet_max_position
            df_magnets = pd.read_sql_query(
                magnet_sql(limit=20), conn, params=(run_id, floor, max_pos))
            audited_pages = self.db.count_audited_pages(run_id)
            magnet_filter_note = (
                f"_Filter: handoff rank ≤ {max_pos}, medical_score ≥ {floor} "
                f"(`technical.vacuum_min_medical`, editorial and uncalibrated), and the "
                f"keyword is in the handoff set or carries a clinical term and not the "
                f"competitor's own brand token. `est_traffic` is DataForSEO's estimated "
                f"monthly visits for that keyword×position, 0 when it was not measured._")

            if not df_magnets.empty:
                report.append("\n## Identified 'Traffic Magnets'")
                report.append(f"Showing {len(df_magnets)} of {audited_pages} audited "
                              f"page(s) that meet the magnet definition.")
                report.append(magnet_filter_note)
                report.append(df_magnets.to_markdown(index=False))

                # Spec 2: Highlight Systemic Vacuums — the magnets with no systemic
                # language. Same predicate as the reframe targets, by construction.
                vacuums = df_magnets[(df_magnets['systems_score'] == 0) | (df_magnets['systemic_label'] == 'Surface-Level')]
                if not vacuums.empty:
                    report.append("\n### ⚡ Strategic Targets: Systemic Vacuums")
                    report.append("These competitors rank on a handed-over keyword using medical language and show no real systemic framing. They are our **primary targets** for content reframing.")
                    for _, v in vacuums.iterrows():
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
                LIMIT 30
            ''', conn, params=(run_id,))

            if not df_geo.empty:
                report.append("\n## GEO / Extractability — Why Competitors Get Cited")
                report.append("Structural signals AI answer engines use to decide whether to quote a "
                              "competitor page (schema markup, credentialed authorship, question-shaped "
                              "headings, freshness). These explain *why* a page is citable — match or "
                              "exceed them on the client's equivalent page.")
                for _, g in df_geo.iterrows():
                    report.append(f"- **{g['url']}** — _{g['extractability_tier']}_: {g['why_cited']}")
                report.append("\n_Heuristic structural proxies for AI citability, not measured citations. "
                              "Answer-first placement and FAQ-answers-in-HTML are not yet measured._")

            # 3c. SERP Overlap & Differentiation Gap (C4 / SC-6)
            df_overlap = pd.read_sql_query('''
                SELECT keyword, cell, self_position, overlap_count, commodity_score,
                       keyword_volume, all_competitor_gap, estimation_basis,
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
                vol = df_overlap.groupby('cell')['keyword_volume'].sum().to_dict()
                report.append("**Volume by cell (est. traffic):** "
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
                report.append("\n_Folds in the Systemic Vacuum list above (not duplicated). "
                              "Competitor positions are SERP-measured; self_position is "
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
                report.append(df_feasibility.to_markdown(index=False))

            # 3e. Barbell Positioning Diagnostic (C2 / SC-4)
            df_positioning = pd.read_sql_query('''
                SELECT domain, is_client, authority_score, focus_score, quadrant
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
                report.append(disp[['domain', 'authority_score', 'focus_score', 'quadrant']]
                              .to_markdown(index=False))
                mid = df_positioning[df_positioning['quadrant'] == 'middle']
                if not mid.empty:
                    report.append("\n⚠️ **Danger zone (undifferentiated middle):** "
                                  + ", ".join(mid['domain'].tolist()) + ".")

            # 3f. Competitive AI Share-of-Voice (C1 / SC-3)
            df_sov = pd.read_sql_query('''
                SELECT engine, entity, entity_type, is_client, category,
                       mention_share, citation_share, avg_sentiment, cited_gap
                FROM sov_daily WHERE run_id = ?
            ''', conn, params=(run_id,))

            if not df_sov.empty:
                report.append("\n## Competitive AI Share-of-Voice")
                report.append("When the AI engines answer category questions, whose brand and "
                              "sources come back. Consumed from serp-discover's AI-visibility "
                              "probes (not re-probed here). _Rolling snapshots — LLM answers vary._")
                for engine in sorted(df_sov['engine'].dropna().unique()):
                    eng = df_sov[df_sov['engine'] == engine]
                    report.append(f"\n### {engine}")
                    men = eng[(eng['entity_type'] == 'brand') & (eng['category'] != 'other')]
                    men = men.sort_values('mention_share', ascending=False).head(10)
                    if not men.empty:
                        report.append("**Mention share:** " + ", ".join(
                            f"{r['entity']}{' (you)' if r['is_client'] else ''} "
                            f"{(r['mention_share'] or 0):.0f}%" for _, r in men.iterrows()))
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
                report.append(disp.drop(columns=['queries']).to_markdown(index=False))

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
                    report.append(comp[['domain', 'signal_type', 'severity']].to_markdown(index=False))
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
                              "About or the handle matches; `candidate` = a name-only match **awaiting "
                              "your confirmation** (see `TEST_RUN_CHECKLIST.md`); `none_found` = no "
                              "channel; `error` = couldn't check this run (retryable — never a "
                              "definitive 'no')._")
                disp = df_yt.copy()
                disp['channel?'] = disp['has_channel'].apply(
                    lambda v: '✓' if v == 1 else ('✗' if v == 0 else '?'))
                disp['domain'] = disp['domain'].apply(
                    lambda d: f"⭐ {d} (you)" if d == client_domain else d)
                cols = ['domain', 'channel?', 'handle', 'channel_title', 'subscriber_count',
                        'last_upload_date', 'uploads_recent', 'match_confidence', 'check_status']
                report.append(disp[cols].to_markdown(index=False))
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

        # Output paths
        md_path = f"strategic_briefing_run_{run_id}.md"
        excel_path = f"audit_results_run_{run_id}.xlsx"

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
