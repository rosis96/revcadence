"""AI extraction layer. Uses OpenAI (OPENAI_API_KEY / OPENAI_MODEL env) when
available; otherwise a deterministic demo extractor so the full pipeline runs
end-to-end with zero cost — the same demo-mode philosophy as the enrichment
dashboard. Both paths return the same shape."""
import json
import os
import re

import requests

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

# Model split (env-configurable — NEVER hardcode a model in a call path).
# Default to gpt-4o everywhere: it is the PROVEN model behind the good results
# (Athenaworks, 7-Eleven). The GPT-5.6 "cost" line looked cheaper per token but in
# practice cost MORE (reasoning/hidden tokens) and wrote worse, so it is not the
# default. Cost is controlled by the token cuts (caching, capped evidence, smaller
# windows, vision off), not by downgrading the model. All overridable via env / UI.
def extract_model() -> str:
    return os.getenv("EXTRACT_MODEL", "gpt-4o")


def writer_model() -> str:
    return os.getenv("WRITER_MODEL", "gpt-4o")


def competitor_model() -> str:
    return os.getenv("COMPETITOR_MODEL", "gpt-4o-mini")


def vision_model() -> str:
    return os.getenv("VISION_MODEL", "gpt-4o-mini")


# Content budgets (env cost levers — input tokens dominate ~10:1).
# Reference incident: EXTRACT_CONTENT_CHARS=22000 caused runaway spend. Keep modest.
def extract_content_chars() -> int:
    return int(os.getenv("EXTRACT_CONTENT_CHARS", "8000"))


def writer_content_chars() -> int:
    return int(os.getenv("WRITER_CONTENT_CHARS", "6000"))

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

# Richer schema extracted from a real discovery-call (Fathom) transcript.
BLUEPRINT_TRANSCRIPT_SCHEMA = {
    "hero_subtitle": "one punchy sentence for the top of the page, specific to them",
    "industry": "their industry in a few words",
    "exec_summary": "3-4 sentences: where they are and the opportunity, grounded in the call",
    "what_we_see": "one honest, specific admiration paragraph about their business (from the call)",
    "bottlenecks": "list of 2-4 concrete revenue bottlenecks they described, each one sentence",
    "what_we_build": "list of 4-6 concrete things we will build/run for them (their words where possible)",
    "roadmap": "list of 3-5 phases, each 'Phase name: what happens' from onboarding to steady state",
    "their_words": "list of up to 4 short verbatim pull-quotes from the prospect in the transcript",
    "commercial": "pricing/scope EXACTLY as discussed on the call (retainer, performance, setup) — empty string if no price was mentioned; NEVER invent a number",
    "target_outcome": "the concrete result they want, one sentence",
    "notes_for_ascendly": "internal note: anything to double-check or any mismatch between what they want and what we offer (never shown to the client)",
}


def has_ai() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _call_openai(system: str, user: str, model: str = "") -> dict:
    chosen = (model or extract_model()).lower()
    payload = {
        "model": chosen,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }
    # GPT-5-family models use reasoning effort rather than sampling temperature.
    # Low is enough because evidence planning/ranking is deterministic in code.
    if chosen.startswith("gpt-5"):
        payload["reasoning_effort"] = "low"
    else:
        payload["temperature"] = 0.2
    resp = requests.post(
        OPENAI_URL,
        headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])


