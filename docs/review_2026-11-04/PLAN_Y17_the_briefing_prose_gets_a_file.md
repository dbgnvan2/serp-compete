# Chunk Y17 — the briefing's prose gets a file

Carried as an adjacent issue by the cold reviews of chunks Y13 and Y15, and
named in Tool 1's `CLAUDE.md` for over a month: *"Tool 2 has no vocabulary
file, so its copy of the same sentence is a constant in its own `db_connect`
and the two have to be changed together."* `db_connect.py` says the same thing
about itself, in a comment above the constant.

## The fault

Tool 1 has **ten** editorial text files. Tool 2 has **none**. Every sentence
the strategic briefing renders — the caveats, the comparability warnings, the
"why there is no number here" lines, the section introductions — is a Python
literal, and the rule both repos are built on says it should not be: *"any
content that requires editorial judgement to refine belongs in YAML or JSON,
not in Python source,"* with the test *"if a non-developer reading the file
might reasonably want to change a value, it's editorial."*

Every sentence in this report is that. They are the hedges on the figures: what
the number does not mean, which population it was measured over, why a cell is
blank rather than zero. The owner is the person who would reword them and the
only person who can say whether a hedge reads honestly. None of them is
reachable without opening Python.

Three consequences are already in the code, and they are what makes this a
defect rather than a preference.

1. **One claim, three wordings, one of them already in config and read by
   nothing.** The EEAT heuristic caveat exists as `reporting.py:656`
   (rendered), as `eeat_scorer.py:7` (a docstring), and as
   `shared_config.eeat_client_messaging.caveat` — which is editorial
   reader-facing text sitting in the config file where it belongs, that no
   module reads. `eeat_client_messaging.positioning` and its three
   `confidence_levels` sentences are likewise unread. This is the
   `feasibility_messages.yml` failure in Tool 1 reproduced exactly: one
   unmeasured state carried two labels in different outputs because the words
   were Python literals in four places.

2. **One fact, four separately-worded warnings.** The handoff's ranks restart
   at 1 on every SERP page, so a rank of 2 may be the second result of page 3.
   That one fact is warned about in four places — run coverage
   (`reporting.py:364`), the magnet filter (`:728`), the SERP-overlap cells
   (`:866`) and the positioning axis (`:985`) — each in its own words, each
   with its own citation of the same finding. Rewording the fact means finding
   all four. They are not literal duplicates, so no de-duplication tool finds
   them.

3. **A constant with a bare duplicate beside it.** `UNKNOWN_CELL = "—"` at
   `reporting.py:13`, and a second bare `"—"` literal at `:669` that bypasses
   it.

## Scope: every sentence the briefing renders

The line is not "these three modules" — that was a first guess. It is **every
reader-facing string the briefing report or its workbook renders**, which is
P5's rule applied to a class of literal rather than one module:

| module | reader-facing sentences |
|---|---|
| `reporting.py` | 84 |
| `reframe_engine.py` | 4, plus 3 LLM-prompt blocks |
| `risk_radar.py` | 4 (`_REACH_UNMEASURED`, `_RECEIVED_NOT_BOUGHT`, `ANCHOR_SPAM_CAVEAT`, the coverage line) — rendered into this report's Reputation-Risk section |
| `db_connect.py` | 4 (`CLEANUP_WARNING`, two consequences, `CLEANUP_DETAIL_ITEM`) — rendered by `reporting.py:309` |
| `geo_profiler.py` | 1 (`why_cited`) — rendered verbatim at `reporting.py:820` |
| `strike_mapper.py` | 1 orphan (`GENERIC_REFRAME`) |

Fixing `reporting.py` and leaving `risk_radar`'s and `db_connect`'s sentences
in Python would be the state the rule itself forbids: *"do not leave old
hardcoded content in place while new content moves to config — this produces a
codebase where similar things live in different places and reviewers can't
find the editorial surface."*

### What stays in Python, and why

Not everything reader-facing is editorial. These are a **format contract**
`validate_xlsx_vs_json`-style consumers and tests depend on, and Tool 1's rule
is explicit that workbook headers are never renamed:

- the 14 Excel sheet names (`reporting.py:1303-1331`) and the four workbook
  column lists;
- every literal that is **also** a comparison value or a DB column value —
  `Surface-Level`, `Strong`, `middle`, `exclusive_competitor`, `self_unknown`,
  `candidate`, `volume_unavailable` and the rest. The *label* may move; the
  literal the code compares against may not, or the comparison silently stops
  matching;
