import logging
import os

import pandas as pd
from src.database import DatabaseManager, load_shared_config, magnet_sql, magnet_thresholds
import datetime

from src.briefing_messages import Messages
from src.serp_overlap import DEFAULT_TOP_N
from src.risk_radar import anchor_caveat_lines, anchor_data_unreadable


def unknown_cell(messages=None) -> str:
    """What an unknown value reads as in a rendered markdown table.

    An em dash, not an empty cell: a blank is indistinguishable from a
    rendering fault, and the briefing's whole convention is that absence is
    stated. The word is `icons.unknown_cell` in `briefing_messages.json`
    (chunk Y17), because it was a module constant with a bare duplicate of
    itself in the cluster table bypassing it.

    *messages* is the render's already-loaded `Messages` (P25). With none it
    reads the file now, which is what a direct caller in a test gets.
    """
    return (messages or Messages()).get("icons.unknown_cell")


def md_table(df, messages=None, **kwargs) -> str:
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
    unknown = unknown_cell(messages)
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
                lambda v: unknown if pd.isna(v) else str(int(v)))
    # `fillna` on a numeric column upcasts to object, which is what we want for
    # display.
    return out.fillna(unknown).to_markdown(**kwargs)


def gsc_pull_note(config, messages=None) -> str:
    """The line that states which Google Search Console pull a section used.

    Purpose: stop a figure from this tool being read beside a figure from
             serp-discover as though both described the same traffic.
    Spec:    docs/review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md §3 Chunk X
             (GSC bullet); docs/handoff_contract.md §GSC
    Tests:   Serp-compete/tests/test_handoff_contract.py::TestGscPullIsStated

    This tool pulls the `gsc_settings.date_range_days` window with the
    `gsc_settings.country` and `gsc_settings.device` filters, so the client's
    own clicks come from the same market and the same device as the
    Canada-scoped, desktop DataForSEO snapshot. Neither report said which pull
    it was.

    It does not state serp-discover's filters. This line said serp-discover
    pulled "90 days, all devices, global", which stopped being true when that
    tool's review chunk D5 gave it `gsc.country` and `gsc.device`: nothing here
    reads that config, so asserting it was a claim this tool cannot check (P6).
    Each report states its own pull and says the two are comparable only where
    both state the same one.

    The values are read from the keys `GSCManager.fetch_performance_data` reads,
    not restated here, so this line cannot drift from the request that was
    actually made. A function rather than inline text for the same reason
    `anchor_caveat_lines` is one: the decision is then testable without
    standing up a whole report.
    """
    # `GSC_DEVICES` is imported here, not at module scope: `gsc_performance`
    # pulls in google-auth, googleapiclient, spacy and openai transitively, and
    # a report should not fail to render because an optional GSC dependency is
    # missing (cold review of chunk X). It is still read from the module that
    # makes the request, so the caveat cannot name a filter the pull did not use.
    from src.api_clients import snapshot_market
    from src.gsc_performance import GSC_DEVICES

    # The words, from `briefing_messages.json` (chunk Y17). The DECISIONS stay
    # here: which of the three country clauses and which of the four device
    # clauses this pull earns is a fact about the config, not wording.
    m = messages or Messages()

    settings = ((config or {}).get("gsc_settings", {}) or {})
    try:
        days = int(settings.get("date_range_days", 90))
    except (TypeError, ValueError):
        days = 90
    country = str(settings.get("country", "can") or "").strip().lower()
    raw_device = str(settings.get("device", "desktop") or "").strip().lower()
    off = raw_device in ("all", "none", "any")
    # Three states, not two. An unrecognised value pulls every device exactly
    # as `all` does, but it is a typo, not a decision, and a report that prints
    # the two the same way hides the misconfiguration behind a sentence that
    # reads deliberate (P1, cold review of chunk X).
    device = "" if off else raw_device if raw_device in GSC_DEVICES else ""
    bad_device = bool(raw_device) and not off and raw_device not in GSC_DEVICES

    # What the SERP side of these figures actually asked for, read from the
    # config the DataForSEO calls read — not asserted here. Claiming "the two
    # match" for any non-empty value is the same P6 breach this note fixed.
    snapshot = snapshot_market()
    snap_country = str(snapshot.get("country") or "").strip().lower()
    snap_device = str(snapshot.get("device") or "").strip().lower()

    unset = m.get("gsc_comparability.unset")
    if not country:
        country_line = m.get("gsc_comparability.country.absent",
                             snap_country=snap_country or unset)
    elif country == snap_country:
        country_line = m.get("gsc_comparability.country.matches",
                             snap_country=snap_country)
    else:
        country_line = m.get("gsc_comparability.country.differs",
                             snap_country=snap_country or unset)

    if bad_device:
        device_line = m.get("gsc_comparability.device.unrecognised",
                            raw_device=raw_device,
                            snap_device=snap_device or unset)
    elif not device:
        device_line = m.get("gsc_comparability.device.absent",
                            snap_device=snap_device or unset)
    elif device == snap_device:
        device_line = m.get("gsc_comparability.device.matches",
                            snap_device=snap_device)
    else:
        device_line = m.get("gsc_comparability.device.differs",
                            device=device, snap_device=snap_device or unset)

    return m.get(
        "gsc_comparability.pull_line",
        days=days,
        country_phrase=(m.get("gsc_comparability.country_phrase.present",
                              country=country) if country
                        else m.get("gsc_comparability.country_phrase.absent")),
        device_phrase=(m.get("gsc_comparability.device_phrase.present",
                             device=device) if device
                       else m.get("gsc_comparability.device_phrase.absent")),
        country_line=country_line,
        device_line=device_line,
    )


