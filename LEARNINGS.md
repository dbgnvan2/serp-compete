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
