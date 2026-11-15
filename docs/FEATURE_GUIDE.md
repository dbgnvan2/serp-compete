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

### 2.1 Competitor handoff ingestion — the audit universe
**What it does:** reads a `competitor_handoff_*.json` file produced by the companion
tool **Serp-Discover** — the list of your target keywords and the competitor
domains/URLs that rank for them — and audits **those URLs on those keywords**. Each
target's `url`, its `primary_keyword_for_url` and the `rank` Serp-Discover measured are
what the audit works from. (Supported handoff versions are listed in
`shared_config.json → handoff.supported_versions`.)

DataForSEO's per-domain `ranked_keywords` list is still fetched, but only as an
**additional enrichment**, and it is filtered before anything is audited. An
enrichment keyword is kept only when it is already in the handoff keyword set **or**
it carries a clinical term from `shared_config.json → clinical.*`, and it is dropped
outright when it contains the competitor's own brand token. Every keyword in the
report is labelled with its source — `handoff` or `ranked_keywords` — in the *Keyword
provenance* line under *Competitor Ranking Summary*, in the `keyword_source` column of
the Traffic-Magnet table, and in each Systemic-Vacuum bullet.

**What it lets you understand:** which numbers are measured facts and which are
enrichment. A `handoff` keyword is one Serp-Discover found the URL ranking for; a
`ranked_keywords` keyword is one DataForSEO associates with the domain and that
survived the relevance filter. Nothing is invented, and nothing off-topic is audited.

**What you can then do:** if a competitor or keyword you care about is missing, widen
the search in Serp-Discover and re-run — don't expect Serp-Compete to discover new
keywords on its own. If a domain shows only `handoff` keywords, DataForSEO returned no
usable enrichment for it; the console says so per domain.