- `strike_mapper.PROVENANCE_MARKER` and `INJECTION_POINT`: idempotency depends
  on byte-matching what earlier runs wrote into a file the owner hand-edits.
  Changing either duplicates headings, which is the P8 bug that module already
  had once.

## What is built

### `briefing_messages.json`, at the repo root beside `shared_config.json`

One file, sectioned by the report section that renders it, in render order:
`gsc_comparability`, `rank_semantics`, `run_coverage`, `executive_summary`,
`capped`, `gsc_section`, `volatility`, `fragile_magnets`,
`competitor_summary`, `systemic_depth`, `eeat`, `clusters`, `magnets`,
`extractability`, `serp_overlap`, `feasibility`, `positioning`, `sov`,
`brand_demand`, `risk_radar`, `youtube`, `reframes`, `db_cleanup`, `icons`.

**JSON, not YAML.** Tool 1's ten files are YAML and an eleventh was the obvious
move. Rejected on three findings in Tool 2 itself: `PyYAML` is not in
`requirements.txt` and **is not importable in this repo's venv**, so the format
would mean pinning a new runtime dependency on the report-rendering path to
hold text — and `requirements.txt`'s own header records what an undeclared
dependency cost here (seven test files uncollectable while the suite reported
158 passed). Tool 2's entire config surface is already JSON. The cost is
stated rather than hidden: JSON has no block scalars and no comments, so a
300-character caveat is one long line and the annotation goes in a sibling
`_<section>_comment` string, which is the convention `shared_config.json`
already uses.

**Not in `shared_config.json`.** The three prior editorial migrations in this
repo went there (`strike_mapper.reframes`, `clinical_pivots`,
`brand.name_suffixes`) and the instinct was to follow them. The reason not to
is chunk Y16: that file has **one** reader and it **raises** on a file it
cannot parse, deliberately, because a caller reading an editorial threshold
must not silently score against a default. A messages file needs the opposite
rule for a missing key — so it gets its own loader with its own documented
contract, rather than bending the one Y16 just established.

`strike_mapper.GENERIC_REFRAME` is the exception that proves the line: it is a
sibling of `strike_mapper.reframes`, which is already in `shared_config.json`
and read from there. It goes beside its siblings, not into the new file.

### `src/briefing_messages.py` — the loader

Two rules, each with a reason, because the two cases are not alike:

