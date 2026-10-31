# Job sources — ADR 0008 §1 research finding

**Status:** Research complete, awaiting the owner's approval of the source list
**Date researched:** 2026-10-31
**Related:** [0008](0008-job-sources.md) (the decision this discharges),
[ROADMAP.md](../ROADMAP.md) Phase 4

This document discharges **ADR 0008 §1** (*"Research and document ToS-compliant access
first, before writing any connector"*) and puts a proposed source list in front of the
owner for approval, per **ADR 0008 §5**.

**Method.** Every endpoint below was called for real on 2026-10-31 from this machine with
an honest `User-Agent`; the status code and payload shape were recorded. Both positive
*and negative* results are reported, because the negatives drove the recommendation. The
probe is committed as [`tools/probe_job_sources.py`](../../tools/probe_job_sources.py) so
these findings can be re-checked rather than taken on trust. Anything not called live is
marked **documented, not called**.

Throughout, the governing question is **what the operator's own terms permit**, not merely
what responds. A `200` is not permission.

---

## 1. Headline findings

Six facts decided the recommendation. **Three are negative**, and one **contradicts an
assumption in the task brief**, so it is stated plainly.

1. **The German federal employment agency's public job API refused the well-known
   community key with `403`.** Both the `rest.arbeitsagentur.de` token endpoint and the
   job search returned `403`. `www.arbeitsagentur.de/jobsuche/` returned `200`, so the host
   is up — **the key is what is refused.** The canonical German source is *not* available
   by the route most write-ups describe.
2. **`JobPosting` JSON-LD is not a universal ATS pattern, and the brief's premise does not
   hold for the largest platforms.** Greenhouse-hosted job pages contain **zero**
   `ld+json` blocks (verified on `job-boards.greenhouse.io` and `boards.greenhouse.io`);
   SmartRecruiters uses **microdata**, not JSON-LD. A JSON-LD-first strategy would return
   nothing for two major platforms. JSON-LD is reliable on **Lever** (verified: 1 block),
   Ashby, Workday and Personio.
3. **softgarden publishes an official, crawler-friendly schema.org `DataFeed`.** Verified:
   `@type: DataFeed`, 6 `DataFeedItem`s each wrapping a full **`JobPosting`** with
   `title, url, datePosted, identifier, description, employmentType, hiringOrganization,
   jobLocation`. Its `robots.txt` says *"All robots allowed"* and names `GPTBot` and
   `PerplexityBot` as allowed. **This is the single best-fitting source in the set**, and
   it was not on the original shortlist.
4. **The major boards are excluded on their own terms.** StepStone's `robots.txt`
   disallows `/5/ergebnisliste.html`, `/search-results`, `/listing`, `/jobs/*?*` and
   `/public-api/`. Indeed's disallows **`/jobs/DE/`** explicitly. LinkedIn's disallows
   `/jobs?runSearch*` and `/api/jobPostings/jobs*`.
5. **SmartRecruiters' API host disallows all crawlers.** Verified:
   `api.smartrecruiters.com/robots.txt` → `User-agent: * / Disallow: /` (only `LinkedInBot`
   is allowed). The endpoint works perfectly — `200`, `totalFound` — and that is precisely
   the trap. **A `200` is not permission**, and ADR 0008 §3 requires `robots.txt` to be
   respected.
6. **Four ATS endpoints are public, unauthenticated and documented** — Lever, Greenhouse,
   Ashby, SmartRecruiters — plus **Personio's** official XML feed and **softgarden's**
   DataFeed. These are the "ATS-hosted public endpoints" ADR 0008 §2 ranks above scraping.

---

## 2. Per-source record (ADR 0008 §1 fields)

**Class:** **A** official public API, unauthenticated · **B** official API/programme
needing a key or agreement · **C** official structured feed (XML/JSON/RSS) ·
**D** undocumented but stable public JSON · **X** prohibited / do not build.

### 2.1 The recommended sources

#### softgarden — **A/C**, recommended first

| Field | Finding |
|---|---|
| Access method | `GET https://{tenant}.career.softgarden.de/jobs.feed.json` (aliases `/jobs.json`, `/.well-known/jobs.json`) |
| Authentication | **None** |
| **Verified 2026-10-31** | **`200`**, `@type: DataFeed`, 6 items, each a full `JobPosting` |
| ToS / robots | `robots.txt`: *"All robots allowed"*; explicitly permits GPTBot, PerplexityBot; advertises a sitemap |
| Scraping restrictions | None stated; actively crawler-friendly |
| Rate limits | None published |
| Search capability | Whole-tenant enumeration; no server-side keyword search |
| Freshness | `datePosted` per item |
| DACH coverage | **Germany-first** (German ATS vendor); Austria/Switzerland per tenant |
| Cost | **Free** |
| Maintenance | **Lowest in the set** — an officially published feed whose payload *is* schema.org |

**Why it is first:** it is the only source that is simultaneously official, unauthenticated,
Germany-focused, whole-corpus enumerable, and deliberately published for machine
consumption. Because the payload is schema.org `JobPosting`, **the same parser serves the
feed and any embedded JSON-LD** — which is exactly the proven shape the repo already
handles.

#### Personio — **C**, recommended

| Field | Finding |
|---|---|
| Access method | `GET https://{company}.jobs.personio.de/xml?language=de` |
| Authentication | **None** (optional partner headers) |
| **Verified 2026-10-31** | **`200`**, `<workzag-jobs><position>` XML |
| ToS / robots | `Allow: /` |
| Rate limits | None published |
| Search capability | Whole-tenant enumeration |
| Freshness | `createdAt` |
| DACH coverage | **Germany/Austria/Switzerland — the SME market nothing else reaches** (saw `Werkstudent`, `Initiativbewerbung`) |
| Cost | **Free** |
| Maintenance | Medium-low. **Caveat:** `<jobDescriptions>` was **empty** for the tenant tested — description text needs the HTML page or the `/job/{id}` JSON-LD (2 blocks verified, but `?language=de` *suppresses* it) |

#### Lever, Greenhouse, Ashby — **A/D**, recommended as one connector family

| Field | Lever | Greenhouse | Ashby |
|---|---|---|---|
| Endpoint | `api.lever.co/v0/postings/{co}?mode=json` | `boards-api.greenhouse.io/v1/boards/{co}/jobs` | `api.ashbyhq.com/posting-api/job-board/{co}` |
| Auth | None | None (*"authentication is not required for any GET endpoints"*) | None |
| **Verified** | **`200`**, 10 postings | **`200`**, 19 jobs | **`200`**, 74 jobs |
| Lists all | Yes, paged | Yes, one call | Yes, one call |
| Key fields | `text`, `categories{location,commitment}`, **`country`**, `createdAt`, `hostedUrl`, `workplaceType` | `title`, `location{name}`, `updated_at`, `first_published`, `absolute_url` | `title`, `location`, `isRemote`, `publishedAt`, `employmentType`, `jobUrl` |
| JSON-LD | **Yes** (1 block) | **No** (0 blocks) | Yes |
| DACH usable | **Yes** — `country` filters cleanly | Via `location.name` text | **Yes** — saw "…- DACH @ Germany" |
| Maintenance | Low | Low | Low |

**One configured employer slug per employer.** No per-site parser.

### 2.2 Considered and rejected

| Source | Class | Evidence | Why rejected |
|---|---|---|---|
| **Bundesagentur für Arbeit** | X as called; B as partner | **`403`** on token endpoint *and* search | Undocumented route, key refused. Not written off — the natural **partner application** candidate |
| **StepStone** | **X** | `robots.txt` disallows result list, `/search-results`, `/listing`, `/jobs/*?*`, `/public-api/` | Prohibited by the operator's own terms |
| **Indeed (DE)** | **X** | `robots.txt` disallows **`/jobs/DE/`** | Same |
| **LinkedIn** | **X** | `robots.txt` disallows `/jobs?runSearch*`, `/api/jobPostings/jobs*`; ToS prohibits automation | Same |
| **SmartRecruiters** | **X** | `200` **but** `api.smartrecruiters.com/robots.txt` → `Disallow: /` | **Works, and is still refused** — §3 requires respecting `robots.txt`. Needs an explicit owner decision if wanted |
| **Workday** | **D** | `POST /wday/cxs/{tenant}/{site}/jobs` verified `200`, but no official API, **2,000-result cap**, Akamai throttling, per-tenant discovery | High maintenance; the most brittle in the set |
| **JOIN** | **D + B** | Two-step HTML→id scrape verified; official `api.join.com/v2/jobs` is Advanced/Enterprise only; `sitemap-jobs-index.xml` → `403` | Two-step scrape plus redirect quirk |
| **Jooble** | **X** | `403` with a Cloudflare interstitial ("Just a moment…") | Defeats non-browser clients; needs a key anyway |
| **Adzuna** | **B** | `401` without credentials → endpoint real; developer portal live | **Genuinely good**, but needs a **free registration** the owner must make. Recommend only if Q1 approves |
| **Remotive / Jobicy / Himalayas** | A/C | All `200` | **Not DACH sources** (Remotive reported `candidate_required_location: "Worldwide"`). Himalayas' `expiryDate` is a useful *shape* precedent only |
| **d.vinci, onlyfy/Prescreen, Umantis, Recruitee, SuccessFactors** | B/C | **documented, not called** — no live tenant found; Recruitee becomes token-gated 2027-02-10; Umantis is per-customer SQL+XSLT | Unverifiable today and/or too bespoke to justify |

ADR 0008 §4 governs the rejections: *"Do not build unreliable scraping workarounds that
break silently or violate terms."* A `robots.txt` `Disallow` on the exact path a connector
needs is not a grey area.

---

## 3. Recommendation

**Build three connectors plus one optional, and no HTML scraper.**

| # | Source | Why it earns its place | Owner must supply |
|---|---|---|---|
| 1 | **softgarden** | Official schema.org DataFeed, crawler-friendly, Germany-first, whole corpus, $0 | nothing |
| 2 | **Personio** | Official XML, Germany/Austria/Switzerland SME coverage nothing else reaches | nothing (per-employer subdomain) |
| 3 | **ATS family: Lever + Greenhouse + Ashby** | Public + documented, carry `country`/location + dates, per-employer precision | employer slugs (Q3) |
| 4 | **Adzuna** *(optional)* | Adds real **keyword search** + salary data | **free `app_id`/`app_key` registration** |
| 5 | **Arbeitnow** *(optional)* | Verified `200`, no auth, ~5,700 postings enumerable | nothing |

**Explicitly not built:** Bundesagentur für Arbeit (key refused), StepStone, Indeed,
LinkedIn, **SmartRecruiters** (robots refusal), Workday, JOIN, Jooble, and **any HTML
scraper**. ADR 0008 §3's scraping allowance is therefore **not exercised** — the
structured sources above suffice for a DACH-first Phase 4, which is what §2 and §4 prefer.

**Decisions only the owner can make:**

- **Q1.** The ATS family: is **SmartRecruiters excluded** (my recommendation, on its
  `robots.txt`) or included deliberately? And is a **free Adzuna registration** acceptable?
- **Q2.** Is a **BA partner application** worth pursuing, or is softgarden + Personio + ATS
  coverage sufficient for DACH? This is the largest coverage question.
- **Q3.** For the ATS family, does the owner have **target employers** to configure now, or
  should the connector ship with a sample list and no committed slugs?

**Cost: $0.00.** Nothing here requires payment; no `--live` authorisation is sought.

---

## 4. What this means for the `Job` model

The verified payloads disagree more than one might hope, and **the disagreements are the
design input**:

- **Location is the hard part.** Lever gives a clean `country`; Ashby gives `location` +
  `isRemote`; Personio gives `office`; Greenhouse gives a display string; **Arbeitnow gives
  free text** (`"Munich HQ"`). One `country` field cannot be populated honestly from all of
  them — so the model must separate **what the source asserted** from **what we inferred**,
  exactly as ADR 0008's consequence requires: *"Every record preserves its source and
  distinguishes verified fields from inferred ones."*
- **Dates differ in kind**: epoch seconds (Arbeitnow), epoch milliseconds (Lever), ISO
  strings (Ashby, softgarden `datePosted`), and `createdAt` only (Personio).
- **Remote is sometimes explicit** (Ashby `isRemote`, Arbeitnow `remote`) and sometimes
  only implied by text.
- **Only Himalayas publishes an `expiryDate`.** No DACH source does. Expiry detection must
  therefore be **observed** — a posting vanishing from a re-enumerated source — not assumed
  from a field.
- **Descriptions are HTML** (softgarden, Ashby, Arbeitnow) or **absent from the feed**
  (Personio). The pipeline's existing `job_description.txt` contract needs an HTML→text step.

---

## 5. Reproducing this

```
.venv\Scripts\python.exe tools\probe_job_sources.py
```

Read-only. Fetches each endpoint with an honest `User-Agent` and prints status, size and
top-level keys, then counts `ld+json` blocks on ATS job pages. No credentials, no cost,
nothing written. Output recorded 2026-10-31:

```
source                           status      bytes  keys / note
BA Jobsuche token endpoint          403          1
BA Jobsuche jobs search             403          1
Adzuna DE search (no creds)         400       1996  <!DOCTYPE html> ...
Jooble (no key)                     403       5631  <title>Just a moment...</title>
Arbeitnow job board                 200    2423809  data, links, meta
Lever postings                      200      83523  list[10] of {id, text, categories, ...}
Greenhouse board                    200      11946  jobs, meta
SmartRecruiters postings            200       3558  offset, limit, totalFound, content
Ashby posting API                   200    2222687  jobs, apiVersion
Personio tenant XML                 200       7890  <workzag-jobs><position>
softgarden DataFeed                 200      31435  @context, @type, numberOfItems, dataFeedElement
Jobicy                              200      17859  apiVersion, jobCount, ...
Himalayas                           200      20277  totalCount, nextCursor, jobs
SmartRecruiters robots.txt          200         72  User-agent: * Disallow: /
softgarden robots.txt               200        193  # All robots allowed

JSON-LD availability on ATS job pages
Lever job page (control, expect >=1)      200  ld+json=1   JobPosting=1
Greenhouse job-boards page                200  ld+json=0   JobPosting=0
Greenhouse boards page                    200  ld+json=0   JobPosting=0
```

**The Lever row is a positive control.** It proves the extractor works, so the two
Greenhouse zeros mean JSON-LD is genuinely **absent** there — not that the probe is broken.
Without that control, "0 blocks" would be worthless evidence.

