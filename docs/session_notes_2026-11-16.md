# Session notes — 2026-11-16

One overnight session on `main`, 19 commits, `77df7df`…`8580a0f`.
Suite **641 → 892 passing, exit 0**. Coverage across `src/` **85%**.

The assigned work was chunk X of the 2026-11-04 review (the compete half). The
rest came from applying the same question to the places nothing had looked:
*what does this actually do, and what does the owner see when it fails?*

---

## 1. Act on these

### 1.1 Re-run any briefing generated since 2026-11-15 — two composites were understated

`_strip_boilerplate`, which I added in chunk C4a (`7c98967`, 2026-11-15),
decomposes every `<script>` before metadata extraction. JSON-LD lives in a
`<script>`. So from that commit until `816c2f4` yesterday, **no page's
structured data was seen at all**, and these were permanently `False` for every
competitor:

- `geo_profiler`: `has_faq_schema`, `has_article_schema`,
  `has_localbusiness_schema`, `has_person_schema`, `has_org_schema` — five
  signals, including the FAQ and question ones C-M-14 had just asked to be
  weighted *above* Organization and Person
- `eeat_scorer`: `schema_author_type_person`, `schema_organization_present`

Extractability tiers collapse toward Weak and the expertise and
authoritativeness dimensions fall, with no caveat — from the consumers' side
those pages genuinely had no schema. **If you generated a briefing in that
window, its GEO and EEAT figures are too low.** Fixed; re-run to get real ones.

### 1.2 Your username and OAuth client ID are in the git history

`shared_config.json` carried
`/Users/davemini2/ProjectsLocal/serp-compete/client_secret_2751….apps.googleusercontent.com.json`
as `auth.gsc_client_secrets`. **No secret value was ever exposed** — the
`client_secret_*.json` file itself is correctly gitignored, and this key only
pointed at it. But the line published your local username and the OAuth client
ID in a committed, pushed file.

- Removed from HEAD (`dd131aa`). **Still in the history.** The client ID is not
  secret by design (browsers receive it), so there is nothing to rotate; if you
  want the username out of the history that needs a rewrite, which is your call.
- It also broke GSC auth on any machine but yours, and the error message pointed
  at the wrong cause. Fixed — see §2.4.

### 1.3 Your pillar draft's five section headings came from a fallback list, not from Search Console

`pillar_north_shore_draft.md` lines 35–39. `gsc_strike_list.md` contains one
row — `| No data | - | - | - | - | - |` — and `strike_mapper` silently
substituted five hard-coded keywords, wrote them in, and printed "Successfully
injected 5 GSC-mapped headers".

They may well be the right headings — they are the configured reframe
vocabulary — but they are **not evidence of search demand**, and nothing in the
draft says so. Your call whether to keep them. The tool now refuses to invent
them (`1a075e8`).

### 1.4 Decisions still waiting on you

| | |
|---|---|
| **Decision 4** | Which side canonicalises domains. Compete is defensive either way, so nothing is blocked — see `docs/handoff_contract.md` §1.3 |
| **Decision 8** | Raise `technical.max_audit_pages_per_domain`, or demote the barbell/EEAT/cluster sections at N≤3. Chunks C4b/C4c and chunk X deliberately did not pre-empt this |
| **`step_dag.py`** | Built, correct, 13 passing tests, and reachable from nothing. Its config key was deleted as having no reader. Wire it into the orchestrator (a feature: step order becomes owner-configurable, with a bad config able to stop the audit) or delete it with its test. Not a cleanup decision |
| **`market_gaps`, `semantic_audit_results`** | Two tables created on every run that nothing writes. Neither holds data. Drop them or build the richer `semantic_audit_results` deliberately — `docs/DATA_PERSISTENCE_MAP_v3.md` §1.4 |
| **`competitor_mining.keywords_per_domain`** | The 2026-05 spec said 20; the code has been doing 100, and that is what I wired. Each keyword is billed — your call |
| **C-C-04** | One Moz client shape for both tools still needs a live call to settle. `docs/TEST_RUN_CHECKLIST.md` §1b carries the check |

### 1.5 Before your next live run

`docs/TEST_RUN_CHECKLIST.md` gained **§0** (render a briefing for free and read
it) and **§2c** (the chunk X cross-tool checks). §0 is the cheap stand-in for
the review protocol's step 4, which no cloud session can do:

```bash
python3 tools/render_sample_briefing.py full -o sample_briefings
```

Four scenarios: `minimal`, `full`, `authority-drop`, `total-outage`. The numbers
are invented — read the wording, the caveats and the N-of-M lines.

---

## 2. What was wrong, by consequence

### 2.1 The report said things that were not so

- **`nan` in two tables**, in exactly the cells where a value had been
  *deliberately withheld* (`pages_audited` for a 429-blocked domain,
  `focus_score` below `positioning.min_focus_tokens`). Correct absences,
  rendered as a broken calculation. Every table now goes through one helper,
  and a test forbids a raw `.to_markdown` anywhere in `reporting.py`.
- **A run that could score nothing dropped its primary action list.** The
  Traffic Magnets section had "found" and "none qualified" branches; when
  *nothing was audited* both were skipped and the heading vanished. A reader
  could not tell "no competitor page qualified" from "no competitor page could
  be read".
