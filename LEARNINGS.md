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
- **Five capabilities exist in `src/` that nothing on the run path reaches** (swept 2026-11-16,
  by parsing every `def` in `src/` and counting references outside its own definition). None is
  a bug today; each is a thing a reader of the code or the docs would reasonably believe runs.
  - `third_party_crawlers.py` (7 functions: Ahrefs/Moz backlinks, internal links, link
    velocity, anchor text, top linking pages) — imported by nothing, and its own docstring says
    its tests are "to be implemented". This is **intentional**: `IMPLEMENTATION_PLAN_v3.md`
    Task 11 created it as a "skeleton for future". But that plan's coverage table claimed
    `test_third_party_crawlers.py` ✅ Done, and no such file exists; corrected 2026-11-16.
  - `step_dag.py` (`StepDAG`, with cycle detection and an execution-order solver) — imported
    only by its own test. It reads `shared_config.json → step_dag`, and chunk C4c **deleted
    that key** as having no reader: strictly the reader existed, but nothing reaches it, and
    `test_config_provenance.py` now asserts the key is gone. So the module can only ever be fed
    by a test fixture. Either wire it into the orchestrator (a feature: the orchestrator
    currently sequences steps directly) or delete it with its test and the spec mention. Not a
    cleanup decision — it is a choice about whether step ordering should be configurable.
  - `api_clients.DataForSEOClient.get_serp_data` — a `serp/google/organic/live/advanced` call
    whose docstring says "To get People Also Ask (PAA) data". Unreferenced. It matters because
    FEATURE_GUIDE §6.1's PAA promise was dropped in C1 on the grounds that the handoff carries
    no PAA, and this is the second way to restore it — at one billed call per keyword, and only
    after hardening: it posts with a bare `requests.post`, predating `post_with_retries`, so
    wiring it as-is reintroduces C-C-12. Recorded in `docs/handoff_contract.md` §4.
  - `database.get_run_urls` and `database.update_traffic_magnet_scores` — unreferenced by `src/`
    **and** by the tests. The second one writes to `semantic_audits` under the comment "legacy
    table if applicable", which is doubly stale: that table is the live scoring cache (see the
    persistence-map entry below), and the method updates only two of the six score columns
    `traffic_magnets` now carries, so calling it today would leave `t2_count`,
    `t3_count`, `scoring_window_words` and `keyword_source` describing a different scoring run.
    If anything is deleted outright, these two are the candidates.
- **The first run after the canonical-domain change has no history for a `www.` domain.**
  Competitor rows are now keyed on the canonical (`www.`-stripped) form, so a site that past
  runs stored as `www.example.com` will be stored as `example.com` from now on. Nothing
  reports a false drop — velocity and volatility both null-guard a missing previous side, and
  a domain with no prior row simply yields no comparison (chunk C2) — but that domain's
  trend restarts, and the run-over-run sections will be quiet for it once. Historical rows
  were deliberately **not** rewritten: a one-time `UPDATE competitor_metrics SET domain = …`
  would preserve the trend and is idempotent, but it silently changes stored data the owner
  may be comparing against already-delivered reports, which is the owner's call rather than a
  side effect of a correctness fix.
- **`visibility_cliff` is kept but will usually be withheld.** With the handoff universe a run
  samples well under `risk_signals.cliff_min_sample` (10) keywords per domain, so the signal
  rarely has a large enough sample to compute. Whether to keep it at all until a data source
  supplies that many (DataForSEO `domain_rank_overview`, or the full `ranked_keywords` count)
  is the owner's open decision 5 in the 2026-11-04 review plan.

## Fix log

Newest first. Format:
**Issue → Root cause (Pn) → What would have caught it → Fix → Rule.**

**A missing `client.da` returned "not feasible — Hyper-Local Pivot" for every competitor, from an authority figure nobody had measured.**
- **Root cause (H2, the same sweep):** `comparison_features` read
  `shared_config.get("client", {}).get("da", 0)`, and `feasibility_by_competitor` then did
  `int(client_da or 0)`. So an absent key made the client DA 0 and
  `check_feasibility(0, competitor_da)` returned False for every rival above the threshold — a
  verdict on the whole competitive set out of one missing config value, which is the
  D-C-03 / D-M-08 class on this side. `save_competitor_feasibility` recorded that 0 against
  every row too, so a later reader could not tell an unmeasured client from one with no
  authority.
- **The same file already did it right, 200 lines down.** The positioning path reads
  `.get("da")` with no default, under a comment saying why: `compute_authority` excludes a
  missing DA and renormalises rather than counting it as zero (C-M-09). One module, two
  readings of one key, and only one of them was fixed when the class was swept.
- **And it matters more going forward, not less.** Decision 6 makes `config.client_da` an
  explicit OVERRIDE to a live provider lookup, so absence becomes the normal case.
- **Fix:** None is preserved, `feasibility_by_competitor` withholds every verdict when the
  client's DA is unknown, the DB column takes NULL, and the report states the absence and its
  likely cause instead of simply omitting the section. A real DA of 0 still produces verdicts —
  that is a measurement.
- **Rule:** when a value has two readers in the same module, fixing one is a coin flip. Grep the
  KEY, not the function — `client.da` appears twice in `comparison_features.py` and the second
  occurrence carries a comment explaining the fix that the first one never got.

**`get_search_volume` was careful at every level except the one its own comment did not cover, and the consumer re-coerced what I had just fixed.**
- **Root cause (H2, two layers):** `DataForSEOClient.get_search_volume` returns None on a
  transport failure, None on an unparseable body, and None on an empty result — the last with
  the comment *"treated as unavailable, not as zero"*. A ROW whose `search_volume` was null
  became **0**. DataForSEO also reports a genuine 0 for a keyword nobody searches, so no consumer
  could tell "no figure" from "no searches". And `compute_branded_demand` summed the rows with
  `or 0`, so even a preserved None would have been flattened a layer later. A brand whose
  queries were answered without volumes was published as having **no branded demand, at a
  0.00% share, with basis `volume_estimated`** — the exact sentence C-C-11's own comment
  describes as the thing it fixed, three lines above the line that still did it.
- **It also defeated a fix I had made four hours earlier.** `competitor_mining` now counts a
  keyword with no volume figure as unmeasured rather than dropping it as small — a branch that
  could never be reached, because the client coerced to 0 before the consumer ever saw it. A
  consumer-side null check is worthless unless the producer preserves the null.
- **What would have caught it:** grepping the PATTERN (`or 0`, `get(…, 0)`) across `src/` rather
  than trusting the chunk that fixed the class. That sweep took one command and surfaced this
  plus `client_da` defaulting to 0.
