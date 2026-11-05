# 0018 — Job discovery: verified sources behind one connector, and a score that is a count

**Status:** Approved (2026-11-05) — implemented in Phase 4
**Related:** [0008](0008-job-sources.md) (the source policy this implements and
partly amends), [0003](0003-profile-identity.md) (the candidate segment the sweep
record follows), [0002](0002-privacy-model.md) /
[0011](0011-private-store-location.md) (why the sweep record is outside the
repository), [§1 research finding](../analysis/job-sources-research.md)

## Context

Phase 4's roadmap scope was fixed long before any source was examined: connectors
over ToS-compliant sources, normalised to one `Job` model, deduplicated, with
expiry detection and *"deterministic, explainable matching with explicit
hard-eligibility vs preference separation"*. ADR 0008 had already set the policy
order — public APIs, then RSS/structured feeds, then partner programmes, then ATS
endpoints — and made scraping a last resort behind the connector interface.

The owner re-confirmed the scope on 2026-10-31: **broad coverage of the major
public job APIs, Germany/DACH first**, with the model designed so other markets can
follow, and the Phase 3 `measured` close-out left alone.

Research then contradicted two assumptions the work was briefed with, and those
corrections are what this record is mostly about:

1. **`JobPosting` JSON-LD is not a portable ATS pattern.** Greenhouse-hosted job
   pages contain **zero** `ld+json` blocks; SmartRecruiters uses microdata. ADR
   0008 §2 ranked ATS JSON-LD near the top of the preference order, and for two
   major platforms that would have yielded nothing.
2. **The German federal source is not reachable by the documented route.**
   `rest.arbeitsagentur.de` refused the well-known community key with `403` on both
   the token and search endpoints, while `www.arbeitsagentur.de` itself returned
   `200`.

Three further findings shaped the build: softgarden publishes an **official
schema.org `DataFeed`** that is explicitly crawler-friendly; the major boards
(StepStone, Indeed, LinkedIn) each disallow in their own `robots.txt` the exact
paths a connector would need; and **SmartRecruiters returns perfect data while its
API host's `robots.txt` is `Disallow: /`**.

## Decision

### 1. Build four sources; make every exclusion visible in code

| Built | Why |
|---|---|
| **softgarden** | Official schema.org `DataFeed`, no credentials, Germany-first, and the payload *is* `JobPosting` so one parser serves feed and JSON-LD |
| **Personio** | Official XML feed, no credentials, the German/Austrian/Swiss SME market nothing else reaches |
| **ATS family** (Lever, Greenhouse, Ashby) | Public, documented or long-stable, per-employer precision, carries `country`/location + dates |
| **Arbeitnow** | Public, no credentials, Germany-first, whole corpus enumerable |

Excluded, **with the reason recorded in the module docstring rather than only in
this ADR**, because "we decided not to" is the knowledge that gets lost:

* **StepStone, Indeed, LinkedIn** — their `robots.txt` disallow the needed paths
  (Indeed disallows `/jobs/DE/` explicitly). ADR 0008 §4 forbids workarounds that
  violate terms. Respecting a refusal means not making the request.
* **SmartRecruiters** — a `200` is not permission. Its API host disallows every
  crawler but `LinkedInBot`.
* **Bundesagentur für Arbeit** — key refused with `403`; the natural candidate for
  a partner application, not written off, only unavailable today.
* **Workday, JOIN, Umantis, Recruitee, d.vinci, onlyfy** — each needs a
  reverse-engineered or per-customer integration.

**ADR 0008 §3's scraping allowance is therefore not exercised.** No HTML scraper
was written.

### 2. Every source-dependent field carries its provenance