- **A caveat pointing at a section that was not there** ("folds in the Systemic
  Vacuum list above", in a run with no such list).
- **A timestamp printed among the failure counts** — the anchor-coverage line
  iterated every key of a dict that chunk C2 had given three non-count keys.
- **`–`** in the risk evidence, from a `json.dumps` default.
- **Two caveats describing behaviour the code no longer had** (`rank_absolute`
  after C-C-17 moved to `rank_group`).

All six were found by rendering a briefing and reading it. None is visible from
a test suite, because a test asserts what someone thought to assert.

### 2.2 Unknown collapsed into zero, or into a negative

- `measured = 1, questions_total = 0` stored for an AI engine whose coverage the
  export genuinely does not state. Now three-valued.
- A zero-question engine's **citations** were still published — a citation share
  for a run that did not happen.
- `infiltrator` scored pages it had never read: the guard was `if not content:`
  and `scrape_content` returns a dataclass, which is always truthy. A blocked
  page's 403 body was counted as prose.
- `infiltrator` read **unmeasured traffic as low traffic** (`est_traffic`
  defaulted to 0, then `> 500`).
- `competitor_mining` read an unmeasured search volume as a small one.
- A 30-day-old **cached** Moz error was reported as this run's outage.

### 2.3 Documents that were confidently wrong

- `DATA_PERSISTENCE_MAP_v3.md` listed 10 of 22 tables and had the semantic
  tables **backwards** — it documented the never-written
  `semantic_audit_results` as a live v3 feature and called `semantic_audits`,
  which every run reads and writes, "Deprecated; use traffic_magnets".
- `SPEC_COVERAGE_REPORT_v3.md` claimed "3/3 Technical Debt Remediation". One was
  real. The second proposed removing two **live** tables "in v4 or 2027-01-01" —
  acting on it would delete the audit's own storage. The third described DAG
  execution the orchestrator does not do.
- `IMPLEMENTATION_PLAN_v3.md` marked three modules done with test files that do
  not exist, and cited an integration point (`orchestrator.py:111`) that
  contains no reference to the module.
- `USER_MANUAL.md` and `FEATURE_GUIDE.md` each stated `vacuum_min_medical` as
  **10** — the pre-decision-3 value — within 24 lines of a paragraph correctly
  explaining it had been re-set to **6**.

Four standing guard tests now diff these against the code
(`test_persistence_map`, `test_documented_values`, `test_no_new_dead_code`,
`test_config_provenance`).

### 2.4 Things that could not work at all

- `competitor_mining` mined `audit_results_run_4.xlsx` **forever**, and no such
  workbook exists, so it wrote an empty gap report that read like a finding. Its
  "we already target this" filter could not fire either (the CSV is in
  gitignored `serp-keyword/`) while the report listed that filter as applied.
- GSC auth failed on any machine but one, with a message naming the wrong cause.
- `strike_mapper` re-injected every heading on every run, into a hand-edited file.
- `get_top_pages` had no retry while every sibling call did, and set no
  `last_error`, so a caller could not tell an outage from a domain with no pages.

### 2.5 Two tests that asserted the bug

- `test_config_integrity` *required* `auth.gsc_client_secrets` to be non-empty —
  which is what pinned the machine-specific path in a committed file. Emptying
  the key failed the suite; that is how §1.2 was found.
- A source-grep (AST) test required every `omitted_domains` comparison to call
  `normalise_domain`, and failed once the grouping key itself became canonical —
  it asserted the fix's absence.

Both replaced with behavioural equivalents.

---

## 3. New capabilities

| | |
|---|---|
| `docs/handoff_contract.md` | What the Tool 1 handoff and exports *mean*, as opposed to `handoff_schema.json`, which says only whether a file is well-formed. Chunk X's deliverable |
| `tools/render_sample_briefing.py` | A full briefing from fabricated data, four scenarios, no credentials. Found six of the defects above in one evening |
| `tests/test_secrets_are_ignored.py` | CLAUDE.md's one CRITICAL rule, enforced by test rather than by attention |
| `tests/test_persistence_map.py` | The schema doc cannot drift from the schema |
| `tests/test_documented_values.py` | A threshold quoted in the docs must be the configured value |
| `tests/test_no_new_dead_code.py` | A function nothing references must be wired, deleted, or declared |
| `tests/test_dictionary_sources.py` | The two clinical-vocabulary files cannot drift apart |
| `tests/test_handoff_contract.py` | The handoff semantics, against the real consumer (37 cases) |

---

## 4. Not done

- **Protocol step 4** (regenerate the briefing from the reference handoff and
  diff the markdown) — no `.env`, no `competitor_history.db`, no reference
  handoff in a cloud session. Nothing was approximated in its place; §1.5 is the
  cheap stand-in.
- **The serp-discover half of chunk X** — the producer-side contract test, the
  `schema_version` bump D1 will bring, `paa_questions` in the handoff, one agreed
  GSC window stated in both reports. Needs that repo.
- **The discover chunks D1–D6.** No discover finding is fixed. D1 (absolute rank)
  is the headline: it invalidates numbers in every report either tool has
  produced, and compete's briefing now *warns* about it rather than fixing it.
- `orchestrator.py` (the Streamlit GUI) is at 0% coverage.
  `third_party_crawlers.py` is a declared skeleton and correctly untested.

---

*Every finding above is in `LEARNINGS.md` with its root cause, what would have
caught it, and the rule drawn from it. The commit messages carry the evidence.*
