# Serp-Compete — Feature Guide & Report Reference

**Who this is for:** anyone reading a Serp-Compete audit who wants to *understand the
outputs* — not just run the tool. For each feature it answers three questions in the
same shape:

> **What it does** → **What it lets you understand** → **What you can then do about it.**

If you only remember one thing: Serp-Compete finds keywords where competitors rank
using *medical-model* language (symptom/diagnosis/treatment) and shows you where a
*systems-approach* (relationship/process, Bowen) page could realistically compete —
then tells you, page by page, how beatable each competitor actually is.

For install/run instructions and configuration, see [USER_MANUAL.md](USER_MANUAL.md)
and `README.md`. This document is about *meaning*.

---

## 1. How one audit run flows (the big picture)

A run moves left-to-right. Each stage adds a layer of understanding to the same set
of competitor pages:

```
Serp-Discover handoff (competitor_handoff_*.json)
      │
      ▼
Filter competitors  →  For each competitor page:  scrape → semantic score → EEAT → GEO
      │                                    (or reuse a ≤7-day cached audit)
      ▼
Per competitor domain: internal-linking cluster
      │
      ▼
Rank the "traffic magnets"  →  flag "systemic vacuums"
      │
      ▼
Your own site (Google Search Console gaps)  →  Automated Bowen reframes (OpenAI)
      │
      ▼
Strategic Briefing (Markdown)  +  audit_results workbook (Excel)
```

Every feature below is one of those layers, and every layer surfaces in a specific
place in the report. The "**Where you see it**" line tells you which section or Excel
sheet to look at.

---

## 2. Input & gatekeeping features

### 2.1 Competitor handoff ingestion
**What it does:** reads a `competitor_handoff_*.json` file produced by the companion
tool **Serp-Discover** — the list of your target keywords and the competitor
domains/URLs that rank for them. (Supported handoff versions are listed in
`shared_config.json → handoff.supported_versions`.)

**What it lets you understand:** the audit is only ever as complete as this input. The
keywords and competitors you see analysed are the ones Serp-Discover handed over —
nothing is invented.

**What you can then do:** if a competitor or keyword you care about is missing, widen
the search in Serp-Discover and re-run — don't expect Serp-Compete to discover new
keywords on its own.

### 2.2 High-authority filter (Page Authority > 50 is skipped)
**What it does:** before auditing a domain, it checks the domain's average Moz Page
Authority. If it exceeds **50**, the whole domain is skipped as "too entrenched."

**What it lets you understand:** the report deliberately concentrates on *reachable*
competitors. A giant like a national health portal is filtered out on purpose, so its
absence is a design choice, not missing data.

