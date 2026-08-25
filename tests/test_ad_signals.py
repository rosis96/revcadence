"""Paid-advertising classification: the deterministic half of ICP qualification.

These tests pin the *policy*, not the plumbing. Each one states the judgement
call it is protecting, because the whole point of putting this in code rather
than in a prompt is that a threshold change should be visible in review.
"""
from app.enrichment import ad_signals as ads


def _sig(platforms, evidence, score, landing=None, identifiers=None):
    return {
        "advertising": {
            "platforms": platforms,
            "evidence": evidence,
            "identifiers": identifiers or {},
            "landing_pages": landing or [],
            "score": score,
        }
    }


def test_a_conversion_tag_plus_breadth_confirms_an_advertiser():
    # A Google Ads conversion ID exists to optimise paid spend. Combined with a
    # second platform and campaign landing pages, this is as close to proof as
    # a company's own website ever gets.
    v = ads.classify(
        _sig(
            ["Google Ads", "Meta"],
            ["Google Ads: conversion tracking", "Meta: Meta Pixel"],
            5,
            landing=["https://x.com/lp/spring", "https://x.com/offer/demo"],
        ),
        website="https://x.com",
        company="X Co",
    )
    assert v["state"] == ads.STATE_CONFIRMED
    assert v["confidence"] >= 80
    assert ads.is_advertiser(v)


def test_a_lone_pixel_is_probable_not_confirmed():
    # A Meta Pixel can sit on a site for years after the last campaign stopped.
    # It earns a shortlist place, never a verdict.
    v = ads.classify(_sig(["Meta"], ["Meta: Meta Pixel"], 2), website="https://y.com")
    assert v["state"] == ads.STATE_PROBABLE
    assert v["confidence"] < 70
    assert ads.is_advertiser(v)


def test_a_high_score_without_a_conversion_tag_stays_probable():
    # Breadth alone must not promote a lead to "confirmed". Three stale pixels
    # are three stale pixels.
    v = ads.classify(
        _sig(
            ["Meta", "TikTok", "LinkedIn Ads"],
            ["Meta: Meta Pixel", "TikTok: TikTok Pixel", "LinkedIn Ads: Insight Tag"],
            6,
        ),
        website="https://z.com",
    )
    assert v["score"] >= ads.CONFIRMED_AT
    assert v["state"] == ads.STATE_PROBABLE


def test_a_clean_site_is_no_evidence_and_still_returns_the_full_shape():
    v = ads.classify({}, website="https://quiet.com", company="Quiet")
    assert v["state"] == ads.STATE_NONE
    assert not ads.is_advertiser(v)
    # Callers and the UI must never branch on key presence.
    for key in ("platforms", "evidence", "landing_pages", "scale_indicators", "verify", "summary"):
        assert key in v


def test_no_verdict_ever_reports_a_spend_figure():
    # The client's bar is $10K/month. Nothing observable on a website supports
    # that number, so nothing here may imply it.
    v = ads.classify(
        _sig(["Google Ads"], ["Google Ads: conversion tracking"], 3), website="https://x.com"
    )
    assert v["spend_bar"]["determinable_from_site"] is False
    blob = repr(v)
    assert "$" not in blob.replace("$10K/month", "")


def test_not_assessed_is_distinct_from_no_evidence():
    # The failure mode this guards: the in-house crawler runs, collects no ad
    # tags because it never looks for them, and a good prospect is filtered out
    # as a non-advertiser.
    v = ads.not_assessed(website="https://x.com", company="X Co")
    assert v["state"] == ads.STATE_UNASSESSED
    assert v["state"] != ads.STATE_NONE
    assert not ads.is_advertiser(v)
    assert v["verify"], "a human must still be able to check by hand"


def test_verify_links_target_the_libraries_unicorn_actually_uses():
    v = ads.classify(_sig(["Meta"], ["Meta: Meta Pixel"], 2), website="https://www.acme.co.uk", company="Acme Ltd")
    urls = {link["platform"]: link["url"] for link in v["verify"]}
    assert "facebook.com/ads/library" in urls["Meta"]
    assert "Acme+Ltd" in urls["Meta"]
    # www. is stripped so the Transparency Center matches the advertiser domain.
    assert "domain=acme.co.uk" in urls["Google"]


def test_the_domain_is_the_search_term_when_no_company_name_is_known():
    v = ads.classify(_sig(["Meta"], ["Meta: Meta Pixel"], 2), website="https://blue-widgets.com")
    meta = next(link for link in v["verify"] if link["platform"] == "Meta")
    assert "blue+widgets" in meta["url"]


def test_attribution_software_is_reported_as_scale_not_as_spend():
    # Triple Whale is bought by companies whose spend justifies attribution
    # software. That is an operational indicator, and it is labelled as one.
    v = ads.classify(
        _sig(
            ["Google Ads", "Meta", "Triple Whale"],
            ["Google Ads: conversion tracking", "Meta: Meta Pixel", "Triple Whale: paid attribution platform"],
            6,
        ),
        website="https://shop.com",
    )
    assert any("attribution" in s for s in v["scale_indicators"])
    assert v["spend_bar"]["determinable_from_site"] is False


def test_scoring_is_explainable_line_by_line():
    # Every point added must be attributable, or a threshold argument becomes
    # unfalsifiable.
    v = ads.classify(
        _sig(["Google Ads", "Meta"], ["Google Ads: conversion tracking"], 3, landing=["/lp/a"]),
        website="https://x.com",
    )
    assert v["score"] == v["base_score"] + 1 + 1  # breadth + one landing page
    assert len(v["scoring"]) == 3


def test_export_columns_align_with_their_headers():
    v = ads.classify(
        _sig(["Google Ads", "Meta"], ["Google Ads: conversion tracking"], 5),
        website="https://acme.com", company="Acme",
    )
    row = ads.export_columns(v)
    assert len(row) == len(ads.EXPORT_HEADERS)
    cells = dict(zip(ads.EXPORT_HEADERS, row))
    assert cells["ad_status"] == ads.STATE_CONFIRMED
    assert cells["ad_platforms"] == "Google Ads; Meta"
    assert "facebook.com/ads/library" in cells["meta_ad_library_url"]
    assert "adstransparency.google.com" in cells["google_ads_transparency_url"]


def test_export_leaves_confidence_blank_when_nothing_was_assessed():
    # A "0" in a confidence column reads as a measured zero. It was not measured.
    row = ads.export_columns(ads.not_assessed(website="https://acme.com"))
    cells = dict(zip(ads.EXPORT_HEADERS, row))
    assert cells["ad_status"] == ads.STATE_UNASSESSED
    assert cells["ad_confidence"] == ""


def test_export_of_a_lead_that_never_ran_is_all_blank_not_a_crash():
    assert ads.export_columns({}) == ["", "", "", "", "", ""]
    assert ads.export_columns(None) == ["", "", "", "", "", ""]
