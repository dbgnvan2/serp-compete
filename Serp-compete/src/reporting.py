import pandas as pd
from src.database import DatabaseManager
import datetime

class ReportGenerator:
    def __init__(self, db_path: str = "competitor_history.db"):
        self.db = DatabaseManager(db_path)

    def generate_summary(self, client_domain: str, expected_competitors: list = None, run_id: int = None, reframes: list = None, token_usage: dict = None, market_alerts: list = None, gsc_findings: dict = None):
        """
        Generate a Markdown report summarizing the audit findings for a specific run.
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

            # Revision 4: Feasibility Drift Alerts
            drift_alerts = self.db.get_feasibility_drift(run_id)
            if drift_alerts:
                report.append("\n## 🚩 Expert Alerts: Fragile Magnets")
                for alert in drift_alerts:
                    report.append(f"- **{alert['url']}**: Page Authority drifted by {alert['drift']:.2f}. "
                                  f"**Strategic Advice:** The competitor is losing authority on this page. "
                                  f"Now is the time to publish your 'Systems Approach' page to overtake them.")

            # Spec 4: Market Velocity Alerts (New Longitudinal Memory)
            if market_alerts:
                report.append("\n## ⚡ Market Velocity Alerts")
                for alert in market_alerts:
                    if alert['type'] == 'Fragile Magnet':
                        report.append(f"- **{alert['domain']}** ({alert['keyword']}): Rank Drift {alert['rank_drift']}, DA Drift {alert['da_drift']}. "
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

            # 3. Traffic Magnets with Systemic Label
            df_magnets = pd.read_sql_query('''
                SELECT domain, url, primary_keyword, est_traffic, medical_score, systems_score, systemic_label
                FROM traffic_magnets
                WHERE run_id = ?
                ORDER BY est_traffic DESC LIMIT 20
            ''', conn, params=(run_id,))

            if not df_magnets.empty:
                report.append("\n## Identified 'Traffic Magnets'")
                report.append(df_magnets.to_markdown(index=False))
                
                # Spec 2: Highlight Systemic Vacuums
                vacuums = df_magnets[(df_magnets['systems_score'] == 0) | (df_magnets['systemic_label'] == 'Surface-Level')]
                if not vacuums.empty:
                    report.append("\n### ⚡ Strategic Targets: Systemic Vacuums")
                    report.append("These competitors use medical language or only surface-level systemic terms. They are our **primary targets** for content reframing.")
                    for _, v in vacuums.iterrows():
                        label_str = f" [{v['systemic_label']}]" if v['systemic_label'] != 'Standard' else ""
                        report.append(f"- **{v['domain']}** ({v['primary_keyword']}): Medical Score {v['medical_score']}, Systems Score {v['systems_score']}{label_str}")

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
                       mention_share, citation_share, avg_sentiment
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
                    client_cited = bool(((eng['entity_type'] == 'domain') & (eng['is_client'] == 1) &
                                         (eng['citation_share'] > 0)).any())
                    comp_cites = eng[(eng['entity_type'] == 'domain') &
                                     (eng['category'] == 'competitor') & (eng['citation_share'] > 0)]
                    if not comp_cites.empty and not client_cited:
                        report.append("⚔️ **Cited but you're not:** "
                                      + ", ".join(sorted(comp_cites['entity'].dropna().unique())))

            # 3g. Branded-Demand Benchmark (C3 / SC-5)
            df_brand = pd.read_sql_query('''
                SELECT domain, brand, branded_search_volume, branded_volume_share,
                       branded_growth, est_branded_click_share, estimation_basis
                FROM brand_demand_bench WHERE run_id = ?
                ORDER BY branded_search_volume DESC
            ''', conn, params=(run_id,))

            if not df_brand.empty:
                report.append("\n## Branded-Demand Benchmark")
                report.append("Brand-search demand, you vs competitors, estimated from public "
                              "search volume. _Competitor figures are volume-estimated (not "
                              "click-measured); your own figure is GSC-anchored when the "
                              "serp-discover D2 export is available — see `estimation_basis`._")
                if (df_brand['estimation_basis'] == 'volume_unavailable').any():
                    report.append("\n> ⚠️ **Search-volume source returned nothing this run** — the "
                                  "figures below are unavailable (likely a DataForSEO outage), not "
                                  "zero demand.")
                disp = df_brand.copy()
                disp['brand'] = disp.apply(
                    lambda r: (f"⭐ {r['brand']} (you)" if r['domain'] == client_domain
                               else r['brand']), axis=1)   # own row identifiable regardless of anchor
                report.append(disp.to_markdown(index=False))

            # 3h. Reputation-Risk Radar (C6 / SC-8)
            df_risk = pd.read_sql_query('''
                SELECT domain, is_own_site, signal_type, severity, evidence_json
                FROM risk_signal WHERE run_id = ?
                ORDER BY is_own_site DESC,
                    CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, domain
            ''', conn, params=(run_id,))

            if not df_risk.empty:
                report.append("\n## Reputation-Risk Radar")
                report.append("Patterns Google is known to penalize — visibility cliffs, off-topic "
                              "commercial subfolders (site-reputation abuse), ranking volatility. "
                              "_**Pattern detections, not confirmed Google penalties.**_")
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

            # 4. Strategic Openings & Reframes
            if reframes:
                report.append("\n## 🎯 Automated Bowen Reframes")
                for r in reframes:
                    report.append(f"\n### Reframe: {r['keyword']}")
                    report.append(f"**Target URL:** {r['url']}")
                    if r['paa']:
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
                if reframes:
                    df_reframes = pd.DataFrame([{"keyword": r['keyword'], "url": r['url'], "reframe": r['reframe'][:500]} for r in reframes])
                    df_reframes.to_excel(writer, sheet_name='Automated Reframes', index=False)
                if token_usage:
                    df_usage = pd.DataFrame([token_usage])
                    df_usage.to_excel(writer, sheet_name='AI Usage Stats', index=False)

        print(f"Strategic Briefing generated: {excel_path} (and {md_path})")
        return report_content
