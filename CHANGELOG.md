# Changelog

All notable changes to Serp-compete (Tool 2).

The version is written in `Serp-compete/src/_version.py` and nowhere else.
The newest entry here must name the same version — a test fails the build
otherwise. `serp-discover` (Tool 1) carries the same version deliberately:
Tool 1 hands this tool a `competitor_handoff_*.json` and the review that
produced v1.5.0 changed both sides of that contract.

## [1.5.0] — 2026-11-19

The first numbered release. The minor digit carries the 2026-11-04
correctness review, run across both tools: 87 indexed findings, closed in
chunks X, D2–D6 and Y1–Y17.

### The finding that invalidated every earlier briefing

**This tool audited a universe the handoff never named.** `main.py` grouped
the handoff's targets by domain and then discarded them, auditing each
domain's own DataForSEO top-10 instead — Canada, API default order, no
position filter. `group_targets` was never read. Run 11's "traffic magnets"
were "archdiocese of vancouver", "airport heights medical clinic" (a St
John's, Newfoundland page) and "555 homer street". Every downstream section
inherited that universe: systemic vacuums, the automated reframes (GPT-4o
spent on the Archdiocese), overlap cells, barbell top-10 counts, velocity
and the authority cliff.

### Absence is stated, never implied

- A Moz failure had become Page Authority 0, which made a competitor a
  "Fragile Magnet — publish now" with an invented authority drift of −35. A
  failed search-volume call had become "0 branded demand".
- Rank, authority and demand each now carry a measured / unmeasured state
  that survives into the briefing, rather than a zero that reads as a
  finding.

### The briefing's prose got a file

Until this release every sentence the briefing printed was a Python literal:
the caveats, the comparability warnings, the "why this cell is blank"
lines, the section introductions. Tool 1 had ten editorial text files and
this tool had none. They now live in `briefing_messages.json`.

The two failure modes are deliberately opposite: a missing or malformed
file raises, because a briefing rendered without its hedges states every
figure as fact; a missing key prints a visible marker and is counted, so a
half-finished edit shows where the hole is instead of vanishing.

Three things made this a defect rather than a preference — the EEAT
heuristic caveat existed in three wordings, one of them already in
`shared_config.json` and read by nothing; the handoff's page-relative ranks
were warned about in four separately worded places, which no
de-duplication finds because they are not duplicates; and `UNKNOWN_CELL`
had a bare `"—"` duplicate beside it.

### Comparability is stated

Sections that put Google Search Console clicks beside DataForSEO ranks now
name which country and device each side was measured over, and say plainly
when the two are not comparable. An unrecognised `device` setting is its own
state: it pulls every device exactly as `all` does, but it is a typo rather
than a decision, and printing the two alike hid the misconfiguration.

### Added

- `Serp-compete/src/_version.py`, `CHANGELOG.md`, and the version stamped
  into the briefing's header through `briefing_messages.json`.
- A database-path config key and a lock timeout, replacing a bare relative
  literal that created an empty database beside whatever directory the
  reader was started from.
- Run coverage in the artefact rather than only in the console: skipped
  domains, failed cleanup steps, unmeasured page authority.
- A client-mismatch warning in the briefing when the handoff names a
  different client from this repo's configuration. Without it the report
  read clean while every figure compared one client's SERPs with another's
  settings.