`JobField` pairs a value with how it was obtained: `STRUCTURED` (the publisher's
own machine-readable field), `PARSED` (the publisher's own words, interpreted),
`INFERRED` (our conclusion), or `ABSENT`.

This is ADR 0008's consequence clause made structural: *"Every record preserves its
source and distinguishes verified fields from inferred ones."* The sources disagree
about location more than anything else — softgarden publishes a full
`PostalAddress` with `addressCountry`, Lever has a `country` field, Greenhouse
gives only a display string, Personio and Arbeitnow give a bare city — and
flattening them to one `country` value would make a published fact
indistinguishable from a guess, irrecoverably.

**Consequences that are deliberate:**

* `country` is **never guessed**. A free-text city never becomes a country.
* `is_dach` requires a **verified** country, so the DACH-first filter cannot be
  driven by an inference.
* `normalise_country` recognises the non-DACH countries the sources actually
  publish (`US`, `GB`, …). An earlier version mapped them to `None`, which made a
  posting explicitly placed in the United States indistinguishable from one whose
  country was never stated. DACH-first is expressed by `is_dach`, not by discarding
  information — which is also what lets other markets follow.

### 3. Deduplication merges only on proof, and never within one source

1. Same `(source, source_id)` is the same record.
2. An identical content fingerprint **from a different source** is the same vacancy.
3. Otherwise they stay separate.

The asymmetry decides it: **a false merge loses a vacancy the user never sees and
is invisible; a false split shows a duplicate, which is annoying but visible.** So
the merge must earn its confidence, every merge records its `MergeReason`, and no
fuzzy threshold is used.

Rule 2's "different source" clause was **added after a real false merge**: merging
on content alone collapsed two reqs from one source sharing company, title, city
and country. Employers routinely open several reqs for one title in one city, and
that merge hid a vacancy silently. A single source's id is authoritative.

### 4. Expiry is observed, never assumed

No DACH source publishes an expiry date, so expiry cannot be read. The sweep record
stores what each source returned, and a job is `DISAPPEARED` only when **the source
that carried it was actually consulted** this run — otherwise disabling one source
would report everything it ever returned as expired. A disappeared job is reported,
**never deleted**: one sweep cannot distinguish a mass expiry from a source outage.

### 5. A match score is a count of named evidence

The score is the number of `Reason`s that fired, and each carries the terms that
produced it. **No weighting, no tuned coefficient, no model call** — a weight would
imply a precision this data does not support (the sources disagree about location,
several omit descriptions, none publishes an expiry date), whereas a count can be
re-derived by reading the evidence list.

**A fact the source did not state is not a miss.** It scores nothing and is
reported in `unknowns`, so sparse data is never mistaken for a poor fit.

### 6. Hard eligibility is not a score, and has three values

* `INELIGIBLE` — a **stated** fact rules it out: a verified foreign country, or a
  language the posting explicitly requires and the profile lacks. Hidden.
* `UNCERTAIN` — a real constraint the data cannot settle: a work-authorisation
  mention, an over-senior title. **Neither hidden nor silently allowed** — shown
  with the reason so the candidate decides.
* `ELIGIBLE` otherwise.

Since preference scoring and eligibility answer different questions, eligibility
never contributes to the score. A keyword the user *asked for* and the posting
lacks is a **non-match** rather than an unknown, and hides the job — without that,
a search for "data engineer" ranked a Major Account Executive and an Electrical
Engineer on live data.

### 7. Obligations are enforced in code, not documented

* One `build_user_agent()` builds every `User-Agent` (ADR 0008 §3, "identify
  itself honestly"), so no connector can forget.
* The request budget is **enforced**, not documented, so a looping bug degrades to
  a slow search rather than a flood; requests to one host are paced.
* A `RobotsPolicy` exists for the next connector that reads a website rather than a
  published API, so it has a checked path instead of an excuse.

## Consequences

* **No test makes a network call.** `RecordingTransport` replays captured payloads
  and raises on an uncaptured URL, so an accidental live fetch fails loudly rather
  than quietly depending on someone else's uptime. `tools/smoke_job_connectors.py`
  is the separate, explicitly-run live check.
* The sweep record lives at `<store>/jobs/<profile_id>/sweep.json`, inside the
  private store under the candidate segment (ADR 0003, ADR 0011), because which
  jobs someone looked at is personal data.
* Searching is **free** — no credentials, no LLM call — so it needs none of the
  spend authorisation a generation run does.
* ADR 0008 §2's ordering still holds, but its JSON-LD assumption is **amended**:
  ATS endpoints are consumed as *list feeds*, not by JSON-LD extraction alone.
* Adding an employer is a configuration line; adding a source is one class.
* Two documentation obligations carry forward: the sample employer lists are
  placeholders the owner should replace, and a Bundesagentur partner application
  remains the largest single coverage gain available.
