# The Tool 1 → Tool 2 handoff contract

**What this is.** The agreement between `serp-discover` (Tool 1, the producer) and
`serp-compete` (Tool 2, the consumer) about the files they pass each other: the
competitor handoff, the AI-visibility export, the Moz block, and the Google Search
Console pull both tools make independently.

**Why it exists.** `handoff_schema.json` says whether a document is *well-formed*.
It cannot say what a field *means* — whether `rank` counts results across a whole
SERP or restarts on every page, whether `www.x.com` and `x.com` are one site, or
what the consumer should do when the producer sends something it cannot trust.
Every entry below is a question the schema could not answer and that cost a wrong
number in a real report.

**Status:** written 2026-11-16 as the serp-compete half of review chunk X
(`review_2026-11-04/REVIEW_WORKPLAN_2026-11-04.md` §3 Chunk X). The serp-discover
half landed 2026-11-17: `serp-discover/tests/test_handoff_contract.py` is the
producer-side contract test, and owner decision 4 is settled there — **the
producer canonicalises every host it publishes** (`targets[].domain`,
`client_domain` and every `moz.domains` key), and this tool keeps normalising
what it reads, because handoff files already on disk carry the older `www.`
form. Both sides normalise; neither depends on the other having done it.

**Held to by:** `Serp-compete/tests/test_handoff_contract.py` (semantics) and
`tests/test_handoff_ingestion.py` (schema). Both call the real consumer. A
contract test that re-implements the contract tests nothing, which is how
`client_brand_names` stayed broken for months with a green suite.

---

## 1. The competitor handoff (`competitor_handoff_*.json`)

### 1.1 Version

