"""Deterministic paid-advertising classification from crawled site evidence.

WHAT THIS ANSWERS
-----------------
"Is this company paying for traffic, and at roughly what operational scale?"

WHAT THIS DOES NOT ANSWER
-------------------------
"Do they spend $10K+/month?" No page on a company's own website states a
media budget, so no honest reader of that page can produce one. Anything
that returned a dollar figure here would be generating it, not observing it
-- and a fabricated number inside a qualification funnel is worse than no
number, because it looks like data. ``spend_bar`` says so explicitly, and
``verify`` carries the deep links a human uses to settle it in seconds.

The design mirrors how Unicorn qualifies today: a wide automated pass on
tag evidence, then human confirmation on the shortlist. This module is the
first half. It is deterministic on purpose -- same HTML in, same decision
out, thresholds visible and tunable, no model in the loop.

INPUT is the ``site.signals`` object from the Company Research API
(``include_signals: true``); its ``advertising`` block is already read off
the markup by ``app/extract/signals.py`` on the API side.
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus, urlsplit

# --------------------------------------------------------------- thresholds
# Weights arrive from the API (3 = conversion tag, 2 = pixel, 1 = supporting).
# These are the RevCadence-side policy knobs: what those weights add up to,
# and where the state boundaries sit. Kept here, in one place, rather than in
# a prompt -- so a threshold change is a code review, not a vibe.

#: A conversion tag is installed for exactly one reason: to let an ad platform
#: optimise against a purchase or lead. Nobody adds one speculatively.
CONVERSION_PROOFS = ("conversion tracking", "view-through conversion", "purchase conversion event")

#: Extra weight for breadth. Running two platforms is a different operation
#: from running one; it is not proof of a bigger budget, but it is a real
#: indicator of a managed programme rather than a single boosted campaign.
PLATFORM_BREADTH_BONUS = 1
PLATFORM_BREADTH_CAP = 3

#: Dedicated paid landing pages: infrastructure built to receive bought traffic.
LANDING_BONUS_ANY = 1
LANDING_BONUS_MANY = 2
LANDING_MANY_AT = 3

#: Paid-attribution platforms (Triple Whale, Northbeam, Hyros) are bought by
#: companies whose ad spend is large enough to need attribution software. That
#: is the closest thing to a scale signal that is actually observable.
ATTRIBUTION_STACK = ("Triple Whale", "Northbeam", "Hyros")

CONFIRMED_AT = 5      # score >= this, AND a conversion tag  -> confirmed
PROBABLE_AT = 2       # score >= this                        -> probable

STATE_CONFIRMED = "confirmed_advertiser"
STATE_PROBABLE = "probable_advertiser"
STATE_NONE = "no_evidence"
#: The crawl never looked. Distinct from "looked and found nothing" -- reading
#: one as the other is how a pipeline quietly disqualifies good prospects.
STATE_UNASSESSED = "not_assessed"

_STATE_LABEL = {
    STATE_CONFIRMED: "Running paid ads (conversion tracking installed)",
    STATE_PROBABLE: "Probably running paid ads (pixels present, no conversion tag)",
    STATE_NONE: "No advertising evidence on the site",
    STATE_UNASSESSED: "Not assessed (no ad-tag signals were collected for this crawl)",
}


def _domain(website: str) -> str:
    raw = (website or "").strip()
    if not raw:
        return ""
    if "//" not in raw:
        raw = "https://" + raw
    host = (urlsplit(raw).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _brand(domain: str, company: str = "") -> str:
    """A search term for the ad libraries: the company name when we have one,
    otherwise the registrable label of the domain."""
    name = " ".join((company or "").split())
    if name:
        return name
    if not domain:
        return ""
    label = domain.split(".")[0]
    return re.sub(r"[-_]+", " ", label).strip()


def _verify_links(domain: str, brand: str, platforms: list[str], country: str = "US") -> list[dict]:
    """Deep links straight to the evidence a human would check by hand.

    This is the part that turns a two-minute lookup into a five-second one.
    Building a URL is not scraping: nothing here fetches anything, and the
    person clicking it is a person, which is the distinction the ad libraries'
    terms actually care about.
    """
    links: list[dict] = []
    if brand:
        links.append({
            "platform": "Meta",
            "what": "Active ads for this brand in the Meta Ad Library",
            "url": ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all"
                    f"&country={country}&q={quote_plus(brand)}&search_type=keyword_unordered"),
        })
    if domain:
        links.append({
            "platform": "Google",
            "what": "Advertiser record in Google Ads Transparency Center",
            "url": f"https://adstransparency.google.com/?region={country}&domain={quote_plus(domain)}",
        })
    if "TikTok" in platforms and brand:
        links.append({
            "platform": "TikTok",
            "what": "TikTok Commercial Content Library (EEA-reaching campaigns only)",
            "url": f"https://library.tiktok.com/ads?region=all&query={quote_plus(brand)}",
        })
    if "LinkedIn Ads" in platforms and brand:
        links.append({
            "platform": "LinkedIn",
            "what": "LinkedIn company Ads tab (open the company, then Posts -> Ads)",
            "url": f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(brand)}",
        })
    return links


def classify(signals: dict | None, website: str = "", company: str = "", country: str = "US") -> dict:
    """Turn the API's site signals into a paid-advertising verdict.

    Returns the same shape whether or not evidence was found, so callers and
    the UI never branch on presence. An empty ``signals`` is a legitimate
    input: it means the crawl succeeded and found nothing, which is itself a
    finding.
    """
    signals = signals or {}
    ads = (signals.get("advertising") or {}) if isinstance(signals, dict) else {}
    platforms = [p for p in (ads.get("platforms") or []) if p]
    evidence_raw = [e for e in (ads.get("evidence") or []) if e]
    identifiers = ads.get("identifiers") or {}
    landing = [u for u in (ads.get("landing_pages") or []) if u]

    base = int(ads.get("score") or 0)
    score = base
    reasons: list[str] = []

    if base:
        reasons.append(f"tag evidence scores {base}")

    breadth = min(max(len(platforms) - 1, 0) * PLATFORM_BREADTH_BONUS, PLATFORM_BREADTH_CAP)
    if breadth:
        score += breadth
        reasons.append(f"{len(platforms)} platforms tagged (+{breadth})")

    if len(landing) >= LANDING_MANY_AT:
        score += LANDING_BONUS_MANY
        reasons.append(f"{len(landing)} dedicated landing pages (+{LANDING_BONUS_MANY})")
    elif landing:
        score += LANDING_BONUS_ANY
        reasons.append(f"{len(landing)} dedicated landing page (+{LANDING_BONUS_ANY})")

    has_conversion = any(any(p in e.lower() for p in CONVERSION_PROOFS) for e in evidence_raw)
    attribution = [p for p in platforms if p in ATTRIBUTION_STACK]

    if score >= CONFIRMED_AT and has_conversion:
        state = STATE_CONFIRMED
    elif score >= PROBABLE_AT:
        state = STATE_PROBABLE
    else:
        state = STATE_NONE

    # Confidence is about the *classification*, not the spend. A conversion tag
    # plus breadth is close to certain; a lone stale pixel is not.
    if state == STATE_CONFIRMED:
        confidence = min(95, 70 + 5 * len(platforms) + (5 if landing else 0))
    elif state == STATE_PROBABLE:
        confidence = min(70, 40 + 8 * len(platforms))
    else:
        confidence = 55 if not platforms else 40

    # Observable operational scale. NOT budget. Each entry is something a
    # human could re-check on the page in ten seconds.
    scale: list[str] = []
    if len(platforms) >= 3:
        scale.append(f"multi-platform programme ({len(platforms)} platforms)")
    if attribution:
        scale.append("paid-attribution software installed (" + ", ".join(attribution) + ")")
    if len(landing) >= LANDING_MANY_AT:
        scale.append(f"{len(landing)} campaign landing pages")
    if has_conversion:
        scale.append("optimising against conversions, not impressions")

    domain = _domain(website)
    brand = _brand(domain, company)

    return {
        "state": state,
        "label": _STATE_LABEL[state],
        "confidence": confidence,
        "score": score,
        "base_score": base,
        "platforms": platforms,
        "evidence": evidence_raw,
        "identifiers": identifiers,
        "landing_pages": landing[:12],
        "scale_indicators": scale,
        "scoring": reasons,
        # Stated once, deliberately, so nothing downstream reads a spend figure
        # into a field that never contained one.
        "spend_bar": {
            "determinable_from_site": False,
            "note": ("A website never states its media budget. This verdict proves whether the "
                     "company buys traffic and at what operational breadth; the $10K/month "
                     "threshold has to come from ad-library volume or from the prospect."),
        },
        "verify": _verify_links(domain, brand, platforms, country=country),
        "summary": _summary(state, platforms, has_conversion, landing),
    }


def _summary(state: str, platforms: list[str], has_conversion: bool, landing: list[str]) -> str:
    if state == STATE_NONE:
        return "No ad platform tags, pixels or campaign landing pages found on the site."
    names = ", ".join(platforms[:4]) or "an ad platform"
    lead = "Conversion tracking for" if has_conversion else "Pixels for"
    tail = f"; {len(landing)} campaign landing page{'s' if len(landing) != 1 else ''}" if landing else ""
    return f"{lead} {names}{tail}."


def not_assessed(website: str = "", company: str = "", country: str = "US") -> dict:
    """The verdict for a lead whose crawl produced no signals at all.

    Returned when the in-house crawler ran instead of the Company Research API
    (it does not read ad tags), so the UI shows "not assessed" rather than a
    clean bill of health nobody earned. Verify links are still populated, so a
    human can settle it by hand in the meantime.
    """
    domain = _domain(website)
    brand = _brand(domain, company)
    return {
        "state": STATE_UNASSESSED,
        "label": _STATE_LABEL[STATE_UNASSESSED],
        "confidence": 0,
        "score": 0,
        "base_score": 0,
        "platforms": [],
        "evidence": [],
        "identifiers": {},
        "landing_pages": [],
        "scale_indicators": [],
        "scoring": [],
        "spend_bar": {
            "determinable_from_site": False,
            "note": "Not assessed: this crawl did not collect ad-tag signals.",
        },
        "verify": _verify_links(domain, brand, [], country=country),
        "summary": ("Ad tags were not read on this crawl. Enable the Company Research API "
                    "in Settings -> Integrations to collect them."),
    }


def is_advertiser(verdict: dict | None) -> bool:
    """True when there is real evidence of buying traffic. Probable counts --
    the shortlist is meant to be wide; the manual pass narrows it."""
    return bool(verdict) and verdict.get("state") in (STATE_CONFIRMED, STATE_PROBABLE)


#: Column headers for the CSV export, in order. Deliberately six plain columns
#: rather than a JSON blob: this file gets opened in a spreadsheet and sorted,
#: and the two library URLs are what turn a shortlist into a ten-minute manual
#: pass. There is no spend column, because no spend figure was ever observed.
EXPORT_HEADERS = [
    "ad_status", "ad_confidence", "ad_platforms", "ad_evidence",
    "meta_ad_library_url", "google_ads_transparency_url",
]


def export_columns(verdict: dict | None) -> list:
    """The six export cells for one lead, aligned with ``EXPORT_HEADERS``."""
    ads = verdict or {}
    links = {v.get("platform"): v.get("url", "") for v in (ads.get("verify") or [])}
    unrated = ads.get("state") in (None, "", STATE_UNASSESSED)
    return [
        ads.get("state", ""),
        "" if unrated else ads.get("confidence", ""),
        "; ".join(ads.get("platforms") or []),
        "; ".join(ads.get("evidence") or []),
        links.get("Meta", ""),
        links.get("Google", ""),
    ]
