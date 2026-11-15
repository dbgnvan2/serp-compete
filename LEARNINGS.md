# LEARNINGS — serp-compete failure-pattern playbook

Purpose: stop this project from repeating its own mistakes. Every bug fix becomes a
reusable check, and new code is reviewed against them. The prime directive: **make
failure loud and make negatives provable** — a transient error must never be recorded
as a permanent fact, and a partial failure must never drop data silently.

## Pattern catalogue

This repo does **not** fork the pattern list. The canonical catalogue is
`~/.claude/standards/learnings.md` (**P1–P22**, imported by the global `~/.claude/CLAUDE.md`).
Reference patterns by their `Pn` id. Repo-specific rules also live in `./CLAUDE.md`.
Add a repo-specific pattern here only if it is genuinely not covered by P1–P22.

## Review checklist (run before merging data-path / fetch / scoring / report changes)

Run the numbered checklist in `~/.claude/standards/learnings.md` (items 1–23, one per
pattern). The high-frequency ones in this codebase:

1. External calls hardened as a class — timeout + retry + backoff on every sibling (P5).
2. Partial failure surfaced ("N of M"), never a silent `None`/`[]` drop (P2).
3. Transient (429/timeout) → retryable state, never a permanent negative (P1).
4. Status/flag verified against the artifact it claims exists (P6).
5. Magic year/date/threshold/topic-word → config, not code; editorial vocab in YAML/JSON (P4).
6. Scoring/matching has an adversarial "looks-right-but-wrong scores lower" test (P7).
7. Dirty-state / second-run test for anything reading persisted state (P8).
8. Built capability has a real caller on the run path — grep the call *site* (P21).
9. Return-type/contract change: grep every call site for checks against the old shape (P22).
10. Import guards don't swallow genuine errors; dual-mode fallbacks still fail loud (P2/P14).

## Open risks (found by review, not yet bitten)

- **C-C-04 — the Moz endpoint and response key are assumed, not verified.** This tool calls
  `api.moz.com/v2/url_metrics` and now reads either `url` or `page` (scheme-insensitively),
  while serp-discover has migrated to JSON-RPC `api.moz.com/jsonrpc` and its real-response
  fixture models the target as `page`. Unverifiable without a live call, so the next real run
  must check the per-domain line `Moz returned N metrics for M URL(s).` — N of 0 against a
  non-zero M means the shape or the endpoint is wrong and every Page Authority will be NULL.
  `docs/TEST_RUN_CHECKLIST.md` §1b carries the check. Then align the client with
  serp-discover's.
- **`visibility_cliff` is kept but will usually be withheld.** With the handoff universe a run
  samples well under `risk_signals.cliff_min_sample` (10) keywords per domain, so the signal
  rarely has a large enough sample to compute. Whether to keep it at all until a data source
  supplies that many (DataForSEO `domain_rank_overview`, or the full `ranked_keywords` count)
  is the owner's open decision 5 in the 2026-11-04 review plan.

## Fix log

Newest first. Format:
**Issue → Root cause (Pn) → What would have caught it → Fix → Rule.**

**The axis the whole tool is built on counted the client's own vocabulary as the opposing model, and counted it badly (C-M-08, C-M-19, C-C-15).**
- **Root cause (P4 / P7):** two independent faults in one number. (1) The editorial list: Tier 1
  held "therapy", "patient", "patients", "condition" and "trauma", so a Bowen practice's own copy
  scored as medical model and every "couples therapy" query was Tier 1 — of 374 real competitor
  keywords in this repo, 68 read as Tier 1 and "therapy" alone accounted for 67. (2) The matching
  mechanics: raw `token.text in set` with no lemmas (so "triangle" scored 0 while "triangles"
  scored 3, and "treatments" scored 0 against the entry "treatment"); `str.count` for phrases but
  only `if " " in phrase`, so the configured Tier-2 term `self-regulation` could **never** match;
  nested phrases counted twice across tiers ("differentiation of self" scored Tier 3 **and** Tier
  2); the scored text was the outline *prepended* to the body, counting every h1-h3 twice, with
  `<header>` and div menus never stripped; and the score was an absolute count over a window of up
  to 500 words, so five medical words meant the same thing in a five-word page and an 805-word one.
