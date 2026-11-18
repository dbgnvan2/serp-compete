# Chunk Y16 — one reader for Tool 2's shared config

Carried as "Adjacent issues found, not fixed" by chunk Y11's cold review and
repeated in the Y13, Y14 and Y15 plans. This chunk is in **`serp-compete`**
(Tool 2); the plan is mirrored here because the review workplan lives in this
repo.

## The fault

`shared_config.json` is the editorial config both tools share: scoring weights,
penalty thresholds, position thresholds, risk signals, the database path, the
clinical vocabulary tiers. Tool 2 has **three** functions named
`load_shared_config`, and they do three different things with the same file:

| Reader | On a corrupt or unreadable file |
|---|---|
| `src/database.py:34` | raises — deliberately, and documented: a caller reading an editorial threshold must not silently score against a default |
| `src/main.py:36` | raises (no handler) |
| `src/scoring_logic.py:8` | `except Exception: pass` → returns `{}` |

Plus a fourth path, `database.config_for_lock_timeout`, which catches and logs
and returns `{}` — that one is correct and documented: the lock wait is not an
editorial threshold, and `DatabaseManager.__init__` reads it even for a caller
that supplied its own `db_path`.

Two faults follow, and the second is the serious one.

**1. The same corrupt file produces three different outcomes** depending on
which module reads it first. `database.load_shared_config`'s docstring states
the rule the repo intends — a reader of an editorial threshold must not score
against a default silently — and `scoring_logic` is the module that most
obviously breaks it (P40: a handler that swallows).

**2. `scoring_logic` reads the file at import time into module globals.**

```python
SHARED_CONFIG = load_shared_config()          # line 17
WEIGHTS       = SHARED_CONFIG.get("technical", {}).get("scoring_weights", {...})
PENALTY_CFG   = SHARED_CONFIG.get("technical", {}).get("penalty_thresholds", {...})
TIER_1_MEDICAL / TIER_2_SYSTEMS / TIER_3_BOWEN_EXPERT = ...
```

So a `shared_config.json` with a trailing comma means every competitor in the
run is scored with the Python fallback weights and the fallback vocabulary
tiers, the run completes, and the briefing reports scores that reconcile with
nothing the owner configured. Nothing is logged: the `except Exception: pass`
is the only place that could have said so. This is the same shape as the Y4
default-argument trap — a configured value bound before any config could be
read — and the same shape as P16, a value read once and never re-read: editing
the config and re-running in one Streamlit process changes nothing, because the
module is already imported.

## What is built

**One reader.** `load_shared_config` lives in one module and the other two
import it. It raises on a file that exists and cannot be parsed, which is what
`database.py` already documents as the intended rule; `config_for_lock_timeout`
stays as the one named, explained exception.

**`scoring_logic` reads at call time, not import time.** The weights, the
penalty thresholds and the vocabulary tiers become accessors that read the
config when a score is computed, matching how `position_thresholds` and
`magnet_thresholds` in `database.py` already take an optional `config`
argument so a caller holding the config does not re-read the file (P25 — one
config→argument mapping).

**One read per run, not eleven.** Eleven call sites each re-read and re-parse
the file. Whether that is worth a cache is a judgement; the honest version is
to measure it first and record the number rather than assume. If a cache goes
in, it is invalidated by the file's mtime, because the GUI edits this file
while the process that reads it is running — a cache keyed on nothing is how
the import-time read above became a bug in the first place.

**The fallbacks are stated, not duplicated.** Several Python fallbacks mirror
`shared_config.json`'s own values (`DEFAULT_VACUUM_MIN_MEDICAL`,
`DEFAULT_POSITION_THRESHOLDS`, `WEIGHTS`, `PENALTY_CFG`). Each must be verbatim
equal to the file's value, enforced by a test, as Tool 1 does for
`db_connect._CLEANUP_DEFAULTS` against `serp_vocab.yml` — otherwise "degrades
to the documented default" degrades to a different number than the document.

## Verification

Full suites for both halves of Tool 2 by exit code (core: `cd Serp-compete &&
PYTHONPATH=. python3 -m pytest tests/ -q`; root: `cd .. && PYTHONPATH=Serp-compete
python3 -m pytest tests/ -q`), plus the mutation gate: each production change
reverted on its own must fail a guard covering its own criterion.

The guards are consequences: a corrupt `shared_config.json` on disk, then what
a score is computed from and what the run says about it. The import-time read
needs a guard that survives the module already being imported — a subprocess,
or a reload with the file replaced — since a test that imports the module in a
clean process would pass either way.

## What is NOT in this chunk

* Changing any threshold or weight. This chunk is about where they are read,
  not what they are.
* Tool 2 having no editorial text file at all — every reader-facing sentence is
  a Python literal. That is a larger chunk of its own, and it is the direct
  analogue of what chunk Y15 just finished in Tool 1.
* The untracked `keyword_enrich.py` in Tool 1: a 25th copy of the database
  name, its own `--db` default, no config load, and a bare `requests.get` that
  records a transient failure as "no suggestions" (P1/P2). Out of scope because
  fixing it would mean committing a file the owner has kept local.

