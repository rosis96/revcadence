# Brief: qualifying prospects on ad spend, without buying the data

**For:** the RevCadence system-building chat
**From:** Rosis (Ascendly / RevCadence)
**Date:** 23 August 2026
**Companion document:** *The Ad Evidence Layer* (PDF) — what is already built and how it works.

---

## 1. The two systems, and where the files are

There are two repositories, both on this machine.

### A. `company-research-api` — our own website crawler, shipped as an API

A FastAPI service on Railway. It crawls a company's website and returns structured
pages plus firmographic signals. It also backs a Custom GPT via an OpenAPI action.

Files worth knowing:

| File | What it is |
|---|---|
| `app/api/routes.py` | The endpoints: `/v1/research`, `/v1/scrape`, batch jobs, diagnostics |
| `app/models/request.py` | Request contract — `url`, `research_depth`, `output_format`, `include_signals`, `advanced` |
| `app/models/response.py` | Response contract — `SiteInfo`, `SiteSignals`, `AdvertisingSignals`, `PageResult` |
| `app/crawl/orchestrator.py` | The crawl loop: seed fetch, render escalation, discovery, ranking, signal assembly |
| `app/extract/signals.py` | **The ad-tag fingerprint table** — `detect_advertising()`, `_AD_FINGERPRINTS`, `detect_landing_pages()` |
| `app/fetch/renderer.py` | The headless browser path |
| `app/fetch/sufficiency.py` | Decides whether a fetched page is good enough or needs the browser |
| `app/scrape_service.py` | Single-URL scrape, with render modes `never` / `auto` / `always` |
| `app/security/*` | SSRF guard, DNS pinning, robots — the crawler is deliberately well-behaved |
| `scripts/calibrate.py` | Harness for running the crawler across many domains and reporting outcomes |
| `tests/` | ~728 tests |

### B. `revcadence` — the platform (a Clay-like enrichment product)

FastAPI + SQLAlchemy + Alembic backend, React frontend, Railway web/worker split.

Files worth knowing:

| File | What it is |
|---|---|
| `app/enrichment/pipeline.py` | The whole cheapest-first funnel (2,131 lines). Free verify → Reoon → title gate + ICP on one scrape → write copy |
| `app/enrichment/company_research.py` | Client for the Company Research API. Pluggable primary crawler; falls back to the in-house one |
| `app/enrichment/crawler.py` | The in-house fallback crawler |
| `app/enrichment/ad_signals.py` | **New.** Deterministic paid-advertising classifier — states, thresholds, ad-library deep links, export columns |
| `app/routers/enrich_lists.py` | List/lead API and the CSV export |
| `app/models/enrich.py` | `EnrichLead`, `EnrichConfig`, `EnrichList` |
| `frontend/src/pages/EnrichListDetail.jsx` | The list view and the research drawer, including the new "Ad activity" panel |
| `tests/test_ad_signals.py` | 13 tests on the classifier |
| `tests/test_company_research_contract.py` | 7 tests pinning the API response shape |
| `tests/fixtures/company_research_response.json` | A real API response, generated from the API's own Pydantic models |

---

## 2. What we are trying to achieve

We have a client, **Unicorn Innovations**. They book meetings for their partners.
Their qualification bar for a prospect is:

> **The company spends $10,000 or more per month on advertising.**

We need to identify companies that clear that bar **before we contact them**, at list
scale — hundreds to thousands of companies — and we need to do it **without buying an
ad-spend data product**.

The target set is **US-based companies**, most of which advertise only in the US.

---

## 3. The idea we have already built

A company's own website leaks whether it buys traffic. Ad platforms require a tag on
the site to attribute conversions, so an advertiser is nearly always carrying evidence
of it in their own markup.

So: on the crawl we already run for ICP scoring, make one extra pass over the homepage
HTML and look for advertising fingerprints. No extra fetch, no extra cost per lead.

The classifier reads 24 fingerprints in three weights:

- **Weight 3 — conversion tracking.** `AW-` conversion IDs, `googleadservices.com/pagead/conversion`, `fbq('track','Purchase')`. These exist only to feed an ad platform's bidding algorithm. Nobody installs them speculatively.
- **Weight 2 — pixels and audience tags.** Meta Pixel, TikTok Pixel, Microsoft UET, LinkedIn Insight Tag, Pinterest, Snap, Criteo, DoubleClick remarketing.
- **Weight 1 — supporting stack.** Triple Whale, Northbeam, Hyros (paid-attribution software), Klaviyo, Attentive, server-side GTM.

It also extracts the literal conversion ID and Meta pixel ID, and campaign landing-page
paths (`/lp/`, `/offer`, `/promo`, `/try-`, `/free-trial`).

Score = summed weights, `+1` per additional platform (capped `+3`), `+1` for any campaign
landing page or `+2` for three or more. Then:

| State | Rule | Meaning |
|---|---|---|
| `confirmed_advertiser` | score ≥ 5 **and** a conversion tag | Buying traffic, optimising against outcomes |
| `probable_advertiser` | score ≥ 2 | Pixels present, no conversion tag |
| `no_evidence` | score < 2 | We looked and found nothing |
| `not_assessed` | no signals collected | We never looked — deliberately kept separate |

The verdict is stored on each lead, shown in the research drawer, and exported as six
CSV columns including prebuilt deep links into the Meta Ad Library and the Google Ads
Transparency Center for that brand.

**It never returns a spend figure.** No page on any website states a media budget, and a
number we generated would be indistinguishable from a number we measured — which in a
qualification funnel is worse than having no number at all.

---