- **What would have caught it:** adversarial vocabulary tests of the kind rule 6 asks for —
  "looks-right-but-wrong scores lower". The suite had none for this module: three tests asserted
  the happy path on a single sentence. A test that scored the CLIENT's own published copy and
  asserted it was not medical model would have failed from the first day, and one that scored a
  term the config itself contains (`self-regulation`) would have shown it was unreachable.
- **Fix:** Tier 1 is diagnostic vocabulary only, in **both** vocabulary sources (`shared_config
  → clinical` shadows `clinical_dictionary.json`, so changing only the file the decision named
  would have done nothing), with the removed words recorded under `neutral_clinical` so they
  cannot drift back silently. One spaCy `PhraseMatcher` over LEMMAS for all three tiers, longest
  match first, each span counted once, with an exact-surface rule so a lemma collision
  ("triangles" vs "triangling") cannot earn the stronger tier. `<header>` and menu/nav elements
  stripped; the body counted once; every score carries `scoring_window_words` and the report shows
  `medical_per_1000`; Surface-Level is a density with a minimum hit count under it. And the
  thresholds moved with the vocabulary: `vacuum_min_medical` 10 → 6 and
  `volume_scaler_min_medical` 15 → 9, set from measured before/after counts on the real corpora
  in the repo and labelled editorial and uncalibrated.
- **Rule:** when a scoring vocabulary changes, every threshold measured in its units changes
  meaning — grep for the thresholds before shipping the list, or the detectors go quiet and look
  like "nothing found". And a dictionary that exists in two places has one of them for show: find
  which the code actually reads before editing either.

**The briefing's own numbers were artefacts of the queries that produced them (C-C-02, C-C-07, C-C-08, C-C-10, C-C-16, C-M-04, C-M-05, C-M-20).**
- **Root cause (P2 / P7 / P8 / P22):** four separate shapes of the same mistake — a SQL or
  display decision changing what a number MEANS, with nothing in the artefact to reveal it.
  (1) `total_keywords` was `SUM(CASE WHEN m.keyword IS NOT NULL …)` across a LEFT JOIN to
  `traffic_magnets` with no URL condition — a cross product, so the figure was keywords ×
  audited pages: 30 for a domain with 10 keywords and 3 pages, and `competitor_mining` sorted
  competitors by it. (2) `LIMIT 30` / `LIMIT 20` sat in the SQL, so the markdown and the Excel
  sheet were truncated identically and neither said so — `ORDER BY url LIMIT 30` meant the EEAT
  and GEO sections showed the alphabetically-first ten of fifteen competitors, and the vacuum
  list was a subset of a 20-row magnet set chosen by an `est_traffic DESC` sort with heavy ties.
  (3) `was_audited_recently` did not return the tier counts its caller needed, so the cache
  path rebuilt them from the weighted score (`t3 = systems_score / 2.0 if >= 2.0`); a page with
  four generic Tier-2 words came back as "one Tier-3 term" and its domain was re-labelled
  *Direct Systemic* on a re-run of unchanged content, overwriting the right label. The same
  column fed `systemic_depth`, whose "High" band was `systems_score > 0` — one occurrence of
  "relationship" — and whose "Medical" band compared a RAW Tier-1 count with a ×2.0/×0.5
  weighted score. (4) `get_competitor_das()` had no run scope while `get_positioning_inputs`
  beside it did, so two adjacent sections reading the same column disagreed about which
  competitors exist. Plus the labels: `keyword_volume` was `MAX(competitor_metrics.traffic)`,
  rendered as "Volume by cell (est. traffic)"; the volatility `shift` had no stated sign
  convention in a metric where bigger is worse; and the briefing never named the handoff it
  read, while the GUI's selection only reached `main.py` when "Copy handoff to root" happened
  to be ticked.