## What was built

**One reader.** `config_io.load_config` is it: `{}` for an absent file, a raise
for one that exists and cannot be parsed. Five bodies were doing that job —
`database.load_shared_config`, `main.load_shared_config`,
`scoring_logic.load_shared_config`, `velocity_module.VelocityTracker._load_config`
and `gsc_performance.GSCManager._load_json(SHARED_CONFIG_PATH)` — and one of
them, the one on the scoring path, swallowed every exception.
`database.load_shared_config` keeps its name, because every test that stubs the
config patches it, but it delegates. `config_for_lock_timeout` stays the one
named exception, for the reason chunk Y11 recorded.

**One path.** Five modules each built the same path from their own `__file__`,
so a reader could not tell whether they agreed without computing all five.
`config_io.SHARED_CONFIG_PATH` is the definition and the other four import it.

**`scoring_logic` reads at call time.** `SHARED_CONFIG`, `WEIGHTS`,
`PENALTY_CFG` and the three vocabulary tiers were module globals derived from an
import-time read. They are now `shared_config()`, `weights()`, `penalty_cfg()`
and `clinical_tiers()`, each taking an optional already-loaded `config` so a
caller holding it does not re-read the file (P25), and
`calculate_weighted_score` takes the same argument. `SemanticAuditor` reads the
vocabulary when it is built.

**No cache, and the measurement rather than the assumption.** The plan asked
whether eleven reads per run need one. Measured: 0.095 ms per read and parse
over 34 KB, so a run spends about a millisecond on this. A cache keyed on
nothing is how the import-time read became a bug in the first place, and the
GUI edits this file while the process that reads it is running. A test records
the measurement so a future reader does not have to guess either.

**The fallbacks say what the document says.** Eight Python fallbacks mirror
`shared_config.json`'s own values — the tier weights, the penalty thresholds,
the density and min-hits triggers, the vacuum floor, the magnet ceiling, the
volatility trigger and the three position thresholds. Each is now asserted
verbatim equal to the file's value, as Tool 1 does for
`db_connect._CLEANUP_DEFAULTS` against `serp_vocab.yml`; otherwise "degrades to
the documented default" degrades to a different number than the document.

## Verification

