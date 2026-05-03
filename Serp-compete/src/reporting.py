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
                if reframes:
                    df_reframes = pd.DataFrame([{"keyword": r['keyword'], "url": r['url'], "reframe": r['reframe'][:500]} for r in reframes])
                    df_reframes.to_excel(writer, sheet_name='Automated Reframes', index=False)
                if token_usage:
                    df_usage = pd.DataFrame([token_usage])
                    df_usage.to_excel(writer, sheet_name='AI Usage Stats', index=False)

        print(f"Strategic Briefing generated: {excel_path} (and {md_path})")
        return report_content
