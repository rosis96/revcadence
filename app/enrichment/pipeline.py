"""The Verify → Enrich pipeline, ported from the enrichment dashboard's
_pipeline_one. Cheapest-first funnel — ORDER IS DELIBERATE, DO NOT REORDER:

  1. FREE verify   → reject dead emails at $0        → status "invalid"
  2. Reoon verify  → mailbox real? not safe → stop   → status "unsafe"
  3. Title gate + ICP (one scrape + one extraction)  → Non-ICP → "skipped"
  4. Write copy (reuses the ICP context — no second scrape/extraction) → "done"

Resume semantics: leads already in a TERMINAL status are never re-processed.
"""
import json
import re
import unicodedata
from datetime import datetime

from ..models.enrich import TERMINAL_STATUSES, EnrichConfig, EnrichLead
from . import ai
from .crawler import crawl_site
from .engine import SENIOR_TITLES
from .reoon import verify_one
from .verify_free import check as free_check

# Invisible / control characters that make downstream tools (Instantly, Excel,
# some CRMs) reject a cell as "characters that cannot be stored". AI writers and
# copy-paste routinely sneak these in: zero-width spaces/joiners, BOM, soft
# hyphen, directional marks, and line/paragraph separators.
_KILL_CHARS = {0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD,
               0x200E, 0x200F, 0x061C, 0x2028, 0x2029, 0x180E, 0xFFFE, 0xFFFF}


def sanitize_text(v):
    """Make any value safe to drop into a CSV cell: normalize to NFC, strip
    zero-width/format/control characters, fold stray newlines/tabs to spaces,
    and collapse runs of whitespace. Visible content is preserved exactly."""
    if v is None:
        return ""
    s = unicodedata.normalize("NFC", str(v))
    out = []
    for ch in s:
        o = ord(ch)
        cat = unicodedata.category(ch)
        if ch in ("\n", "\r", "\t") or cat in ("Zl", "Zp"):
            out.append(" "); continue          # line/para breaks → space (keep words apart)
        if o in _KILL_CHARS:
            continue
        if cat in ("Cc", "Cf", "Cs", "Co"):
            continue
        out.append(ch)
    return " ".join("".join(out).split())


def _config(db, workspace_id) -> EnrichConfig:
    cfg = db.query(EnrichConfig).filter(EnrichConfig.workspace_id == workspace_id).first()
    if cfg is None:
        cfg = EnrichConfig(workspace_id=workspace_id)
        db.add(cfg)
        db.flush()
    return cfg


def _title_gate(title: str) -> bool:
    t = (title or "").lower()
    return any(s in t for s in SENIOR_TITLES)