Both halves of Tool 2 by exit code: core **885 passed**, root **162 passed**
(**900** and **162** after the cold review's fixes and their guards). Tool 1
unchanged and still green (2325 passed, 68 skipped, EXIT=0). Mutation gate:
**22 mutations, 22 caught, 0 vacuous** on the first build; **33 caught, 0
vacuous** after the cold review, whose fixes added eleven mutations. Two came back vacuous on the
first pass and both were real gaps, now closed: the "one reader" guard looked
for functions *named* `load_shared_config`, so `gsc_performance`'s
`_load_json(SHARED_CONFIG_PATH)` and `VelocityTracker._load_config` passed it
while still reading the file themselves — the guard now checks where the path
goes, not what a function is called; and `weights({})` returning an empty
mapping rather than the documented defaults was invisible because every call
site carried its own copy of the default, which is the duplication the
accessors exist to remove.

The import-time guards run in a subprocess, because a test that imports the
module in this process would pass either way. Three of them: importing
`scoring_logic` opens no config file at all; a corrupt config raises out of
`calculate_weighted_score` instead of scoring against the Python defaults; and
editing the file between two scores in one process changes the second score.

## Cold review and what it changed

A cold `learning-qa` pass over the uncommitted diff (9 tracked files plus the
two new ones) returned **8 findings — 1 high, 7 medium** — against P1–P45. All
eight are fixed, each with a guard. What it checked and found sound is recorded
at the end.

**F1 (high, P40 + P1 + P2 + P11) — the new raise was swallowed one layer below
where it was guarded, and the swallow wrote a permanent negative per page.**
`SemanticAuditor._scoring_window_words` read the config, and the call sat inside
`scrape_content`'s `try` / `except Exception`. So a `shared_config.json` that
could not be parsed *at the moment a page was scraped* did not stop the run:
every page came back `http_status=0, extraction_status="error"`, `main.py` wrote
a market snapshot with `rank` / `systems_score` / `medical_score` all NULL for
every URL, printed "Skipping unreadable page" and continued. A persisted "we
could not read this page" that was actually "I could not read my own config"
— and `calculate_weighted_score`, where this chunk's guard fires, was never
reached on the run path. The trigger is the case the per-call read was
introduced for: the GUI edits this file while the process that reads it is
running.

The fix is the one the chunk should have made in the first place: the analyser
reads the config **once, when it is built** — vocabulary, scoring window and
stock-image hosts together — and holds it. That is per run, not per import, so
an edit still takes effect on the next run; and it is outside every per-page
handler, so a corrupt file stops the run before the first page is fetched.

**F2 (medium, P5) — two opposite policies for the same file, 280 lines apart in
the same module and the same `try` block.** `semantic.stock_image_hosts` read
the same config and deliberately swallowed, with the rule written out as a
comment — "a config read must not break a scrape" — while the scoring-window
read, edited by this chunk, raised. Both were called from inside
`scrape_content`. `stock_image_hosts` now takes the already-loaded config, and
with none it reads and raises like every other reader.

**F3 (medium, P6 + documentation rule 13) — three live docstrings and one new
doc paragraph stated the behaviour this chunk reversed.** `config_io`'s module
and `load_config` docstrings still explained the *difference* between this
reader and `scoring_logic.load_shared_config`, "which swallows it" — a function
this chunk deletes; `tests/test_config_io.py` said the same, and added "which is
right on the scoring path", the belief Y16 exists to reverse. The new
FEATURE_GUIDE paragraph said a file that will not parse stops the run, which F1
made false. All four corrected, and the FEATURE_GUIDE and USER_MANUAL passages
now say *when* the read happens and what an edit mid-run does.

**F4 (medium, P37/P31 corollary) — a new guard that was vacuous for its own
criterion, inside a batch reporting "0 vacuous".**
`test_every_module_names_the_file_in_one_place` asserted that the four modules'
`SHARED_CONFIG_PATH` values were *equal*. They were equal before the change too
— `abspath(join(dirname(__file__), "..", "..", "shared_config.json"))` and
`join(PROJECT_ROOT, "shared_config.json")` resolve to the same string — so
reverting all three assignments left it green. It proved the paths agreed, never
that there was one definition. Replaced by a check that the literal
`"shared_config.json"` appears in exactly one file in `src/`, plus an
`assertIs` that each module's constant is the same object. The mutation set now
carries a per-module "builds its own path" mutation for all three.

**F5 (medium, P19 corollary) — a source-text assertion where a consequence was
available, green against a re-introduction of the bug.** The import-time
vocabulary guard read `semantic.py` as text and asserted `"TIER_1_MEDICAL" not
in source` and `"clinical_tiers()" in source`. Reintroduce the read as
`TIERS = clinical_tiers()` at module level and both hold. Replaced by the
consequence: build two analysers either side of a changed file and assert each
holds its own vocabulary.

**F6 (medium, P2 + P40) — the EMPTY-vocabulary outcome this chunk exists to
prevent was still reachable, in the function the chunk edited.**
`load_dictionary`'s `clinical_dictionary.json` fallback was
`except Exception: pass` followed by three empty lists. Reached whenever the
config parses but its `clinical` block is absent — one GUI edit away, since the
block is editorial — and the dictionary file is then unreadable. Every page then
scored 0 in all three tiers with label `Standard`, the run completed, and the
briefing reported that as a measurement. The unreadable file now raises, the
same rule as the config itself; "no vocabulary configured anywhere" stays a
legitimate state (`reframe_engine` reports it as `NO_MEDICAL_VOCABULARY_NOTE`)
but is now logged rather than silent.

**F7 (medium, P33 + P5) — the fallback-equality sweep was complete along one
axis and reported as complete.** The axis it enumerated — the fallbacks
`scoring_logic` and `database` declare — really was complete; the claim "the
fallbacks say what the document says" was not. Three more Python literals mirror
a `shared_config.json` value and were unasserted: `semantic`'s
`DEFAULT_SCORING_WINDOW_WORDS`, `analysis`'s `DEFAULT_FEASIBILITY_THRESHOLD`,
and `db_connect`'s `DEFAULT_LOCK_TIMEOUT_SECONDS` — the last asserted against
the literal `5.0` in the Y11 tests rather than against the file, so the constant
and the file could still drift from each other. All three now compared to the
file.

**F8 (medium, P19) — one score could be computed from two versions of the
config.** The vocabulary was frozen when the analyser was built while the
weights, penalties and window were read per call; one run holds one analyser, so
after a mid-run edit a single `analyze_text` combined the old vocabulary with
the new weights and nothing recorded which version produced the score. F1's fix
settles this too: `analyze_text` passes the config the analyser holds, so one
score comes from one read. The FEATURE_GUIDE now says so.

One further defect surfaced while writing F1's and F2's guards, and is worth
recording because it would have made several of this chunk's own tests vacuous:
`scoring_logic` had `from src.config_io import load_config`, which binds the
name at import, so patching the one reader did not reach the scoring path and a
test that believed it had made the file unreadable was testing nothing (P43).
The module now calls `config_io.load_config()` through the module.

### Adjacent issues found, not fixed

- `tools/render_sample_briefing.py` opens `shared_config.json` with its own body
  at two places. It is a developer tool outside `src/`, and the one-definition
  guard walks `src/` only.
- `orchestrator.py` now defines `SHARED_CONFIG_PATH` and nothing in the module
  uses it.
- `penalty_cfg()` can return the module-level `DEFAULT_PENALTY_CFG` object
  itself, which a caller that mutated it would corrupt process-wide.
- `GSCManager.__init__`'s abort on a corrupt config is reported by `main.py` as
  `❌ GSC Check Error`, which mislabels it. Pre-existing; unchanged by this
  chunk.
- `docs/tool2_review_bundle/` holds stale copies of `database.py` and
  `gsc_performance.py` carrying the old path construction. It is a frozen
  2026-05-02 snapshot; per the precedent set in chunk Y10 the drift is noted in
  its README rather than the copy maintained.