## 4. The problem

### 4.1 The core gap

Everything above proves **whether** a company advertises. It does not establish
**how much** they spend, which is the actual bar.

The obvious external sources do not close it:

- **Meta Ad Library API** — returns commercial ads only for campaigns reaching the EU/EEA, with `eu_total_reach`. Spend figures exist only for political ads, and only as ranges. Our targets are US-only advertisers, so this returns almost nothing useful for us.
- **Google Ads Transparency Center** — has no API at all. Web interface only.
- **TikTok Commercial Content API** — EEA only.

So there is no free, sanctioned, programmatic source of US ad volume or spend.

### 4.2 What the client does today

We asked Unicorn how they qualify. Their answer, verbatim from Lucas Prichard:

> "Internally, we're verifying active ads on the Meta Ads Library and Ads Transparency
> for Google. But just having a view/count of the ads that are actively running doesn't
> really paint the full picture, so unless it's a really established brand with dozens or
> hundreds of active ads running — there will need to be some manual verification in the
> booking/follow-up process."

They do it by hand, per prospect, and they do not consider the ad count sufficient on
its own. They have no systematic method to hand us.

### 4.3 Where our own layer under-detects — and it is the wrong direction

All three known failure modes are **false negatives**, and all three correlate with
*larger* advertisers. That inverts the usual intuition: a `no_evidence` result on a big
brand is more likely a detection gap than a fact about the brand.

1. **Container-injected tags.** When Google Ads conversion tracking is deployed through a GTM container, the raw HTML only shows `gtm.js` — the `AW-` ID lives inside the container and appears only after JavaScript runs. Our crawler currently renders in a browser when a page is *blocked* or *too thin*, not when its text is already sufficient. So text-rich, tag-rich sites are exactly the ones we may read pre-render. **This one we know how to fix** (see 5.1).

2. **Server-side tagging.** Meta's Conversions API and server-side GTM move the tag off the page entirely. The companies most likely to have made that move are the ones with enough spend to care about signal loss — the segment we are trying to find.

3. **Consent gating.** Tags held behind a consent manager may not be present pre-consent.

### 4.4 Hard constraints

- **No paid ad-intelligence data products** unless nothing else works. (SpyFu, Semrush, Similarweb, AdBeat, Pathmatics all sell spend estimates. We know they exist. The point of this exercise is to avoid the per-record cost.)
- **Nothing that violates a platform's terms of service.** A human clicking through the Meta Ad Library is fine. A bot doing it at list scale is not. Any proposal has to stay on the right side of that line, and should say explicitly which side it is on.
- Must work at list scale — hundreds to thousands of companies per run — inside a funnel where a lead currently costs cents, not dollars.
- US companies, US-only advertisers.

---

## 5. What we are asking

**Can you solve this? And if not fully, how close can we get?**

Specifically:

### 5.1 The known fix — will you build it?

Add a force-render path for qualification crawls, so container-injected ad tags are
visible. `app/scrape_service.py` already supports `render: always`; the crawl endpoint
(`/v1/research`) has no equivalent flag. Options we can see:

- add `force_render` (or `render: never|auto|always`) to `AdvancedOptions` in `app/models/request.py` and thread it through `app/crawl/orchestrator.py::_fetch_seed`, or
- have `revcadence` make one extra `/v1/scrape` call with `render: always` against the homepage purely for signal detection.

Which is better, and what does it cost us in latency and render budget?

### 5.2 The open question

Is there an approach we have missed for getting a defensible **scale or volume** signal
on US advertisers, at list scale, without buying spend data and without breaking any
platform's terms?

Things we have thought of but not evaluated properly — tell us which are real and which
are dead ends:

- Hiring signals (a company advertising for a Paid Media Manager, or naming an agency)
- The commerce and attribution stack as a spend proxy — the reasoning being that
  Triple Whale, Northbeam and Hyros are paid subscriptions bought *because* spend is
  large enough to need attribution
- Volume of campaign landing pages, and how often they change over time
- The same conversion ID appearing across multiple domains (one operator, several brands)
- Anything in publicly published data — filings, agency case studies, press
- Whether the Meta Ad Library's *sanctioned* API surface can be made useful for a
  US-only advertiser at all

### 5.3 Calibration

We have no measured accuracy figures. Every threshold in section 3 is currently a
judgement call, not a measurement — and an attempt to measure hit rate failed because
the environment's outbound requests are proxied.

Unicorn has roughly twenty clients whose actual spend they know. Running the classifier
against those twenty turns every threshold into a measurement. How would you design that
calibration run, and what would you want to record from it?

### 5.4 The honest framing question

If the answer is that spend genuinely cannot be determined from public signals, we would
rather know that clearly than build something that looks confident and is wrong. In that
case the question becomes: **what is the best-possible ranking signal**, so a human pass
of twelve prospects a week starts at the top of a well-ordered list instead of a random
one?

---

## 6. State of play

- The classifier is built, wired end to end, and covered by 20 passing tests.
- No database migration was needed — the verdict lives in the lead's existing JSON column.
- While wiring it up we found that the Company Research API integration had **never actually run**: the mapper read each page body from `markdown`/`text`, but the API has always called that field `content`. Every page mapped to an empty string, every response looked like a failed crawl, and the pipeline silently fell back to the in-house crawler. Nothing errored, nothing logged. Fixed, with a contract test that fails against the old mapper.
- Unicorn is sending a script on Monday that documents how they confirm spend in conversation. That is the artefact our automated layer should feed, not duplicate.

Read the companion PDF for the full detail on what the classifier looks for and where it
is weak.
