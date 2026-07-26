"""Focused regression checks for the evidence-first enrichment architecture.

Run: python -m tests.test_enrichment_quality
No network or AI calls are made.
"""
from app.enrichment import crawler
from app.enrichment.crawler import _discover_sitemap, crawl_site
from app.enrichment.pipeline import (
    _augmented_formats,
    _assign_evidence,
    _flatten_signals,
    _qc_failures,
    _research_packet,
    _reading_instruction,
    _validate_text_evidence,
)


PASS = []


def check(name, condition):
    PASS.append(bool(condition))
    print(("✓" if condition else "✗ FAIL"), name)
    assert condition, name


def main():
    html = """
    <html><head><title>Proof Studio</title></head><body>
      <main>
        <h1>Fierce Advocates for Justice</h1>
        <p>Annual Fund revenue increased 60% and the campaign finished one year early.</p>
        <figure><img src="/john-jay-result.jpg" alt="John Jay College case study">
          <figcaption>Justice campaign impact</figcaption></figure>
      </main>
    </body></html>
    """
    crawl = crawl_site("https://proof.example/case-study/john-jay", html_override=html)
    check("page-level records retained", len(crawl["page_records"]) == 1)
    check("case study page classified", crawl["page_records"][0]["page_type"] == "case_study")
    check("image labels retained in research text", "John Jay College case study" in crawl["text"])
    check("image candidate keeps source page",
          crawl["image_candidates"][0]["page_url"].endswith("/case-study/john-jay"))
    lazy_html = """
    <html><body><img src="data:image/gif;base64,AAAA"
      data-src="/real-case-study.jpg" alt="Named client case study"></body></html>
    """
    lazy = crawl_site("https://proof.example/work", html_override=lazy_html)
    check("lazy image resolves to the real asset",
          lazy["image_candidates"][0]["url"] == "https://proof.example/real-case-study.jpg")

    class FakeResponse:
        def __init__(self, status_code, text):
            self.status_code, self.text = status_code, text

    original_get = crawler.requests.get
    sitemap_docs = {
        "https://proof.example/sitemap.xml":
            "<sitemapindex><sitemap><loc>https://proof.example/work-sitemap.xml</loc></sitemap></sitemapindex>",
        "https://proof.example/work-sitemap.xml":
            "<urlset><url><loc>https://proof.example/case-study/flagship</loc></url></urlset>",
    }
    crawler.requests.get = lambda url, **_: FakeResponse(
        200, sitemap_docs[url]) if url in sitemap_docs else FakeResponse(404, "")
    try:
        discovered = _discover_sitemap("https://proof.example", "proof.example")
    finally:
        crawler.requests.get = original_get
    check("nested sitemap indexes are followed",
          discovered == ["https://proof.example/case-study/flagship"])

    pages = [
        {"url": "https://proof.example/case", "page_type": "case_study",
         "title": "Case", "text": "Annual Fund revenue increased 60%."},
        {"url": "https://proof.example/", "page_type": "homepage",
         "title": "Home", "text": "Generic homepage text " * 1000},
    ]
    packet = _research_packet({"page_records": pages}, 1400)
    check("research packet labels source URLs", "URL: https://proof.example/case" in packet)
    check("high-value page survives content budget", "Annual Fund revenue increased 60%" in packet)
    long_case = [{
        "url": "https://proof.example/deep-case", "page_type": "case_study",
        "title": "Deep case", "text": ("Background and process. " * 100)
        + "Annual Fund revenue increased 60% and the $50 million campaign finished early.",
    }]
    proof_packet = _research_packet({"page_records": long_case}, 1100)
    check("late-page measurable proof survives truncation", "60%" in proof_packet
          and "$50 million" in proof_packet)

    evidence = _validate_text_evidence({"page_records": pages}, [{
        "type": "measurable_result",
        "claim": "Annual Fund revenue increased 60%",
        "source_url": "https://proof.example/case",
        "supporting_quote": "Annual Fund revenue increased 60%",
    }, {
        "type": "award", "claim": "Won a global award",
        "source_url": "https://proof.example/case",
        "supporting_quote": "A quote that is not on the page",
    }])
    check("only source-verifiable evidence survives", len(evidence) == 1)
    check("validated evidence has stable id", evidence[0]["id"] == "ev_1")

    facts = {"_evidence_version": 2, "evidence": evidence}
    signals = _flatten_signals(facts)
    check("provenance survives signal scoring", signals[0]["source_url"] == evidence[0]["source_url"])
    formats = [{"name": "value_proposition", "label": "Value proposition"}]
    assignments = _assign_evidence(facts, formats)
    check("variable assignment exposes supporting quote",
          assignments["value_proposition"]["supporting_quote"].endswith("60%"))

    good = {"value_proposition": "John Jay's Annual Fund revenue increased 60%."}
    bad = {"value_proposition": "John Jay's Annual Fund revenue increased 75%."}
    generic = {"value_proposition": "We can help increase your revenue and create more growth."}
    check("supported number passes QC", not _qc_failures(good, assignments, facts))
    check("invented number fails QC", "unsupported number" in
          _qc_failures(bad, assignments, facts)["value_proposition"])
    check("generic copy cannot borrow a broad evidence word",
          "distinctive anchor" in _qc_failures(generic, assignments, facts)["value_proposition"])

    product_facts = {"_evidence_version": 2, "evidence": [{
        "id": "ev_2", "type": "project",
        "claim": "Cambot 360 AI-Powered 3D Camera",
        "source_url": "https://proof.example/cambot",
        "supporting_quote": "Four 4K lenses create auto-stitched 16K views with AI autofocus.",
        "source_kind": "html", "confidence": 1,
    }]}
    product_formats = [{"name": "product_complimentary", "label": "Product compliment",
                        "examples": ["old one", "approved two", "approved three"]}]
    product_assign = _assign_evidence(product_facts, product_formats)
    weak_product = {"product_complimentary":
                    "Cambot 360 looks advanced. Is it popular with clients?"}
    strong_product = {"product_complimentary":
                      "Cambot 360's four 4K lenses creating auto-stitched 16K views are ambitious. "
                      "Is it a flagship project?"}
    check("project name without its meaningful detail fails QC",
          "omits the concrete detail" in
          _qc_failures(weak_product, product_assign, product_facts, product_formats)
          ["product_complimentary"])
    check("specific mechanism plus question passes product QC",
          not _qc_failures(strong_product, product_assign, product_facts, product_formats))
    augmented = _augmented_formats(product_formats, product_assign)
    check("only two recent approved examples enter the paid prompt",
          augmented[0]["examples"] == ["approved two", "approved three"])
    check("B2 is the detailed default writing standard",
          "B2-level business English" in _reading_instruction(""))
    too_complex = {"value_proposition":
                   "John Jay's Annual Fund revenue increased 60% while this concrete proof "
                   "creates a detailed commercial narrative that enables multiple stakeholders "
                   "throughout a complicated purchasing committee to understand the strategic implications "
                   "and consequently move the opportunity forward with substantially greater organizational confidence."}
    check("B2 QC rejects an overlong sentence",
          "longer than 40 words" in
          _qc_failures(too_complex, assignments, facts, formats, "b2 business")["value_proposition"])
    rejected_formats = [{**product_formats[0], "rejected_examples": [
        {"text": "Cambot is technically sophisticated.", "reason": "Too vague."},
        {"text": "Leveraging this capability is impressive.", "reason": "Too corporate."},
        {"text": "Cambot has innovative solutions.", "reason": "Generic filler."},
    ]}]
    rejected_augmented = _augmented_formats(rejected_formats, product_assign)
    check("only two recent rejected examples enter the paid prompt",
          [x["reason"] for x in rejected_augmented[0]["avoid_examples"]]
          == ["Too corporate.", "Generic filler."])

    print(f"\n{sum(PASS)}/{len(PASS)} checks passed")


if __name__ == "__main__":
    main()