**What you can then do:** trust that everything left in the report is a realistic
reframing target. If you specifically want to study an excluded heavyweight, note that
Serp-Compete is not the tool for it (that's a backlink/authority job — see §7).

### 2.3 The 7-day audit cache (and carry-forward)
**What it does:** a URL that was already audited in the last 7 days is reused from the
database instead of being re-scraped. When that happens, the page's EEAT and GEO
profiles — and, for an all-cached competitor, its cluster result — are **carried
forward** from the most recent real scrape rather than recomputed.

**What it lets you understand:** frequent re-runs are cheap and gentle on competitor
servers, and a re-run won't blank out the EEAT/GEO/cluster sections just because it
served pages from cache. The console prints an **"Enrichment coverage"** line each run —
`fresh / carried-forward / cache-hit-no-prior / failed` — so you can always tell
*computed-this-run* from *reused-from-cache* from *failed*.

**What you can then do:** if you need genuinely fresh structural numbers (e.g. a
competitor just relaunched a page), run the audit outside the 7-day window or after the
cache expires. A carried-forward profile keeps its original timestamp, so it never
pretends to be newer than it is.

---

## 3. Content-analysis features (the core scoring)

### 3.1 Semantic analysis — Medical vs. Systems language
**What it does:** scrapes each competitor page and counts vocabulary in three tiers:

| Tier | Meaning | Example words |
|---|---|---|
| **Tier 1 — Medical** | symptom-focused, diagnostic | symptom, diagnosis, disorder, treatment |
| **Tier 2 — Systems** | relational/process | differentiation, triangles, family process |
| **Tier 3 — Bowen** | deep systemic | emotional fusion, pursuer-distancer, differentiation of self |

It produces a **Medical Score** and a weighted **Systems Score** (Tier 3 counts more
than Tier 2), then assigns a **Systemic Label** of **Standard** or **Surface-Level**.
A page is **Surface-Level** when it leans heavily on medical language but has no deep
Bowen (Tier 3) content at all. (Exact weights/thresholds live in `shared_config.json`
and `src/scoring_logic.py` — editable without code changes.)

**What it lets you understand:** *how* a competitor is winning a keyword — by
symptom-and-label framing, or by genuine relational depth. A high Medical Score with a
Surface-Level label means the page ranks despite saying nothing systemic.

**What you can then do:** target the Surface-Level / high-Medical pages first. They rank
on demand you can serve better with a differentiation- and process-oriented page.

**Where you see it:** the *Competitor Ranking Summary* ("systemic_depth" column) and
every *Traffic Magnets* row (medical_score / systems_score / systemic_label).

### 3.2 EEAT scoring — how credible the competitor page looks
**What it does:** scores each page on four credibility dimensions Google is known to
value — **E**xperience, **E**xpertise, **A**uthoritativeness, **T**rustworthiness —
from on-page signals (author byline, credentials, publish/update dates, schema, HTTPS,
contact/privacy links, external links). Each page also gets a **confidence** rating.

**What it lets you understand:** how strong the *credibility signals* are on the page
you'd be competing against — and, just as usefully, where they're weak.

**What you can then do:** if a competitor's EEAT is low (no author, no dates, no
schema), you can out-signal them by publishing a page with a credentialed author
byline, dates, and structured data. If their EEAT is high, plan to *match* those
signals, not just the words.

**Where you see it:** *EEAT Competitive Analysis (Heuristic)* section and the *EEAT
Scores* Excel sheet.

> **Read it honestly:** these are heuristic proxies built from SEO conventions, **not**
> Google's private EEAT model. Use them to *compare* competitors, not as an absolute
> verdict.

### 3.3 Internal-linking cluster detection — how well-defended a competitor is
**What it does:** looks at how a competitor's scraped pages link to each other and
classifies the domain as **isolated**, **linked**, **clustered**, or
**insufficient_data**. A page that several others link to is a "hub" (the in-degree
threshold and minimum page count are in `shared_config.json → cluster_thresholds`,
defaults 2 and 3).

**What it lets you understand:** whether a competitor has built a mutually-reinforcing
topic cluster (hard to displace) or a set of orphan pages (easier to overtake).