def _icp_and_facts(lead: EnrichLead, cfg: EnrichConfig) -> dict:
    """One scrape + one extraction; returns ctx reused by the writer."""
    deep = getattr(cfg, "research_depth", "") == "deep"
    # Research the PROSPECT the way a human would: read MULTIPLE pages (follow_all
    # reaches the /work, /case-study, /about pages where the real proof lives) and
    # render JS when a render key is configured (render=True is a safe no-op
    # otherwise). Homepage-only, no-render crawls are the #1 reason copy comes out
    # generic — the citeable facts (named projects, clients, metrics) are on inner
    # pages and behind JS.
    crawl = crawl_site(lead.website, html_override=(lead.data or {}).get("html_override", ""),
                       max_pages=12 if deep else 6, max_chars=32000 if deep else 18000,
                       follow_all=True, render=True)
    if crawl.get("error") or not crawl.get("text"):
        return {"error": crawl.get("error") or "no website content", "crawl": crawl}
    if ai.has_ai():
        # Structured ICP brain (legacy ICP_JSON): procedure steps, allowed
        # categories, hard_non_icp auto-rejects, default-when-unsure.
        icp_block = cfg.icp_definition or "B2B companies selling high-value services to other businesses."
        try:
            icp = json.loads(cfg.icp_definition or "")
            icp_block = ""
            if icp.get("procedure"):
                icp_block += "PROCEDURE (follow in order):\n" + "\n".join(icp["procedure"]) + "\n"
            if icp.get("icp_categories"):
                icp_block += "ICP CATEGORIES (allowed fits):\n- " + "\n- ".join(icp["icp_categories"]) + "\n"
            if icp.get("hard_non_icp"):
                icp_block += "HARD NON-ICP (auto-reject if any matches):\n- " + "\n- ".join(icp["hard_non_icp"]) + "\n"
            if icp.get("default"):
                icp_block += f"WHEN UNSURE, RETURN: {icp['default']}\n"
        except Exception:
            pass  # plain-text ICP definition — use as-is
        system = ("You are an ICP classifier and fact extractor. Ground everything ONLY in the "
                  "provided site text — never invent. ICP definition (single source of truth):\n"
                  + icp_block
                  + "\nAlso pull SPECIFIC, CITEABLE PROOF from the site so cold email can reference real "
                    "detail (never invent; copy names/numbers verbatim; leave a field empty if not present). "
                    'Return JSON: {"icp_decision": "ICP"|"Non-ICP"|"Needs Review", "icp_score": 0-100, '
                    '"icp_reason": str, "industry": str, "facts": {"description": str, "services": [str], '
                    '"notable_work": [str — named projects/campaigns/case studies, each WITH any stated '
                    'outcome or metric], "clients": [str — named clients/brands they have worked with], '
                    '"proof_points": [str — awards, numbers, results, recognitions], '
                    '"differentiators": [str — named methodologies/frameworks or what makes them distinct]}}')
        research_chars = 14000 if deep else 10000
        user = (f"Company: {lead.company}\nSite: {crawl.get('url')}\nText:\n"
                f"{crawl.get('text')[:research_chars]}")
        try:
            out = ai._call_openai(system, user, model=ai.extract_model())
            out["crawl"] = crawl
            out["source"] = "openai"
            return out
        except Exception as e:
            pass  # fall through to demo
    facts = ai.extract_company(crawl)
    fit = facts.get("icp_fit", "unknown")
    return {"icp_decision": "ICP" if fit in ("strong", "possible") else "Needs Review",
            "icp_score": {"strong": 85, "possible": 60}.get(fit, 40),
            "icp_reason": facts.get("icp_reason", ""), "industry": facts.get("industry", ""),
            "facts": {"description": facts.get("description", ""), "services": facts.get("services", [])},
            "crawl": crawl, "source": "demo"}