| | |
|---|---|
| Producer writes | `schema_version`: `"2.0"`, or `"2.1"` with the optional `moz` block (since serp-discover's chunk D1, 2026-11-16). `"1.0"` / `"1.1"` are the same shape with page-relative ranks and still validate, because files on disk carry them |
| Consumer accepts | exactly the versions in `shared_config.json` → `handoff.supported_versions` |
| On an unlisted version | **hard fail**, before any API call — `main._unsupported_handoff_version` |
| On an absent version | hard fail |
| Empty `supported_versions` | means "accept any version" (the pre-2026-11-15 behaviour) |

Enforcement only helps while the config and the schema agree about which versions
exist. They disagreed until 2026-11-15: the config listed 2.0/2.1 while every real
handoff carried 1.0 or 1.1, so switching enforcement on would have rejected every
file (C-C-14). `test_the_configured_list_matches_what_the_schema_documents` now
fails if they drift apart again.

### 1.2 Fields the consumer reads

Every field below is read. A field the producer writes and the consumer silently
drops is a defect, not a harmless extra — `client_brand_names` was in the schema,
written by Tool 1, documented, and thrown on the floor, so the client's branded
demand was measured for the bare stem "livingsystems" (C-C-13).

| Handoff field | Becomes | Notes |
|---|---|---|
| `targets[].url` | `url` | fetched verbatim — **never rewritten**, see §1.3 |
| `targets[].domain` | `domain`, then the canonical group key | see §1.3 |
| `targets[].primary_keyword_for_url` | `primary_keyword` | the audit universe's keyword |
| `targets[].source_keyword` | `source_keyword` | |
| `targets[].rank` | `position` | absolute from schema v2.0; page-relative in v1.0/v1.1, see §1.4 |
| `targets[].entity_type` / `content_type` / `title` | same names | |
| `client_brand_names` | threaded to `run_comparison_features` | falls back to `client.name` on the legacy path |
| `client_domain` | the own-site checks | |
| `moz` (1.1, optional) | the anchor-text radar | see §3 |
| `exclusions` | read for the report's coverage line | |

**Not in the handoff, and not invented:** there is no `est_traffic` (it is set to
`0`, meaning *not measured*, and filled from DataForSEO's `etv` only when
DataForSEO reports the same url **and** keyword), and no PAA questions — see §4.

### 1.3 Domain canonical form

> **Owner decision 4 is SETTLED (2026-11-17, serp-discover's half of chunk X):**
> the producer strips `www.` at write time, in every host it publishes, and Tool 2
> keeps normalising at ingest. Both sides normalise. Tool 2's rule below is
> unchanged — it is what lets a handoff file written before that date, and any
> future breach of the producer's half, still group correctly.

Tool 1 now writes `targets[].domain`, `client_domain` and every `moz.domains` key
in the canonical form (`domain_utils.normalize_domain`), held to by
`serp-discover/tests/test_handoff_contract.py`. Until then `targets[].domain` was
canonical while the `moz.domains` keys beside it were `netloc.lower()` with `www.`
kept, so one handoff carried both spellings of one site; in the same function the
producer's client test was a substring test, so a bare `livingsystems.ca` in its
config dropped `notlivingsystems.ca` as "the client" and its omit list only
matched a host written in the same form. Handoff files already on disk carry the
old spellings.

**Tool 2's rule: the canonical form is lower-cased and `www.`-stripped, and it is
applied at the grouping boundary** — `audit_universe.group_targets_by_domain`.
One site is one audited competitor, whichever spellings arrive. Everything
downstream (the `competitors` and `competitor_metrics` rows, the brand token, the
omit-list test, the report's domain names, the Moz anchor scope) sees that one
form.

**Target URLs are never rewritten.** `https://www.x.com/a` is not guaranteed to be
the same page as `https://x.com/a`, so the URL the producer sent is the URL that
gets fetched. Canonicalisation is about *identity*, not about *addresses*.

What went wrong before 2026-11-16, and what each failure cost:

- `brand_utils.derive_brand_name("www.jerichocounselling.com")` returned the brand
  `"www"`. 15 of 34 domains in a real handoff carried the prefix and every one of
  them got the same meaningless brand (C-C-01, fixed in C1).
- Four entries on `omitted_domains.txt` leaked through, `psychologytoday.com`
  among them, so a directory the client had explicitly excluded was audited and
  named in a client report (fixed in C1).
- `run_audit` grouped on the raw string while the omit-list test normalised, so
  one site became two competitors — two DataForSEO enrichment calls, two
  `competitors` rows, the site's keyword count split in half for the barbell and
  positioning — and an omitted `www.` host was skipped while its bare twin was
  audited (fixed here, Chunk X).
- `moz.domains` keys kept `www.` while the run's domain list was canonical, so
  comparing them raw dropped every `www.` host from the anchor scope: a run whose
  Moz fetches had failed would have reported neither anchor risks nor unreadable
  domains (fixed here, Chunk X).

**If Tool 1 starts stripping at write time**, none of this code changes:
`normalise_domain` is idempotent.

**The prefixes stripped** are `www.` and `m.`, repeatedly, and only while a `.`
remains in what is left — the same rule and the same `ALIAS_PREFIXES` constant
as `serp-discover`'s `domain_utils.normalize_domain` (review chunk Y1). The two
tools must agree: a host the producer canonicalises one way and the consumer
another is two sites again at the join. The client's own entry in `moz.client`
is compared in this form too, so a handoff file already on disk carrying the
pre-chunk-X `www.` spelling still has its own anchors recognised.

**`client_domain` is checked, not assumed.** `handoff_moz.remember_client_domain`
retains the host the handoff published and `client_domain_mismatch` compares it
with `shared_config.client.domain`; `run_audit` prints the disagreement. A
handoff that does not say — the legacy `market_analysis_*.json` path, a manual
target list, or a pre-2.0 file — is silence, not a mismatch (P1).

### 1.4 Rank semantics

> **Review finding H1 / D-C-01 — FIXED on the serp-discover side 2026-11-16
> (its chunk D1). Files produced before that date are still affected.**

SerpAPI restarts `position` at 1 on every paginated page. Up to schema v1.1
`serp-discover` stored that value verbatim as `Rank` and `_merge_google_pages`
concatenated the pages **without an offset**, so in its 3-page Balanced mode the
ranks ran `1..9, 1..10, 1..10`: three targets each claimed rank 1, and a "rank 2"
might be the second result of page 3. The handoff inherited it, so
**`targets[].rank` is page-relative in schema v1.0 and v1.1.**

Chunk D1 renumbers the merged pages to the absolute SERP position and bumps the
handoff to **v2.0** (**v2.1** when the optional `moz` block is present). The
document's shape did not change — only the meaning of `rank` — which is exactly
why the version moved: it is the only way Tool 2 can tell the two conventions
apart in a file that otherwise looks identical.

Tool 2 cannot fix the producer. Its obligation is to know which convention it is
reading and to say so:

- `handoff.absolute_rank_versions` in `shared_config.json` lists the versions whose
  `rank` counts results across the whole SERP. It holds **`2.0` and `2.1`** as of
  2026-11-16.
- While the ingested version is not in that list, the briefing's coverage block
  carries a warning naming the version and telling the reader to read the `rank`
  column as "where on its SERP page", not as a market position. v1.0/v1.1 files
  already on disk still get that warning, correctly.
- `supported_versions` keeps 1.0 and 1.1 alongside 2.0/2.1, so an older handoff
  still validates rather than hard-failing; it is read with the warning attached.

Consequence for the scoring sections: `rank ≤ technical.magnet_max_position` is a
real top-10 test on a v2.x handoff. On the v1.x reference distribution it admitted
29 of 29 results, so it had no filtering effect at all; what it admits on absolute
ranks has **not been measured** — no v2.x handoff exists on disk yet. The same
applies to the barbell authority axis and the SERP-overlap comparison, which take
a genuine top-10 position as an input (see `docs/session_notes_2026-11-16.md` §1.4).

This value is **not editorial**: it records what the producer actually emits. Do
not set it to make a warning go away.

---

## 2. The AI-visibility export (`ai_visibility_export_*.json`)

**Selection contract (locked in Phase 0):** the newest export whose
`data_available` is true **by its in-file `source_run_ts`**, never by filename or
mtime. `sov.export_path` overrides.

**Shape read:** `engines`, `brand_mentions[{engine, brand, mention_count,
questions_total, is_client}]`, `ai_citations[{engine, domain, brand, is_client,
cite_count}]`, `answer_sentiment[{engine, brand, polarity}]`. The export itself was
checked on both sides and is sound.

**An engine must have answered something.** Tool 1 writes brand-mention rows for
engines it skipped or that failed, carrying `questions_total: 0` (D-C-05 /
D-C-11, open upstream). Publishing shares over those rows printed "0% mention
share, named in 0% of answers" for an engine that was never asked — a claim of
measured absence. So:

- an engine whose rows report no answered questions is **excluded** from the
  shares — its citations too, since an engine that answered nothing cannot have
  cited anything — and named in the report as *not measured*;
- an engine that answered questions and found nothing **keeps** its rows: a
  measured absence is a finding;
- `presence_rate` is `None`, not `0.0`, when no question count is available;
- the per-engine counts are persisted in `sov_coverage` so an **old** report can
  still say which engines were not measured.

**Coverage is three-valued, because the export cannot distinguish two of the
cases.** An engine listed in `engines` with no brand-mention rows at all may
have been asked its questions with no tracked brand coming back, or may never
have run. Nothing in the file separates those. So `sov_coverage.measured` is:

| Value | Meaning | Report wording |
|---|---|---|
| `1` | the export reports answered questions for it | its shares are published |
| `0` | the export reports zero answered questions | "Not measured this run" |
| `NULL` | the export carries no mention rows for it | "Coverage unknown" |

Recording the third case as `measured = 0` would claim knowledge the file does
not carry; recording it as `measured = 1, questions_total = 0` would be a row
contradicting itself.

**Brand matching.** The export carries display names ("Jericho Counselling") while
the run carries derived tokens ("jericho"). They are matched through
`derive_brand_name`, so a rival that is mentioned but never cited is classified as
a competitor instead of vanishing into "other" (C-M-11/C-M-17).

---

## 3. Moz

### 3.1 Two client shapes — unresolved

| | serp-discover | serp-compete |
|---|---|---|
| Endpoint | JSON-RPC `api.moz.com/jsonrpc` (migrated) | `api.moz.com/v2/url_metrics` |
| Page-authority key | its real-response fixture models `page` | reads `url`, falling back to `page` |

Compete reads **both** keys (`result.get('url') or result.get('page')`), so it
survives either shape. Which endpoint is live is **not settled** — C-C-04 is
PLAUSIBLE, not confirmed, and confirming it needs a live key, which no cloud
session has. `docs/TEST_RUN_CHECKLIST.md` §1b carries the check for the next live
run. Until then: one client shape for both tools remains an open Chunk X item.

### 3.2 A cached error is not a fresh outage

Tool 1 caches a competitor's Moz block for up to 30 days and **can cache it with a
failed sub-call inside** (D-C-10, open upstream), so the same error is re-served
every run until the cache expires.

`moz.domains[*].fetched_at` (per domain) is the collection time;
`moz.generated_at` is only when the handoff was assembled, and is an upper bound.
A block whose `fetched_at` trails `generated_at` by more than
`risk_signals.moz_cache_tolerance_hours` (default 24) was served from the cache,
so `anchor_coverage` reports `errored_cached` and `errored_age_unknown` as
**sub-counts of** `errored` — never additions to it — and the report says which.
An undated block is neither: "no date" is not evidence of a cache hit any more
than of a fresh outage.

### 3.3 Statuses

`ok` / `no_record` / `error` / `skipped_run_cap` / `skipped_quota` are
distinguished all the way to the report, because "we looked and found nothing" and
"we could not look" are different facts. A domain with no anchors is omitted from
the anchors map rather than mapped to an empty one, so absence can never be read
as "this domain has no spam anchors". The client's own anchors travel in
`moz.client`, not `moz.domains` — Tool 1 excludes the client from the competitor
list by design — and the client block wins for its own domain.

---

## 4. People Also Ask

`docs/FEATURE_GUIDE.md` §6.1 promised PAA context in the Bowen reframes. **The
handoff has no PAA field**, so the promise was dropped in chunk C1 rather than
quietly satisfied from somewhere else. `convert_handoff_to_targets` returns an
empty PAA map, and the reframe prompt carries the marker that it was generated
from the keyword, URL and score with no page content supplied.

There are two ways to restore it, and they are not equivalent:

1. **The producer sends them** (the Chunk X bullet's preference): Tool 1 already
   has the questions, so the handoff gains `paa_questions` per target and this
   tool reads them. No extra API spend, and the questions are the ones from the
   SERP Tool 1 actually measured.
2. **This tool fetches them itself.** `api_clients.DataForSEOClient.get_serp_data`
   already exists for exactly this — its docstring says "To get People Also Ask
   (PAA) data" — and **nothing calls it**. Wiring it would mean one
   `serp/google/organic/live/advanced` call per keyword, billed per call, on top
   of the per-domain `ranked_keywords` calls the run already makes. It would also
   need hardening first: it posts with a bare `requests.post` and no retry or
   backoff, predating `post_with_retries`, so it would reintroduce the failure
   class C-C-12 fixed everywhere else.

Until one of those is chosen the empty map is correct and is asserted by a test,
so it cannot be back-filled by accident.

(The legacy `market_analysis_*.json` path *does* carry `paa_questions`, which is
why `convert_legacy_to_targets` returns a populated map. That path is deprecated.)

---

## 5. Google Search Console

Both tools pull GSC independently, and until 2026-11-16 neither report said which
pull it was — so a figure from one was read beside a figure from the other as
though both described the same traffic.

| | serp-discover | serp-compete |
|---|---|---|
| Window | `gsc.lookback_days` (90) | `gsc_settings.date_range_days` (90) |
| Country | `gsc.country` (`ca` → `CAN`) | `gsc_settings.country` (`can`) |
| Device | `gsc.device` (`desktop`) | `gsc_settings.device` (`desktop`) |
| Paging | `GSC_PAGE_SIZE` × `GSC_MAX_PAGES` | `startRow`, `GSC_PAGE_SIZE` × `GSC_MAX_PAGES`, with a partial-data warning |

The serp-discover column names that tool's config keys, not values this repo has
read: nothing here can see them, so this table is the key to look in, and that
tool's own report states the pull it made (review chunk X; its filters were added
by its review chunk D5).

Both filters exist so the client's own clicks come from the same population as
the DataForSEO snapshot this repo requests — `dataforseo_snapshot` in
`shared_config.json` (`location_code` 2124, `device: desktop`), promoted out of
`api_clients.py` literals in chunk X. Every GSC report here —the briefing's GSC
section, `gsc_strike_list.md` and `gsc_strategic_gap.md` — prints the window,
country and device the pull used (`reporting.gsc_pull_note`, read from the same
config keys the fetcher reads) and **compares** each against that block rather
than asserting they agree: a country or device that does not match is printed as
not comparable, and a value GSC does not accept is named as a misconfiguration
rather than printed as a deliberate `all`.

---

## 6. What is still open

| Item | Owner / where |
|---|---|
| Decision 4 — which side canonicalises domains | owner; Tool 2 is defensive either way (§1.3) |
| H1 / D-C-01 — absolute ranks | fixed by serp-discover chunk D1, 2026-11-16 (handoff v2.0/2.1); Tool 2 still warns on a v1.x file (§1.4) |
| C-C-04 — one Moz client shape, live endpoint | needs a live Moz key (§3.1) |
| D-C-05 / D-C-11 — engines with zero answers | serp-discover chunk D3; Tool 2 excludes them (§2) |
| D-C-10 — cached Moz errors | serp-discover chunk D2; Tool 2 dates them (§3.2) |
| `paa_questions` in the handoff | serp-discover, if the promise is to be restored (§4) |
| One agreed GSC window, stated in both reports | both repos (§5) |
| A producer-side contract test | serp-discover |

Nothing in this document licenses guessing at any of the above. Where the producer
is wrong and Tool 2 cannot fix it, Tool 2's job is to be explicit about what it
received — not to correct it silently or to report it as if it were right.
