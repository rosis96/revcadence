"""Contract test between RevCadence and the Company Research API.

WHY THIS FILE EXISTS
--------------------
The mapper read the page body from ``markdown``/``text``. The API has always
called it ``content`` — ``output_format`` changes the *encoding* of that
string, never the key. So every page mapped to "", every response looked like
a failed crawl, and the pipeline silently fell back to the in-house crawler.
Nothing errored. Nothing logged. The integration simply never ran.

That is the failure mode a contract test exists to prevent: a shape change on
one side of a boundary that the other side absorbs as a plausible-looking
empty result. The fixture below is generated from the API's own Pydantic
models, so when the API's shape moves, this fails instead of the pipeline
going quiet.
"""
import json
import pathlib

from app.enrichment.company_research import _to_crawl_shape

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "company_research_response.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text())


def test_page_bodies_survive_the_mapping():
    crawl = _to_crawl_shape("https://ex.com", _payload())
    assert crawl["error"] is None, "a successful crawl must not be reported as an error"
    assert "skincare" in crawl["text"]
    assert "Founded in 2016" in crawl["text"]
    assert len(crawl["page_records"]) == 2
    assert all(r["text"] for r in crawl["page_records"])


def test_every_page_is_labelled_with_its_source_url():
    # The writer cites pages by URL; unlabelled text is ungroundable.
    crawl = _to_crawl_shape("https://ex.com", _payload())
    assert "# SOURCE: https://ex.com/" in crawl["text"]
    assert "# SOURCE: https://ex.com/about" in crawl["text"]


def test_site_signals_come_through_intact():
    crawl = _to_crawl_shape("https://ex.com", _payload())
    signals = crawl["signals"]
    assert signals["technologies"] == ["Shopify", "Klaviyo"]
    assert signals["employee_count"] == 42
    ads = signals["advertising"]
    assert "Google Ads" in ads["platforms"]
    assert ads["score"] == 6
    assert ads["landing_pages"]


def test_signals_are_never_the_organization_block_wearing_a_signals_hat():
    payload = _payload()
    payload["site"]["signals"] = None
    payload["site"]["organization"] = {"legal_name": "Example Co Ltd"}
    crawl = _to_crawl_shape("https://ex.com", payload)
    assert crawl["signals"] == {}, "absent signals must read as absent, not as an unrelated object"


def test_the_classifier_reads_the_mapped_signals_end_to_end():
    from app.enrichment import ad_signals

    crawl = _to_crawl_shape("https://ex.com", _payload())
    verdict = ad_signals.classify(crawl["signals"], website=crawl["url"], company="Example Co")
    assert verdict["state"] == ad_signals.STATE_CONFIRMED
    assert "Google Ads" in verdict["platforms"]
    assert any(link["platform"] == "Meta" for link in verdict["verify"])


def test_a_failed_crawl_is_reported_as_an_error_not_as_empty_success():
    payload = _payload()
    payload["status"] = "failed"
    payload["status_reason"] = "bot_blocked"
    payload["pages"] = []
    crawl = _to_crawl_shape("https://ex.com", payload)
    assert crawl["error"] == "bot_blocked"


def test_diagnostics_name_the_crawler_so_the_pipeline_can_tell_who_ran():
    # The ad classifier keys off this to distinguish "found nothing" from
    # "never looked". If the value drifts, leads get an unearned clean bill.
    crawl = _to_crawl_shape("https://ex.com", _payload())
    assert crawl["diagnostics"]["source"] == "company_research_api"
