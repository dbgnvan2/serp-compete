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

_(none open — the two risks found during the F7 review were fixed; see the fix log.)_

## Fix log

Newest first. Format:
**Issue → Root cause (Pn) → What would have caught it → Fix → Rule.**

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