- **A missing or malformed FILE raises.** The opposite of Tool 1's
  `report_writing_directives.yml` contract ("missing/malformed file degrades to
  no directives, never an aborted report"), and the difference is the point:
  directives are advice to a model, while these sentences are the hedges on the
  report's own figures. A briefing rendered without its caveats is a briefing
  that overstates every number in it, confidently and silently. That is worse
  than a stopped run, and it is the same judgement chunk Y16 made about the
  scoring config.
- **A missing KEY renders a visible marker and logs.** `[message missing:
  eeat.score_caveat]` in the report body, counted and logged once per run. An
  owner part-way through an edit gets a report that says where the hole is
  (P2), not a sentence that vanished.

Read once per run and held, which is the shape chunk Y16's cold review arrived
at: the read is outside every per-section handler, so a failure stops the
render before the first section rather than becoming a per-section blank.

### The interpolation design

Most of these sentences carry a number mid-clause, and half the work is keeping
the *grammar* out of Python. Three patterns, all of which already exist in
Tool 1:

- **A conditional clause is its own key**, and an outer template composes it:
  `gsc_comparability.pull_line` takes `{country_line}` and `{device_line}`,
  each resolved from its own three-way key set. Eight keys, one line. The
  precedent is `gsc_messages.yml`'s `population_suffix`.
- **Grammatical number gets a key pair, not a Python conditional.**
  `sov.not_measured` currently interpolates
  `{'these engines' if len(x) > 1 else 'this engine'}` — four such switches
  across two messages. Half a sentence in Python is still a sentence in
  Python, so each becomes `.one` / `.many`.
- **A number quoted in prose comes from the key it describes, or the key is
  created.** `feasibility.intro` says "feasible when client DA + 5 ≥ competitor
  DA" and the `5` has no config key at all. Externalising the sentence without
  externalising the number reproduces exactly the drift this chunk exists to
  stop, so `feasibility.da_margin` is added and the sentence interpolates it.
  Same for `serp_overlap.action_queue_truncated`, whose `15` is a literal in
  both the prose and the `.head(15)` beside it.

## Verification

- Both compete suites by exit code, and Tool 1 unchanged.
- **~25 test files pin exact wording** and must change in this chunk. Two
  existing tests are the template for how: `test_strike_mapper.py:182` asserts
  `GENERIC_REFRAME` **by symbol**, not by text, and
  `test_y13_a_cleanup_failure_is_a_number.py:191` asserts the *placeholders*
  are present rather than the sentence. A test that pins prose it does not own
  pins it twice, so each becomes an assertion against the loaded message.
- A guard that every key the code asks for exists in the file, and every key in
  the file is asked for — the dead `eeat_client_messaging` entries are what an
  unasked-for key looks like.
- A guard that the `systemic_depth` status keys match the Python literals the
  code still compares against (Tool 1's `feasibility_messages.yml` pattern).
- A guard that a malformed file raises and a missing key renders its marker.
- Mutation gate over the loader, the contract and each duplicated-fact family.

## Adjacent issues found, not fixed

- `shared_config.eeat_client_messaging.positioning` and `.confidence_levels`
  are editorial strings nothing renders. This chunk makes `.caveat` the source
  for the rendered sentence; whether the other two should be rendered or
  deleted is an editorial decision for the owner, not a refactor.
- `reframe_engine`'s three LLM-prompt blocks are editorial by the same test but
  are not report prose. Tool 1 keeps prompts in prompt files, not in a messages
  file; they are in scope for the file but under a `reframes.prompt` section
  that is explicitly not report output.
- `reporting.py` is 1334 lines with no size cap. `serp_audit.py` in Tool 1 has
  one at 2200 enforced by a test; `config_manager.py` there is at 2931 with
  none. Three modules now want the same guard.

## What the build found that this plan had wrong

Recorded rather than quietly corrected, because each one changed the work.

1. **`risk_radar.py` has about ten reader-facing sentences, not four.** The
   scope table counted three constants and the coverage line; the module also
   renders the anchor-cause clauses, the caveat lines and the two sub-headings.
2. **`feasibility.da_margin` was not created.** The plan said the `5` in
   "client DA + 5" had no config key, so the sentence should get one. It has a
   key: `technical.feasibility_threshold`, which `analysis.feasibility_threshold()`
   already reads and `check_feasibility` already decides by. A second key for
   the same number would have been the drift this chunk exists to stop, so the
   sentence interpolates the existing one.
3. **Three dead `framework_caption` keys, not one `eeat_client_messaging`.**
   `serp_overlap`, `positioning` and `sov` each carried one in
   `shared_config.json` and no module read any of them. All three moved into
   the messages file verbatim and are listed with `eeat.positioning` and
   `eeat.confidence_levels` as the keys deliberately kept and unrendered.
4. **The EEAT caveat had four wordings, not three.** The fourth is a dataclass
   field default stored on every EEAT score row (`eeat_scorer.EEATScore.caveat`),
   and `geo_profiler.GeoProfile.caveat` is the same shape. Both are under 70
   characters, so the prose guard below found them only once it was pointed at
   those two modules. They are now `eeat.row_caveat` and
   `extractability.profile_caveat`, read through `field(default_factory=...)`.
5. **The migration duplicated four keys of its own**, found by the key-coverage
   guard before any commit: `positioning.client_marker` (already `icons.you`),
   `risk_radar.own_heading` and `.competitor_heading` (already
   `headings.risk_own_site` / `.risk_competitors`), and a `risk_radar.anchor_coverage`
   stub left at `null`. Deleted.
6. **~25 test files pin exact wording and were left alone.** The plan said each
   must become an assertion against the loaded message. That is right for a
   test that named a Python *constant* (`UNKNOWN_CELL`, `GENERIC_REFRAME`,
   `CLEANUP_WARNING`) or asserted a call's source text, and four test files
   changed for that reason. It is wrong for a test asserting what the rendered
   report *says*: that is the contract with the reader, and rewriting it to
   assert `Messages().get(...)` on both sides makes it assert only that the
   renderer rendered the file — which the key-coverage guard already covers,
   tautologically and with no reader in it. Those tests pass unchanged, which
   is also the evidence that the migration did not reword anything.
7. **Two guards were vacuous and were replaced.** The mutation gate walked
   through both: `report.extend(self.shortfall_lines())` moved inside a comment
   still satisfied `source.index(...)`, and the action-queue truncation note
   was a closure over the render's `row_cap`, so hardcoding its number was
   invisible. Both are now methods on `ReportGenerator`
   (`shortfall_lines`, `action_queue_note`, `action_queue_row_cap`) that a test
   calls with values of its own. A third, `test_strike_mapper.py`'s assertion
   that `generic_reframe()` returns the configured value, passed while the call
   site held the literal; the call site is now checked too (P19/P27/P30).
8. **A missing placeholder went uncounted when the caller passed no fields at
   all.** `get` short-circuited on `if not fields`, so a caller that forgot its
   arguments printed a literal `{domain}` into the briefing and nothing
   recorded it. The condition is now on the message, not the call.

## Verification as run

- compete core **948 passed** (exit 0), compete root **162 passed** (exit 0),
  Tool 1 **2325 passed, 68 skipped, 196 subtests** (exit 0, untouched).
- 48 guards in `tests/test_y17_the_briefing_prose_gets_a_file.py`.
- Mutation gate over 35 reverts of this chunk's production changes:
  **35 caught, 0 vacuous, 0 anchor-failures.**
- `tools/render_sample_briefing.py` rendered a full sample briefing from this
  working tree and from a detached worktree at the pre-change commit, and the
  two were diffed. (`sample_briefings/` is gitignored, so there is no committed
  copy to compare against; the baseline had to be rendered.) **The whole
  difference is the timestamp and two words**: the SERP-overlap and positioning
  warnings now cite "review finding H1 / D-C-01" where they said "H1 /
  D-C-01", because the citation is one key and the four warnings that quote it
  no longer phrase it two ways. That is the intended consequence and the only
  wording change in about 240 migrated sentences. The render also carried no
  `[message missing: ...]` marker and no shortfall line, so every key it asked
  for was in the file.

## The cold `learning-qa` review and what it changed

Run over the whole diff after the build was green. Every medium-or-higher
finding is fixed with a guard; the low ones are dropped per the process, except
one noted below.

**H1 — a missing prompt block would have been sent to the model.** `get`'s
policy is a visible marker, which is right for a sentence the reader sees and
wrong for an LLM prompt: the marker would have been sent, paid for, and the
model's answer written into the briefing as a reframe, while nothing in the
report said a hedge had gone missing, because a prompt is not rendered. There
is now a second reader, `Messages.prompt`, which returns `None` and records the
miss, and `ReframeEngine._no_prompt` turns that into the same
`generated: False` status the no-API-key and no-medical-vocabulary paths
already return. Both sit on one resolver, `_resolve`, so there is one
definition of what "resolved" means.

**H2 — the shortfall count covered only the report's own keys.**
`ReportGenerator` holds its own `Messages`, but six other consumers build a
throwaway one (`ReframeEngine`, `GeoProfile`, `EEATScore`,
`detect_anchor_spam`, `cleanup_failure_warning`, `anchor_coverage_lines`), and
their markers landed in the briefing or in a database row while the report's
count read zero and printed nothing — after `README.md` and the user manual
had stated that count as a guarantee. The ledger is now module-level
(`briefing_messages._MISSES`), the same shape as `db_connect._CLEANUP_FAILURES`
and reset the same way, by `main.run_audit` at the start of a run.

**M1 — `reporting.py` imported `logging` nowhere** while the new cap reader
logged. Fixed.

**M2 — the action-queue row cap was a literal in the messages file.** A row
count is not a sentence. It is `shared_config.json`
`serp_overlap.action_queue_row_cap` now, with the documented fallback
`ReportGenerator.DEFAULT_ACTION_QUEUE_ROW_CAP` and the same
"says-so-in-the-log" degradation as `db_connect.lock_timeout_from_config`: a
cap of 0 would print an empty action queue, which reads as "no keywords
qualify".

**M3 — a stray brace aborted the whole render.** `str.format` raises
`ValueError: Single '{' encountered`, and the file is documented as
hand-editable, so that is the expected typo. It is caught beside the missing
placeholder now and renders a marker, which is what this module's own
docstring already promised.

**M4 — `db_connect` asked the messages file from inside an `except` and an
`atexit` hook.** Those are the two places where the file may itself be the
broken thing, and asking it there turns a warning into a failure. They now go
through `_words(key, fallback, /, ...)`, which degrades to a named
`FALLBACK_*` constant and says in the warning that the built-in wording was
used. These are the only two prose literals the migration left in Python, and
a guard asserts there is no third.

**M5 — the file was parsed ten-plus times per run.** `GeoProfile` and
`EEATScore` resolve a stored sentence when the ROW is built, and a run builds
one per audited page. `load_messages` now caches the parse keyed on
`(abspath, st_mtime_ns, st_size)` — on what an edit changes, not on nothing,
which is the distinction chunk Y16 drew, because the GUI edits these files
between runs in one process.

**M6 — two of the new guards were source-text assertions.** See correction 7
above; the same class of defect, found again in this chunk's own tests. The
four-warnings citation guard now counts parsed `citation=` keyword arguments
rather than substrings, so a comment quoting the key does not satisfy it.

**M7 — `icons.unknown_cell` set to `""` would have satisfied every
assertion.** `test_report_rendering.py` compares the render against the
configured value, so an empty marker passes on both sides while the cells
render blank, which is the thing the em dash exists to prevent. The cell is now
asserted to be non-blank independently.

**M8 — the migration stopped at the briefing.** `GSCManager` and
`competitor_mining` write three standalone markdown reports of their own
(`gsc_strike_list.md`, `gsc_strategic_gap.md`, `competitor_keyword_gaps.md`)
and every sentence of them was still a Python literal, including the hedges
that are the point of the chunk. Two were near-identical rewordings of keys
that *had* moved, so "one claim, several wordings" had come to span two files.
Both modules are migrated (`gsc_reports.*`, `mining_report.*`, 42 further
keys) and both are in the prose guard's module list now.

**M9 — two claims are still worded more than once, on purpose.** The EEAT
heuristic caveat went from FOUR wordings to THREE, not to one: the long
rendered `eeat.caveat`, the short `eeat.row_caveat` stored on every score row,
and the `eeat_scorer` module docstring, which is written for whoever reads the
module and is not report output. Separately, three sections carry a
`framework_caption` that restates their own rendered `intro` at greater length;
both wordings moved into the file verbatim, because rewriting the report's
editorial content is the owner's call and not the migration's. Recorded as an
editorial decision for the owner rather than reversed, and guarded:
`TestTheRecordedDuplicatesDoNotGrow` fails if a third key carries the EEAT
claim or a fourth section gains a caption — which is how the original defect
was built, one reasonable addition at a time.

**L5, half taken.** `strike_mapper.headings_for` called `generic_reframe()`
inside the per-query loop while `reframes()` was hoisted; it reads once now.
The other half — `strike_mapper._config`'s blanket `except Exception: return
{}` swallowing the deliberate raise chunk Y16 added to the shared-config
loader — is left as an adjacent issue: it changes the failure behaviour of a
module outside this chunk's subject. L1–L4 dropped per the process.

### Two failures the fixes themselves caused, and what they say

* **A guard in `test_handoff_contract.py` was reading the method's source**
  for the empty-GSC-report sentence, so it went red the moment the words left
  Python. It asserts over the rendered markdown now. Third instance of P19/P27
  in this chunk.
* **`shared_config.json` stopped round-tripping byte for byte.** `config_io`
  writes with `ensure_ascii=False`, and the comment added for M2 carried an
  escaped `—` rather than a literal em dash. `test_config_io` caught it.
  The GUI saves that file on any settings change, so the diff would have been
  the whole file.

### Verification after the fixes

- compete core **967 passed** (exit 0), compete root **162 passed** (exit 0),
  Tool 1 **2325 passed, 68 skipped, 196 subtests** (exit 0, untouched by this
  chunk — only its copy of the workplan and one `CLAUDE.md` claim changed).
- 67 guards in `tests/test_y17_the_briefing_prose_gets_a_file.py`.
- Mutation gate re-run over **49** reverts, the 35 of the build plus one per
  fix above: **49 caught, 0 vacuous, 0 anchor-failures.** Three of the new
  mutations came back VACUOUS on the first run — the prompt policy, the brace
  catch and the `FALLBACK_*` degradation each had the fix but no consequence
  test — and `TestTheThreeFailuresTheGateFoundUnguarded` is what the gate
  bought.

### Adjacent issues found, not fixed

- `strike_mapper._config` swallows every exception, including the raise chunk
  Y16 added deliberately (L5, above).
- `test_documented_values.py` scans `sample_briefings/`, which is gitignored
  local output. A sample render in the working tree made the suite fail on a
  false positive (its regex took "1000" out of a long sentence as the quoted
  value of `vacuum_min_medical`). The test is sound on a clean checkout and the
  render was moved out, but a suite whose result depends on local output files
  is fragile.
- `reporting.py` is ~1400 lines with no size cap, while `serp_audit.py` in
  Tool 1 has one enforced by a test.
- `reporting.py`'s mention-share table caps at a literal `.head(10)` with no
  config key — the sibling of the cap M2 moved.
