"""AI extraction layer. Uses OpenAI (OPENAI_API_KEY / OPENAI_MODEL env) when
available; otherwise a deterministic demo extractor so the full pipeline runs
end-to-end with zero cost — the same demo-mode philosophy as the enrichment
dashboard. Both paths return the same shape."""
import json
import os
import re

import requests

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

COMPANY_SCHEMA = {
    "industry": "primary industry, 2-4 words",
    "description": "one factual sentence about what the company does",
    "services": "list of up to 5 concrete services/products found on the site",
    "location": "HQ city/region if stated, else empty",
    "employee_hint": "employee count or range if stated, else empty",
    "icp_fit": "one of: strong / possible / weak / unknown — B2B companies that sell to other businesses score higher",
    "icp_reason": "one short sentence explaining the fit",
}

BLUEPRINT_SECTIONS = {
    "exec_summary": "3-4 sentence executive summary of their revenue situation and the opportunity",
    "bottleneck": "the single most likely revenue bottleneck, one sentence",
    "recommendations": "list of 3 concrete recommended focus areas, each one sentence",
}


def has_ai() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _call_openai(system: str, user: str) -> dict:
    resp = requests.post(
        OPENAI_URL,
        headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
                 "Content-Type": "application/json"},
        json={
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])


def extract_company(crawl: dict) -> dict:
    """crawl → structured company facts + provenance marker."""
    if has_ai() and crawl.get("text"):
        system = ("You extract verified facts from website text. Only state what the text "
                  "supports — never invent. Return JSON with keys: "
                  + json.dumps(COMPANY_SCHEMA))
        user = (f"Website: {crawl.get('url')}\nTitle: {crawl.get('title')}\n"
                f"Meta: {crawl.get('meta_description')}\n\nSite text:\n{crawl.get('text')[:8000]}")
        try:
            data = _call_openai(system, user)
            data["_source"] = "openai"
            return data
        except Exception as e:
            demo = _demo_company(crawl)
            demo["_source"] = f"demo (openai failed: {e})"
            return demo
    demo = _demo_company(crawl)
    demo["_source"] = "demo"
    return demo


def _demo_company(crawl: dict) -> dict:
    """Deterministic no-cost extraction from title/meta/text."""
    text = (crawl.get("text") or "").lower()
    desc = crawl.get("meta_description") or crawl.get("title") or ""
    buckets = {
        "Software / SaaS": ("saas", "software", "platform", "api "),
        "Marketing / Agency": ("marketing", "agency", "seo", "advertis", "campaign"),
        "E-commerce": ("shop", "store", "e-commerce", "ecommerce"),
        "Professional Services": ("consult", "law", "account", "advisory"),
        "Landscaping / Trades": ("landscap", "plumb", "roof", "hvac", "construction"),
    }
    industry = next((name for name, keys in buckets.items() if any(k in text for k in keys)), "")
    services = re.findall(r"(?:we (?:offer|provide|specialize in)|our services include)\s+([^.]{10,80})", text)[:5]
    b2b = any(k in text for k in ("b2b", "businesses", "clients", "companies", "teams"))
    return {
        "industry": industry,
        "description": desc[:200],
        "services": services,
        "location": "",
        "employee_hint": "",
        "icp_fit": "possible" if b2b else "unknown",
        "icp_reason": "site mentions serving businesses" if b2b else "no clear B2B signal in demo mode",
    }


def generate_blueprint_content(company: dict, contact: dict, enrichment: dict) -> dict:
    """Blueprint sections from enrichment data. AI when available, structured
    fallback otherwise."""
    if has_ai():
        system = ("You write concise, specific revenue-blueprint sections for a B2B services firm. "
                  "No fluff, no buzzwords (never: leverage, robust, seamless, unlock, elevate). "
                  "Return JSON with keys: " + json.dumps(BLUEPRINT_SECTIONS))
        user = json.dumps({"company": company, "contact": contact, "enrichment": enrichment})[:8000]
        try:
            data = _call_openai(system, user)
            data["_source"] = "openai"
            return data
        except Exception:
            pass
    ind = enrichment.get("industry") or "their industry"
    return {
        "exec_summary": f"{company.get('name', 'The company')} operates in {ind}. "
                        "This blueprint outlines how a structured revenue system — captured leads, "
                        "systematic follow-up, and instrumented pipeline — increases qualified "
                        "meetings without added headcount.",
        "bottleneck": "Lead follow-up depends on manual effort, so response speed and consistency drop as volume grows.",
        "recommendations": [
            "Instrument every inbound reply with AI triage and drafted responses.",
            "Introduce a single pipeline with stage exit criteria and follow-up automation.",
            "Add meeting scheduling with timezone-correct proposed slots to cut booking friction.",
        ],
        "_source": "template",
    }