def analyze_site_images(company: str, images: list, limit: int = 3) -> list:
    """Read a tiny, evidence-ranked set of website images.

    Image analysis is deliberately bounded and can be disabled with
    ENRICH_IMAGE_VISION=0. It is for visible names, project labels, diagrams,
    awards and metrics—not aesthetic guesses. Returned observations remain
    explicitly marked as visual until the evidence normalizer validates them.
    """
    if not has_ai() or os.getenv("ENRICH_IMAGE_VISION", "1") != "1":
        return []
    selected = [x for x in (images or []) if x.get("url")][:max(0, min(limit, 5))]
    if not selected:
        return []
    content = [{
        "type": "text",
        "text": (
            f"Company: {company}\nInspect these images from the company's own website. "
            "Extract ONLY text or concrete facts visibly present: named clients/projects, "
            "methodologies, awards, services, or measurable results. Do not infer quality, "
            "importance, intent, or business performance. Return JSON "
            '{"observations":[{"image_url":str,"page_url":str,"type":str,'
            '"claim":str,"visible_text":str,"confidence":0-1}]}. '
            "Return an empty observations list if an image is decorative or ambiguous."
        ),
    }]
    allowed = {}
    for image in selected:
        allowed[image["url"]] = image
        content.append({"type": "text", "text": json.dumps({
            "image_url": image["url"], "page_url": image.get("page_url", ""),
            "alt": image.get("alt", ""), "caption": image.get("caption", ""),
        })})
        content.append({"type": "image_url", "image_url": {"url": image["url"], "detail": "low"}})
    try:
        selected_model = vision_model().lower()
        vision_payload = {
            "model": selected_model,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content":
                          "You are a conservative visual evidence extractor. Never guess."},
                         {"role": "user", "content": content}],
        }
        if selected_model.startswith("gpt-5"):
            vision_payload["reasoning_effort"] = "low"
        else:
            vision_payload["temperature"] = 0
        resp = requests.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
                     "Content-Type": "application/json"},
            json=vision_payload,
            timeout=90,
        )
        resp.raise_for_status()
        raw = json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception:
        return []
    out = []
    for obs in raw.get("observations") or []:
        image_url = str(obs.get("image_url") or "")
        meta = allowed.get(image_url)
        claim = str(obs.get("claim") or "").strip()
        visible = str(obs.get("visible_text") or "").strip()
        try:
            confidence = float(obs.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0
        if not meta or not claim or confidence < 0.75:
            continue
        out.append({
            "type": str(obs.get("type") or "visual").strip(),
            "claim": claim, "supporting_quote": visible,
            "source_url": meta.get("page_url", ""), "image_url": image_url,
            "source_kind": "image", "confidence": min(confidence, 1.0),
        })
    return out[:12]


def extract_company(crawl: dict) -> dict:
    """crawl → structured company facts + provenance marker."""
    if has_ai() and crawl.get("text"):
        system = ("You extract verified facts from website text. Only state what the text "
                  "supports — never invent. Return JSON with keys: "
                  + json.dumps(COMPANY_SCHEMA))
        user = (f"Website: {crawl.get('url')}\nTitle: {crawl.get('title')}\n"
                f"Meta: {crawl.get('meta_description')}\n\nSite text:\n"
                f"{crawl.get('text')[:extract_content_chars()]}")
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


def find_competitors(company_name: str, industry: str = "", services=None) -> list:
    """Top-3 real competitors from model knowledge (NO web search — the cheap
    version was chosen deliberately). Anti-fabrication is mandatory: never
    invent a name to fill a slot. Returns [{name, why}] (possibly fewer/empty)."""
    if not has_ai():
        return []  # demo mode: no fabrication, return none
    system = ("You identify real competitor companies from your knowledge. "
              "CRITICAL: only name companies you are confident genuinely exist; "
              "never invent a name to fill a slot; return fewer or none if unsure. "
              'Return JSON: {"competitors": [{"name": str, "why": one short sentence}]} '
              "with at most 3 entries.")
    user = json.dumps({"company": company_name, "industry": industry,
                       "services": services or []})
    try:
        out = _call_openai(system, user, model=competitor_model())
        comps = out.get("competitors", [])
        return [{"name": str(c.get("name", "")).strip(), "why": str(c.get("why", "")).strip()}
                for c in comps if c.get("name")][:3]
    except Exception:
        return []


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


def blueprint_from_transcript(company: dict, contact: dict, transcript: str) -> dict:
    """Turn a discovery-call (Fathom) transcript into a full, personalized
    blueprint. Grounds every section in what was actually said; pricing comes
    ONLY from the call. AI-required — returns a clearly-marked template draft when
    no key is set so the flow still works."""
    transcript = (transcript or "").strip()
    if has_ai() and transcript:
        system = (
            "You are Ascendly/RevCadence's blueprint writer. From a real discovery-call transcript, "
            "produce a personalized Growth Blueprint for THIS prospect. Ground every section in what "
            "was actually said — do not invent facts, numbers, or pricing. If a price/scope was quoted "
            "on the call, capture it verbatim in 'commercial'; if none was, leave 'commercial' empty. "
            "No buzzwords (never: leverage, robust, seamless, unlock, elevate, world-class). "
            "Write like a sharp human. Return JSON with keys: " + json.dumps(BLUEPRINT_TRANSCRIPT_SCHEMA))
        user = json.dumps({"company": company, "contact": contact,
                           "transcript": transcript[:24000]})
        try:
            data = _call_openai(system, user)
            data["_source"] = "openai"
            return data
        except Exception as e:
            out = _blueprint_transcript_fallback(company, contact)
            out["_source"] = f"template (openai failed: {str(e)[:120]})"
            return out
    out = _blueprint_transcript_fallback(company, contact)
    out["_source"] = "template (no transcript or no OPENAI_API_KEY)"
    return out


def _blueprint_transcript_fallback(company: dict, contact: dict) -> dict:
    name = company.get("name", "your company")
    return {
        "hero_subtitle": f"A managed revenue engine built for {name}.",
        "industry": company.get("industry", ""),
        "exec_summary": f"This is a draft blueprint for {name}. Add a call transcript and regenerate to "
                        "personalize every section from what was actually discussed.",
        "what_we_see": f"{name} has a real business and a clear reason prospects reach out — the opportunity "
                       "is to make that pipeline consistent and instrumented.",
        "bottlenecks": ["Lead follow-up is manual, so speed and consistency drop as volume grows.",
                        "There's no single instrumented pipeline, so deals stall without a clear next step."],
        "what_we_build": ["Managed outbound + inbound reply handling", "CRM automation and pipeline instrumentation",
                          "Meeting scheduling with real open times", "Proposal and follow-up recovery"],
        "roadmap": ["Onboarding: connect systems, set ICP and messaging.",
                    "Build: infrastructure, copy, and CRM workflows.",
                    "Launch & manage: go live, handle replies, book meetings.",
                    "Optimize: report, refine, and scale what works."],
        "their_words": [],
        "commercial": "",
        "target_outcome": "A predictable flow of qualified meetings without added headcount.",
        "notes_for_ascendly": "Draft generated without a transcript — regenerate with the call for a real blueprint.",
    }