- **What would have caught it:** a test that renders the real report from a seeded database and
  reads the OUTPUT — the numbers, the sheets, the row counts — rather than asserting that a
  function returned something. Every one of these passed a unit test of its own component.
  Specifically: seed 10 keywords and 3 magnet rows and assert 10; seed 45 rows and assert 45
  in the sheet; and the P8 test the finding asked for — run the audit twice and assert
  `market_position` is identical when the second run is cache-served
  (`test_cc08_market_position_is_stable_across_a_cached_rerun`).
- **Fix:** magnet aggregates come from a per-domain subquery and the count is
  `COUNT(DISTINCT m.keyword)`, renamed `sampled_keywords` (the sample, not the competitor's
  keyword count) beside a `pages_audited` column. The `LIMIT`s are gone from the SQL: the Excel
  sheets carry every row, the markdown caps for display via `reporting.*` and prints "Showing
  the first N of M". `t2_count` / `t3_count` are persisted on both `semantic_audits` and the
  per-run `traffic_magnets` row (a cache hit writes no new audit row, so the run's own table
  has to carry them), the estimate is deleted, `systemic_depth` reads the counts, and a domain
  whose counts are incomplete has its classification WITHHELD rather than guessed.
  `get_competitor_das(run_id)` is run-scoped with `run_id` **required**, so no caller can
  reintroduce the stale set. `best_rival_etv` replaces `keyword_volume` through the row, the
  column, the report and the sheet; the sign convention is stated; `--handoff` carries the
  selected file from the GUI and `run_audit.sh` into `main.py` and the briefing header names
  it; `orchestrator.reports_dir` is honoured.
- **Rule:** a number in a report is only as good as the query that made it — so test the
  rendered artefact, not the function. Two specific smells to grep for: an aggregate over a
  join whose ON clause does not match the aggregate's grain (that is a cross product wearing a
  SUM), and a `LIMIT` inside a query whose output is also an export. And when a stored figure
  is not what its name says, rename it everywhere in one commit; a column, a row key, a report
  label and a doc that disagree are four chances to mislead.

**Null was zero in every longitudinal path, so outages and sampling noise rendered as measured collapses (C-C-03, C-C-05, C-C-06, C-C-09, C-C-11, C-C-12, C-C-18, C-M-06, C-M-07).**
- **Root cause (P1 / P2 / P5):** the same substitution in five places. A Moz failure or a URL
  Moz had no record for became `pa = 0` (`moz_metrics_map.get(url, 0)`), so every page of every
  affected domain reported a ~-35 authority collapse — and the next working run reported +35;
  `avg_pa = 0` also silently disabled the "PA > 50" filter and wrote 0 as the competitor's
  measured authority. A per-brand search-volume failure became `0` volume at a `0.00%` share
  labelled `volume_estimated`. An errored scrape was omitted from the visibility series rather
  than recorded, so the series fell and read as the competitor losing visibility. A 429 on the
  client's own page was stored as a 0/0 semantic audit and served from the 7-day cache, which
  suppressed the Clinical Mismatch check as a confident "no mismatches" (the `content !=
  "BLOCK"` test had been dead since the ScrapedPage refactor — P22). And `get_search_volume`
  was hardened with timeout + retry + backoff while its siblings `get_relevant_pages` and
  `get_url_metrics` had neither, so a DataForSEO 429 dropped a competitor with no trace in the
  artefact and a `ConnectionError` aborted the run after `create_run` had written its row.
  Two further faults compounded them: the drift detector was not scoped to the run (so a
  competitor skipped this run kept its last drop in every later briefing, forever) and had no
  threshold (38 → 37 produced "Strike this page now"), and the visibility series was grouped by
  `DATE(timestamp)` over a ≤3-row sample, so a same-day re-run was a "50% cliff".