> **Fixed 2026-11-15 (C-M-01, owner decision 1b).** Until this change the handoff
> targets were grouped by domain and then discarded: the audit worked from each
> domain's DataForSEO top-10 (Canada, API default order, no position filter). That is
> why run_11's "Traffic Magnets" were `archdiocese of vancouver`, `airport heights
> medical clinic` (a St John's NL page) and `555 homer street`. Reports generated
> before this date describe that sample, not your target keywords.

### 2.2 High-authority filter (Page Authority > 50 is skipped)
**What it does:** before auditing a domain, it checks the domain's average Moz Page
Authority. If it exceeds **50**, the whole domain is skipped as "too entrenched."

**What it lets you understand:** the report deliberately concentrates on *reachable*
competitors. A giant like a national health portal is filtered out on purpose, so its
absence is a design choice, not missing data.

**What you can then do:** trust that everything left in the report is a realistic
reframing target. If you specifically want to study an excluded heavyweight, note that
Serp-Compete is not the tool for it (that's a backlink/authority job — see §7).

> **When Moz does not answer, the filter cannot be applied** — and the briefing says so
> under *Run coverage* rather than letting it pass silently. Before 2026-11-15 a Moz
> failure made the average Page Authority 0, which disabled this filter without a word
> and wrote 0 into the competitor's authority figure as though it had been measured
> (C-C-03). Unknown authority is now NULL, no `competitors` row is written, and the
> domain is named in the report.

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
**What it does:** of the audited competitor pages, shows the ones that meet all three
parts of the magnet definition, richest estimated traffic first:

| Part of the definition | How it is tested |
|---|---|
| **Ranks well** | the handoff `rank` Serp-Discover measured is ≤ `technical.magnet_max_position` (10) |
| **Uses medical language** | `medical_score` ≥ `technical.vacuum_min_medical` (10) |
| **On a keyword that matters** | the keyword is in the handoff set or carries a clinical term, and is not the competitor's own brand token |

The section header states how many of the audited pages qualified ("Showing 3 of 97"),
and the filter itself is printed under it, so an empty list reads as "nothing met the
definition", never as "nothing was audited".

**What it lets you understand:** which competitor pages are worth the most attention —
pages already ranking for one of *your* keywords, on medical-model language a systemic
page can out-argue.

**What you can then do:** treat the top of this list as your content backlog, richest
opportunity first.

**Where you see it:** *Identified 'Traffic Magnets'* section and the *Traffic Magnets*
Excel sheet. `est_traffic` is DataForSEO's estimated monthly visits for that
keyword×position; **0 means not measured**, not "no traffic" — the handoff carries no
traffic estimate, so a figure appears only where DataForSEO reported the same URL and
keyword.

### 4.2 Systemic Vacuums (strategic targets)
**What it does:** from the traffic magnets — so all three conditions above already
hold — isolates the pages that score **zero** on systems language **or** are labelled
**Surface-Level**: your keyword, met by a well-ranking page with medical vocabulary and
no systemic framing.

**What it lets you understand:** the cleanest openings — keywords with proven ranking
and *no* real systemic answer competing. These are also exactly the pages §6.1 drafts a
reframe for; the two lists cannot disagree, because they are one database query.

**What you can then do:** write the differentiation/emotional-process page for these
exact keywords first; you're filling a vacuum, not fighting for a crowded term.

**Where you see it:** *⚡ Strategic Targets: Systemic Vacuums* (a sub-list under Traffic
Magnets). Each bullet names the keyword's source and handoff rank.

> **Fixed 2026-11-15 (C-M-02, owner decision 2).** The previous rule was
> `systems_score = 0 OR systemic_label = 'Surface-Level'`, ordered by estimated traffic
> alone — no medical-language condition, no position condition, no relevance test. A
> page with no vocabulary of any kind (empty, blocked-but-200, or simply off-topic)
> sorted to the top: run_11 named `rcav.org` (medical 0, systems 0) a *primary target
> for content reframing*. `technical.vacuum_min_medical` is an **editorial, uncalibrated**
> floor as of 2026-11-14, started at 10 to match the `penalty_thresholds.tier_1_max`
> value in use at the time.

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

### 4.4 SERP Overlap & Differentiation Gap — where you collide vs. where you're safe  ⭐ newest
**What it does:** builds a keyword-by-keyword matrix of *who ranks where* — your
tracked competitors' SERP positions (from the audit) plus your own positions (from
Google Search Console) — and sorts every target keyword into one of five cells:
**shared_commodity** (you + several rivals on a commoditized SERP),
**shared_defensible** (you + a rival or two, still differentiated), **exclusive_self**
(only you rank), **exclusive_competitor** (rivals rank, you're absent), or **absent**.
It also flags the keywords *every* tracked rival ranks for but you don't.

**What it lets you understand:** the shape of the battlefield — which keywords are
crowded, commoditized ground (high AI-absorption risk, low differentiation payoff)
versus where you hold a defensible or exclusive position, and exactly where rivals are
winning while you're not on the board.

**What you can then do:** work the two action queues. **exclusive-competitor**
(especially "every rival ranks, you don't") = your clearest content gaps to fill;
**shared-commodity** = differentiate hard or deprioritize (don't fight for
undifferentiated ground). The feasibility read (your Domain Authority vs each
competitor's) flags which are realistic.

> **Fixed 2026-11-15.** The per-cell figure is now labelled **best-rival ETV**: it
> is `MAX(competitor_metrics.traffic)` per keyword — the DataForSEO estimated monthly
> visits of the best-ranking audited rival — summed per cell. It was presented as
> "Volume by cell (est. traffic)" and stored in a column called `keyword_volume`,
> which reads as search demand (C-M-20).

**Where you see it:** the *SERP Overlap & Differentiation Gap* section (cell
distribution + both action queues) and the *SERP Overlap* Excel sheet. It **folds in**
the Systemic Vacuum list rather than repeating it.

> **Read it honestly:** competitor positions are SERP-measured; your `self_position`
> is first-party GSC (a keyword you rank for only shows if it's in your Search Console
> data). If GSC is unavailable for a run, your presence is marked **unknown** (not
> "absent") and those keywords are withheld from the action queues. "Commodity" is a
> **local overlap-density proxy** (how many rivals share the SERP) — a strategic
> framing, not a measured index. A companion **Competitor Feasibility** read (your
> Domain Authority vs each competitor's) flags which targets are realistic — **for
> the competitors this run audited**. Until 2026-11-15 that table read every domain
> ever stored, so it listed competitors that were not in the current handoff at all,
> with authority figures of unknown age, while the Barbell section beside it (reading
> the same column) listed only this run's (C-C-10).

### 4.5 Barbell Positioning — the shape of the competitive field  ⭐ newest
**What it does:** places every competitor (and you) on a 2×2 — an **authority** axis
(Moz Domain Authority plus how many keywords they rank top-10 for — the *same* formula
for you and competitors) against a **focus** axis (how concentrated their language
identity is: a clear
medical *or* systems voice = focused; a mix = broad). Each domain lands in a quadrant:
**authoritative** (big & credible), **niche_owner** (small & sharply focused),
**middle** (undifferentiated), or **emerging** / **insufficient_data** when there's too
little signal to place them.

**What it lets you understand:** the strategic shape of your market. The "barbell"
idea: winners sit at the two ends — large-and-authoritative or small-and-niche — while
the **undifferentiated middle loses**. It shows which competitors are entrenched
authorities, which are focused specialists, and which are stuck in the beatable middle.

**What you can then do:** pick your play by where rivals sit. Middle-quadrant
competitors are the softest targets. To win, lean into an end of the barbell — a
sharply focused systemic niche (`niche_owner`) rather than competing broadly with an
`authoritative` incumbent.

**Where you see it:** the *Barbell Positioning Diagnostic* section (quadrant
distribution + a per-domain authority/focus/quadrant table, with **you** always plotted
and the danger-zone middle flagged) and the *Positioning* Excel sheet.

> **Read it honestly:** these are heuristic axes, not a measured market model. "Focus"
> is *tier-identity concentration* (medical vs. systems language), not topic-count
> breadth. You're always plotted, but since Search Console (not a page audit) feeds your
> own axes, a run without GSC leaves you `insufficient_data` rather than mis-placed.

### 4.6 AI Answer Share-of-Voice — whose brand the models return  ⭐ newest
**What it does:** consumes serp-discover's AI-visibility probes (it does *not* re-ask the
models here) and, per engine (Gemini / ChatGPT / Perplexity / …), computes what share of
brand mentions and cited sources are yours vs each competitor's vs "other," plus
per-competitor sentiment and a "cited but you're not" gap list.

**What it lets you understand:** who wins the *AI answer*, not just the blue links. When
someone asks an engine a category question, is your brand named and your site cited, or are
competitors taking the airtime? The gap list shows which competitor domains an engine trusts
but never cites you alongside.

**What you can then do:** focus your GEO/citation work (§3.4) on the engines where your
mention-share is low, and treat the "cited but you're not" domains as coverage/outreach targets.

**Where you see it:** the *Competitive AI Share-of-Voice* section (per-engine leaderboards +
gaps) and the *AI Share-of-Voice* Excel sheet.

> **Read it honestly:** rolling snapshots — LLM answers swing between runs and model versions.
> If serp-discover hasn't produced an AI-visibility export, the section is simply absent (not zero).

### 4.7 Branded-Demand Benchmark — how your brand pull compares  ⭐ newest
**What it does:** estimates each competitor's *branded* search demand (searches for
"<brand>", "<brand> reviews/pricing/…") from public search volume, and ranks you against them
by branded volume, share, and growth. The brand searched is the **display brand**
reassembled from the domain — "Lavender Counselling", not the bare stem "lavender" —
and your own row uses the `client_brand_names` the handoff carries (falling back to
`client.name`), not your domain stem. The exact query strings are in the `queries`
column of the *Branded Demand* Excel sheet.

**What it lets you understand:** the strength of each brand's *pull* — how many people already
search for them by name. Branded demand is a lead indicator of market presence that on-page
SEO can't fake.

**What you can then do:** see whether you compete on brand or only on generic keywords, and
spot competitors whose branded demand is growing fast (rising threats) or shrinking (gaps).

**Where you see it:** the *Branded-Demand Benchmark* section (you ⭐ vs competitors) and the
*Branded Demand* Excel sheet.

> **Read it honestly:** competitor figures are *search-volume estimates*, not click-measured
> (only your own can be GSC-anchored, when that export exists). Generic brand names are pruned
> rather than guessed; if the volume source is down for a run, the section says so, not zeros.
> An **ambiguous** brand name — one whose bare stem pulls at least
> `branded_demand.ambiguous_brand_ratio` (10, editorial and uncalibrated) times the
> practice name's volume — is labelled `ambiguous_brand`: its share and growth are
> withheld and it leaves the share denominator, because that demand cannot be
> attributed to the practice.
>
> **Fixed 2026-11-15 (C-M-03, C-C-01, C-C-13).** The volume was previously fetched for
> the bare matching token, so "lavender", "bach", "clear", "coast" and "wong" measured
> demand for plants, composers, shorelines and surnames; every `www.` domain searched
> for the literal term "www" and so shared one identical row; and your own row used the
> stem `livingsystems` because the code read a `client.brand_names` key that does not
> exist in `shared_config.json`.

### 4.8 YouTube Presence — who in your competitive set is on YouTube  ⭐ newest
**What it does:** for each competitor (and you), asks the official **YouTube Data API** whether
a channel exists and, if so, its subscribers, last-upload date, recent-activity count, and a
**match confidence**. It *discovers* which rivals run channels instead of you researching it by
hand (this is the retired "do competitors have channels?" question, now answered in-audit).

**What it lets you understand:** where the competitive attention is moving off-SERP — which
rivals are building a YouTube audience, how big, and how actively they publish.

**What you can then do:** decide whether YouTube is a channel worth entering, and (if a deeper
transcript/brand-mention dive is ever built as Phase 2) hand off only the channels worth diving.

**Where you see it:** the *YouTube Presence* section (you ⭐) and the *YouTube Presence* Excel
sheet — per competitor: has-channel?, handle, subscribers, last upload, recent uploads,
confidence, status.

> **Read it honestly:** a same-name channel is **never** auto-confirmed. `confirmed` means the
> domain is in the channel's About **or** the handle matches; a bare name match is a
> **`candidate`** you confirm yourself (see `TEST_RUN_CHECKLIST.md`) before trusting it —
> confirmed ones can be pinned in `youtube_presence.channel_map` so future runs cost ~1 quota
> unit instead of ~100. `none_found` = no channel; `error` = couldn't check this run (quota /
> network) — retryable, **never** recorded as a definitive "no". **Needs a free `YOUTUBE_API_KEY`
> in the env**; with no key the whole section is simply absent (not zeros, not an error).

## 5. Movement-over-time features (longitudinal memory)

Each run records a snapshot, so later runs can compare against earlier ones.

### 5.1 Volatility alerts
**What it does:** flags competitors whose *average position* moved by 3 places or more
between this run and the previous one (*Volatility Alerts*).

**What it lets you understand:** direction of travel — who's rising, who's slipping —
which a single snapshot can't show.

**What you can then do:** re-prioritise. A competitor gaining fast may be worth
answering now; one falling may be about to open a gap.

**Where you see it:** *📉 Volatility Alerts*.

### 5.2 Fragile-Magnet alerts (authority drift)
**What it does:** highlights competitor pages that are *losing* Moz Page Authority —
a drop of at least `risk_signals.pa_drop_min` (3) between this run and the previous run
that saw the same page. The rank move is reported beside it as evidence; it does not
trigger the alert on its own.

**What it lets you understand:** timing — a lucrative competitor page that's weakening
is the moment to strike.

**What you can then do:** publish your competing "systems approach" page while their
authority is dropping, to overtake them on the way down.

**Where you see it:** *🚩 Expert Alerts: Fragile Magnets (authority drift)*.

> **Read it honestly.** A page whose authority was not measured in **both** runs is
> absent from this list: unknown, not unchanged. The threshold is editorial and
> uncalibrated (2026-11-15).
>
> **Fixed 2026-11-15 (C-C-03, C-C-05, C-M-06).** There were two independent
> Fragile-Magnet detectors with different thresholds, rendering under two headings for
> the same event, and all three of their inputs were wrong: a Moz outage arrived as
> Page Authority **0**, so every page of every affected domain showed a ~-35 authority
> collapse (and the next working run showed +35); any drop at all qualified, so 38 → 37
> produced "Strike this page now"; and the detector was not scoped to the run, so a
> competitor skipped this run (omitted, PA-filtered, DataForSEO 429, dropped from the
> handoff) kept its last recorded drop in every later briefing, indefinitely. There is
> now one detector, thresholded, run-scoped, and silent when either side is unmeasured.

---

### 5.3 Reputation-Risk Radar — penalty-pattern early warning  ⭐ newest
**What it does:** scans for patterns Google is known to act on — a sudden visibility collapse
(`visibility_cliff`), an off-topic *commercial* subfolder on an otherwise on-topic domain
(`parasite_subfolder` / site-reputation abuse), and ranking volatility — and separates **your
own-site warnings** from competitor intel.

**What it lets you understand:** risk and timing. A competitor whose visibility just cliffed
is a moment to strike; a parasite subfolder is a rival doing something Google may penalize. On
your own site, the same signals are early warnings.

**What you can then do:** fix own-site warnings first (before a penalty lands), and treat
competitor cliffs as windows to publish and overtake.

**Where you see it:** the *Reputation-Risk Radar* section (own-site warnings first, then
competitor signals) and the *Reputation Risk* Excel sheet.

> **Read it honestly:** these are **pattern detections, not confirmed Google penalties**. A
> parasite flag needs both topical mismatch *and* commercial-intent keywords (the subfolder's
> name alone never triggers one); a cliff is measured against a recent window, not all-time.
>
> **`visibility_cliff` is often withheld, and that is the honest answer.** It is computed
> per **run** (not per calendar day) from every ranked keyword of that run, as the share
> in the top 10, and only for domains with at least `risk_signals.cliff_min_sample` (10)
> measured keywords in two or more runs. Below that floor the signal is withheld and the
> section says so — it is not reported as "visibility held".
>
> **Fixed 2026-11-15 (C-C-06, C-M-07).** The series used to be the number of
> `market_history` rows with rank ≤ 10, grouped by `DATE(timestamp)` — at most
> `technical.max_audit_pages_per_domain` (3) rows per domain per run, because the
> snapshot was written only for pages that scraped cleanly. So it measured the tool's own
> sampling: two runs on one day then one the next gave `[6, 3]`, a "high severity 50%
> collapse"; one page slipping from rank 10 to 11, or one errored scrape, gave `[3, 2]`.
> An errored scrape is now recorded with a NULL rank rather than omitted. Whether the
> signal should exist at all before a data source routinely supplies ten or more ranked
> keywords per snapshot is an open question for the owner (decision 5 of the review plan)
> — this release keeps it, with the floor.

## 6. Action features (drafting help)

### 6.1 Automated Bowen Reframes (OpenAI `gpt-4o`)
**What it does:** for the Systemic Vacuums (§4.2 — the same query, so the same pages),
generates a structured content outline that reframes the competitor's medical-model
angle into a Bowen systems approach.

**What it lets you understand:** a concrete starting structure — how the systemic
counter-argument to a given competitor page could be organised.

**What you can then do:** hand it to a writer as a scaffold. It is a *starting point*,
not publish-ready copy — the clinical judgement and voice are still yours.

**Where you see it:** *🎯 Automated Bowen Reframes* section and the *Automated Reframes*
Excel sheet. (Token spend is reported under *💰 AI Token Usage*.)

> **What the model is given.** The keyword, the competitor's URL and its medical score —
> **not the competitor's page text**, which is never fetched for the prompt. Every
> generated draft therefore ends with the line *"Generated by gpt-4o from the keyword,
> URL and score above — no page content was supplied."* A page with `medical_score` 0
> gets *"No medical vocabulary detected … reframe not applicable"* and costs no tokens,
> instead of a draft asserting a "Medical Model" page that was never observed
> (C-M-15). `temperature` is 0.7, so two runs will not produce identical text.
>
> **People-Also-Ask context** appears only on the deprecated `market_analysis_*.json`
> path. The Tool 1 handoff has no PAA field (`handoff_schema.json`), so a handoff-driven
> run has no PAA to weave in; this guide previously promised it on every run.

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
| Executive Summary | What this run set out to find, plus **Run coverage**: domains audited vs. in the handoff, which were skipped and why, which had no Moz authority figure, and how the keyword universe was assembled | Orientation; check coverage before reading anything as absence |
| 📈 Internal GSC Performance Gaps | Your own low-CTR / Page-2 / mismatch opportunities | Fix titles, boost near-misses |
| 💰 AI Token Usage | Cost of the reframes this run | Budget awareness |
| 📉 Volatility / 🚩 Fragile Magnets | Who moved since the last run that saw the same page (one authority-drift detector, thresholded) | Re-prioritise & time your strike |
| Competitor Ranking Summary | Each competitor's `sampled_keywords` (distinct keywords THIS run audited, not keywords it ranks for), `pages_audited`, avg position, `systemic_depth` from the Tier-2/3 counts, recommended strategy, and the **Keyword provenance** line | Pick who to target |
| EEAT Competitive Analysis | How credible each page *looks* | Out-signal the weak, match the strong |
| Internal Linking Cluster Analysis | How defended each competitor is | Prefer isolated targets |
| GEO / Extractability | *Why* AI engines cite each page | Copy the structure that earns citations |
| Identified 'Traffic Magnets' | Pages ranking top-10 on one of your keywords with medical-model language (§4.1 states the filter and how many of the audited pages met it) | Your content backlog |
| ⚡ Systemic Vacuums | Those same pages with no systemic answer — the reframe targets | Write these first |
| SERP Overlap & Differentiation Gap | Where you collide (commodity) vs. are exclusive | Fill exclusive-competitor gaps; differentiate/skip commodity |
| Barbell Positioning Diagnostic | The 2×2 shape of the field (who's authoritative / niche / stuck in the middle) | Target the middle; win by picking a barbell end |
| YouTube Presence | Which competitors run a channel, how big/active (you ⭐); Data-API metadata check | Decide if YouTube is worth entering; confirm `candidate` channels |
| 🎯 Automated Bowen Reframes | Draft outlines to counter each page | Brief your writer |

### 8.2 Excel workbook — sheet-by-sheet
`Competitor Summary` · `Traffic Magnets` · `EEAT Scores` · `Cluster Analysis` ·
`GEO Extractability` · `SERP Overlap` · `Feasibility` · `Positioning` · `AI Share-of-Voice` · `Branded Demand` · `Reputation Risk` · `YouTube Presence` · `Automated Reframes` · `AI Usage Stats`. Each sheet is the
tabular form of the matching briefing section — use it to sort/filter (e.g. sort
*GEO Extractability* by tier, or *Traffic Magnets* by traffic) and to paste into a
content plan. *Traffic Magnets* carries `keyword_source` and the handoff `rank`;
*Branded Demand* carries the `queries` actually sent for volume; *SERP Overlap*
carries `best_rival_etv` (see §4.4).

**Every sheet is the FULL set of rows for the run.** The markdown briefing caps the
long sections for readability — `reporting.markdown_row_cap` (30) and
`reporting.magnet_markdown_row_cap` (20) — and says so inline ("Showing the first 30
of 45 profiled page(s)"). Until 2026-11-15 the cap was a `LIMIT` in the SQL, so the
sheet was truncated identically and nothing said so: with 15 competitors × 3 pages the
*EEAT* and *GEO* sections and sheets showed the alphabetically-first ~10 competitors
and silently dropped the other five, and the *Traffic Magnets* sheet was cut to 20
rows chosen by an `est_traffic DESC` sort with heavy ties (C-C-07). A sheet only appears if that run produced data for it.

---

## 9. How to read the numbers honestly (limitations in one place)

- **The audited universe is the handoff, plus filtered enrichment** (§2.1). Every
  keyword carries a source: `handoff` = Serp-Discover measured that URL ranking for it;
  `ranked_keywords` = a DataForSEO enrichment keyword that passed the relevance filter;
  `unlabelled` = a row written before 2026-11-15, whose provenance is unknown and which
  is therefore never treated as a magnet, vacuum or reframe target.
- **The handoff `rank` is whatever Serp-Discover wrote.** Serp-Compete does not
  re-measure it. Tool 1's rank semantics are themselves under repair (its paginated
  SERP positions restart at 1 per page), so a rank from a handoff generated before that
  fix understates how far down the page a result really was.
- **A missing number is NULL, not zero, all the way down** (fixed 2026-11-15). An
  unmeasured Moz Page Authority, a brand whose search volume the provider would not
  return, a page whose scrape errored, a drift whose two sides were not both measured:
  each is stored and rendered as unknown. Where that leaves a section quieter than it
  used to be, the briefing states the coverage — *Run coverage* in the Executive
  Summary names the skipped domains, the unmeasured authorities and the "N of M URLs
  had PA" count.
- **`sampled_keywords` is this run's sample, not the competitor's keyword count.**
  It is the distinct keywords audited for the domain: its handoff targets plus any
  enrichment keywords that passed the relevance filter. Until 2026-11-15 the column
  was called `total_keywords` and was inflated by a cross join — keywords × audited
  pages — so a domain with 10 keywords and 3 pages reported 30 and the column
  mis-ranked competitors by breadth (C-C-02).
- **`systemic_depth` reads the Tier-2 / Tier-3 counts**, with `Not recorded` when a
  cache-served page predates those counts. It used to read "High" from
  `systems_score > 0` (one occurrence of "relationship") and "Medical" from a raw
  Tier-1 count compared with a weighted systems score (C-M-05). The Tier-2 band is a
  COUNT, not a density: per-1000-word densities need the page word counts that
  C-M-19 (chunk C4) adds.
- **`best_rival_etv` is the best-ranking RIVAL's estimated monthly visits** for that
  keyword — not search volume and not your traffic. It was labelled "Volume by cell
  (est. traffic)" and stored as `keyword_volume` (C-M-20).
- **The magnet / vacuum thresholds are editorial and uncalibrated**
  (`technical.vacuum_min_medical` = 10 and `technical.magnet_max_position` = 10, both
  dated 2026-11-14; `branded_demand.ambiguous_brand_ratio` = 10). They were chosen to
  match the documented definitions, not derived from outcome data. Raising or lowering
  them changes the magnet, vacuum and reframe lists together, by design.
- **`est_traffic` is DataForSEO's `etv`** — estimated monthly visits for that
  keyword×position, not measured traffic, and **0 means not measured**: the handoff
  carries no traffic figure, so one appears only where DataForSEO reported the same URL
  and keyword.
- **Reframes never see the competitor's page** (§6.1), and the vocabulary scores behind
  the floor are counts of configured terms on the first ~500 words plus headings, not a
  judgement of what the page argues.
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
- **SERP-overlap "commodity" is a local proxy** (how many tracked rivals share the
  SERP), not a measured commodity index; and your `self_position` comes only from GSC,
  so a keyword you rank for won't show as "yours" unless it's in your Search Console
  data (and a page-2 position is treated as absent from the top-N battle).
- **Barbell positioning axes are heuristic**, not a measured market model. "Focus" is
  language-tier concentration (medical vs. systems), not topic breadth; and because
  your own axes come from GSC (not a page audit), a run without GSC marks you
  `insufficient_data` rather than mis-plotting you.
- **Alert thresholds are editorial and uncalibrated too**: `risk_signals.pa_drop_min`
  (3) for Fragile Magnets and `risk_signals.cliff_min_sample` (10) for visibility
  cliffs, both dated 2026-11-15. The cliff floor is high relative to what one run
  samples, so the signal is often withheld; that is deliberate (§5.3).
- **AI-era comparison features are consumed/estimated, honestly labelled.** AI Share-of-Voice
  is a rolling snapshot consumed from serp-discover (absent when there's no export, never
  zero); Branded-Demand competitor figures are search-volume estimates (only your own can be
  GSC-anchored) and say so when the source is down; Reputation-Risk items are *pattern
  detections, not confirmed Google penalties*.
- **Reframes are AI-drafted scaffolds**, not clinical copy — always apply your own
  judgement.

---

*This guide describes the behaviour shipped in the code as of the C1/C3/C6 (AI
Share-of-Voice, Branded Demand, Reputation Risk) release. If a feature's behaviour changes,
update this file alongside `suite_enhancement_spec_SERPCOMPETE_v1.md`.*
