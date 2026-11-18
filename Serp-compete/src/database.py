import sqlite3
import datetime
import logging
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from src import db_connect

# Paths relative to serp-compete/src/
SHARED_CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "shared_config.json"))

def config_for_lock_timeout() -> Dict[str, Any]:
    """`shared_config.json` for the lock wait alone, never raising.

    `load_shared_config` raises on a corrupt or unreadable file, deliberately:
    a caller reading an editorial threshold must not silently score against a
    default. The lock wait is not that — it is how long to wait for a lock —
    and `DatabaseManager.__init__` reads it even when the caller supplied its
    own `db_path`, so raising here would newly fail construction for a caller
    that never reads the config at all (cold review of chunk Y11). The file's
    real readers still raise where they are.
    """
    try:
        return load_shared_config()
    except Exception as exc:
        logging.warning(
            "Could not read %s for the database lock wait (%s); using the "
            "documented default. Every other setting in that file is read "
            "elsewhere and will report this itself.", SHARED_CONFIG_PATH, exc)
        return {}


def load_shared_config() -> Dict[str, Any]:
    """shared_config.json, or {} when it is absent.

    Here rather than only in main.py so a consumer that is handed a DB but not a
    config (ReportGenerator) reads the same editorial thresholds the audit wrote
    with, instead of hard-coding them (P4).
    """
    if os.path.exists(SHARED_CONFIG_PATH):
        with open(SHARED_CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {}


# C-M-02 / owner decision 2 (2026-11-14): the magnet floor and the "ranks well"
# ceiling are editorial config, and both have a documented default. The fallbacks
# here mirror shared_config.json so a missing config degrades to the documented
# definition rather than to "no filter at all", which is the bug being fixed.
DEFAULT_VACUUM_MIN_MEDICAL = 6
# C-M-18: the volatility TRIGGER (shared_config `risk_signals.volatility_min_shift`).
# It was the literal 3 in the query while a config key the owner could edit
# (`volatility_high_shift`) only set the severity band.
DEFAULT_VOLATILITY_MIN_SHIFT = 3
DEFAULT_MAGNET_MAX_POSITION = 10


# C-C-15: `tag_competitor_position`'s three thresholds, previously Python literals
# (`traffic > 1000 and medical_score > 15`, `systems_t2 > 10`). The defaults mirror
# shared_config `technical.position_thresholds`, whose `_source` note records that
# they are editorial and what they were before decision 3 shrank the vocabulary.
DEFAULT_POSITION_THRESHOLDS = {
    "volume_scaler_min_traffic": 1000,
    "volume_scaler_min_medical": 9,
    "generalist_min_t2": 10,
}


def position_thresholds(config: Dict[str, Any] = None) -> Dict[str, float]:
    """`technical.position_thresholds`, with the documented defaults."""
    technical = (config if config is not None else load_shared_config()).get("technical", {}) or {}
    configured = technical.get("position_thresholds", {}) or {}
    return {key: configured.get(key, default)
            for key, default in DEFAULT_POSITION_THRESHOLDS.items()}


def magnet_thresholds(config: Dict[str, Any] = None) -> Tuple[int, int]:
    """(vacuum_min_medical, magnet_max_position) from `technical.*`."""
    technical = (config if config is not None else load_shared_config()).get("technical", {}) or {}
    return (int(technical.get("vacuum_min_medical", DEFAULT_VACUUM_MIN_MEDICAL)),
            int(technical.get("magnet_max_position", DEFAULT_MAGNET_MAX_POSITION)))


# ONE definition of "Traffic Magnet" and of "Systemic Vacuum", shared by the
# briefing's magnet table, its vacuum list and the reframe target query. Two
# producers with different definitions is exactly what made the vacuum list and
# the reframe list disagree, so these predicates are not duplicated in SQL
# anywhere else. Parameter order: run_id, min_medical, max_position.
#
# "Ranks well" is the HANDOFF rank (what Tool 1 measured), "uses only medical
# language" is the medical floor, and `keyword_relevant` is the C-M-02 relevance
# test evaluated at ingest by src/audit_universe.py. A row written before those
# columns existed has keyword_relevant NULL and is therefore NOT a magnet: the
# relevance of an old row cannot be reconstructed, and claiming it is relevant is
# the failure this fix removes.
_MAGNET_PREDICATE = (
    "run_id = ? AND keyword_relevant = 1 AND medical_score >= ? "
    "AND rank IS NOT NULL AND rank <= ?"
)
_VACUUM_EXTRA = " AND (systems_score = 0 OR systemic_label = 'Surface-Level')"
_MAGNET_COLUMNS = ("domain, url, primary_keyword, keyword_source, rank, est_traffic, "
                   "medical_score, systems_score, systemic_label, t2_count, t3_count, "
                   "scoring_window_words")


def magnet_sql(vacuum_only: bool = False, columns: str = _MAGNET_COLUMNS,
               limit: int = None) -> str:
    """The magnet (or vacuum) SELECT. Bind (run_id, min_medical, max_position)."""
    sql = (f"SELECT {columns} FROM traffic_magnets WHERE {_MAGNET_PREDICATE}"
           f"{_VACUUM_EXTRA if vacuum_only else ''} ORDER BY est_traffic DESC")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return sql


DEFAULT_DATABASE_NAME = "competitor_history.db"


def resolve_db_path(config, config_path=None):
    """The configured database, as an absolute path.

    One resolver for `technical.database_path`, called by `load_db_path` and
    by `VelocityTracker`. Those were two hand-rolled copies with two
    *different* default names, so a config with the key deleted sent the
    competitor rows to `competitor_history.db` and the velocity reads to
    `living_systems_intel.db` — one run writing an empty file while the other
    read the live one, with no warning on either side (P5/P32, the cold review
    of chunk Y12).

    A relative name resolves against the directory holding the config, never
    the current working directory. An absolute name is used as given, `~` is
    expanded, and a blank, non-string or malformed value is reported and the
    default used — the section too, not only the leaf: `"technical": null` was
    an `AttributeError` from a `.get` on `None` while a blank leaf got the
    designed warning. Tool 1 resolves `database.path` the same way
    (`db_connect.resolve_database_path`).
    """
    if config_path is None:
        config_path = SHARED_CONFIG_PATH
    section = config.get("technical") if isinstance(config, dict) else None
    if not isinstance(section, dict):
        if section is not None:
            logging.warning(
                "%s `technical` is %r, which is not a block of settings; "
                "using the default database %s.",
                os.path.basename(config_path), section, DEFAULT_DATABASE_NAME)
        section = {}
    db_name = section.get("database_path", DEFAULT_DATABASE_NAME)
    if not isinstance(db_name, str) or not db_name.strip():
        logging.warning(
            "%s technical.database_path is %r, which is not a path; using "
            "the default %s.", os.path.basename(config_path), db_name,
            DEFAULT_DATABASE_NAME)
        db_name = DEFAULT_DATABASE_NAME
    db_name = os.path.expanduser(db_name.strip())
    if os.path.isabs(db_name):
        return db_name
    return os.path.abspath(os.path.join(os.path.dirname(config_path), db_name))


def load_db_path():
    """The configured database for this repo's own `shared_config.json`.

    With no config present the name was returned bare — relative to the
    current working directory — so a reader run from another directory opened
    a new empty database beside itself rather than reporting that the history
    was missing (review chunk Y12). It is reported now: a run with no config
    is a run on defaults, and the database it lands on is the thing worth
    knowing.
    """
    if os.path.exists(SHARED_CONFIG_PATH):
        return resolve_db_path(load_shared_config())
    resolved = resolve_db_path({})
    logging.warning(
        "No %s found, so technical.database_path is unset: using %s. If the "
        "history looks empty, this is the file it was read from.",
        SHARED_CONFIG_PATH, resolved)
    return resolved


class DatabaseManager:
    def __init__(self, db_path: str = None, config: Dict[str, Any] = None):
        self.db_path = db_path or load_db_path()
        # Resolved once per instance, like `load_db_path` above and every other
        # editorial threshold in this module: the wait before a concurrent
        # write fails with `database is locked` was sqlite3's undeclared 5.0
        # until review chunk Y11, while the Streamlit orchestrator and an audit
        # write this file at the same time. `config` is the same optional
        # argument `position_thresholds` and `magnet_thresholds` take, so a
        # caller holding the config does not re-read the file.
        self.lock_timeout = db_connect.lock_timeout_from_config(
            config if config is not None else config_for_lock_timeout())
        self._create_tables()

    def connection(self):
        """A managed connection: committed on a clean exit, always closed.

        `_get_connection` returned a bare `sqlite3.connect`, and every caller
        used it as `with ... as conn:`, which commits but never closes the
        handle — per competitor and per URL inside the audit loop. Two callers
        took it bare and never closed it at all (review chunk Y10).
        """
        return db_connect.connection(self.db_path, timeout=self.lock_timeout)

    def _create_tables(self):
        with self.connection() as conn:
            cursor = conn.cursor()
            
            # Runs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_domain TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Phase 3: Competitors Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS competitors (
                    domain TEXT PRIMARY KEY,
                    avg_da INTEGER,
                    domain_authority INTEGER,
                    last_crawled_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Phase 3: Traffic Magnets Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS traffic_magnets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    domain TEXT,
                    url TEXT,
                    primary_keyword TEXT,
                    est_traffic REAL,
                    medical_score INTEGER,
                    systems_score INTEGER,
                    systemic_label TEXT,
                    keyword_source TEXT,
                    keyword_relevant BOOLEAN,
                    rank INTEGER,
                    t2_count INTEGER,
                    t3_count INTEGER,
                    scoring_window_words INTEGER,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')

            # Phase 3: Market Gaps Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS market_gaps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    keyword TEXT,
                    competitor_overlap_count INTEGER,
                    feasibility_status TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')

            # Legacy tables maintained for compatibility during migration
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS competitor_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    domain TEXT NOT NULL,
                    url TEXT NOT NULL,
                    keyword TEXT,
                    position INTEGER,
                    traffic REAL,
                    keyword_source TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS semantic_audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    url TEXT NOT NULL,
                    medical_score INTEGER,
                    systems_score INTEGER,
                    systemic_label TEXT,
                    t2_count INTEGER,
                    t3_count INTEGER,
                    scoring_window_words INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Revision 3: Competitor Metadata Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS competitor_metadata (
                    domain TEXT PRIMARY KEY,
                    market_position TEXT,
                    strategy TEXT,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Revision 4: Longitudinal History Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS competitor_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    url TEXT,
                    position INTEGER,
                    pa REAL,
                    traffic_value REAL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    drift REAL DEFAULT 0,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')

            # v3: EEAT Scores Table (Gap 3 enhancement)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS eeat_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    scored_at TEXT NOT NULL,
                    has_author_byline BOOLEAN,
                    has_publish_date BOOLEAN,
                    has_update_date BOOLEAN,
                    has_likely_original_images BOOLEAN,
                    first_person_count_normalised REAL,
                    case_study_signal BOOLEAN,
                    experience_score REAL,
                    has_credentials_in_byline BOOLEAN,
                    schema_author_type_person BOOLEAN,
                    tier_3_or_tier_2_present BOOLEAN,
                    expertise_score REAL,
                    domain_authority_normalised REAL,
                    external_link_count_normalised REAL,
                    schema_organization_present BOOLEAN,
                    authoritativeness_score REAL,
                    is_https BOOLEAN,
                    has_contact_link BOOLEAN,
                    has_privacy_link BOOLEAN,
                    trustworthiness_score REAL,
                    score_confidence TEXT,
                    caveat TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_eeat_scores_url ON eeat_scores(url)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_eeat_scores_run ON eeat_scores(run_id)')

            # v3: Cluster Results Table (Gap 4 enhancement)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cluster_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    domain TEXT NOT NULL,
                    analysed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    pages_analysed INTEGER,
                    internal_link_graph TEXT,
                    hub_candidates TEXT,
                    cluster_signal TEXT,
                    resolution_caveat TEXT,
                    avg_in_degree REAL,
                    max_in_degree INTEGER,
                    num_connected_components INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cluster_results_domain ON cluster_results(domain)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cluster_results_run ON cluster_results(run_id)')

            # v3: Semantic Audit Results Table (detailed tier scoring)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS semantic_audit_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    tier_1_medical_score INTEGER,
                    tier_1_medical_terms_found TEXT,
                    tier_2_systems_score INTEGER,
                    tier_2_systems_terms_found TEXT,
                    tier_3_bowen_score INTEGER,
                    tier_3_bowen_terms_found TEXT,
                    systemic_label TEXT,
                    medical_model_indicator BOOLEAN,
                    extraction_status TEXT,
                    content_length INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_semantic_audit_results_url ON semantic_audit_results(url)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_semantic_audit_results_run ON semantic_audit_results(run_id)')

            # --- MIGRATIONS: Add columns if they don't exist (Yolo Mode robustness) ---
            try:
                # Add systemic_label to semantic_audits
                cursor.execute("ALTER TABLE semantic_audits ADD COLUMN systemic_label TEXT DEFAULT 'Standard'")
            except sqlite3.OperationalError:
                pass # Already exists

            try:
                # Add systemic_label to traffic_magnets
                cursor.execute("ALTER TABLE traffic_magnets ADD COLUMN systemic_label TEXT DEFAULT 'Standard'")
            except sqlite3.OperationalError:
                pass # Already exists

            # C-M-01 / C-M-02: keyword provenance, the relevance verdict and the
            # handoff rank. ALTER beside CREATE (the fourth occurrence of this
            # class in this file) so a DB written before this chunk is repaired
            # instead of breaking save_traffic_magnet and the magnet query.
            for table, column, decl in (
                ("traffic_magnets", "keyword_source", "TEXT"),
                ("traffic_magnets", "keyword_relevant", "BOOLEAN"),
                ("traffic_magnets", "rank", "INTEGER"),
                ("competitor_metrics", "keyword_source", "TEXT"),
                # C-M-03: the query strings whose volume became "branded demand",
                # so the Excel sheet can show what was actually asked for.
                ("brand_demand_bench", "queries", "TEXT"),
                # C-C-08 / C-M-05: the real Tier-2 / Tier-3 counts, so a cache hit
                # no longer has to GUESS them back out of the weighted score.
                ("semantic_audits", "t2_count", "INTEGER"),
                ("semantic_audits", "t3_count", "INTEGER"),
                # The same counts on the per-run magnet row: a cache-served page
                # writes no semantic_audits row for THIS run, so the run's own table
                # has to carry them or the report cannot tell a real count from a
                # missing one.
                ("traffic_magnets", "t2_count", "INTEGER"),
                ("traffic_magnets", "t3_count", "INTEGER"),
                # C-M-19: the window the score was counted over, so a density can be
                # derived and checked. An absolute count over an unknown window is
                # the figure the finding is about.
                ("traffic_magnets", "scoring_window_words", "INTEGER"),
                ("semantic_audits", "scoring_window_words", "INTEGER"),
                # C-M-09: the competitor's DOMAIN authority, kept apart from
                # `avg_da`, which is (and always was) the average PAGE authority of
                # its sampled URLs. Conflating the two is the finding.
                ("competitors", "domain_authority", "INTEGER"),
            ):
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
                except sqlite3.OperationalError:
                    pass  # Already exists

            # C-M-20: `keyword_volume` was never a search volume — it is
            # MAX(competitor_metrics.traffic), i.e. the best-ranking RIVAL's
            # DataForSEO ETV for that keyword. Renamed in place (SQLite >= 3.25) so
            # the column, the report and the Excel sheet all say the same thing. The
            # PRAGMA check keeps this idempotent and safe on a DB that has either
            # name, or both.
            try:
                overlap_columns = [row[1] for row in
                                   cursor.execute("PRAGMA table_info(serp_overlap)").fetchall()]
                if "keyword_volume" in overlap_columns and "best_rival_etv" not in overlap_columns:
                    cursor.execute("ALTER TABLE serp_overlap "
                                   "RENAME COLUMN keyword_volume TO best_rival_etv")
            except sqlite3.OperationalError as exc:
                logging.warning("serp_overlap column rename skipped: %s", exc)

            try:
                # C1/SC-3: add cited_gap to an EXISTING sov_daily (the C1 commit created the
                # table without it). Fresh DBs get it from CREATE TABLE below; this repairs
                # DBs created between the two commits so save_sov + the report don't break.
                cursor.execute("ALTER TABLE sov_daily ADD COLUMN cited_gap BOOLEAN")
            except sqlite3.OperationalError:
                pass # Already exists, or sov_daily not yet created (fresh DB)

            try:
                # SC-7-YT P1.9 (F1/P8): reach an EXISTING yt_channel_presence with the
                # activity column via ALTER, not only CREATE TABLE. Fresh DBs get it from
                # CREATE TABLE below; a DB that predates this column is repaired here so
                # save_yt_presence + the report don't break. (Mirrors the cited_gap fix.)
                cursor.execute("ALTER TABLE yt_channel_presence ADD COLUMN uploads_recent INTEGER")
            except sqlite3.OperationalError:
                pass # Already exists, or yt_channel_presence not yet created (fresh DB)

            try:
                # SC-8.4: reach an EXISTING anchor_coverage with the reason
                # column via ALTER, not only CREATE TABLE. A DB written between
                # the two commits otherwise breaks both save and the report.
                # (Mirrors the cited_gap and uploads_recent repairs above —
                # third occurrence of this class in this file.)
                cursor.execute("ALTER TABLE anchor_coverage ADD COLUMN reason TEXT")
            except sqlite3.OperationalError:
                pass  # Already exists, or anchor_coverage not yet created

            for _anchor_col in ("errored_cached", "errored_age_unknown"):
                try:
                    # Chunk X (D-C-10 downstream): sub-counts of `errored`
                    # saying how many of this run's error blocks were Tool 1
                    # cache hits rather than fresh outages. ALTER beside CREATE
                    # for the same reason as `reason` above.
                    cursor.execute("ALTER TABLE anchor_coverage ADD COLUMN "
                                   f"{_anchor_col} INTEGER")
                except sqlite3.OperationalError:
                    pass  # Already exists, or anchor_coverage not yet created

            # SC-1: GEO / Extractability Profiles Table
            # (Spec: suite_enhancement_spec_v1.md#SC-1)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS geo_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    profiled_at TEXT NOT NULL,
                    extractability_tier TEXT,
                    has_faq_schema BOOLEAN,
                    has_article_schema BOOLEAN,
                    has_localbusiness_schema BOOLEAN,
                    has_person_schema BOOLEAN,
                    has_org_schema BOOLEAN,
                    has_author_byline BOOLEAN,
                    credential_count INTEGER,
                    question_heading_count INTEGER,
                    question_heading_ratio REAL,
                    has_publish_date BOOLEAN,
                    has_update_date BOOLEAN,
                    present_signals TEXT,
                    why_cited TEXT,
                    caveat TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_geo_profiles_url ON geo_profiles(url)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_geo_profiles_run ON geo_profiles(run_id)')

            # C4 / SC-6: SERP Overlap & Differentiation Gap matrix
            # (Spec: suite_enhancement_spec_v1.md#C4). Competitors keyed by domain.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS serp_overlap (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    keyword TEXT NOT NULL,
                    snapshot_date TEXT,
                    competitors_ranking_json TEXT,
                    self_position INTEGER,
                    overlap_count INTEGER,
                    commodity_score REAL,
                    best_rival_etv REAL,
                    cell TEXT,
                    all_competitor_gap BOOLEAN,
                    config_ref TEXT,
                    estimation_basis TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_serp_overlap_run ON serp_overlap(run_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_serp_overlap_cell ON serp_overlap(cell)')

            # C4 / SC-6: per-competitor feasibility (client DA vs each competitor DA),
            # the check_feasibility half of the AnalysisEngine wiring.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS competitor_feasibility (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    domain TEXT NOT NULL,
                    client_da INTEGER,
                    competitor_da INTEGER,
                    feasible BOOLEAN,
                    suggestion TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_competitor_feasibility_run ON competitor_feasibility(run_id)')

            # C2 / SC-4: Barbell Positioning (authority x focus 2x2). Domain-keyed.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positioning (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    domain TEXT NOT NULL,
                    is_client BOOLEAN,
                    computed_at TEXT,
                    authority_score REAL,
                    focus_score REAL,
                    quadrant TEXT,
                    rationale_json TEXT,
                    estimation_basis TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_positioning_run ON positioning(run_id)')

            # C1 / SC-3: AI Answer Share-of-Voice (per engine, per entity). Consumed
            # from serp-discover's AI-visibility export; competitors keyed by domain.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sov_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    engine TEXT,
                    snapshot_date TEXT,
                    entity TEXT,
                    entity_type TEXT,
                    is_client BOOLEAN,
                    category TEXT,
                    mention_share REAL,
                    citation_share REAL,
                    presence_rate REAL,
                    avg_sentiment REAL,
                    cited_gap BOOLEAN,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sov_daily_run ON sov_daily(run_id)')

            # Chunk X: how many questions each engine actually answered behind
            # this run's sov_daily rows. An engine serp-discover skipped is
            # dropped from sov_daily rather than published at 0% share, so
            # without this table "engine absent from the table" could not be
            # told apart from "engine measured, nothing matched" afterwards —
            # the same gap anchor_coverage was created to close.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sov_coverage (
                    run_id INTEGER NOT NULL,
                    engine TEXT NOT NULL,
                    questions_total INTEGER,
                    measured BOOLEAN,
                    PRIMARY KEY (run_id, engine),
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')

            # C3 / SC-5: Branded-Demand Competitive Benchmark. Domain-keyed.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS brand_demand_bench (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    domain TEXT,
                    brand TEXT,
                    period TEXT,
                    branded_search_volume INTEGER,
                    branded_volume_share REAL,
                    branded_growth REAL,
                    est_branded_click_share REAL,
                    estimation_basis TEXT,
                    queries TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_brand_demand_run ON brand_demand_bench(run_id)')

            # C6 / SC-8: Reputation-Risk Radar. Domain-keyed; is_own_site separates
            # own-site warnings from competitor intel.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS risk_signal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    domain TEXT,
                    is_own_site BOOLEAN,
                    detected_at TEXT,
                    signal_type TEXT,
                    severity TEXT,
                    evidence_json TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_risk_signal_run ON risk_signal(run_id)')

            # SC-8.4: how the anchor-text fetch actually went for this run, so a
            # past run's coverage can be recovered. Without it, "no anchor
            # signals" in an old report is indistinguishable from "every fetch
            # failed that day" — the counts existed only in that run's console
            # output and its rendered markdown.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS anchor_coverage (
                    run_id INTEGER PRIMARY KEY,
                    detected_at TEXT,
                    collected_at TEXT,
                    fetch_status TEXT,
                    reason TEXT,
                    total INTEGER,
                    with_anchors INTEGER,
                    read_no_anchors INTEGER,
                    no_record INTEGER,
                    errored INTEGER,
                    skipped INTEGER,
                    unknown INTEGER,
                    -- Sub-counts of `errored`, not additions to it: how many
                    -- of those error blocks Tool 1 re-served from its 30-day
                    -- cache, and how many carried no date to judge by.
                    errored_cached INTEGER,
                    errored_age_unknown INTEGER,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')

            # SC-7-YT Phase 1: YouTube Presence Check. Domain-keyed (competitors is
            # `domain TEXT PRIMARY KEY` — deliberately NO competitor_id). One row per
            # (run_id, domain): the best-matched channel, or the none_found/error state.
            # channel_id is coerced to '' when absent so the PK stays stable for the
            # no-channel row; save_yt_presence uses INSERT OR REPLACE (within-run idempotent).
            # (Spec: sc7-yt-spec.md#3 — Phase 1 data model.)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS yt_channel_presence (
                    run_id INTEGER NOT NULL,
                    domain TEXT NOT NULL,
                    checked_at TEXT,
                    has_channel BOOLEAN,
                    channel_id TEXT DEFAULT '',
                    handle TEXT,
                    channel_title TEXT,
                    channel_url TEXT,
                    subscriber_count INTEGER,
                    video_count INTEGER,
                    last_upload_date TEXT,
                    uploads_recent INTEGER,
                    match_confidence TEXT,
                    match_basis TEXT,
                    check_status TEXT,
                    estimation_basis TEXT,
                    PRIMARY KEY (run_id, domain, channel_id),
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_yt_presence_run ON yt_channel_presence(run_id)')

            conn.commit()

    def create_run(self, client_domain: str) -> int:
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO runs (client_domain) VALUES (?)', (client_domain,))
            conn.commit()
            return cursor.lastrowid

    def save_competitor_summary(self, domain: str, avg_da: int,
                                domain_authority: int = None):
        """Persist a competitor's authority figures.

        `avg_da` is the average Moz PAGE authority of the URLs sampled this run — the
        name is historic and misleading, which is half of C-M-09. `domain_authority`
        is the real Moz Domain Authority of the domain root, read from the same
        url_metrics response, and is None when Moz did not return one: unknown, never
        the page figure wearing a domain label.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO competitors (domain, avg_da, domain_authority, last_crawled_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(domain) DO UPDATE SET
                    avg_da = excluded.avg_da,
                    domain_authority = COALESCE(excluded.domain_authority,
                                                competitors.domain_authority),
                    last_crawled_at = CURRENT_TIMESTAMP
            ''', (domain, avg_da, domain_authority))
            conn.commit()

    def save_traffic_magnet(self, run_id: int, domain: str, url: str, keyword: str,
                            traffic: float, medical: int, systems: float,
                            label: str = "Standard", keyword_source: str = None,
                            keyword_relevant: bool = None, rank: int = None,
                            t2_count: int = None, t3_count: int = None,
                            scoring_window_words: int = None):
        """Persist one audited page.

        `t2_count` / `t3_count` are this page's real Tier-2 / Tier-3 term counts
        (C-C-08), NULL when the page came from the semantic cache before they were
        persisted — the report then reads `systemic_depth` as "Not recorded" rather
        than inferring depth from a weighted score.

        `keyword_source` / `keyword_relevant` / `rank` come from
        src/audit_universe.py (C-M-01/C-M-02). They are nullable on purpose: a
        caller that cannot say where a keyword came from must not be able to claim
        it was relevant, and `magnet_sql` requires `keyword_relevant = 1`, so an
        unlabelled row is persisted and reported but never becomes a magnet, a
        vacuum or a reframe target.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO traffic_magnets (run_id, domain, url, primary_keyword, est_traffic, medical_score, systems_score, systemic_label, keyword_source, keyword_relevant, rank, t2_count, t3_count, scoring_window_words)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (run_id, domain, url, keyword, traffic, medical, systems, label,
                  keyword_source,
                  (None if keyword_relevant is None else int(bool(keyword_relevant))),
                  rank, t2_count, t3_count, scoring_window_words))
            conn.commit()

    def save_geo_profile(self, run_id: int, profile: Any):
        """SC-1: persist a GeoProfile for a competitor URL.

        Accepts a src.geo_profiler.GeoProfile. present_signals is stored as a
        JSON string. (Spec: suite_enhancement_spec_v1.md#SC-1)
        """
        s = profile.signals
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO geo_profiles (
                    run_id, url, profiled_at, extractability_tier,
                    has_faq_schema, has_article_schema, has_localbusiness_schema,
                    has_person_schema, has_org_schema, has_author_byline,
                    credential_count, question_heading_count, question_heading_ratio,
                    has_publish_date, has_update_date, present_signals, why_cited, caveat)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                run_id, profile.url, profile.profiled_at, profile.extractability_tier,
                s.get("has_faq_schema"), s.get("has_article_schema"),
                s.get("has_localbusiness_schema"), s.get("has_person_schema"),
                s.get("has_org_schema"), s.get("has_author_byline"),
                len(s.get("matched_credentials", [])), s.get("question_heading_count"),
                s.get("question_heading_ratio"), s.get("has_publish_date"),
                s.get("has_update_date"), json.dumps(profile.present_signals),
                profile.why_cited, profile.caveat,
            ))
            conn.commit()

    # Finding 1 (P8) — carry-forward allowlist. Never interpolate an arbitrary
    # table/column into SQL; only these structural-profile tables (keyed by the
    # named column) may be carried forward for a cache-served URL/domain.
    _CARRY_FORWARD_TABLES = {
        "geo_profiles": "url",
        "eeat_scores": "url",
        "cluster_results": "domain",
    }

    def carry_forward_profile(self, table: str, match_col: str, match_val: str,
                              run_id: int) -> bool:
        """Copy the latest prior structural profile for a cached URL/domain into run_id.

        Purpose: a re-run within the 7-day semantic-audit cache window must not blank
                 the EEAT/GEO/cluster report sections. On a cache hit no page is
                 re-scraped, so those engines cannot run; instead we re-associate the
                 most recent prior row (from another run) with the current run_id.
                 Honest — it reuses a real earlier scrape (original timestamps
                 preserved), exactly as was_audited_recently reuses prior scores; it
                 never fabricates a row.
        Spec:    suite_enhancement_spec_SERPCOMPETE_v1.md#SC-1 (Finding 1 fix)
        Tests:   tests/test_wiring.py::test_geo_carry_forward_populates_new_run_on_cache_hit

        Returns True if a prior row was carried forward, False if none existed
        (the caller counts the miss and surfaces it — see run_audit enrichment
        coverage summary).
        """
        if self._CARRY_FORWARD_TABLES.get(table) != match_col:
            raise ValueError(
                f"carry_forward_profile: {table}.{match_col} not in allowlist"
            )
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table})")
            cols = [row[1] for row in cursor.fetchall()]  # row[1] = column name
            cursor.execute(
                f"SELECT * FROM {table} WHERE {match_col} = ? AND run_id != ? "
                f"ORDER BY id DESC LIMIT 1",
                (match_val, run_id),
            )
            row = cursor.fetchone()
            if not row:
                return False
            rowdict = dict(zip(cols, row))
            rowdict["run_id"] = run_id  # re-point the copy at the current run
            insert_cols = [c for c in cols if c != "id"]  # id is AUTOINCREMENT
            placeholders = ", ".join("?" for _ in insert_cols)
            cursor.execute(
                f"INSERT INTO {table} ({', '.join(insert_cols)}) "
                f"VALUES ({placeholders})",
                [rowdict[c] for c in insert_cols],
            )
            conn.commit()
            return True

    def save_competitor_metrics(self, metrics: List[Dict[str, Any]], run_id: int):
        with self.connection() as conn:
            cursor = conn.cursor()
            for metric in metrics:
                cursor.execute('''
                    INSERT INTO competitor_metrics (run_id, domain, url, keyword, position, traffic, keyword_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (run_id, metric['domain'], metric['url'], metric.get('keyword'),
                      metric.get('position'), metric.get('traffic'),
                      metric.get('keyword_source')))
            conn.commit()

    def save_serp_overlap(self, run_id: int, rows: List[Dict[str, Any]]):
        """C4/SC-6: persist the classified who-ranks-where matrix rows.

        Spec:  suite_enhancement_spec_v1.md#C4
        Tests: tests/test_serp_overlap.py::test_sc6_save_and_read_roundtrip
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO serp_overlap (
                    run_id, keyword, snapshot_date, competitors_ranking_json,
                    self_position, overlap_count, commodity_score, best_rival_etv,
                    cell, all_competitor_gap, config_ref, estimation_basis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, r["keyword"], r.get("snapshot_date"),
                 json.dumps(r.get("competitors_ranking", {})),
                 r.get("self_position"), r.get("overlap_count"),
                 r.get("commodity_score"), r.get("best_rival_etv"), r.get("cell"),
                 int(bool(r.get("all_competitor_gap"))), r.get("config_ref"),
                 r.get("estimation_basis"))
                for r in rows
            ])
            conn.commit()

    def save_competitor_feasibility(self, run_id: int, client_da: Optional[int],
                                    feasibility: Dict[str, Dict[str, Any]]):
        """C4/SC-6: persist per-competitor feasibility (check_feasibility output), the
        second half of the AnalysisEngine wiring — surfaced, not discarded.

        `client_da` is written as NULL when it was not measured. `int(client_da
        or 0)` recorded DA 0 against every row, so a later reader of the table
        could not tell an unmeasured client from one with no authority at all —
        and the rows would carry a verdict computed from that 0.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO competitor_feasibility
                    (run_id, domain, client_da, competitor_da, feasible, suggestion)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, domain,
                 None if client_da is None else int(client_da),
                 v.get("competitor_da"),
                 int(bool(v.get("feasible"))), v.get("suggestion"))
                for domain, v in (feasibility or {}).items()
            ])
            conn.commit()

    def save_positioning(self, run_id: int, rows: List[Dict[str, Any]],
                         computed_at: str = None):
        """C2/SC-4: persist the barbell positioning rows (competitors + the client)."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO positioning (run_id, domain, is_client, computed_at,
                    authority_score, focus_score, quadrant, rationale_json, estimation_basis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, r["domain"], int(bool(r.get("is_client"))), computed_at,
                 r.get("authority_score"), r.get("focus_score"), r.get("quadrant"),
                 json.dumps(r.get("rationale", {})), r.get("estimation_basis"))
                for r in rows
            ])
            conn.commit()

    def save_sov(self, run_id: int, rows: List[Dict[str, Any]]):
        """C1/SC-3: persist per-engine share-of-voice rows (from the AV export)."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO sov_daily (run_id, engine, snapshot_date, entity, entity_type,
                    is_client, category, mention_share, citation_share, presence_rate,
                    avg_sentiment, cited_gap)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, r.get("engine"), r.get("snapshot_date"), r.get("entity"),
                 r.get("entity_type"), int(bool(r.get("is_client"))), r.get("category"),
                 r.get("mention_share"), r.get("citation_share"), r.get("presence_rate"),
                 r.get("avg_sentiment"), int(bool(r.get("cited_gap"))))
                for r in rows
            ])
            conn.commit()

    def save_sov_coverage(self, run_id: int, rows: List[Dict[str, Any]]):
        """Chunk X: per-engine question counts behind this run's SoV rows.

        Purpose: let an OLD report say which engines were not measured.
        Tests:   tests/test_handoff_contract.py::TestSovEngineCoverage

        serp-discover writes brand-mention rows for an engine that answered
        nothing (D-C-05/11), so `compute_sov` now drops those engines rather
        than publishing a 0% share for them. Dropping them silently would make
        "openai is absent from the table" mean either "not measured" or "no
        entities matched", so the counts are persisted beside the rows for the
        same reason `anchor_coverage` is (P2/P25).

        Idempotent per run: the run's rows are replaced, so re-running a run
        does not double them.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sov_coverage WHERE run_id = ?', (run_id,))
            cursor.executemany(
                'INSERT INTO sov_coverage (run_id, engine, questions_total, measured) '
                'VALUES (?,?,?,?)',
                # `measured` is deliberately three-valued: True, False, or NULL
                # for "the export does not say". Coercing NULL to 0 would turn
                # "we cannot tell" into "we checked and it was not measured".
                [(run_id, r.get("engine"),
                  None if r.get("questions_total") is None else int(r["questions_total"]),
                  None if r.get("measured") is None else int(bool(r["measured"])))
                 for r in (rows or [])])
            conn.commit()

    def get_sov_coverage(self, run_id: int) -> List[Dict[str, Any]]:
        """Chunk X: this run's per-engine SoV coverage, or [] if unrecorded.

        [] means the run predates the table — NOT that every engine was
        measured. The caller must not render a complete-coverage claim from it.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            try:
                rows = cursor.execute(
                    'SELECT engine, questions_total, measured FROM sov_coverage '
                    'WHERE run_id = ? ORDER BY engine', (run_id,)).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc).lower():
                    raise
                logging.warning("sov_coverage schema behind: %s", exc)
                return []
        return [{"engine": r[0], "questions_total": r[1],
                 "measured": None if r[2] is None else bool(r[2])}
                for r in rows]

    def save_risk_signals(self, run_id: int, rows: List[Dict[str, Any]], detected_at: str = None):
        """C6/SC-8: persist reputation-risk signals (pattern detections)."""
        import json as _json
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO risk_signal (run_id, domain, is_own_site, detected_at,
                    signal_type, severity, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, r.get("domain"), int(bool(r.get("is_own_site"))), detected_at,
                 r.get("signal_type"), r.get("severity"),
                 # ensure_ascii=False: this JSON is printed verbatim in the
                 # briefing's risk section, and the default escaped the en dash
                 # in the interpretation sentence to `–` in the owner's
                 # report. SQLite stores TEXT as UTF-8 either way.
                 _json.dumps(r.get("evidence", {}), ensure_ascii=False))
                for r in rows
            ])
            conn.commit()

    #: Appended to, never reordered: `save_anchor_coverage` and
    #: `get_anchor_coverage` both bind positionally against this tuple.
    _ANCHOR_COVERAGE_COUNTS = ("total", "with_anchors", "read_no_anchors",
                               "no_record", "errored", "skipped", "unknown",
                               "errored_cached", "errored_age_unknown")

    def save_anchor_coverage(self, run_id: int, coverage: Dict[str, Any],
                             detected_at: str = None):
        """SC-8.4: persist how the anchor-text fetch went for this run.

        INSERT OR REPLACE on the run_id PK, so re-saving a run is idempotent.
        Called even when coverage is empty — a run that attempted nothing and a
        run whose every fetch failed must stay distinguishable afterwards, and
        writing no row at all would collapse them.
        """
        coverage = coverage or {}
        with self.connection() as conn:
            # Column list and placeholders are derived from the one tuple, so
            # adding a count cannot leave the INSERT and the SELECT disagreeing
            # about which column holds what.
            columns = ("run_id", "detected_at", "collected_at", "fetch_status",
                       "reason") + self._ANCHOR_COVERAGE_COUNTS
            conn.cursor().execute(
                f'INSERT OR REPLACE INTO anchor_coverage ({", ".join(columns)}) '
                f'VALUES ({",".join("?" * len(columns))})',
                (run_id, detected_at, coverage.get("collected_at"),
                 coverage.get("fetch_status"), coverage.get("reason"),
                 *[int(coverage.get(k, 0) or 0) for k in self._ANCHOR_COVERAGE_COUNTS]))
            conn.commit()

    def get_anchor_coverage(self, run_id: int) -> Dict[str, Any]:
        """SC-8.4: read back a run's anchor-fetch coverage, or {} if unrecorded.

        {} means the run predates this table — not that the run was clean. The
        caller must not render a "everything was readable" claim from it.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            try:
                selected = ("collected_at", "fetch_status",
                            "reason") + self._ANCHOR_COVERAGE_COUNTS
                row = cursor.execute(
                    f'SELECT {", ".join(selected)} '
                    'FROM anchor_coverage WHERE run_id = ?', (run_id,)).fetchone()
            except sqlite3.OperationalError as exc:
                # Narrow: _create_tables() runs on every construction, so the
                # missing-table case this was written for is unreachable. Left
                # broad, it swallowed "database is locked" and "disk image is
                # malformed" as "this run predates the table" — silently, with
                # no caveat rendered and nothing saying why (P1/P2).
                message = str(exc).lower()
                # "no such column" too: a DB lagging a schema change must
                # degrade, not abort the report. Narrowing this to the table
                # case turned the next added column into a crash in the only
                # caller, which has no exception handling of its own.
                if "no such table" not in message and "no such column" not in message:
                    raise
                logging.warning("anchor_coverage schema behind: %s", exc)
                return {}
        if not row:
            return {}
        out = {"collected_at": row[0], "fetch_status": row[1], "reason": row[2]}
        out.update(dict(zip(self._ANCHOR_COVERAGE_COUNTS, row[3:])))
        return out

    def save_yt_presence(self, run_id: int, rows: List[Dict[str, Any]]):
        """SC-7-YT Phase 1: persist per-competitor YouTube presence rows.

        Spec:  sc7-yt-spec.md#3 (Phase 1 data model)
        Tests: tests/test_youtube_presence.py::test_p1_8_second_run_clean,
               ::test_p1_9_migrates_on_existing_db

        One row per (run_id, domain). channel_id is coerced to '' when absent so the
        PK (run_id, domain, channel_id) is stable for the none_found/error row. A re-save of
        the SAME run first DELETEs that run's rows, then inserts — so it is idempotent even
        when a domain's status FLIPS between saves (e.g. error→confirmed moves channel_id
        from '' to a real UC… id; a bare INSERT OR REPLACE would then leave the old '' row as
        a stale duplicate). No double-count, no stale row (P8). A new run gets a new run_id,
        so runs never collide. has_channel is stored as-is (True/False/None — None means
        unknown/error, never coerced to False; P1).
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM yt_channel_presence WHERE run_id = ?", (run_id,))
            cursor.executemany('''
                INSERT OR REPLACE INTO yt_channel_presence (
                    run_id, domain, checked_at, has_channel, channel_id, handle,
                    channel_title, channel_url, subscriber_count, video_count,
                    last_upload_date, uploads_recent, match_confidence, match_basis,
                    check_status, estimation_basis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, r["domain"], r.get("checked_at"),
                 (None if r.get("has_channel") is None else int(bool(r.get("has_channel")))),
                 r.get("channel_id") or "", r.get("handle"), r.get("channel_title"),
                 r.get("channel_url"), r.get("subscriber_count"), r.get("video_count"),
                 r.get("last_upload_date"), r.get("uploads_recent"),
                 r.get("match_confidence"), r.get("match_basis"), r.get("check_status"),
                 r.get("estimation_basis"))
                for r in rows
            ])
            conn.commit()

    def get_visibility_series(self, domain: str) -> List[Dict[str, Any]]:
        """C6/SC-8: a per-domain visibility series, one snapshot per RUN, oldest→newest.

        Each snapshot is `{run_id, ranked, attempted, rate}` where `ranked` is the
        number of the domain's keywords in the top 10 that run, `attempted` is how
        many had a measured position at all, and `rate = ranked / attempted`.

        C-C-06 / C-M-07: this used to read `market_history` grouped by
        `DATE(timestamp)`, summing every run of a calendar day, over a sample whose
        per-run maximum was `technical.max_audit_pages_per_domain` (3) because the
        snapshot was written inside the processed-page branch. So the series measured
        the tool's own sampling: two runs on one day then one the next produced
        `[6, 3]` — a "high severity visibility cliff, 50% drop" — and one page slipping
        from rank 10 to 11, or one errored scrape, produced `[3, 2]`. Reading
        `competitor_metrics` keyed by `run_id` uses every ranked keyword of the run,
        one snapshot per run, and the rate normalises for how many were measured;
        `risk_signals.cliff_min_sample` then withholds the signal when the sample is
        too small to support a step-change test at all.

        [] when the table or the data is absent — never a fabricated series.

        `position <= 10` has the same defect as every other rank comparison on
        this side: a handoff-sourced position restarts at 1 on every SERP page
        (H1 / D-C-01), so `ranked` equals `attempted` and the rate is a
        constant 1.0 for every domain in every run. The cliff detector would
        therefore find no step change even with a large sample — it is not
        merely under-sampled, its input is degenerate until serp-discover's D1
        lands. This bears on owner decision 5 (keep the signal, or remove it
        until a real data source exists): the decision was taken on the sample
        size, and this is a second and stronger reason.
        """
        try:
            with self.connection() as conn:
                rows = conn.execute('''
                    SELECT run_id,
                           SUM(CASE WHEN position IS NOT NULL AND position <= 10
                                    THEN 1 ELSE 0 END) AS ranked,
                           SUM(CASE WHEN position IS NOT NULL THEN 1 ELSE 0 END) AS attempted
                    FROM competitor_metrics
                    WHERE domain = ? AND run_id IS NOT NULL
                    GROUP BY run_id ORDER BY run_id
                ''', (domain,)).fetchall()
        except sqlite3.OperationalError:
            return []
        series: List[Dict[str, Any]] = []
        for run_id, ranked, attempted in rows:
            ranked, attempted = int(ranked or 0), int(attempted or 0)
            if not attempted:
                continue  # nothing measured that run — not a visibility of zero
            series.append({"run_id": int(run_id), "ranked": ranked,
                           "attempted": attempted, "rate": ranked / attempted})
        return series

    def get_parasite_candidates(self, run_id: int) -> List[Dict[str, Any]]:
        """C6/SC-8: per (domain, subfolder) keyword sets + the domain's core terms (from
        its OTHER subfolders) so a genuinely off-topic subfolder reads as a mismatch."""
        from urllib.parse import urlparse
        by_domain: Dict[str, Dict[str, set]] = {}
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT domain, url, keyword FROM competitor_metrics "
                "WHERE run_id = ? AND keyword IS NOT NULL AND url IS NOT NULL", (run_id,)
            ).fetchall()
        for domain, url, keyword in rows:
            path = urlparse(str(url)).path.strip("/")
            subfolder = "/" + path.split("/")[0] if path else "/"
            by_domain.setdefault(domain, {}).setdefault(subfolder, set()).add(keyword)
        candidates: List[Dict[str, Any]] = []
        for domain, subs in by_domain.items():
            for sub, kws in subs.items():
                if sub == "/":
                    continue  # the root is not a "parasite subfolder"
                core = set()
                for other_sub, other_kws in subs.items():
                    if other_sub != sub:
                        core |= other_kws
                if not core:
                    continue  # single-subfolder domain → can't judge mismatch
                candidates.append({"domain": domain, "subfolder": sub,
                                   "keywords": list(kws), "core_terms": list(core)})
        return candidates

    def save_brand_demand(self, run_id: int, rows: List[Dict[str, Any]]):
        """C3/SC-5: persist the branded-demand benchmark rows."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO brand_demand_bench (run_id, domain, brand, period,
                    branded_search_volume, branded_volume_share, branded_growth,
                    est_branded_click_share, estimation_basis, queries)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (run_id, r.get("domain"), r.get("brand"), r.get("period"),
                 r.get("branded_search_volume"), r.get("branded_volume_share"),
                 r.get("branded_growth"), r.get("est_branded_click_share"),
                 r.get("estimation_basis"), " | ".join(r.get("queries") or []) or None)
                for r in rows
            ])
            conn.commit()

    def get_positioning_inputs(self, run_id: int) -> Dict[str, Dict[str, Any]]:
        """C2/SC-4: per-competitor {moz_da, top10_count, medical_total, systems_total}.

        C-M-09, 2026-11-15 — three changes to make the two sides of the plot
        comparable:

        * `moz_da` is the competitor's **Domain** Authority
          (`competitors.domain_authority`), not `avg_da`, which is the average PAGE
          authority of the URLs sampled this run. The client's figure was always a
          Domain Authority, so "the same formula for you and competitors" was
          comparing a DA with a PA — and the client landed `authoritative` by
          construction. A domain with no stored DA gets None (excluded and
          renormalised by compute_authority), never the page figure.
        * `top10_count` counts only keywords the HANDOFF handed over
          (`keyword_source = 'handoff'`), which is the universe the client's own
          count can be restricted to as well. Before, the client's count came from
          every GSC query it ranked for (saturating the component) while a
          competitor's came from a <=10-keyword DataForSEO sample.
        * the focus totals are UNWEIGHTED counts: Tier-1 hits against Tier-2 plus
          Tier-3 hits. `SUM(systems_score)` was the x2.0/x0.5 weighted score, so the
          entropy was computed over a raw count and a weighted one (C-M-10).
          `t2_count`/`t3_count` exist per row since C3; a row without them
          contributes nothing rather than a wrong number, and `tier_counts_known`
          records that.
        """
        inputs: Dict[str, Dict[str, Any]] = {}
        with self.connection() as conn:
            cursor = conn.cursor()
            # Every domain this run audited, so this reader and
            # `get_competitor_das(run_id)` agree by construction about which
            # competitors exist (C-C-10). A domain with no tier signal lands as
            # `insufficient_data` rather than vanishing from the plot.
            for (domain,) in cursor.execute(
                    'SELECT DISTINCT domain FROM competitor_metrics WHERE run_id = ?',
                    (run_id,)).fetchall():
                inputs.setdefault(domain, {})
            # tier totals (the focus axis) — unweighted counts
            cursor.execute('''SELECT domain, SUM(medical_score),
                                     SUM(COALESCE(t2_count, 0) + COALESCE(t3_count, 0)),
                                     MIN(CASE WHEN t2_count IS NULL OR t3_count IS NULL
                                              THEN 0 ELSE 1 END)
                              FROM traffic_magnets WHERE run_id = ? GROUP BY domain''',
                           (run_id,))
            for domain, medical, systems, counts_known in cursor.fetchall():
                d = inputs.setdefault(domain, {})
                d["medical_total"] = float(medical or 0)
                d["systems_total"] = float(systems or 0)
                d["tier_counts_known"] = bool(counts_known)
            # top-10 ranking count over the SHARED (handoff) keyword universe.
            #
            # NOT a count of genuine top-10 rankings while the handoff's ranks
            # are page-relative: `position` here IS the handoff rank, which
            # restarts at 1 on every SERP page (H1 / D-C-01), so `mp <= 10`
            # admits every handoff keyword. C-M-09 fixed the UNIVERSE asymmetry
            # (both sides now count over the handoff's keywords); it did not
            # fix the rank semantics, which inflate the authority axis by
            # 21-27 points on realistic inputs — enough to cross
            # `positioning.authority_threshold`. The briefing says so in the
            # Barbell section, driven by `handoff.absolute_rank_versions`.
            cursor.execute('''SELECT domain, COUNT(*) FROM (
                                SELECT domain, keyword, MIN(position) AS mp
                                FROM competitor_metrics
                                WHERE run_id = ? AND keyword IS NOT NULL
                                  AND position IS NOT NULL
                                  AND keyword_source = 'handoff'
                                GROUP BY domain, keyword)
                              WHERE mp <= 10 GROUP BY domain''', (run_id,))
            for domain, count in cursor.fetchall():
                inputs.setdefault(domain, {})["top10_count"] = int(count)
            # Moz DOMAIN authority per domain (the authority axis, shared with the
            # client). Only attach it to domains actually audited this run.
            cursor.execute('SELECT domain, domain_authority FROM competitors '
                           'WHERE domain_authority IS NOT NULL')
            for domain, domain_authority in cursor.fetchall():
                if domain in inputs:
                    inputs[domain]["moz_da"] = int(domain_authority)
                    inputs[domain]["authority_basis"] = "moz_domain_authority"
            for domain, values in inputs.items():
                values.setdefault("authority_basis", "unmeasured")
                values.setdefault("top10_universe", "handoff keywords")
                # A stable shape: 0 means "no handoff keyword in the top 10", which
                # compute_authority excludes and renormalises over the DA alone.
                values.setdefault("top10_count", 0)
        return inputs

    def get_competitor_positions(self, run_id: int) -> Dict[str, Dict[str, int]]:
        """C4/SC-6: {keyword: {domain: best (lowest) position}} from competitor_metrics."""
        positions: Dict[str, Dict[str, int]] = {}
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT keyword, domain, MIN(position) FROM competitor_metrics
                WHERE run_id = ? AND keyword IS NOT NULL AND position IS NOT NULL
                GROUP BY keyword, domain
            ''', (run_id,))
            for keyword, domain, position in cursor.fetchall():
                positions.setdefault(keyword, {})[domain] = int(position)
        return positions

    def get_best_rival_etv(self, run_id: int) -> Dict[str, float]:
        """C4/SC-6: {keyword: the best-ranking rival's DataForSEO ETV} for cell rollups.

        C-M-20: this was called `get_keyword_volumes` and its output was rendered as
        "Volume by cell (est. traffic)" and stored in a column called
        `keyword_volume` — three names for a figure that is neither a search volume
        nor the client's traffic. It is `MAX(competitor_metrics.traffic)`: the highest
        DataForSEO estimated monthly visits any audited rival has for that keyword at
        its position.
        """
        volumes: Dict[str, float] = {}
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT keyword, MAX(traffic) FROM competitor_metrics
                WHERE run_id = ? AND keyword IS NOT NULL
                GROUP BY keyword
            ''', (run_id,))
            for keyword, traffic in cursor.fetchall():
                volumes[keyword] = float(traffic or 0.0)
        return volumes

    def get_competitor_das(self, run_id: int) -> Dict[str, int]:
        """C4/SC-6: {domain: avg_da} for the domains THIS RUN audited (feasibility input).

        `run_id` is required (C-C-10). `competitors` is domain-keyed and overwritten in
        place, so the unscoped read this replaces made the *Competitor Feasibility*
        table list every domain ever stored — competitors that are not in this run's
        handoff at all, with DA values of unknown age and no `last_crawled_at`
        rendered — while `get_positioning_inputs` right beside it was already
        run-scoped. The two read the same column and disagreed, so the parameter is
        mandatory rather than optional: an unscoped caller is the bug (P22).

        Returns {} when this run has no stored DA — feasibility then degrades
        gracefully rather than borrowing another run's numbers.
        """
        das: Dict[str, int] = {}
        with self.connection() as conn:
            # C-M-09: the DOMAIN authority. The feasibility table compares "your DA"
            # with "each competitor's DA" and the competitor side was the average
            # PAGE authority of its sampled URLs. A competitor with no measured DA is
            # ABSENT from the map, so feasibility withholds a verdict for it rather
            # than comparing against a page figure.
            rows = conn.execute(
                'SELECT c.domain, c.domain_authority FROM competitors c '
                'WHERE c.domain_authority IS NOT NULL AND c.domain IN '
                '(SELECT DISTINCT domain FROM competitor_metrics WHERE run_id = ?)',
                (run_id,)).fetchall()
            for domain, domain_authority in rows:
                das[domain] = int(domain_authority)
        return das

    def save_semantic_audit(self, url: str, medical_score: int, systems_score: float,
                            run_id: int, label: str = "Standard",
                            t2_count: int = None, t3_count: int = None,
                            scoring_window_words: int = None):
        """Persist one page's vocabulary scores AND the tier counts behind them.

        C-C-08 / C-M-05: the counts were thrown away and the 7-day cache path then
        reconstructed them from the weighted score — `t3 = systems_score / 2.0 if
        systems_score >= 2.0`. So a page with four generic Tier-2 words (score 2.0)
        came back from cache as "t3 = 1" and its domain was re-labelled *Direct
        Systemic* on the re-run, overwriting the right label with the wrong one.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO semantic_audits (run_id, url, medical_score, systems_score, systemic_label, t2_count, t3_count, scoring_window_words)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (run_id, url, medical_score, systems_score, label, t2_count, t3_count,
                  scoring_window_words))
            conn.commit()

    def save_competitor_history(self, run_id: int, url: str, position: int,
                                pa: float, traffic: float):
        """
        Revision 4: Store snapshot data and calculate drift.
        Drift = Current_PA - Previous_PA.

        C-C-03: `pa` is nullable and NULL means "Moz had no figure for this URL this
        run" — a Moz 401/429/5xx, or a URL Moz has no record for. The drift is then
        NULL as well, not `0 - 35`: the previous code stored a missing PA as 0 and so
        reported a -35 authority collapse for every page of every affected domain,
        with the mirror-image +35 on the next working run.
        """
        pa_value = None if pa is None else float(pa)
        with self.connection() as conn:
            cursor = conn.cursor()

            # Find the previous MEASURED PA for this URL (a NULL snapshot is not a
            # comparison point).
            cursor.execute('''
                SELECT pa FROM competitor_history
                WHERE url = ? AND run_id < ? AND pa IS NOT NULL
                ORDER BY run_id DESC LIMIT 1
            ''', (url, run_id))
            prev_row = cursor.fetchone()
            prev_pa = prev_row[0] if prev_row else None
            drift = (None if pa_value is None or prev_pa is None
                     else pa_value - float(prev_pa))

            cursor.execute('''
                INSERT INTO competitor_history (run_id, url, position, pa, traffic_value, drift)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (run_id, url, position, pa_value, traffic, drift))
            conn.commit()

    def get_pa_coverage(self, run_id: int) -> Tuple[int, int]:
        """(URLs with a measured Page Authority, URLs attempted) for a run.

        "N of M URLs had PA" is persisted rather than printed and forgotten: it is the
        NULL-vs-value distinction in `competitor_history.pa`, so an old run can still
        say whether its authority figures were measured (P2).
        """
        with self.connection() as conn:
            row = conn.execute(
                'SELECT COUNT(pa), COUNT(*) FROM competitor_history WHERE run_id = ?',
                (run_id,)).fetchone()
        return (int(row[0] or 0), int(row[1] or 0))

    def tag_competitor_position(self, domain: str, medical_score: int, systems_t2: int,
                                systems_t3: int, traffic: float,
                                tier_counts_complete: bool = True):
        """
        Revision 3: Categorize competitor for 'Battle Strategy'.
        Volume Scaler: High Traffic + High Medical Score.
        Generalist: High Tier 2 Score.
        Direct Systemic: Presence of Tier 3 terms.

        `tier_counts_complete` is False when any of this domain's audited pages came
        from the semantic cache without stored tier counts (C-C-08). The Tier-2 and
        Tier-3 sums are then a partial count, and the two labels that rest on them —
        *Direct Systemic* and *Generalist* — are withheld rather than decided on
        whatever fraction of the domain happened to be re-scraped. They return on the
        next run that scrapes the domain fresh. (The thresholds themselves are still
        hard-coded here; that is C-C-15 / C-M-18, chunk C4.)
        """
        # C-C-15: the three thresholds are config, not Python literals. CLAUDE.md:
        # "editorial content ... belongs in config". They also had to move because
        # decision 3 shrank the Tier-1 vocabulary, which changes what `medical_score`
        # of 15 means — a number buried in code cannot be re-set with the vocabulary.
        thresholds = position_thresholds()
        min_traffic = thresholds["volume_scaler_min_traffic"]
        min_medical = thresholds["volume_scaler_min_medical"]
        min_t2 = thresholds["generalist_min_t2"]

        market_position = "Unknown"
        strategy = "General observation"
        is_volume_scaler = traffic > min_traffic and medical_score > min_medical

        if not tier_counts_complete and not is_volume_scaler:
            market_position = "Not classified (incomplete tier counts)"
            strategy = ("Some pages were served from the 7-day semantic cache without "
                        "stored tier counts; re-run outside the cache window to classify.")
        elif is_volume_scaler:
            market_position = "Volume Scaler"
            strategy = "Do not compete on volume; compete on clinical authority."
        elif systems_t3 > 0:
            market_position = "Direct Systemic"
            strategy = "Use 'Functional Facts' to provide a more rigorous Bowen alternative."
        elif systems_t2 > min_t2:
            market_position = "Generalist"
            strategy = "Target their lack of Tier 3 depth."

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO competitor_metadata (domain, market_position, strategy, last_updated)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(domain) DO UPDATE SET
                    market_position = excluded.market_position,
                    strategy = excluded.strategy,
                    last_updated = CURRENT_TIMESTAMP
            ''', (domain, market_position, strategy))
            conn.commit()

    def get_competitor_metadata(self, domain: str) -> Dict[str, str]:
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT market_position, strategy FROM competitor_metadata WHERE domain = ?', (domain,))
            row = cursor.fetchone()
            if row:
                return {"market_position": row[0], "strategy": row[1]}
            return {"market_position": "N/A", "strategy": "N/A"}

    def get_latest_run_id(self) -> int:
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT MAX(id) FROM runs')
            result = cursor.fetchone()
            return result[0] if result[0] else None

    def get_volatility_alerts(self, run_id: int) -> List[Dict[str, Any]]:
        """
        Flag a competitor whose average position moved by at least
        `risk_signals.volatility_min_shift` places since the previous run.

        C-M-18: the threshold was the literal 3, while `risk_signals.
        volatility_high_shift` (6) sat in config and was read only for the severity
        band — so the knob the owner could see did not control whether an alert
        fired. Both now live in config, and the trigger is the one being read here.
        """
        volatility_min_shift = float((load_shared_config().get("risk_signals", {}) or {})
                                     .get("volatility_min_shift",
                                          DEFAULT_VOLATILITY_MIN_SHIFT))
        with self.connection() as conn:
            cursor = conn.cursor()
            # Get previous run_id
            cursor.execute('SELECT id FROM runs WHERE id < ? ORDER BY id DESC LIMIT 1', (run_id,))
            prev_run = cursor.fetchone()
            if not prev_run:
                return []
            prev_run_id = prev_run[0]

            cursor.execute('''
                SELECT curr.domain, AVG(curr.position) as curr_avg, AVG(prev.position) as prev_avg
                FROM competitor_metrics curr
                JOIN competitor_metrics prev ON curr.domain = prev.domain AND curr.keyword = prev.keyword
                WHERE curr.run_id = ? AND prev.run_id = ?
                GROUP BY curr.domain
                HAVING ABS(AVG(curr.position) - AVG(prev.position)) >= ?
            ''', (run_id, prev_run_id, volatility_min_shift))
            
            alerts = []
            for row in cursor.fetchall():
                alerts.append({
                    "domain": row[0],
                    "shift": round(row[1] - row[2], 2),
                    "type": "Volatility Alert"
                })
            return alerts

    def count_audited_pages(self, run_id: int) -> int:
        """Every page this run audited, magnet or not — the M in "N of M"."""
        with self.connection() as conn:
            row = conn.execute(
                'SELECT COUNT(*) FROM traffic_magnets WHERE run_id = ?', (run_id,)
            ).fetchone()
        return int(row[0] or 0)

    def keyword_source_counts(self, run_id: int) -> Dict[str, int]:
        """{keyword_source: distinct keywords} for a run — the report's provenance line.

        Rows written before the column existed group under 'unlabelled', which is
        what they are; they are not folded into 'handoff'.
        """
        counts: Dict[str, int] = {}
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT COALESCE(keyword_source, 'unlabelled'), COUNT(DISTINCT keyword) "
                "FROM competitor_metrics WHERE run_id = ? AND keyword IS NOT NULL "
                "GROUP BY 1", (run_id,)).fetchall()
        for source, count in rows:
            counts[str(source)] = int(count or 0)
        return counts

    def identify_strategic_openings(self, run_id: int, min_medical: int = None,
                                    max_position: int = None,
                                    limit: int = 5) -> List[Dict[str, Any]]:
        """The reframe targets: Systemic Vacuums, highest estimated traffic first.

        A row qualifies only when it is a magnet — handoff rank <= `max_position`,
        `medical_score >= min_medical`, and its keyword passed the C-M-02 relevance
        test at ingest — AND it shows no systemic language (systems_score 0 or the
        Surface-Level label).

        Before this gate existed the only condition was "systems_score = 0 OR
        Surface-Level", ordered by est_traffic alone, so `rcav.org` (medical 0,
        systems 0) was named a primary target for content reframing and gpt-4o was
        spent reframing the Archdiocese of Vancouver (C-M-02 / C-M-15). The floor
        and ceiling default to shared_config `technical.vacuum_min_medical` /
        `technical.magnet_max_position`.
        """
        if min_medical is None or max_position is None:
            config_min, config_max = magnet_thresholds()
            min_medical = config_min if min_medical is None else min_medical
            max_position = config_max if max_position is None else max_position
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                magnet_sql(vacuum_only=True,
                           columns="url, primary_keyword, est_traffic, medical_score, "
                                   "systemic_label, keyword_source, rank",
                           limit=limit),
                (run_id, min_medical, max_position))

            openings = []
            for row in cursor.fetchall():
                openings.append({
                    "url": row[0],
                    "keyword": row[1],
                    "traffic": row[2],
                    "medical_score": row[3],
                    "systemic_label": row[4],
                    "keyword_source": row[5],
                    "rank": row[6],
                })
            return openings

    def update_traffic_magnet_scores(self, run_id: int, url: str, medical: int, systems: int):
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE traffic_magnets
                SET medical_score = ?, systems_score = ?
                WHERE run_id = ? AND url = ?
            ''', (medical, systems, run_id, url))
            
            # Also update legacy semantic_audits table if applicable
            cursor.execute('''
                UPDATE semantic_audits
                SET medical_score = ?, systems_score = ?
                WHERE run_id = ? AND url = ?
            ''', (medical, systems, run_id, url))
            
            conn.commit()

    def get_run_urls(self, run_id: int) -> List[str]:
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT url FROM traffic_magnets WHERE run_id = ?', (run_id,))
            return [row[0] for row in cursor.fetchall()]

    def was_audited_recently(self, url: str, days: int = 7) -> Dict[str, Any]:
        """
        Optimization: Check if this URL has been audited in the last X days to avoid re-scraping.

        Returns the tier counts too (C-C-08). `t2_count` / `t3_count` are None for a
        row written before they were persisted: the caller must then treat the counts
        as UNKNOWN rather than estimate them from the weighted score, which is the bug
        this return shape exists to remove (P22 — the old shape lacked the fields its
        caller needed, so the caller invented them).
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT medical_score, systems_score, systemic_label, t2_count, t3_count,
                       scoring_window_words
                FROM semantic_audits 
                WHERE url = ? AND timestamp > datetime('now', ?)
                ORDER BY timestamp DESC LIMIT 1
            ''', (url, f'-{days} days'))
            row = cursor.fetchone()
            if row:
                return {
                    "medical_score": row[0],
                    "systems_score": row[1],
                    "systemic_label": row[2],
                    "t2_count": row[3],
                    "t3_count": row[4],
                    "scoring_window_words": row[5],
                }
            return None