- **What would have caught it:** a second-run test where the provider fails — for each of them.
  The suite had second-run tests, but every one fed the *success* path; and two of the asserts
  passed only because an earlier run of the same suite had left rows in the repo's own database
  (`test_analyze_gaps_logic` wrote `semantic_audits` with run_id 0 and then read its own
  7-day cache), so they would have failed on a blank machine. Dirty-state tests have to seed
  the dirt themselves and own their database (P8).
- **Fix:** unknown is NULL end to end — `competitor_history.pa`, `market_history.da`,
  `market_history.rank`, `branded_search_volume` — and every consumer skips rather than
  substitutes. `api_clients.post_with_retries` hardens all three external POSTs as a class
  (429/5xx retried, other 4xx terminal, never raising out of `get_relevant_pages`);
  `page_authority_map` omits URLs Moz had no record for instead of defaulting them to 0;
  `get_search_volume` returns `None` for "could not answer" and a mapping only when it
  answered with rows. One run-scoped, thresholded drift detector (`risk_signals.pa_drop_min`)
  replaces the two. The visibility series is per `run_id` from `competitor_metrics`, normalised
  by how many keywords were measured, with a `risk_signals.cliff_min_sample` floor below which
  the signal is withheld and the briefing says so. Coverage travels into the artefact: *Run
  coverage* names the skipped domains with reasons, the unmeasured authorities, and "N of M
  URLs had PA".
- **Rule:** `.get(key, 0)` on an external result is a bug the type system will not catch —
  default to `None` and make the consumer decide. A fetch helper hardened in one method must be
  extracted and applied to its siblings in the same commit, or the next sibling is the next
  outage. And when a detector's sample is too small to support its own test, withholding the
  signal with a stated reason is the answer; a number computed on three rows is not a
  measurement.