- **Fix:** the client preserves None (and a measured 0 stays 0). `compute_branded_demand` sums
  only the rows with figures, treats "answered, no figure for any query" as unmeasured, and
  labels a partial total `volume_estimated_partial` — a lower bound, which understates that
  brand's share against the others. The ambiguity probe no longer compares against a summed-up
  0, which had been letting every ambiguous brand through the gate.
- **Rule:** a function that handles absence at three levels and coerces at the fourth reads as
  careful, and the comment explaining the three is what stops anyone checking the fourth. When
  fixing a null-handling class, fix it at the producer FIRST — otherwise every consumer-side
  guard is dead code that looks like diligence.

**The SERP-overlap top-10 test is asymmetric, so a keyword nobody wins is reported as "your clearest content gap". Four consumers of H1 in total, each distorted differently.**
- **Root cause (H1, consumed a fourth time):** `build_overlap_rows` filters competitor
  positions on `p <= top_n` and the client's on `raw_self <= top_n`. The competitor side comes
  from the handoff, whose ranks restart at 1 on every SERP page; the client side comes from
  Search Console and is **absolute**. So a rival counts as top-10 at any true position while the
  client counts only if it genuinely is.
  Worked through on the real function: rivals at true positions 14, 22 and 27 (handoff ranks 4,
  2, 7) with the client at a true GSC position of 12 classifies as `exclusive_competitor` —
  "rivals rank, you're absent — your clearest content gaps to fill", the section's own
  description of the top action queue — for a keyword where **nobody** is in the top 10 and the
  client is the closest of the four.
  `exclusive_competitor` and `shared_commodity` are therefore overstated and `exclusive_self`
  understated. And the competitor column mixes scales within itself: handoff rows are
  page-relative, enrichment rows carry DataForSEO's absolute `rank_group` (C-C-17).
- **The fourth consumer, and what it means for decision 5:** `get_visibility_series` counts
  `position <= 10` per run, so `ranked` equals `attempted` and the visibility rate is a constant
  1.0 for every domain in every run. The cliff detector would find no step change **even with a
  large sample** — its input is degenerate, not merely thin. Decision 5 (keep the cliff, or
  remove it until a real data source exists) was taken on the sample size; this is a second and
  stronger reason, and the owner should know it before the decision is revisited.
- **Why C-M-11 did not catch it:** C-M-11 was explicitly about unlike position scales, and it
  fixed two of the three — the market (GSC `country=can` against a Canada-scoped SERP snapshot)
  and the SERP-feature model (`rank_group` over `rank_absolute`). The pagination mismatch is the
  third, it is upstream, and it was not on the list.
- **Rule:** when two sides of a comparison come from different providers, enumerate every way
  the two scales can differ, and check them off one at a time. Market, element model,
  pagination, freshness — fixing two of four leaves a comparison that still is not one, and the
  fixed ones make it look audited. Four consumers, four different distortions: a vacuous
  criterion, a saturated component, an asymmetric filter, a degenerate series. None of them
  looks like the others, and finding one is not finding them.

**The barbell's authority axis is inflated by 21-27 points, which moves domains across the quadrant boundary — the same root cause, in the section that gives a verdict rather than a list.**
- **Root cause (H1, consumed again):** `get_positioning_inputs` counts top-10 rankings as
  `MIN(position) <= 10` over the handoff keywords. That `position` IS the handoff rank, which
  restarts at 1 on every SERP page — so **every** handoff keyword counts as a top-10 ranking.
  With the default weights (`moz_da` 0.7 / `top10` 0.3) and `top10_saturation` 10, a domain
  holding ten or more handoff keywords saturates the component whatever its real positions.
  Measured on the real formula: Moz DA 30 with **no genuine top-10 ranking at all** scores
  **51** instead of 30. `positioning.authority_threshold` is 50, so the inflation moves it from
  `emerging` to `authoritative` — it inverts the diagnostic the section exists to provide.
- **Why C-M-09 did not catch it:** C-M-09 was about commensurability — the client's count came
  from every GSC query it ranked for while competitors' came from the handoff, so the client was
  `authoritative` by construction. Fixing the UNIVERSE (both sides now count over the handoff's
  keywords) left the RANK SEMANTICS untouched, and the fix's own comment says "both sides count
  top-10 rankings over the same keyword universe" — which is true, and not the problem.
- **Fix:** the section states that the axis is an upper bound, with the arithmetic, and that
  `top10_count` means "handoff keywords" and not "top-10 rankings". Noted at the query in
  `database.py` where a code reader meets it, and in FEATURE_GUIDE §9. Driven by
  `handoff.absolute_rank_versions` like the others, so D1 retires all three warnings at once.
- **Rule:** one upstream data defect has as many consequences as it has consumers, and they do
  not look alike: for the magnet filter H1 makes a criterion vacuous, for the barbell it
  saturates a component, for the rank column it is a mislabel. Finding it in one consumer is not
  finding it. Enumerate every read of the affected field — `grep` for the column, not for the
  finding id — and ask of each one what the wrong semantics do to THAT calculation.

**The Traffic Magnet filter's "ranks well" criterion admits everything, so the owner's primary action list is three times longer than its own definition.**
- **Root cause (H1, consumed):** `_MAGNET_PREDICATE` is
  `… AND rank IS NOT NULL AND rank <= ?`, bound to
  `technical.magnet_max_position` (10) and compared against the HANDOFF's rank.
  serp-discover stores SerpAPI's per-page `position` verbatim and concatenates paginated pages
  without an offset (D-C-01), so in its 3-page mode the ranks run `1..9, 1..10, 1..10`. A result
  at true position 25 carries a rank of 5 and passes. **Against the committed reference run's
  distribution the filter admits 29 of 29 results** — true positions 1 through 29. The criterion
  the README and the USER_MANUAL both describe as "ranks well" filters nothing, and
  `magnet_max_position` is a knob with no effect.
- **Which means** the Traffic Magnet list is not "competitor pages that rank well" but "handoff
  pages that clear the medical floor and the relevance test", and the Systemic Vacuums and the
  gpt-4o reframe targets share the predicate and inherit it. Some of the pages the owner is
  being told to counter are on page 2 or 3 of the SERP.
- **Why three chunks of review missed it:** C1 was about WHICH keywords enter the universe and
  C3/C4 were about what the scores measure. Nobody asked whether the rank COMPARISON still means
  anything once H1 is known — and H1 was filed as a serp-discover finding, so on this side it
  read as "their bug", when half its consequences are here. Yesterday I added a caveat that the
  rank COLUMN is page-relative, which is a weaker and much less useful statement than "the
  filter is off".
- **Fix:** the magnet section now says the criterion is not in force, with the arithmetic, what
  the list actually is, and that the vacuums and reframes inherit it. The config key carries the
  same, so changing it is not mistaken for tuning. `USER_MANUAL` and `FEATURE_GUIDE` corrected
  where they described the filter as working. It is all driven by
  `handoff.absolute_rank_versions`, so D1 retires it with no code change. Not fixed by
  reconstructing an absolute rank from the rank sequence's resets: that is inferable in
  principle, and silently wrong the moment Tool 1 reorders its targets.