def _write_copy(lead: EnrichLead, cfg: EnrichConfig, ctx: dict, enrichments=None) -> dict:
    """Writes the configured variables, reusing ctx (no second scrape).
    `enrichments`: selected output variable names (legacy 'choose enrichments
    to output') — empty/None = all configured."""
    # Variable selection: honour each variable's on/off flag (default on), then an
    # optional per-run narrowing. This is what lets you choose which variables get
    # written instead of always writing every one.
    formats = [f for f in (cfg.formats or []) if f.get("enabled", True)]
    if enrichments:
        sel = [f for f in formats if f.get("name") in enrichments]
        if sel:
            formats = sel
    if not formats:
        formats = [{"label": "Personalized First Line", "name": "personalized_first_line",
                    "guidance": "One specific sentence proving we researched THIS company, "
                                "grounded in a real fact from their site. No generic flattery.",
                    "min_words": 12, "max_words": 25}]
    rules = [ln.strip() for ln in (cfg.rules or "").splitlines() if ln.strip()]
    if ai.has_ai():
        reading = (getattr(cfg, "reading_level", "") or "").strip()
        level_line = (f"\nREADING LEVEL: write so a {reading} reader understands it easily — "
                      "short sentences, everyday words, no jargon." if reading else "")
        # Static prefix FIRST (prompt caching), per-lead content LAST — preserve ordering.
        system = ("You write personalized cold-email copy grounded ONLY in verified facts. "
                  "Never fabricate. Match each variable's guidance and word range exactly. "
                  "GROUND IN SPECIFICS: lead with the most concrete, checkable detail available about "
                  "the prospect — a named project, client, campaign, metric, methodology, or award from "
                  "VERIFIED FACTS (notable_work / clients / proof_points / differentiators) or the site "
                  "excerpt. One real, verifiable detail beats any amount of general praise. "
                  "BANNED — never write vague flattery with no specific fact behind it: 'impressive', "
                  "'truly sets a high standard', 'world-class', 'sets you apart', 'love how', 'bold and "
                  "dynamic', 'high standard in the industry', or similar. If you have no specific verified "
                  "detail for a variable, use its 'fallback' instruction when provided; if there is no "
                  "fallback and no specific fact, return an empty string for that variable (never pad with "
                  "praise, never invent). "
                  "Use the CLIENT PROFILE as the voice of an insider: when it helps, connect the "
                  "prospect to the profile's problem_library entry for their industry, and reference a "
                  "case_study or proof_point ONLY if it genuinely fits — never invent one or its metrics."
                  + level_line +
                  "\nCLIENT PROFILE:\n" + json.dumps(cfg.profile or {}) +
                  "\nGLOBAL RULES (obey every line):\n" + "\n".join(rules) +
                  "\nVARIABLES (return JSON keyed by 'name'):\n" + json.dumps(formats))
        deep = getattr(cfg, "research_depth", "") == "deep"
        wc = 16000 if deep else 9000
        user = ("LEAD: " + json.dumps({"first_name": lead.first_name, "company": lead.company,
                                       "title": lead.title}) +
                "\nVERIFIED FACTS: " + json.dumps(ctx.get("facts", {})) +
                "\nSITE EXCERPT:\n" + (ctx.get("crawl", {}).get("text", "")[:wc]))
        try:
            out = ai._call_openai(system, user,
                                  model=(getattr(cfg, "writer_model", "") or ai.writer_model()))
            return {"vars": {f["name"]: out.get(f["name"], "") for f in formats}, "source": "openai"}
        except Exception:
            pass
    desc = (ctx.get("facts", {}) or {}).get("description", "") or f"what {lead.company} does"
    return {"vars": {f.get("name", f"var_{i}"):
                     f"Really like how {lead.company} focuses on {desc[:80].rstrip('.')} — impressive work."
                     for i, f in enumerate(formats)}, "source": "demo"}


_EMAIL_RE = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_EMAIL_KEYS = {"email", "email address", "e-mail", "e mail", "work email",
               "primary email", "email_address", "emailaddress", "mail"}


def _reoon_key(cfg) -> str:
    """The Reoon API key to verify with: the workspace's saved key (encrypted in
    config) first, else the REOON_API_KEY env var. Empty = no verification."""
    import os

    from ..crypto import decrypt
    enc = getattr(cfg, "reoon_api_key_enc", "") or ""
    return (decrypt(enc) if enc else "") or os.getenv("REOON_API_KEY", "")


def email_from_row(data) -> str:
    """Recover an email from the raw uploaded row when the standard lead.email is
    empty (import didn't map the CSV's email column). Prefers a column that looks
    like an email header, else the first value that looks like an email address."""
    if not isinstance(data, dict):
        return ""
    for k, v in data.items():
        if str(k).strip().lower().rstrip(".") in _EMAIL_KEYS and v:
            m = _EMAIL_RE.search(str(v))
            if m:
                return m.group(0).lower()
    for v in data.values():
        if isinstance(v, str) and "@" in v:
            m = _EMAIL_RE.search(v)
            if m:
                return m.group(0).lower()
    return ""