**What you can then do:** prioritise **isolated**/**linked** competitors as easier
wins; for **clustered** ones, plan to build your own supporting cluster, not a single
page. Treat **insufficient_data** as "not enough evidence," not "no cluster."

**Where you see it:** *Internal Linking Cluster Analysis* section and the *Cluster
Analysis* Excel sheet.

> **Read it honestly:** the tool samples only up to **3 pages** per competitor, so
> `insufficient_data` is common and the view is a keyhole, not the whole site.

### 3.4 GEO / Extractability — *why* an AI answer engine would cite the page  ⭐ newest
**What it does:** profiles each competitor page for the *structural* signals that make
AI answer engines (and featured snippets) likely to **quote** it: schema markup
(FAQPage, Article, Organization, Person, LocalBusiness), a **credentialed** author
byline, **question-shaped headings** (a heading that is genuinely a question — ends in
"?" and opens with how/what/why/etc.), and **freshness** (publish/update dates). It
rolls these into a tier — **Strong / Moderate / Weak** (or **Unknown** if the page
couldn't be fetched) — and writes a plain-language **"why cited"** sentence.

**What it lets you understand:** not just whether a competitor ranks, but the concrete
reasons an AI engine finds their page *easy to extract and quote* — the mechanics
behind "why do they keep getting cited?"

**What you can then do:** match or exceed those exact structures on your equivalent
page. If the competitor's "why cited" says *"FAQPage schema + credentialed author +
2 question-shaped headings,"* that's your build checklist.

**Where you see it:** *GEO / Extractability — Why Competitors Get Cited* (sorted
Strong→Weak) and the *GEO Extractability* Excel sheet.

> **Read it honestly:** these are heuristic proxies for citability, **not** measured
> citations. Two signals from the design (answer-first placement, and FAQ answers
> embedded in raw HTML) need rendering analysis the scraper doesn't do yet, so they're
> declared "not measured" rather than guessed.

---

## 4. Opportunity features (where to act)

### 4.1 Traffic Magnets
**What it does:** ranks the audited competitor pages by estimated traffic and shows
each one's keyword, traffic, medical/systems scores, and systemic label.

**What it lets you understand:** which competitor pages are worth the most attention —
the high-traffic keywords where a better page would capture real demand.

**What you can then do:** treat the top of this list as your content backlog, richest
opportunity first.

**Where you see it:** *Identified 'Traffic Magnets'* section and the *Traffic Magnets*
Excel sheet.

### 4.2 Systemic Vacuums (strategic targets)
**What it does:** from the traffic magnets, isolates the pages that score **zero** on
systems language **or** are labelled **Surface-Level** — high demand met only by
medical-model or shallow content.

**What it lets you understand:** the cleanest openings — keywords with proven traffic
and *no* real systemic answer competing.

**What you can then do:** write the differentiation/emotional-process page for these
exact keywords first; you're filling a vacuum, not fighting for a crowded term.

**Where you see it:** *⚡ Strategic Targets: Systemic Vacuums* (a sub-list under Traffic
Magnets).

### 4.3 Your own site — Google Search Console gaps
**What it does:** analyses *your* site's Search Console data for **High-Impression /
Low-CTR** queries (seen but not clicked), **Page-2 targets** (positions 11–20), and
**clinical mismatches** (your systems pages surfacing for medical queries, or vice
versa).

**What it lets you understand:** the opportunities you already own — pages a nudge away
from Page 1, and titles that aren't earning the click.

**What you can then do:** rewrite meta titles with systemic depth for the low-CTR
queries; give the Page-2 near-misses a focused boost before starting anything new.

**Where you see it:** *📈 Internal GSC Performance Gaps* (only appears when GSC data is
available for the run).

---

## 5. Movement-over-time features (longitudinal memory)

Each run records a snapshot, so later runs can compare against earlier ones.

### 5.1 Market Velocity & Volatility alerts
**What it does:** flags competitors whose rank or authority has shifted meaningfully
between runs (*Market Velocity Alerts*, *Volatility Alerts*).

**What it lets you understand:** direction of travel — who's rising, who's slipping —
which a single snapshot can't show.

**What you can then do:** re-prioritise. A competitor gaining fast may be worth
answering now; one falling may be about to open a gap.

### 5.2 Fragile-Magnet / Feasibility-Drift alerts
**What it does:** highlights high-value competitor pages that are *losing* Page
Authority between runs.

**What it lets you understand:** timing — a lucrative competitor page that's weakening
is the moment to strike.

**What you can then do:** publish your competing "systems approach" page while their
authority is dropping, to overtake them on the way down.

**Where you see it:** *⚡ Market Velocity Alerts*, *📉 Volatility Alerts*, and *🚩 Expert
Alerts: Fragile Magnets*.

---

## 6. Action features (drafting help)

### 6.1 Automated Bowen Reframes (OpenAI `gpt-4o`)
**What it does:** for the strategic openings, generates a structured content outline
that reframes the competitor's medical-model angle into a Bowen systems approach,
weaving in the real "People Also Ask" anxieties captured for that keyword.

**What it lets you understand:** a concrete starting structure — how the systemic
counter-argument to a given competitor page could be organised.

**What you can then do:** hand it to a writer as a scaffold. It is a *starting point*,
not publish-ready copy — the clinical judgement and voice are still yours.

**Where you see it:** *🎯 Automated Bowen Reframes* section and the *Automated Reframes*
Excel sheet. (Token spend is reported under *💰 AI Token Usage*.)

---

## 7. What Serp-Compete deliberately does **not** do

**Backlink / off-site authority analysis is out of scope.** The tool reads on-page and
structural signals only. It uses Domain/Page Authority as its single authority proxy
and does **not** map competitors' backlink profiles, toxic links, or referring-domain
diversity — that needs a paid link-graph provider and is judged low-ROI here. So "how
many sites link to them?" is a question this report intentionally can't answer.

---

## 8. Reading the two output files

Every run writes two files (named by run number, e.g. `strategic_briefing_run_12.md`
and `audit_results_run_12.xlsx`).

### 8.1 Strategic Briefing (Markdown) — section-by-section
| Section | One-line meaning | Your move |
|---|---|---|
| Executive Summary | What this run set out to find | Orientation |
| 📈 Internal GSC Performance Gaps | Your own low-CTR / Page-2 / mismatch opportunities | Fix titles, boost near-misses |
| 💰 AI Token Usage | Cost of the reframes this run | Budget awareness |
| 📉 / ⚡ / 🚩 Alerts | Who moved since last run | Re-prioritise & time your strike |
| Competitor Ranking Summary | Each competitor's depth, position, recommended strategy | Pick who to target |
| EEAT Competitive Analysis | How credible each page *looks* | Out-signal the weak, match the strong |
| Internal Linking Cluster Analysis | How defended each competitor is | Prefer isolated targets |
| GEO / Extractability | *Why* AI engines cite each page | Copy the structure that earns citations |
| Identified 'Traffic Magnets' | Highest-value keyword pages | Your content backlog |
| ⚡ Systemic Vacuums | Traffic with no systemic answer | Write these first |
| 🎯 Automated Bowen Reframes | Draft outlines to counter each page | Brief your writer |

### 8.2 Excel workbook — sheet-by-sheet
`Competitor Summary` · `Traffic Magnets` · `EEAT Scores` · `Cluster Analysis` ·
`GEO Extractability` · `Automated Reframes` · `AI Usage Stats`. Each sheet is the
tabular form of the matching briefing section — use it to sort/filter (e.g. sort
*GEO Extractability* by tier, or *Traffic Magnets* by traffic) and to paste into a
content plan. A sheet only appears if that run produced data for it.

---

## 9. How to read the numbers honestly (limitations in one place)

- **EEAT, cluster, and GEO tiers are heuristic proxies**, not ground truth or Google's
  real models. They're for *comparing* competitors and building a checklist — not for
  declaring anyone objectively good or bad.
- **Only up to 3 pages per competitor are sampled.** Cluster analysis especially is a
  keyhole view; `insufficient_data` means "not enough sampled," not "no structure."
- **GEO leaves two signals unmeasured** (answer-first placement, FAQ-answers-in-raw-HTML)
  and says so, rather than approximating them.
- **Cache vs. fresh:** on a re-run within 7 days, EEAT/GEO/cluster figures may be
  *carried forward* from the last real scrape (timestamps show their true age). A
  competitor that stays cached every run won't get its cluster recomputed until it's
  re-scraped. The console **"Enrichment coverage"** line tells you, each run, how many
  profiles were fresh vs. carried vs. failed — check it if a section looks unchanged.
- **High-authority domains (avg Page Authority > 50) are absent by design.**
- **Reframes are AI-drafted scaffolds**, not clinical copy — always apply your own
  judgement.

---

*This guide describes the behaviour shipped in the code as of the SC-1 (GEO /
Extractability) release. If a feature's behaviour changes, update this file alongside
`suite_enhancement_spec_SERPCOMPETE_v1.md`.*