- **Rule:** when a finding is filed against the producer, list the consumer's own consequences
  separately, by hand. "Open upstream" describes who fixes the cause, not who is affected — and
  a caveat about a COLUMN is not a caveat about a FILTER that reads it.

**The Excel workbook's EEAT scores were text, because the display formatting ran in place on the frame the exporter gets.**
- **Root cause (P16):** `USER_MANUAL.md` promises "**the Excel sheets always carry every row**",
  and structurally they do — the exporter writes the full `df_*` frames, not the capped `disp_*`
  ones. But the EEAT section formatted its four dimensions with
  `df_eeat[col] = df_eeat[col].apply(...)`, in place, on `df_eeat` — which is the frame
  `to_excel` receives 600 lines later. Four float64 columns were exported as **strings**: "0.6",
  and "—" where a value was unknown. The owner could not sort, chart or average the EEAT scores,
  and a display marker sat in a numeric column. My own `md_table` fills a copy for exactly this
  reason, two hundred lines above.
- **What would have caught it:** opening the workbook. Nothing ever had — the suite asserted on
  the markdown only, so the second half of every briefing was unexamined.
- **And my first attempt at the test was vacuous.** It asserted `is_numeric_dtype` on
  `pd.read_excel`'s output and **passed with the defect restored**, because pandas parses the
  string "0.6" back into a float on the way in: the stored cell is text and the reader hides it.
  The test now reads the raw cell types with `openpyxl` (`cell.data_type == "n"`), and I verified
  it fails when the in-place formatting is put back.
- **Rule:** a reader that is helpful enough to coerce types will hide the bug you are testing
  for. When the artifact is a file format, assert on the file, not on what your library makes of
  it. And when a frame is both displayed and exported, format a copy — the two consumers want
  different things, and the one that wants numbers is the one nobody looks at.

**Three owner-facing report sections had never been rendered, because the test fixture mocks the components that fill them.**
- **Root cause (P19):** the end-to-end harness MagicMocks `GeoProfiler`, `EEATScorer` and
  `ClusterDetector`, so no rendered briefing — in any test, or in any of the renderer's
  scenarios — had ever contained the EEAT, Extractability or Cluster tables. Every defect found
  by reading the artifact this week came from the sections that DO render.