def client_mismatch_line(run_coverage: dict = None, messages=None) -> str:
    """The report's client-mismatch caveat, or `""` when the two agree.

    The sentence itself comes from `handoff_moz.client_domain_mismatch`; this
    only decides how the report says it. Separate from `generate_summary` so
    it can be tested without a populated database and an Excel write (cold
    review of chunk Y1).
    """
    mismatch = (run_coverage or {}).get("client_domain_mismatch")
    if not mismatch:
        return ""
    return (messages or Messages()).get("gsc_comparability.client_mismatch",
                                       mismatch=mismatch)


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
        # Chunk Y17: every sentence this report renders, read ONCE and held.
        # Here rather than inside a section because a messages file that will
        # not parse must stop the render before the first section, not become a
        # per-section blank (the shape chunk Y16's cold review arrived at).
        self.messages = Messages()
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
        m = self.messages
        if not cited:
            return m.get("extractability.citation_check.no_export")
        strong = df_geo[df_geo["extractability_tier"] == "Strong"]
        if strong.empty:
            return m.get("extractability.citation_check.no_strong_tier")
        from src.brand_utils import normalise_domain
        cited_norm = {normalise_domain(entity) for entity in cited}
        strong_domains = {normalise_domain(str(url).split("/")[2])
                          for url in strong["url"] if str(url).count("/") >= 2}
        confirmed = sorted(strong_domains & cited_norm)
        unconfirmed = sorted(strong_domains - cited_norm)
        return m.get(
            "extractability.citation_check.result",
            confirmed=len(confirmed), total=len(strong_domains),
            confirmed_clause=(
                m.get("extractability.citation_check.confirmed_clause",
                      names=", ".join(confirmed)) if confirmed else ""),
            unconfirmed_clause=(
                m.get("extractability.citation_check.unconfirmed_clause",
                      names=", ".join(unconfirmed)) if unconfirmed else ""),
        )

    #: What the action queues print when `shared_config.json` says nothing.
    #: 15 is what the briefing printed before the number had a key.
    DEFAULT_ACTION_QUEUE_ROW_CAP = 15

    def action_queue_row_cap(self) -> int:
        """How many action-queue rows the briefing prints.

        A threshold, so it is in `shared_config.json` beside its two siblings
        `reporting.markdown_row_cap` and `reporting.magnet_markdown_row_cap`,
        not in the file of sentences — the sentence that quotes it
        interpolates it, which is what stops the prose claiming one cap while
        the slice takes another. It was a literal `15` in both places before
        chunk Y17, and briefly a key in the messages file, where it was read
        with `raw()` and so defaulted silently (cold review, M2).

        A value that is absent, zero, negative or not a number falls back and
        SAYS SO in the log, the way `db_connect.lock_timeout_from_config`
        does: a cap of 0 would print an empty action queue, which reads as
        "no keywords qualify".
        """
        configured = (self.config.get("serp_overlap") or {}).get(
            "action_queue_row_cap")
        if configured is None:
            return self.DEFAULT_ACTION_QUEUE_ROW_CAP
        try:
            cap = int(configured)
        except (TypeError, ValueError):
            cap = 0
        if cap < 1:
            logging.warning(
                "shared_config.json serp_overlap.action_queue_row_cap is %r, "
                "which is not a row count; printing %d rows per action queue.",
                configured, self.DEFAULT_ACTION_QUEUE_ROW_CAP)
            return self.DEFAULT_ACTION_QUEUE_ROW_CAP
        return cap

    def action_queue_note(self, total: int, row_cap: int) -> str:
        """`_(top N of M)_`, or `""` when nothing was cut.

        A method rather than a closure so a test can call it with a cap of its
        own: as a closure it was reachable only through a full render, and a
        mutation that hardcoded the number passed every guard.
        """
        if total <= row_cap:
            return ""
        return self.messages.get("serp_overlap.action_queue_truncated",
                                 shown=row_cap, total=total)

    def shortfall_lines(self) -> list:
        """The "N message(s) missing" line, or nothing.

        Asked for last, after every section has asked for its words. The
        markers are already in the body; this is the count, so the reader does
        not have to hunt for them (P2). A method for the same reason as
        `action_queue_note`.
        """
        line = self.messages.shortfall_line()
        return [line] if line else []

    def _capped(self, df, cap: int, label_key: str):
        """(display frame, "showing N of M" note) — C-C-07.

        A LIMIT in the SQL truncated the markdown AND the Excel sheet identically and
        said nothing: the EEAT and GEO sections showed the alphabetically-first ~10
        competitors of 15 and the Excel sheet, which is supposed to be the full
        export, was cut to the same 30 rows.
        """
        total = len(df)
        label = self.messages.get("capped.labels.%s" % label_key)
        if total <= cap:
            return df, self.messages.get("capped.complete", total=total,
                                         label=label)
        return (df.head(cap),
                self.messages.get("capped.truncated", cap=cap, total=total,
                                  label=label))

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
        # The words, held: one read for the whole render (chunk Y17).
        m = self.messages
        report = [
            m.get("headings.title", run_id=run_id),
            m.get("headings.client", client_domain=client_domain),
            m.get("headings.date", timestamp=timestamp),
            # C-C-16: name the input. Two handoffs in the project root differ only by
            # timestamp, and the briefing used to be silent about which one it read.
            m.get("headings.handoff",
                  handoff=(os.path.basename(handoff_name) if handoff_name
                           else m.get("headings.handoff_not_recorded"))),
            m.get("headings.executive_summary"),
            m.get("executive_summary.intro"),
        ]

        # The handoff names the client it was produced for. A disagreement with
        # this repo's `shared_config.client.domain` goes in the artefact, not
        # only into a console line somebody read once: the report is what is
        # still here weeks later, and without this it reads clean while every
        # figure in it compares one client's SERPs with another's configuration
        # (cold review of chunk Y1).
        mismatch_line = client_mismatch_line(run_coverage, m)
        if mismatch_line:
            report.insert(4, mismatch_line)

        # Run coverage, in the artefact rather than only in the console (P2).
        if run_coverage:
            skipped = run_coverage.get("skipped_domains") or []
            report.append(m.get(
                "run_coverage.line",
                domains_audited=run_coverage.get("domains_audited", 0),
                domains_in_handoff=run_coverage.get("domains_in_handoff", 0),
                pa_measured=run_coverage.get("pa_measured", 0),
                pa_total=run_coverage.get("pa_total", 0)))
            if skipped:
                report.append(m.get("run_coverage.skipped", domains="; ".join(
                    m.get("run_coverage.skipped_item", domain=d, reason=r)
                    for d, r in skipped)))
            db_cleanup = run_coverage.get("db_cleanup")
            if db_cleanup:
                report.append(m.get("run_coverage.db_cleanup",
                                    db_cleanup=db_cleanup))
            unmeasured = run_coverage.get("unmeasured_pa_domains") or []
            if unmeasured:
                report.append(m.get("run_coverage.pa_unmeasured",
                                    domains=", ".join(unmeasured)))
            enrichment_failures = run_coverage.get("enrichment_failures") or []
            if enrichment_failures:
                report.append(m.get(
                    "run_coverage.enrichment_unavailable",
                    items="; ".join(m.get("run_coverage.enrichment_item",
                                          domain=d, reason=r)
                                    for d, r in enrichment_failures)))
            blocked = run_coverage.get("blocked_domains") or []
            if blocked:
                report.append(m.get("run_coverage.blocked",
                                    domains=", ".join(blocked)))
            cached = run_coverage.get("cached_domains") or []
            if cached:
                report.append(m.get("run_coverage.cached",
                                    domains=", ".join(cached)))
            incomplete = run_coverage.get("incomplete_tier_domains") or []
            if incomplete:
                report.append(m.get("run_coverage.incomplete_tiers",
                                    domains=", ".join(incomplete)))
            universe = run_coverage.get("universe") or {}
            if universe:
                report.append(m.get(
                    "run_coverage.universe",
                    handoff=universe.get("handoff", 0),
                    kept=universe.get("enrichment_kept", 0),
                    dropped_brand=universe.get("enrichment_dropped_brand", 0),
                    dropped_irrelevant=universe.get(
                        "enrichment_dropped_irrelevant", 0)))
            # Chunk X (rank semantics / H1): serp-discover stores SerpAPI's
            # per-page `position` verbatim and concatenates paginated pages
            # without an offset, so the handoff's ranks restart at 1 on every
            # page. Until its chunk D1 lands and bumps `schema_version`, a
            # "rank 2" in this report may be the second result of page 3.
            if run_coverage.get("rank_semantics_error"):
                report.append(m.get("rank_semantics.undetermined",
                                    error=run_coverage["rank_semantics_error"]))
            elif run_coverage.get("rank_is_absolute") is False:
                report.append(m.get(
                    "rank_semantics.page_relative",
                    version=(run_coverage.get("handoff_version")
                             or m.get("rank_semantics.version_unknown")),
                    citation=m.get("rank_semantics.finding_citation")))
        else:
            report.append(m.get("run_coverage.unrecorded"))

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
            report.append(m.get("headings.gsc_section"))
            report.append(m.get("gsc_section.intro"))
            report.append(gsc_pull_note(self.config, m))

            target_gaps = gsc_findings.get("target_gaps")
            if target_gaps is not None and not target_gaps.empty:
                report.append(m.get("headings.gsc_target_gaps"))
                report.append(m.get("gsc_section.target_gaps_intro"))
                report.append(md_table(target_gaps[['query', 'impressions', 'ctr', 'tier']],
                                       messages=m, index=False))

            low_hanging = gsc_findings.get("low_hanging")
            if low_hanging is not None and not low_hanging.empty:
                report.append(m.get("headings.gsc_low_hanging"))
                report.append(m.get("gsc_section.low_hanging_intro"))
                report.append(md_table(
                    low_hanging[['query', 'page', 'position', 'impressions']],
                    messages=m, index=False))

            mismatches = gsc_findings.get("mismatches")
            if mismatches:
                report.append(m.get("headings.gsc_mismatches"))
                report.append(m.get("gsc_section.mismatches_intro"))
                report.append(md_table(pd.DataFrame(mismatches), messages=m,
                                       index=False))

        if token_usage:
            report.append(m.get("headings.token_usage"))
            report.append(m.get("token_usage.prompt",
                                count=token_usage.get("prompt_tokens", 0)))
            report.append(m.get("token_usage.completion",
                                count=token_usage.get("completion_tokens", 0)))
            report.append(m.get("token_usage.total",
                                count=token_usage.get("total_tokens", 0)))

        with self.db.connection() as conn:
            # 1. Volatility Alerts
            volatility = self.db.get_volatility_alerts(run_id)
            if volatility:
                report.append(m.get("headings.volatility"))
                # C-M-20: the sign convention was never stated, and in SERP positions
                # a bigger number is worse — the opposite of most metrics.
                report.append(m.get("volatility.sign_convention"))
                df_vol = pd.DataFrame(volatility)
                report.append(md_table(df_vol, messages=m, index=False))

            # Spec 4: Fragile Magnets — ONE authority-drift detector (C-C-05 / C-M-06).
            # There used to be two, under two headings, for the same event:
            # `database.get_feasibility_drift` (drift < -2, per URL) and
            # `VelocityTracker.get_market_alerts` (da_drift < 0, unscoped). The first
            # is gone; this is the survivor, run-scoped and thresholded.
            if market_alerts:
                report.append(m.get("headings.fragile_magnets"))
                threshold = next((a.get('pa_drop_min') for a in market_alerts
                                  if a.get('pa_drop_min') is not None), None)
                report.append(m.get(
                    "fragile_magnets.intro",
                    threshold_clause=(
                        m.get("fragile_magnets.threshold_clause",
                              threshold=threshold) if threshold is not None
                        else "")))
                for alert in market_alerts:
                    if alert['type'] == 'Fragile Magnet':
                        rank_drift = alert.get('rank_drift')
                        if rank_drift == 0:
                            rank_note = m.get("fragile_magnets.rank_unchanged")
                        elif rank_drift is not None:
                            rank_note = m.get("fragile_magnets.rank_drift",
                                              rank_drift=rank_drift)
                        else:
                            rank_note = m.get("fragile_magnets.rank_not_measured")
                        report.append(m.get(
                            "fragile_magnets.row", domain=alert['domain'],
                            keyword=alert['keyword'], da_drift=alert['da_drift'],
                            rank_note=rank_note, advice=alert['advice']))
                    else:
                        report.append(m.get("fragile_magnets.other_row",
                                            type=alert['type'],
                                            domain=alert['domain'],
                                            keyword=alert['keyword']))

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
                    return m.get("systemic_depth.not_recorded")
                if (row.get('max_t3') or 0) >= 1:
                    return m.get("systemic_depth.bowen")
                if (row.get('t2_total') or 0) >= self.t2_depth_min:
                    return m.get("systemic_depth.systems")
                if row.get('has_surface') == 1:
                    return m.get("systemic_depth.surface")
                if (row.get('t2_total') or 0) > 0:
                    return m.get("systemic_depth.trace")
                return m.get("systemic_depth.none")

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
                    report.append(m.get("headings.missing_data"))
                    report.append(m.get("competitor_summary.missing_data",
                                        domains=", ".join(missing)))

            if not df_metrics.empty:
                report.append(m.get("headings.competitor_summary"))
                # C-C-17 changed the enrichment rank to `rank_group`, the organic
                # position; this caveat still named `rank_absolute`, so the report
                # described a scale it had stopped using.
                report.append(m.get("competitor_summary.column_caveat"))
                report.append(md_table(df_metrics, messages=m, index=False))
                # C-M-01: say where this run's keywords came from. `handoff` =
                # Tool 1 measured the URL ranking for it; `ranked_keywords` = a
                # DataForSEO enrichment keyword that passed the relevance filter;
                # `unlabelled` = written before provenance was recorded.
                sources = self.db.keyword_source_counts(run_id)
                if sources:
                    report.append(m.get(
                        "competitor_summary.keyword_provenance",
                        counts=", ".join(
                            m.get("competitor_summary.provenance_item",
                                  source=src, count=n)
                            for src, n in sorted(sources.items()))))

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
                report.append(m.get("headings.eeat"))
                report.append(m.get("eeat.intro"))
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
                unknown = unknown_cell(m)
                for col in ['experience_score', 'expertise_score', 'authoritativeness_score', 'trustworthiness_score']:
                    display_eeat[col] = display_eeat[col].apply(
                        lambda x: f"{x:.1f}" if pd.notna(x) else unknown)
                # A table of dashes with no stated cause is the failure mode
                # this report exists to avoid. The usual cause is an absent
                # `eeat_weights` block: EEATScorer then has nothing to weight
                # with and correctly computes nothing, silently.
                _dimensions = ['experience_score', 'expertise_score',
                               'authoritativeness_score', 'trustworthiness_score']
                if all((display_eeat[col] == unknown).all()
                       for col in _dimensions):
                    report.append(m.get("eeat.no_composite"))
                report.append(m.get("eeat.score_caveat"))
                disp_eeat, eeat_note = self._capped(display_eeat, self.markdown_row_cap,
                                                    "scored_pages")
                report.append(eeat_note)
                report.append(md_table(disp_eeat, messages=m, index=False))
                report.append(m.get("eeat.caveat"))

            # 2c. Cluster Analysis (Gap 4 enhancement)
            df_clusters = pd.read_sql_query('''
                SELECT domain, pages_analysed, cluster_signal, avg_in_degree, max_in_degree
                FROM cluster_results
                WHERE run_id = ?
                ORDER BY domain
            ''', conn, params=(run_id,))

            if not df_clusters.empty:
                report.append(m.get("headings.clusters"))
                report.append(m.get("clusters.intro"))
                # `unknown_cell(m)`, not a second bare em dash: this literal used to
                # bypass the constant beside it (chunk Y17).
                df_clusters['avg_in_degree'] = df_clusters['avg_in_degree'].apply(
                    lambda x: f"{x:.2f}" if x is not None else unknown_cell(m))
                report.append(md_table(df_clusters, messages=m, index=False))
                report.append(m.get("clusters.sample_caveat"))

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
            # ONE message, composed from two keys: the filter sentence and the
            # clause saying its rank half is inoperative. It used to be built with
            # `+=` in two statements, so the second was a conditional half of a
            # sentence living in Python (chunk Y17).

            # The "rank ≤ N" half of that filter is INOPERATIVE while the
            # handoff's ranks are page-relative, and saying so belongs here
            # rather than only in the coverage block: this is the list the owner
            # acts on.
            #
            # serp-discover stores SerpAPI's per-page `position` verbatim and
            # concatenates paginated pages without an offset (H1 / D-C-01), so
            # in its 3-page mode the ranks run 1..9, 1..10, 1..10. Against the
            # committed reference run's distribution, `rank <= 10` admits 29 of
            # 29 results — true positions 1 through 29. The criterion the README
            # and the USER_MANUAL describe as "ranks well" therefore filters
            # nothing at all, and `technical.magnet_max_position` is a knob with
            # no effect until the producer is fixed.
            magnet_filter_note = m.get("magnets.filter_note", max_pos=max_pos,
                                       floor=floor)
            if (run_coverage or {}).get("rank_is_absolute") is False:
                magnet_filter_note += m.get(
                    "magnets.rank_filter_inoperative", max_pos=max_pos,
                    version=((run_coverage or {}).get("handoff_version")
                             or m.get("rank_semantics.version_unknown")),
                    citation=m.get("rank_semantics.finding_citation"))

            if not df_magnets.empty:
                disp_magnets, magnet_note = self._capped(
                    df_magnets, self.magnet_row_cap, "qualifying_pages")
                report.append(m.get("headings.magnets"))
                report.append(m.get("magnets.count_line", n=len(df_magnets),
                                    audited=audited_pages,
                                    capped_note=magnet_note))
                report.append(magnet_filter_note)
                report.append(md_table(disp_magnets, messages=m, index=False))

                # Spec 2: Highlight Systemic Vacuums — the magnets with no systemic
                # language. Same predicate as the reframe targets, by construction.
                vacuums = df_magnets[(df_magnets['systems_score'] == 0) | (df_magnets['systemic_label'] == 'Surface-Level')]
                vacuums_rendered = not vacuums.empty
                if not vacuums.empty:
                    disp_vacuums, vacuum_note = self._capped(
                        vacuums, self.markdown_row_cap, "vacuums")
                    report.append(m.get("headings.vacuums"))
                    report.append(m.get("magnets.vacuums_intro"))
                    report.append(vacuum_note)
                    for _, v in disp_vacuums.iterrows():
                        label_clause = (
                            m.get("magnets.vacuum_label_clause",
                                  label=v['systemic_label'])
                            if v['systemic_label'] != 'Standard' else "")
                        report.append(m.get(
                            "magnets.vacuum_row", domain=v['domain'],
                            keyword=v['primary_keyword'],
                            source=v['keyword_source'], rank=v['rank'],
                            medical_score=v['medical_score'],
                            systems_score=v['systems_score'],
                            label_clause=label_clause))
            elif audited_pages:
                # Absence stated, not implied: 100 audited pages and no magnet is a
                # fact about the filter, and the reader cannot otherwise tell it from
                # "nothing was audited" (P2).
                report.append(m.get("headings.magnets"))
                report.append(m.get("magnets.none_qualified",
                                    audited=audited_pages))
                report.append(magnet_filter_note)
            else:
                # …and the third case, which the branch above names but did not
                # handle: NOTHING was scored, so the section used to vanish
                # entirely. A reader seeing no Traffic Magnets heading cannot
                # tell "no competitor page qualified" from "no competitor page
                # could be read", and this is the report's primary action list.
                # Found by rendering the total-outage scenario and reading it
                # (tools/render_sample_briefing.py).
                report.append(m.get("headings.magnets"))
                report.append(m.get("magnets.nothing_scored"))

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
                report.append(m.get("headings.extractability"))
                report.append(m.get("extractability.intro"))
                report.append(self._geo_citation_check(conn, run_id, df_geo))
                # C-C-07: capped for display only (tier order, then url); the sheet
                # carries all of them.
                disp_geo, geo_note = self._capped(df_geo, self.markdown_row_cap,
                                                  "profiled_pages")
                report.append(geo_note)
                for _, g in disp_geo.iterrows():
                    report.append(m.get("extractability.row", url=g['url'],
                                        tier=g['extractability_tier'],
                                        why_cited=g['why_cited']))
                report.append(m.get("extractability.footnote"))

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
                # The same `top_n` the classification used, from the same
                # section of the config, so the warning cannot name a
                # different number than the test it describes.
                overlap_top_n = int((self.config.get("serp_overlap", {}) or {})
                                    .get("top_n", DEFAULT_TOP_N))
                report.append(m.get("headings.serp_overlap"))
                report.append(m.get("serp_overlap.intro"))
                # The top-N test is ASYMMETRIC while the handoff's ranks are
                # page-relative, and this section's `exclusive_competitor` cell
                # is described as the top action queue — so the distortion has
                # to be stated here.
                #
                # `comp_top` filters competitor positions on `p <= top_n`,
                # where a handoff-sourced position restarts at 1 on every SERP
                # page; `self_present` filters the client's GSC position, which
                # is absolute. Competitors therefore pass the top-10 test at
                # any true position while the client passes only if genuinely
                # in the top 10. Worked through: rivals at true positions 14,
                # 22 and 27 with a client at 12 classifies as
                # `exclusive_competitor` — "rivals rank, you're absent" — for a
                # keyword where NOBODY is in the top 10 and the client is the
                # closest of the four.
                #
                # Worse, the competitor column is itself a MIX: handoff rows
                # carry the page-relative rank, enrichment rows carry
                # DataForSEO's absolute `rank_group` (C-C-17). C-M-11 fixed the
                # market mismatch (GSC country=can) and the SERP-feature
                # mismatch (rank_group over rank_absolute); the pagination
                # mismatch is this one, and it is upstream.
                if (run_coverage or {}).get("rank_is_absolute") is False:
                    report.append(m.get(
                        "serp_overlap.asymmetric_warning",
                        top_n=overlap_top_n,
                        citation=m.get("rank_semantics.finding_citation")))
                # If the client's GSC positions were unavailable this run, self-presence
                # is UNKNOWN — say so loudly rather than imply "you're absent".
                if 'self_unknown' in set(df_overlap['cell']):
                    report.append(m.get("serp_overlap.self_unknown_warning"))
                counts = df_overlap['cell'].value_counts().to_dict()
                report.append(m.get(
                    "serp_overlap.cell_distribution",
                    counts=", ".join(f"{cell}: {n}"
                                     for cell, n in sorted(counts.items()))))
                # C-M-20: this is not a search volume and not your traffic. It is
                # MAX(competitor_metrics.traffic) per keyword — the best-ranking
                # RIVAL's DataForSEO ETV — summed per cell.
                vol = df_overlap.groupby('cell')['best_rival_etv'].sum().to_dict()
                report.append(m.get(
                    "serp_overlap.best_rival_etv",
                    values=", ".join(f"{cell}: {int(v)}"
                                     for cell, v in sorted(vol.items()))))
                # The row cap is in the file beside the sentence that quotes it, so
                # the prose cannot say "top 15" while the slice takes another number
                # (chunk Y17).
                row_cap = self.action_queue_row_cap()

                def _queue_note(total):
                    return self.action_queue_note(total, row_cap)

                excl = df_overlap[df_overlap['cell'] == 'exclusive_competitor']
                if not excl.empty:
                    report.append(m.get("headings.action_queue_exclusive")
                                  + _queue_note(len(excl)))
                    for _, r in excl.head(row_cap).iterrows():
                        gap = (m.get("serp_overlap.exclusive_row_gap_clause")
                               if r['all_competitor_gap'] else "")
                        report.append(m.get("serp_overlap.exclusive_row",
                                            keyword=r['keyword'],
                                            n=int(r['overlap_count']),
                                            gap_clause=gap))
                comm = df_overlap[df_overlap['cell'] == 'shared_commodity']
                if not comm.empty:
                    report.append(m.get("headings.action_queue_commodity")
                                  + _queue_note(len(comm)))
                    for _, r in comm.head(row_cap).iterrows():
                        report.append(m.get("serp_overlap.commodity_row",
                                            keyword=r['keyword'],
                                            n=int(r['overlap_count'])))
                report.append(m.get(
                    "serp_overlap.footnote",
                    vacuum_clause=(m.get("serp_overlap.footnote_vacuum_clause")
                                   if vacuums_rendered else "")))

            # 3d. Competitor Feasibility (C4 / SC-6: check_feasibility, surfaced)
            df_feasibility = pd.read_sql_query('''
                SELECT domain, competitor_da, feasible, suggestion
                FROM competitor_feasibility
                WHERE run_id = ?
                ORDER BY feasible DESC, domain
            ''', conn, params=(run_id,))

            if df_feasibility.empty and not df_overlap.empty:
                # Silence here used to be indistinguishable from "no competitor
                # was scorable". The commonest cause is an unmeasured client DA:
                # `feasibility_by_competitor` now withholds every verdict rather
                # than computing them all from a default of 0.
                report.append(m.get("headings.feasibility"))
                report.append(m.get("feasibility.not_computed"))
            if not df_feasibility.empty:
                report.append(m.get("headings.feasibility"))
                # The margin comes from the key `analysis.check_feasibility` reads,
                # not from a second literal: the sentence said "+ 5" while the knob
                # was `technical.feasibility_threshold` (chunk Y17).
                from src.analysis import feasibility_threshold
                report.append(m.get("feasibility.intro",
                                    threshold=f"{feasibility_threshold():g}"))
                df_feasibility['feasible'] = df_feasibility['feasible'].apply(
                    lambda x: "✅" if x else "❌")
                report.append(md_table(df_feasibility, messages=m, index=False))

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
                report.append(m.get("headings.positioning"))
                report.append(m.get("positioning.intro"))
                # The authority axis is INFLATED while the handoff's ranks are
                # page-relative, and by enough to move a domain across
                # `positioning.authority_threshold` (50). `top10_count` is
                # `MIN(position) <= 10` over the handoff keywords, and that
                # position restarts at 1 on every SERP page — so every handoff
                # keyword counts as a top-10 ranking. With the default weights
                # (moz_da 0.7 / top10 0.3) and `top10_saturation` 10, a domain
                # with ten or more handoff keywords saturates the component at
                # 100 regardless of where it really ranks: DA 30 and NO genuine
                # top-10 rankings scores 51 instead of 30. The quadrant is the
                # verdict this section exists to give, so this cannot live in
                # the coverage block.
                if (run_coverage or {}).get("rank_is_absolute") is False:
                    # The threshold the sentence quotes comes from the key
                    # `positioning.classify` reads, not from a second literal.
                    from src.positioning import DEFAULT_AUTHORITY_THRESHOLD
                    report.append(m.get(
                        "positioning.authority_inflated_warning",
                        citation=m.get("rank_semantics.finding_citation"),
                        threshold=(self.config.get("positioning", {}) or {}).get(
                            "authority_threshold", DEFAULT_AUTHORITY_THRESHOLD)))
                quad_counts = df_positioning['quadrant'].value_counts().to_dict()
                report.append(m.get(
                    "positioning.quadrant_distribution",
                    counts=", ".join(f"{q}: {n}"
                                     for q, n in sorted(quad_counts.items()))))
                disp = df_positioning.copy()
                disp['domain'] = disp.apply(
                    lambda r: m.get("icons.you", value=r['domain'])
                    if r['is_client'] else r['domain'], axis=1)
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
                          'authority_basis']], messages=m, index=False))
                floors = {str(_rationale(r, 'min_focus_tokens', '')) for _, r in
                          df_positioning.iterrows()} - {''}
                if floors:
                    report.append(m.get("positioning.focus_floor_footnote",
                                        floor=sorted(floors)[0]))
                mid = df_positioning[df_positioning['quadrant'] == 'middle']
                if not mid.empty:
                    report.append(m.get("positioning.danger_zone",
                                        domains=", ".join(mid['domain'].tolist())))

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
                report.append(m.get("headings.sov"))
                report.append(m.get("sov.intro"))
                if sov_unmeasured:
                    report.append(m.plural(
                        "sov.not_measured", len(sov_unmeasured),
                        engines=", ".join(sorted(sov_unmeasured))))
                if sov_unknown:
                    report.append(m.plural(
                        "sov.coverage_unknown", len(sov_unknown),
                        engines=", ".join(sorted(sov_unknown))))
                for engine in sorted(df_sov['engine'].dropna().unique()):
                    eng = df_sov[df_sov['engine'] == engine]
                    report.append(m.get("headings.sov_engine", engine=engine))
                    brands = eng[eng['entity_type'] == 'brand']
                    men = brands[brands['category'] != 'other']
                    men = men.sort_values('mention_share', ascending=False).head(10)
                    if not men.empty:
                        # C-M-17: `presence_rate` is the quantity the guide describes
                        # ("whose brand the models return") — named in k of n answers —
                        # and it was computed and never printed. `mention_share` is a
                        # share of all brand mentions, including "other".
                        # pd.notna, not `is not None`: a SQL NULL arrives from
                        # pandas as NaN, which IS not None and would have rendered
                        # "named in nan% of answers". A brand row can carry NULL
                        # here — the export gave no question count for it (Chunk X).
                        report.append(m.get(
                            "sov.mention_share_intro",
                            values=", ".join(
                                m.get("sov.mention_share_value",
                                      entity=r['entity'],
                                      you_clause=(
                                          m.get("sov.mention_share_you_clause")
                                          if r['is_client'] else ""),
                                      share=(r['mention_share'] or 0),
                                      presence_clause=(
                                          m.get("sov.mention_share_presence_clause",
                                                presence=r['presence_rate'] * 100)
                                          if pd.notna(r['presence_rate']) else ""))
                                for _, r in men.iterrows())))
                    # …and the remainder, so the shares visibly sum to 100.
                    other_share = brands[brands['category'] == 'other']['mention_share'].sum()
                    if other_share:
                        other_names = sorted(
                            brands[brands['category'] == 'other']['entity'].dropna().unique())
                        report.append(m.get(
                            "sov.other_brands", share=other_share,
                            names_clause=(
                                m.get("sov.other_brands_names_clause",
                                      names=", ".join(other_names[:8]))
                                if other_names else "")))
                    gap_rows = eng[eng['cited_gap'] == 1]   # single source: the persisted flag
                    if not gap_rows.empty:
                        report.append(m.get(
                            "sov.cited_gap",
                            entities=", ".join(
                                sorted(gap_rows['entity'].dropna().unique()))))

            # 3g. Branded-Demand Benchmark (C3 / SC-5)
            df_brand = pd.read_sql_query('''
                SELECT domain, brand, branded_search_volume, branded_volume_share,
                       branded_growth, est_branded_click_share, estimation_basis,
                       queries
                FROM brand_demand_bench WHERE run_id = ?
                ORDER BY branded_search_volume DESC
            ''', conn, params=(run_id,))

            if not df_brand.empty:
                report.append(m.get("headings.brand_demand"))
                report.append(m.get("brand_demand.intro"))
                n_unavailable = int((df_brand['estimation_basis'] == 'volume_unavailable').sum())
                if n_unavailable:
                    # C-C-11: this used to be an all-or-nothing caveat, because a
                    # per-brand provider failure was stored as 0 volume and a 0.00%
                    # share. Now each unmeasured brand is NULL and says so.
                    report.append(m.get("brand_demand.unavailable",
                                        n=n_unavailable, total=len(df_brand)))
                n_ambiguous = int((df_brand['estimation_basis'] == 'ambiguous_brand').sum())
                if n_ambiguous:
                    report.append(m.get("brand_demand.ambiguous", n=n_ambiguous))
                disp = df_brand.copy()
                disp['brand'] = disp.apply(
                    lambda r: (m.get("icons.you", value=r['brand'])
                               if r['domain'] == client_domain
                               else r['brand']), axis=1)   # own row identifiable regardless of anchor
                # `queries` is Excel-only: one row can carry seven query strings, which
                # would make the markdown table unreadable.
                report.append(md_table(disp.drop(columns=['queries']),
                                       messages=m, index=False))

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
                report.append(m.get("headings.risk_radar"))
                report.append(m.get("risk_radar.intro"))
                # C-C-06 / C-M-07: say why a cliff may be absent. The series is now
                # per RUN (not per calendar day) and normalised by how many keywords
                # were measured, and it is withheld entirely below
                # `risk_signals.cliff_min_sample` — so "no visibility cliff" must not
                # be readable as "we looked and the visibility held".
                cliff_floor = (self.config.get("risk_signals", {}) or {}).get("cliff_min_sample")
                if cliff_floor:
                    report.append(m.get("risk_radar.cliff_floor",
                                        floor=cliff_floor))
                report.extend(anchor_caveat_lines(
                    df_risk['signal_type'].tolist() if not df_risk.empty else [],
                    risk_coverage, m))
                if df_risk.empty:
                    report.append(m.get("risk_radar.none_detected"))
                own = df_risk[df_risk['is_own_site'] == 1]
                if not own.empty:
                    report.append(m.get("headings.risk_own_site"))
                    for _, r in own.iterrows():
                        report.append(m.get("risk_radar.own_row",
                                            signal_type=r['signal_type'],
                                            severity=r['severity'],
                                            domain=r['domain'],
                                            evidence=r['evidence_json']))
                comp = df_risk[df_risk['is_own_site'] == 0]
                if not comp.empty:
                    report.append(m.get("headings.risk_competitors"))
                    report.append(md_table(comp[['domain', 'signal_type', 'severity']],
                                           messages=m, index=False))
                    for _, r in comp[comp['signal_type'] == 'anchor_text_spam'].iterrows():
                        report.append(m.get("risk_radar.anchor_evidence_row",
                                            domain=r['domain'],
                                            evidence=r['evidence_json']))

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
                report.append(m.get("headings.youtube"))
                report.append(m.get("youtube.intro"))
                disp = df_yt.copy()
                disp['channel?'] = disp['has_channel'].apply(
                    lambda v: '✓' if v == 1 else ('✗' if v == 0 else '?'))
                disp['domain'] = disp['domain'].apply(
                    lambda d: m.get("icons.you", value=d) if d == client_domain
                    else d)
                cols = ['domain', 'channel?', 'handle', 'channel_title', 'subscriber_count',
                        'last_upload_date', 'uploads_recent', 'match_confidence', 'check_status']
                report.append(md_table(disp[cols], messages=m, index=False))
                n_cand = int((df_yt['check_status'] == 'candidate').sum())
                if n_cand:
                    report.append(m.get("youtube.candidates", n=n_cand))
                n_err = int((df_yt['check_status'] == 'error').sum())
                if n_err:
                    report.append(m.get("youtube.errors", n=n_err))

            # 4. Strategic Openings & Reframes
            if reframes:
                report.append(m.get("headings.reframes"))
                report.append(m.get("reframes.intro"))
                for r in reframes:
                    report.append(m.get("headings.reframe_entry",
                                        keyword=r['keyword']))
                    report.append(m.get("headings.reframe_url", url=r['url']))
                    if r.get('paa'):
                        report.append(m.get("headings.reframe_paa",
                                            paa=", ".join(r['paa'][:5])))
                    report.append("\n" + r['reframe'])
                    report.append(m.get("headings.reframe_separator"))

        # Output paths — `orchestrator.reports_dir` when the GUI set one (C-C-16),
        # else the working directory as before.
        out_dir = self.output_dir or "."
        if out_dir not in (".", ""):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as exc:
                print(self.messages.get("output.dir_unusable", path=out_dir,
                                        error=exc))
                out_dir = "."
        md_path = os.path.join(out_dir, f"strategic_briefing_run_{run_id}.md")
        excel_path = os.path.join(out_dir, f"audit_results_run_{run_id}.xlsx")

        # Last, after every section has asked for its words: how many it could
        # not find. The markers are already in the body; this is the count, so
        # the reader does not have to hunt for them (P2).
        report.extend(self.shortfall_lines())

        report_content = "\n".join(report)
        with open(md_path, "w") as f:
            f.write(report_content)
        
        # Excel Export
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            # No connection here: every sheet below is a DataFrame already built
            # under the block above (its last query is line 1229). This opened a
            # transaction and closed it again for zero statements, while reading
            # as though the sheets were queried here (cold review of chunk Y10).
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