**The audit never read the handoff: `main.py` grouped Tool 1's targets by domain and then audited each domain's DataForSEO top-10 instead (C-M-01, and C-M-02 / C-M-15 / C-M-03 / C-C-01 / C-C-13 downstream).**
- **Root cause (P21 / P6):** `for domain, group_targets in domain_groups.items():` never read
  `group_targets`; the loop body called `dfs_client.get_relevant_pages(domain)`
  (`ranked_keywords/live`, Canada, API default order, `limit 10`, no position filter) and
  audited whatever came back. A built-and-ingested capability — the handoff targets, validated
  against `handoff_schema.json` on the way in — had no consumer, while the docs
  (`FEATURE_GUIDE` §2.1: "nothing is invented") described the consumer that did not exist.
  Everything downstream inherited the wrong universe: run_11's "Traffic Magnets" were
  `archdiocese of vancouver`, `airport heights medical clinic` (a St John's NL page) and
  `555 homer street`, and gpt-4o was spent reframing the Archdiocese of Vancouver. Three
  more findings were the same shape: `derive_brand_name("www.x.com")` → `"www"` (the
  `normalise_domain` helper existed in the same file and was not applied — P7), the handoff's
  `client_brand_names` dropped while the code read a `client.brand_names` key that does not
  exist in `shared_config.json` (P4/P21), and the vacuum query having no language, position or
  relevance condition at all (P7).
- **What would have caught it:** an end-to-end `run_audit` test with every external call faked,
  asserting that the handoff's URL and keyword are what get audited
  (`Serp-compete/tests/test_main_audit_universe.py`). Nothing short of that would: each unit
  on its own was correct, and the suite was 441-green with the universe wrong. A unit test of
  the ingestion would have passed too — the ingestion worked; nobody consumed it.
- **Fix:** `src/audit_universe.py` builds the (url, keyword) rows a domain may be audited on —
  handoff first, `ranked_keywords` admitted only as enrichment that is in the handoff set or
  carries a clinical term and never carries the competitor's brand token, with every drop
  counted. Provenance (`keyword_source`), the relevance verdict (`keyword_relevant`) and the
  handoff `rank` are persisted (ALTER beside CREATE) and printed. One predicate
  (`database.magnet_sql`) now defines magnet / vacuum / reframe target, so the vacuum list and
  the reframe list cannot disagree. `normalise_domain` runs before every brand derivation;
  branded demand queries the display brand with an ambiguous-brand gate; a reframe at medical 0
  states the absence and spends no tokens.
- **Rule:** when a module ingests and validates an input, grep for the *consumer* of that
  input, not just the producer (P21 applies to data as well as to functions) — and when a doc
  states what a tool audits, that sentence is a test case. A loop variable that is never read
  is a missing consumer, so treat an unused binding in a run path as a finding, not lint.

**Comparison-layer feature imports sat outside their per-feature guards → one bad import aborted all five.**
- **Root cause (P13):** in `run_comparison_features` the five `from src.… import …` compute-imports were at
  the top of the function, *outside* each feature's `try/except`, while the docstring promised "Never raises."
  A single module failing to import would raise past all five and error the unguarded caller (`main.py`).
  Neutralised in prod only because `main.py` eagerly loads the heavy deps — a latent, not firing, bug.
- **What would have caught it:** a test forcing one feature's module import to fail and asserting the others
  still persist (`tests/test_comparison_features.py::test_p13_one_feature_import_failure_degrades_only_that_feature`).
- **Fix:** moved each feature's compute-import INSIDE its own guard; the one shared import (`derive_brand_name`)
  was made dependency-free (next entry) so its remaining top-level import can't trip the failure mode.
- **Rule:** a guard must wrap *every* step whose failure it is meant to contain — including the import. Put
  shared imports behind a dependency-free helper; keep feature-specific imports inside the feature's guard.

**`derive_brand_name` stripped suffixes case-sensitively and hardcoded its vocab.**
- **Root cause (P7 / P4):** the strip ran on the raw domain stem *before* `.lower()`, so `JerichoCounselling.com`
  kept its suffix and derived `jerichocounselling` instead of `jericho` — a mis-derived brand silently
  mis-classifies C1 SoV / C3 branded-demand entities. The suffix list was editorial vocab hardcoded in Python.
- **What would have caught it:** an adversarial mixed-case test (`tests/test_brand_utils.py::test_case_insensitive_suffix_strip`).
- **Fix:** extracted the function to dependency-free `src/brand_utils.py`, lower-cased before stripping, and
  moved the vocab to `shared_config.json → brand.name_suffixes` (the module default mirrors it as a standalone
  fallback for `competitor_mining.py`, which runs without config).
- **Rule:** normalize case before matching; editorial vocab (suffixes, trigger words) belongs in config, not
  logic (rule #9).

**Offline `competitor_mining.py` silently disabled C1 (AI Share-of-Voice) + C3 (Branded-Demand).**
- **Root cause (P21 / P2):** the module used bare `from api_clients import …` / `from reframe_engine import …`
  (repo canonical is `from src.…`), so it was un-importable as `src.competitor_mining`. The run path
  (`comparison_features.py`) imports `derive_brand_name` from it; the guarded per-feature `try/except`
  swallowed the resulting `ModuleNotFoundError`, so C1/C3 produced nothing with no visible error.
- **What would have caught it:** an assembly-level smoke test that imports the real run path and asserts
  each feature persists (`tests/test_comparison_features.py`) — it did, once the assembly was extracted.
- **Fix:** dual-mode imports (`try: from src.… except ImportError: from …`) so the module resolves both as a
  submodule and as the standalone `python3 src/competitor_mining.py`; removed the temporary inlined
  `_derive_brand_name` so brand derivation has one canonical source; `tests/test_competitor_mining.py` locks
  both dual-mode branches + the shared function (incl. a None-guard that was a latent crash).
- **Rule:** a standalone script that is *also* imported must use package-qualified imports (`from src.x`); a
  `try/except ImportError` guard around a feature can hide an entire disabled capability — grep the call
  *site* (P21) **and** assert the import in a test, don't trust that the class merely exists.