- **What that hid:** the EEAT section formatted each dimension with
  `f"{x:.1f}" if x is not None else "—"`. pandas reads a SQL NULL as NaN in a numeric column and
  `NaN is not None` is True, so a page whose dimension could not be computed printed **"nan"**
  beside the pages that could. It only looked right when EVERY value was NULL — the column is
  then dtype object and the values really are None — which is why the realistic case (one
  competitor's Domain Authority unmeasured) was the broken one. This is the same defect as the
  SoV `presence_rate` line, in a section nothing had ever looked at.
- **And what the fixture itself hid:** the renderer built its config from the test fixture's
  partial `CONFIG`, which has no `eeat_weights` block. `EEATScorer` then has nothing to weight
  with and correctly computes nothing — so the first `deep` render showed four columns of dashes
  and I spent twenty minutes hunting a product bug that was a property of my own fixture. The
  renderer now starts from the repo's **own** `shared_config.json`, so the sample reflects the
  owner's real thresholds and weights.
- **Which turned out to be a real gap too:** an absent config block produces a full table of
  unknowns with no stated cause. The section now says so, and names `eeat_weights` as the thing
  to check, because "a table of dashes with no explanation" is the failure mode this whole report
  is written to avoid.
- **Rule:** a mock in a fixture is a section of the artifact nobody has ever seen. When the
  harness stands in for a component, the output of that component is untested by construction —
  and "we render the report in a test" stops being true for precisely the parts that are hardest
  to reason about. Check what the fixture replaces before trusting what the render shows.

**The GUI's config write was not atomic, and a truncated `shared_config.json` is silently catastrophic rather than loudly broken.**
- **Root cause (P16):** `orchestrator.save_config` was
  `open(SHARED_CONFIG_PATH, 'w')` then `json.dump`. The open truncates
  immediately, so a process killed mid-write, a full disk, or two GUI interactions racing leaves
  the file half-written. That is not a loud failure: `scoring_logic.load_shared_config` swallows
  every exception and returns `{}` — which I had asserted earlier the same day as deliberate for
  the scoring path — so the next audit runs with **every threshold at its Python default and an
  EMPTY clinical vocabulary**, scoring every page 0 and reporting nothing wrong. Two reasonable
  decisions in two files compose into a silent catastrophe.
- **Same function, second defect:** `json.dump` defaults to `ensure_ascii=True`. The config is
  now full of provenance notes containing em dashes and arrows, so the first time anyone changed
  the reports directory in the GUI, every comment in the file would have been rewritten as
  `\u2014` and `\u2192`. Valid JSON, identical values, and the whole file unreadable in a diff.
- **What would have caught it:** nothing could. The orchestrator is a Streamlit script —
  importing it runs the UI — so it sits at 0% coverage and none of it is reachable from a test.
  The two functions that could do damage are now `src/config_io.py`, which is importable.
- **Fix:** write to a temporary file in the **same directory** (`os.replace` is only atomic
  within one filesystem, and `/tmp` is usually another), fsync, then replace; on any exception
  the original is untouched and the temporary is removed. `ensure_ascii=False`. It refuses an
  empty mapping over a non-empty file, because every caller arrives having loaded the file and
  changed one key, so an empty config means an upstream failure — and the one thing worse than
  losing a setting is erasing the config the audit reads. `load_config` RAISES on a corrupt
  file, unlike its scoring-path cousin: treating a corrupt file as `{}` and then saving would
  overwrite it with the single key the GUI changed.
  The strongest test is the simplest: the repo's own `shared_config.json` must round-trip
  byte-for-byte.
- **Rule:** a config file that a UI writes and a pipeline reads needs an atomic write, and the
  reason is not the write — it is the reader. Ask what the consumer does with a corrupt file
  before deciding how careful the producer has to be. Here the consumer was deliberately
  forgiving, which is exactly what made the producer's carelessness invisible.

**A committed config file carried the path to a developer's machine, published their username and the OAuth client ID, broke GSC auth everywhere else — and a test required it to be that way.**
- **Root cause (P4 / P19):** `shared_config.json` is committed and pushed. Its
  `auth.gsc_client_secrets` held
  `/Users/<name>/ProjectsLocal/serp-compete/client_secret_<id>.apps.googleusercontent.com.json`.
  No secret VALUE was exposed — the secret file itself is gitignored, and this key only points
  at it — but the line publishes a local username and the OAuth client ID in a file anyone with
  the repo can read. And it was functionally wrong anywhere but that one machine, because
  `_authenticate`'s chain was `if not client_secrets:` before the discovery glob: a non-empty
  string is truthy, so a configured-but-MISSING path was kept and the fallback never ran. GSC
  auth therefore failed on every other machine with "GSC Client Secrets file not found." —
  pointing at the wrong cause — while a usable `client_secret_*.json` sat in the repo root.
- **What kept it there:** `test_config_integrity.test_gsc_config_integrity` asserted
  `assert secrets_path, "GSC Client Secrets path is missing from config"`, under the comment
  "Client Secrets path should be absolute or point to an existing file". The test REQUIRED the
  defect. Emptying the key failed the suite, which is how it was found — and it is the second
  test this week that asserted a bug rather than the behaviour (the first was the omit-filter
  source-grep in chunk X).
- **Fix:** the key is empty, with a comment saying why an absolute path is wrong and that the
  secret file is gitignored. Discovery moved into `gsc_performance.find_client_secrets`, which
  tries the configured path, `gsc_auth.json`, the working directory and the repo root, and
  **accepts a candidate only if the file exists**. The integrity test now asserts the safe
  property instead: if the key is set it must be relative, must not name a home directory, and
  must not embed the client ID.
- **And a standing guard, because CLAUDE.md's one CRITICAL rule was enforced by attention:**
  `tests/test_secrets_are_ignored.py` asks `git check-ignore` whether
  `client_secret_*.json`, `token.json` (the OAuth REFRESH token
  `gsc_performance.TOKEN_PATH` writes on first auth), `.env`, `google-secrets.txt` and the audit
  database would be staged — for files that do not exist yet, which is the point — and asserts
  none is already tracked, since `.gitignore` is not consulted for a path already in the index.
  It also scans the committed config for credential-shaped VALUES; that scan is what found this.
- **Rule:** a path in a committed file is published, even when the thing it points at is not. And
  "verify X before every commit", written in a CLAUDE.md, is a rule enforced by attention —
  which is to say, enforced until someone is in a hurry. If the failure is unrecoverable, and a
  pushed secret is, write the test.

**The keyword-gap miner mined run 4 forever, could not apply the filter it claimed to apply, and its whole config block had been specified in 2026-05 and never built.**
- **Root cause (P4 / P14 / P19):** `src/competitor_mining.py`, at 19% coverage, held a literal
  for every value `docs/serp_tools_upgrade_spec_v3.md` had specified as a config key in May —
  seven of them. `AUDIT_XLSX` pinned `audit_results_run_4.xlsx` (the spec's own default), so an
  owner eleven audits later was ranking competitors from the fourth run; with no such workbook
  in the repo it printed an error and wrote an EMPTY gap report that read like a finding.
  `KEYWORDS_CSV` points into gitignored `serp-keyword/`, so the "we already target this" filter
  returned an empty set and every competitor keyword read as a gap — while the report listed
  "Filters Applied: … Target CSV: …", naming a file it had never opened. The brand filter was
  `if brand in kw_lower`, the substring test `audit_universe.contains_brand_token` was written to
  replace in C1. `search_volume` defaulted to 0 and was compared `< 10`, so an unmeasured volume
  was dropped as a small one. And it had its own raw `requests.post` to the same
  `ranked_keywords/live` endpoint `DataForSEOClient` already calls — no timeout, no retry,
  unguarded `['tasks'][0]['result'][0]` indexing, a second copy of the payload.
- **What would have caught the config half:** the guard I had written four hours earlier.
  `test_documented_values` failed the moment I added my own `keywords_per_domain: 100`, because
  the spec said 20 — which is how I found that the block had been designed and abandoned rather
  than never conceived. I had been about to invent key names for knobs that already had
  specified ones.
- **Fix:** the spec's key names, wired. Two departures, surfaced rather than resolved quietly:
  `keywords_per_domain` stays at the module's 100 rather than the spec's 20, because 100 is what
  has been running and each keyword is billed, so the depth is the owner's call; and
  `audit_xlsx_path` becomes an optional override, empty by default, because pinning a run number
  is the defect — the latest workbook is now chosen **by run number, not mtime**, so a re-saved
  old workbook cannot become "the latest audit". `brand_suffix_removal` and `enabled` were
  deliberately NOT added, with reasons recorded in both the config and the spec. The report now
  states whether the gap filter was applied at all, and names any domain the provider would not
  answer for as unmeasured rather than gap-free.
- **Rule:** before adding a config key, grep the specs for its name. A knob specified and never
  built looks identical to a knob nobody thought of — until you add a second one beside it with
  a different name and a different default, and now the owner has two. The guard that catches
  this is the one that compares documents with the config, which is why it is worth having even
  though its first week was mostly false positives.

**I shipped a regression in C4a that silently zeroed seven signals across two composites, and found it a day later by writing the tests that chunk never had.**
- **Root cause (P22 / P19):** C-M-19 (commit `7c98967`, 2026-11-15) added
  `SemanticAuditor._strip_boilerplate` so that nav, footer, `<header>`, menu divs, `<style>`
  and `<script>` would stop entering the scored text window — a correct fix for a real problem
  (a menu listing seven treatment services scored medical 9 on an about page). It runs at
  `semantic.py:306`. `_extract_metadata` runs at `:323`, and its JSON-LD block looked for
  `soup.find_all('script', type='application/ld+json')` — in a soup whose every `<script>` had
  just been decomposed. **From 2026-11-15 to 2026-11-16 no page's structured data was ever
  seen.** Permanently False, for every competitor: `has_faq_schema`,
  `has_article_schema`, `has_localbusiness_schema`, `has_person_schema`, `has_org_schema` in
  `geo_profiler` — five of its signals, including the FAQ and question ones C-M-14 had just
  asked to be weighted ABOVE Organization and Person — and `schema_author_type_person` and
  `schema_organization_present` in `eeat_scorer`. Extractability tiers collapse toward Weak and
  the expertise and authoritativeness dimensions fall, for every page, with no caveat anywhere,
  because from the consumers' point of view the pages genuinely had no schema.
- **What would have caught it:** a test on `scrape_content`. `semantic.py` was at **67%** and
  the uncovered blocks were precisely the scrape failure paths and the whole of
  `_extract_metadata`. Three chunks of review work had read that module closely and none of us
  noticed that the module with the most owner-facing consequences had its extraction untested.
  The 2026-11-15 suite was green at 617 tests.
- **Fix:** the JSON-LD strings are captured BEFORE stripping and passed into
  `_extract_metadata`. Not by exempting `<script type="application/ld+json">` from the
  stripping, which was the one-line option: the blocks would then have reached the scoring
  window and counted `schema.org`, `@type` and every property name as prose — trading a
  zeroed signal for an inflated one. There are now tests that the schema reaches
  `geo_profiler.profile_page` and `eeat_scorer.score_page`, and that `schema.org` does NOT
  appear in `scoring_text`.
- **Also found in the same pass:** `stock_image_hosts` existed twice — read from
  `shared_config.json` by `eeat_scorer` and hard-coded as a literal set inside
  `_extract_metadata` — so editing that config key changed the EEAT stock-image penalty and
  left `likely_original_images_count` alone. One visible knob controlling half of what it
  appears to (C-C-14's class, in a module C4 had just edited). And the host comparison was
  case-sensitive, so `IStockPhoto.com` in a `src` attribute counted as the practice's own
  photography.
- **Rule:** when you add a pass that MUTATES a shared parse tree, every later reader of that
  tree is now reading something different, and the compiler cannot tell you which. Either take
  what you need before the mutation, or do not mutate — and write the test for the consumer,
  not for the mutation. This one slipped through a careful review of the very function that
  broke it, because the function looked right and nothing exercised what it fed.

**The fragility list scored pages it had never read, because the guard was `if not content:` on a dataclass.**
- **Root cause (P16 / P14):** `src/infiltrator.py` (documented in `compete-spec.md`#C3 as a live
  implementation, 0% coverage until 2026-11-16) scrapes a competitor page and scores it. The
  guard was `if not content: continue` — and `scrape_content` has returned a `ScrapedPage`
  dataclass since chunk C2. A dataclass with no `__bool__` is ALWAYS truthy, so a page whose
  fetch was blocked or errored passed the guard and had its 403 body counted as prose.
  `main.py` has branched on `extraction_status` since C-C-09; this module never did, and the
  change that made the old guard meaningless was in a different file.
- **Same module, second defect:** `est_traffic` fell back to 0 and 0 was then compared with
  `> 500`, so a page whose traffic DataForSEO did not report was classified "Standard" — not
  fragile — on the strength of a number nobody measured. `page_traffic` now returns None for
  unmeasured, a measured 0 stays 0, and there is a third verdict ("Traffic not measured")
  instead of folding the unknown into the negative.
- **What would have caught it:** `coverage report --sort=cover`. It took one command to find
  four modules at 0%, two of which — this and `strike_mapper` — were documented as done and
  carried defects of exactly the class the 2026-11-04 review was commissioned to find.
- **Fix:** `_readable()` branches on `extraction_status` (and still accepts a plain string, which
  was the pre-dataclass contract); the threshold moved to
  `shared_config.json → infiltrator.fragility_min_traffic`; the report leads with its coverage so
  an empty table cannot read as "nothing is fragile"; clients are injectable so the thing is
  testable at all; and running it with no arguments no longer scrapes two hard-coded real
  competitor domains by default. 26 tests.
- **Rule:** when a function's return type changes, every truthiness test on it elsewhere becomes
  a silent always-true. `if not x` on an object is a bug waiting for someone to change what `x`
  is, and the change will be in a file the author of the `if` never opens. And run coverage
  occasionally: a module at 0% is not untested code, it is unexamined code, and the two defects
  above had been live for months behind a "✅ Done".

**A content tool wrote five invented keywords into the owner's pillar draft, and the docs said it was tested.**
- **Root cause (P14 / P8 / P4):** `src/strike_mapper.py` maps the GSC strike list onto the pillar
  draft's H2s. `gsc_strike_list.md` in this repo holds exactly one row — `| No data | - | - | - |
  - | - |` — and `get_top_gsc_keywords` silently substituted five hard-coded keywords when it
  found nothing. `inject_headers` then wrote them into `pillar_north_shore_draft.md`. **The five
  headings in that draft today are those invented keywords**, and nothing in the file or the
  console said they came from an editorial list rather than Search Console. The same function was
  non-idempotent (every run re-injected every heading, into a file the owner edits by hand), its
  placeholder test was `parts[1] != "No data"` — exact and case-sensitive, blind to the `-` and
  empty-cell forms the generator also writes — and its reframe vocabulary was a dict in Python
  source, against this repo's own CLAUDE.md rule.
- **What would have caught it:** a coverage run. `IMPLEMENTATION_PLAN_v3.md` listed
  `test_strike_mapper.py` as "(existing)" and `SPEC_COVERAGE_REPORT_v3.md` marked the module
  "✅ Done" with a line-number citation. The file never existed and the module was at **0%**.
  Two other claimed test files — `test_orchestrator.py`, `test_third_party_crawlers.py` — do not
  exist either, and the spec's "Integration point: called from orchestrator.py:111" is not true:
  `orchestrator.py` contains no reference to `strike_mapper` at all.
- **Fix:** no data now means no headings, unless `--allow-fallback` is passed, and then the
  output says the headings are editorial and not Search Console data. Injection is idempotent
  and recognises headings the owner wrote by hand. The vocabulary moved to
  `shared_config.json → strike_mapper`, with the Python constant as a guarded fallback. It is a
  dry run by default — it edits a content file, so writing is opt-in.
  `tests/test_strike_mapper.py`, 21 cases.
- **For the owner:** the five `##` headings in `pillar_north_shore_draft.md` came from the
  fallback list, not from Search Console. They may still be the right headings — they are the
  configured reframe vocabulary — but they are not evidence of search demand, and nothing in the
  draft says so.
- **Rule:** a fallback that returns plausible content is worse than an error. This one ran, wrote
  a file and printed "Successfully injected 5 GSC-mapped headers" — with no GSC data anywhere in
  the process. And a "✅ Done" with a test filename beside it is the most expensive kind of wrong
  entry in a status doc: it stops anyone looking.

**In a run where nothing could be scored, the report's primary action list disappeared instead of saying so.**
- **Root cause (P2):** the Traffic Magnets section had two branches — magnets found, and "none
  of the N audited page(s) met the magnet definition". The second branch's own comment says the
  reader "cannot otherwise tell it from 'nothing was audited'". When nothing WAS audited both
  branches were skipped and the heading vanished, so the exact confusion the comment names was
  the one case left unhandled. A reader seeing no Traffic Magnets heading cannot tell "no
  competitor page qualified" from "no competitor page could be read". The same render showed
  the SERP Overlap section saying it "folds in the Systemic Vacuum list above" when there was
  no such list — a caveat pointing at a section that is not there.
- **What would have caught it:** rendering a briefing with every provider down. The honest-absence
  behaviour is the thing chunk C2 was for, and nobody had ever read the artifact it produces.
  `tools/render_sample_briefing.py total-outage` now does exactly that: Moz answers nothing for
  every URL, DataForSEO 429s every call and reports no volume, every scrape is blocked.
- **Fix:** a third branch stating that no page could be scored, that this is not a finding about
  the competitors, and where to look for why; the cross-reference is now conditional on the list
  it points at. Both locked by tests that render the scenario and read the output.
- **Rule:** the two-branch shape is the recurring bug of this codebase, and it showed up three
  times in one evening — `measured` as a boolean when the source has three states, the magnet
  section as found/not-found when "unscorable" is a third, `errored` as one bucket when a cached
  failure and a fresh one are different facts. Before writing the `else`, count the states the
  SOURCE can be in.

**The console printed a timestamp as a failure count, and the risk evidence reached the owner with escaped unicode.**
- **Root cause (P22 / P19):** the anchor-coverage console line built its breakdown by iterating
  EVERY key of the coverage dict (`f"{v} {k}"` for anything truthy). That was correct when the
  dict held only counts. Chunk C2 then added `collected_at`, `fetch_status` and `reason` to the
  same dict, and the line started reading "Anchor coverage: 1 of 4 domain(s) had anchor data (3
  errored, 2026-11-16T09:00:00+00:00 collected_at)." Adding a key to a dict changed the meaning
  of a sentence three modules away. Separately, `save_risk_signals` dumped the evidence with
  `json.dumps`' default `ensure_ascii=True`, and the briefing prints that string verbatim — so
  the owner's report carried `\u2013` where an en dash belonged.
- **What would have caught it:** nothing in the suite, because the line was inline in
  `run_comparison_features`, which needs a database, a config and five fake clients to reach. It
  surfaced by rendering a briefing through the end-to-end fakes and reading the console output
  beside it.
- **Fix:** `risk_radar.anchor_coverage_lines` — the breakdown filters on `isinstance(value, int)`
  and the two sub-counts of `errored` get their own sentence, with tests for a timestamp, a
  status string and a clean run. `ensure_ascii=False` on the evidence dump, with a test that a
  dash survives the round trip unescaped. Both now sit beside `anchor_caveat_lines` and
  `gsc_pull_note`, which exist for the same reason.
- **Rule:** a loop over a dict's keys is a contract with everyone who ever adds a key to it, and
  that contract is invisible at both ends. Name the keys you mean, or filter by type. And a
  display string assembled inside a function that needs five fakes to call is a display string
  with no tests — pull it out; the repo has three of these helpers now and each was extracted
  after the inline version shipped something wrong.

**The briefing printed `nan` in the owner's tables, in the two places where a value was deliberately withheld.**
- **Root cause (P16 / P25):** chunk C2 made the data layer honest about NULL — an unmeasured
  Page Authority, a withheld focus score, a page count for a domain whose scrapes all failed.
  The rendering layer was never taught the same thing: `DataFrame.to_markdown` prints a missing
  float as `nan`, so the Competitor Ranking Summary showed `pages_audited` as `nan` for the two
  domains blocked by the 429 circuit breaker, and the Barbell table showed `focus_score` as
  `nan` for the three domains whose focus was withheld for too small a sample. Both were CORRECT
  absences — the `quadrant` column said `insufficient_data` right beside the `nan` — rendered in
  a way that reads as a broken calculation. A float artefact in a client-facing table is the
  exact inverse of this report's convention that an unmeasured thing says so.
- **What would have caught it:** rendering a briefing and reading it. No test asserted on a
  rendered table's *cells*, and none would have: the defect is invisible unless you look at the
  artifact. The review protocol's step 4 ("regenerate the report and diff the markdown") is
  exactly this check, and it is the step a cloud session cannot do for real — no `.env`, no
  history DB, no reference handoff. What it CAN do is drive the end-to-end test fakes and read
  the markdown they produce, which is how this was found, along with two stale sentences in the
  report's own caveats (`rank_absolute` after C-C-17 had moved to `rank_group`).
- **Fix:** one `reporting.md_table` helper that every table render now goes through, filling
  missing values with an em dash; a test asserts no `.to_markdown` call survives outside it,
  because a single raw one reintroduces the defect in a briefing nobody reads until after it is
  sent. It fills a COPY, so the Excel sheets keep real NULLs and their columns stay numeric.
- **And the fix had its own cosmetic bug, found the same way:** a count column with one NULL in
  it is float64, so filling the NULLs left the rest as "1.0" and "2.0". Whole-numbered columns
  are now printed as whole numbers, with a test for the negative case because `int()` truncates
  toward zero and drift columns are signed.
- **Rule:** read the artifact. A test suite asserts what someone thought to assert; the rendered
  report shows what the owner will actually see, and `nan` in a table is the kind of thing that
  survives a green suite indefinitely. Where the real artifact cannot be produced, drive the
  end-to-end fakes and read THAT — it is not the protocol's step 4, but it is not nothing.

**The schema document pointed at an empty table and called the live one deprecated, and two tables are created on every run that nothing uses.**
- **Root cause (P21 / P19):** `docs/DATA_PERSISTENCE_MAP_v3.md` was written on 2026-05-02 as a
  *design* doc and no chunk since updated it, although the repo's own rule is that contract docs
  change in the same push as the thing they describe. It listed 10 of the 22 tables that exist,
  omitting every table added for the C1–C6 comparison features. Its §3 proposed renaming
  `semantic_audits` to `semantic_audit_results` "for clarity"; what actually happened is that the
  new table was created — with two indexes and three JSON `*_terms_found` columns — and never
  written, while `semantic_audits` kept taking every write and was later extended by chunk C3. So
  the document described the empty table as a live v3 feature and the live table as "Deprecated;
  use traffic_magnets". `market_gaps` was likewise marked "Active" with no writer anywhere.
- **What would have caught it:** nothing in the suite looked at the document at all. Building a
  fresh database, listing `sqlite_master` and diffing it against the doc takes 40 lines and finds
  all of it at once — which is now `Serp-compete/tests/test_persistence_map.py`.
- **Fix:** §1 regenerated from the live schema: all 22 tables with purpose, key columns, writer
  module → reader module, and status, including which columns each review chunk added and why.
  §1.4 declares `market_gaps` and `semantic_audit_results` as created-but-never-used instead of
  omitting them, since a documented table implies a place to look for data. The original design
  section is kept behind a banner saying where each proposal actually landed. Dropping the two
  dead tables is left to the owner: neither holds data, so the only cost of keeping them is one
  paragraph, and `semantic_audit_results`' richer shape would make the scores auditable if
  anyone wants to build it deliberately.
- **Also caught by the guard, in my own first draft of it:** the phantom-table check matched every
  backticked identifier in a row, so it flagged 35 column names as phantom tables — useless
  noise that would have been deleted within a week. It now reads the row's first cell only. And
  the §1.4 check split the document on `---`, which is also the markdown table separator, so it
  was asserting against three lines of prose that stopped before the table it meant to read: a
  guard that passed on text it had never seen. Both have explicit can-this-fail cases now.
- **The same sweep over the two status documents, 2026-11-16.** `SPEC_COVERAGE_REPORT_v3.md`
  claimed "3/3 Technical Debt Remediation". One of the three was real (editorial content moved
  to config — verified, 20 `clinical_pivots` entries with a fallback). The second listed
  `competitor_metrics` and `semantic_audits` as deprecated with a plan to remove them "in v4 or
  2027-01-01", which would delete the audit's own working storage. The third described the
  orchestrator executing a topologically sorted DAG; `step_dag.py` was built, never wired, and
  its config section has since been deleted. `IMPLEMENTATION_PLAN_v3.md` separately marked the
  third-party skeleton "✅ Done" with a test file that has never existed. All corrected in place
  rather than deleted, because the original claims are evidence of how the drift happened.
  Its per-file test-count table — stale twice over, listing `test_eeat_scorer.py` at 54 against
  80 today — was replaced with the two suite totals and the command that produces them: a
  hand-maintained count is wrong the moment anyone adds a test, so the document should carry the
  command, not the number.
- **The third sweep: thresholds quoted in prose, 2026-11-16.** `USER_MANUAL.md` told the owner a
  Traffic Magnet needs `medical_score >= technical.vacuum_min_medical (10)` and showed
  `"vacuum_min_medical": 10` in its config example, 24 lines above a paragraph correctly
  explaining the value had been re-set to **6**. One document, three statements, two wrong — and
  this is the floor that decides which competitor pages become magnets, vacuums and gpt-4o
  reframe targets, so an owner tuning against the documented 10 would be reasoning about a
  filter that admits a different set of pages. `FEATURE_GUIDE.md` had the same stale 10 in its
  Traffic Magnet table; I had edited that file twice the same evening without noticing, and only
  the guard found it.
  `Serp-compete/tests/test_documented_values.py` now diffs every threshold figure quoted in the
  docs against `shared_config.json`. Its two false positives are instructive: "see the §3.3
  caveat" and "open decision 8" both read as quoted values, because these documents cite
  themselves constantly. Both are excluded by pattern, with a test asserting that a *stale*
  figure beside a citation is still caught — an exclusion that lets a wrong number hide behind
  a cross-reference would be worse than no guard.
  The review directory is excluded entirely: those files quote pre-fix values on purpose, and
  "correcting" them would destroy the audit trail they exist to be.
- **Rule:** a schema or contract document needs a test, not a convention. "Update the docs in the
  same push" is a rule people follow until the push is urgent; a guard that diffs the document
  against the thing it describes is what actually holds. And when a guard is written, write the
  case that proves it can fail — a guard asserting against the wrong slice of a file looks
  identical to a guard that is passing. Corollary for the figures a document quotes: if a number
  can be computed, print the command instead of the number, and date any number you do print.
  A "✅ COMPLETE" with a count beside it is the form this rots into — it reads as verified long
  after it stopped being true, and nobody re-derives it because it looks already checked.

**The handoff contract was enforced where it could be machine-checked and assumed everywhere else (Chunk X: canonical domains, rank semantics, zero-answer engines, cached Moz errors, the GSC pull).**
- **Root cause (P6 / P19 / P21):** `handoff_schema.json` validates shape, so everything the
  schema *can* check was checked and everything it cannot was taken on trust. Tool 1 writes
  domains as `netloc.lower()` with `www.` kept while its own brand and citation paths strip it,
  so one site arrived in two spellings; `run_audit` grouped on the raw string while the omit-list
  test two lines below normalised, so the same site became two audited competitors with its
  keyword count split between them — and an omitted `www.` host was skipped while its bare twin
  was audited. The same mismatch silently emptied the Moz anchor scope: `moz.domains` keys keep
  `www.`, the run's domain list does not, so a run whose anchor fetches all failed would have
  reported neither findings nor unreadable domains. `targets[].rank` is serp-discover's
  per-page SERP `position` with no offset applied across paginated pages (H1 / D-C-01, still
  open upstream), and this tool printed it as a position with nothing saying so. The
  AI-visibility export carries brand-mention rows for engines that answered nothing, and
  computing shares over them published "0% mention share, named in 0% of answers" — a measured
  absence for a question never asked. And an `anchor_texts.status == "error"` was counted as
  this run's outage although Tool 1 can re-serve a cached failure for 30 days.
- **What would have caught it:** a contract test that calls the real consumer. The one that
  existed, `tests/test_handoff_ingestion.py::TestHandoffConversion`, carried its own copy of
  `main.convert_handoff_to_targets` under the comment *"Simulate the conversion logic from
  main.py"* — so the shipped function could drop a field with every assertion still green, and
  one had: `client_brand_names` was in the schema, written by Tool 1, documented, and discarded
  (C-C-13). The grouping loop had no test at all, because it was unreachable: inline in
  `run_audit`, which needs live API clients.
- **Fix:** `docs/handoff_contract.md` — the semantics the schema cannot express, with every open
  cross-tool item named and attributed. The grouping became
  `audit_universe.group_targets_by_domain`, canonical and callable, with both sides of
  `handoff_moz`'s domain matching normalised to agree with it. `handoff.absolute_rank_versions`
  records which schema versions carry absolute ranks (empty today), and the briefing warns on the
  rank column until one does — so the warning retires itself when D1 ships, with no code change.
  `compute_sov` drops engines with no answered questions, names them, returns `presence_rate`
  `None` rather than `0.0` when there is no count, and persists the per-engine counts in a new
  `sov_coverage` table so an *old* report can still say what was unmeasured. `anchor_coverage`
  splits `errored` into `errored_cached` / `errored_age_unknown` sub-counts by comparing each
  domain's `fetched_at` against the handoff's assembly time. `reporting.gsc_pull_note` states
  the window, country and device scope from the keys the fetcher reads. The simulated conversion
  tests now call the real functions, and `Serp-compete/tests/test_handoff_contract.py` (37 cases)
  holds the semantics.
- **Also fixed on the way:** the SoV report line tested `presence_rate is not None`, but a SQL
  NULL arrives from pandas as NaN, which *is* not None — so the first NULL would have rendered
  "named in nan% of answers". `anchor_data_unreadable` was left alone deliberately: the new
  counters are sub-counts of `errored`, so adding them to it would have inflated the unreadable
  total. And `handoff_rank_is_absolute` is passed the run's own config rather than reading
  `shared_config.json` again — the second read resolves relative to `src/`, so an
  orchestrator- or test-supplied config was ignored and the report could have described a rank
  convention the run was not using.
- **Caught on an adversarial re-read of this chunk's own diff, same day:** the SoV engine gate
  I had just written was two-valued, and so stored a row contradicting itself. An engine listed
  in the export with no brand-mention rows at all was recorded as `measured = 1,
  questions_total = 0` — "we asked nothing and that counts as measured". From the export alone
  that case is genuinely ambiguous: the questions may have been asked with no tracked brand
  coming back, or the engine may never have run. `measured` is now three-valued (1 / 0 / NULL)
  with its own report wording, and the same re-read found that a zero-question engine's
  *citations* were still being published, which would have put a citation share in the report
  for a run that did not happen. The lesson is about the shape of the fix, not the bug: I
  replaced a two-state coercion (`or 0`) with a different two-state coercion, which is how the
  null-is-not-zero class keeps coming back — the question to ask is how many states the SOURCE
  can distinguish, not how many the consumer finds convenient.
- **Rule:** a contract test must call the thing it is a contract for. If a test re-implements the
  code it covers, it tests the copy. And when two modules compare the same identifier — a
  domain, a key, an id — normalise it in ONE place and make every comparison go through that
  place; two paths that disagree about what a domain is will each look correct in isolation.

**The consumers read their inputs at the wrong scale, the wrong market and the wrong depth, and documented knobs controlled nothing (C-M-11, C-C-17, C-M-16, C-M-17, C-M-18, C-C-14).**
- **Root cause (P2 / P4 / P6 / P21):** every one of these is a contract read loosely. GSC was
  asked for ONE 5000-row page, and since it returns rows by clicks descending, the zero-click
  long tail of a real property was simply missing — and `serp_overlap`'s module docstring treats
  an absent query as "the client is absent", so the missing rows became the top action queue. The
  same matrix compared a 90-day GLOBAL GSC average against a Canada-only DataForSEO snapshot with
  a symmetric `<= top_n` test, and the competitor side used `rank_absolute`, which counts SERP
  features, so an organic #8 under three features read as 11. A rival's own brand query sat in
  "your clearest content gaps to fill". The AI-visibility export carries display names ("Jericho
  Counselling") while the matcher held derived tokens ("jericho"), so a mentioned-but-uncited
  rival fell into "other", which the report filters out — printing the client's 25% with no
  visible 75% — and `presence_rate`, the quantity the section's own description promises, was
  computed and never rendered. A YouTube handle matching the bare brand token ("@bach" for
  bachcounselling.com) was `confirmed`, and `none_found` — "not found by a 3-result name search" —
  was stored as `has_channel = False` and rendered as a definitive ✗. And four thresholds that
  drive verdicts were literals in Python (`+5`, `avg_pa > 50`, volatility `>= 3`, the GSC 90-day
  window) while config keys with the same names sat unread, so the knobs the owner could see did
  nothing and the ones that mattered were invisible.
- **What would have caught it:** a test that feeds a consumer MORE than one page of input, and
  one that asserts a documented config key changes behaviour. The suite mocked GSC with three
  rows, so pagination could never be exercised; and no test asked whether
  `technical.feasibility_threshold` did anything, which is why it sat decorative since March.
- **Fix:** GSC paginates with `startRow` until a short page, filters on
  `gsc_settings.country`, reads `date_range_days`, and reports partial data as partial; the
  overlap universe excludes rival-brand keywords and the top-N test uses `rank_group`; the SoV
  matcher runs the export's brand through `derive_brand_name` and the report prints
  `presence_rate` and the "other" remainder; a YouTube handle must equal the domain stem, and
  `none_found` carries `has_channel = None` with the report saying what it means; the four
  literals moved into config, `handoff.supported_versions` is enforced (with its values corrected
  from 2.0/2.1 to the real 1.0/1.1), and eight keys with no reader were deleted with the removal
  recorded in the file. Every threshold now carries a `_source` note, FEATURE_GUIDE §9 has the
  provenance table, and a standing guard test fails when a new threshold arrives without one.
- **Rule:** when an API returns a page, assume there is a second one; when two numbers are
  compared, check they come from the same market and the same scale; and a config key with no
  reader is worse than no key — it is a lie about what the owner controls. Grep for a reader
  before documenting a knob.

**Every composite score flattered the client or the template, and said so with unearned precision (C-M-09, C-M-10, C-M-12, C-M-13, C-M-14).**
- **Root cause (P6 / P7 / P2):** five separate scores, one habit — comparing numbers that were
  not comparable, then presenting the result with more confidence than the inputs carry. The
  barbell's authority axis said "the same formula for you and competitors" while the competitor
  value was the average Moz **Page** Authority of its sampled URLs and the client's was a Domain
  Authority; the client's top-10 count came from every GSC query it ranked for (saturating the
  component at 240 queries) against a rival's ≤10-keyword sample, so the client landed
  `authoritative` by construction. Focus was an entropy over a raw Tier-1 count against a
  ×2.0/×0.5-weighted systems score, computed on ≤3 pages, so one occurrence of "relationship"
  moved a domain across a quadrant boundary. EEAT's `score_confidence` was a count of null
  dimensions, which made it `high` for every page that loaded — a constant column labelled
  confidence — beside composites of booleans rendered to 2 dp, and its authoritativeness
  component was fed the URL's PA where it expected a DA. The cluster key kept scheme and host
  verbatim, so a www/non-www mismatch produced `isolated`, which the manual told the owner to
  read as "easier to overtake". And the extractability section was headed "Why Competitors Get
  Cited" and asserted that the structures it found were *why* rivals were cited, while a stock
  WordPress post (Yoast schema, byline "admin", a date) out-scored a real FAQ page and nothing in
  the section measured a citation at all.
- **What would have caught it:** a test that asserts the CLIENT is not automatically the best
  thing on the plot, and one that feeds each composite the shape its own documentation claims to
  reward (an FAQ page vs a stock WP post; a www-mismatched link graph; a page with one tier
  token). The suite tested each formula's arithmetic on inputs chosen to make it work.
- **Fix:** Moz `domain_authority` is read from the url_metrics call already being made and stored
  beside `avg_da` (never backfilled from it); both sides of the top-10 count use the handoff's
  keyword universe; focus is withheld below `positioning.min_focus_tokens` and the counts behind
  it are printed; EEAT confidence is weighted signal coverage, capped when a composite is
  withheld, at 1 dp with the value set stated; the cluster key is host-normalised and the
  "prefer isolated" advice is gone; the extractability tier is weighted toward FAQ schema and
  question headings, generic bylines do not count as authorship, the section is renamed
  "Extractability signals (structural, unvalidated)", and when an AI-visibility export exists the
  Strong tiers are checked against the real citations in it.
- **Rule:** before comparing two numbers, say out loud what each one measures — "average page
  authority of three sampled URLs" and "domain authority" are not the same quantity, and a label
  like `avg_da` will hide that for months. And a confidence that cannot come out low is not a
  confidence: if a column has one value in practice, delete it or compute it from something that
  varies.

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