def process_lead(db, lead: EnrichLead, cfg: EnrichConfig, steps: str = "pipeline",
                 enrichments=None) -> str:
    """Run one lead through the funnel. steps: 'esp' (provider detection only),
    'verify' (stop after Reoon) or 'pipeline' (full). Returns the resulting status."""
    # Self-heal: if the import left lead.email empty but the uploaded row carries
    # an email (mapping miss), backfill it now so ESP, Verify and export all work.
    if not (lead.email or "").strip():
        recovered = email_from_row(lead.data or {})
        if recovered:
            lead.email = recovered
    # ESP-only: fast, FREE, MX-based mailbox-provider detection. This is a
    # standalone first step — it NEVER charges Reoon and NEVER changes the funnel
    # status, so it can run on any lead (even already-verified ones) up front.
    if steps == "esp":
        email = lead.email or ""
        if "@" in email:
            from .verify_free import _doh_mx, _mx_hosts, esp_for
            domain = email.split("@", 1)[1].lower()
            # True if MX host already cached, else resolve now (populates _mx_hosts).
            res = True if domain in _mx_hosts else _doh_mx(domain)
            label = esp_for(domain)          # Microsoft | Google | Other | ""
            if label:
                lead.esp = label
            elif res is False:               # resolved but no mail server (parity: Unknown)
                lead.esp = "Unknown"
            # res is None → couldn't determine (transient); leave blank so a re-run retries
        db.commit()
        return lead.status or "esp"

    if lead.status in TERMINAL_STATUSES:
        return lead.status  # resume semantics — never re-charge finished work

    # 1. FREE verify ($0) + ESP detection (byproduct of the MX lookup)
    if not lead.free_status:
        v = free_check(lead.email)
        lead.free_status = v["verdict"]
        if "@" in (lead.email or ""):
            from .verify_free import esp_for
            lead.esp = lead.esp or esp_for(lead.email.split("@", 1)[1])
        if v["reject"]:
            lead.status = "invalid"
            lead.email_status = "skipped"     # Reoon credit saved
            lead.verify_source = "free"
            db.commit()
            return lead.status

    # 2. Reoon (mailbox-level). Single explicit decision:
    #    safe/valid            → deliverable, proceed
    #    catch_all/unknown     → proceed ONLY if the workspace's Only Safe is off
    #    anything else         → unsafe, stop (no ICP, no writer tokens)
    if not lead.email_status or lead.email_status == "skipped":
        r = verify_one(lead.email, key=_reoon_key(cfg))
        lead.email_status = r["status"]
        lead.verify_source = "reoon"
        lead.result = {**(lead.result or {}), "_reoon": r["raw"]}
        deliverable = r["status"] in ("safe", "valid")
        uncertain = r["status"] in ("catch_all", "unknown")
        if not deliverable and not (uncertain and not cfg.only_safe):
            lead.status = "unsafe"
            db.commit()
            return lead.status
    if steps == "verify":
        db.commit()
        return lead.status or "pending"

    # 3. Title gate (before any scraping) + ICP
    if not cfg.skip_title_gate and lead.title and not _title_gate(lead.title):
        lead.title_status = "rejected"
        lead.status = "skipped"
        lead.icp_decision = "Non-ICP"
        lead.icp_reason = "title gate: not a senior decision-maker"
        db.commit()
        return lead.status
    lead.title_status = lead.title_status or "pass"

    if not lead.website:
        lead.status = "error"
        lead.result = {**(lead.result or {}), "_error": "no website"}
        db.commit()
        return lead.status

    icp = _icp_and_facts(lead, cfg)
    if icp.get("error"):
        lead.status = "error"
        lead.result = {**(lead.result or {}), "_error": icp["error"]}
        db.commit()
        return lead.status
    lead.icp_decision = icp.get("icp_decision", "Needs Review")
    lead.icp_score = icp.get("icp_score")
    lead.icp_reason = icp.get("icp_reason", "")
    lead.industry = icp.get("industry", "")
    # ICP filtering: reject Non-ICP unless the workspace turned it off (then the
    # ICP is still recorded for reference, but every verified lead is enriched).
    if lead.icp_decision == "Non-ICP" and not getattr(cfg, "skip_icp", 0):
        lead.status = "skipped"
        db.commit()
        return lead.status

    # 4. Write copy — reuses icp ctx; no second scrape/extraction
    written = _write_copy(lead, cfg, icp, enrichments=enrichments)
    clean_vars = {k: sanitize_text(v) for k, v in written["vars"].items()}
    lead.result = {**(lead.result or {}), **clean_vars,
                   "_facts": icp.get("facts", {}), "_writer": written["source"]}
    lead.status = "done"
    lead.updated_at = datetime.utcnow()
    db.commit()
    return lead.status
