"""The Verify → Enrich pipeline, ported from the enrichment dashboard's
_pipeline_one. Cheapest-first funnel — ORDER IS DELIBERATE, DO NOT REORDER:

  1. FREE verify   → reject dead emails at $0        → status "invalid"
  2. Reoon verify  → mailbox real? not safe → stop   → status "unsafe"
  3. Title gate + ICP (one scrape + one extraction)  → Non-ICP → "skipped"
  4. Write copy (reuses the ICP context — no second scrape/extraction)
     → "done", "needs_review", or "generation_failed"

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
from .writer_quality import (
    anchor_matches,
    evidence_terms,
    enrich_signal,
    local_candidate_score,
    plan_core_assignments,
    role_signal_score,
    supporting_detail_matches,
)

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


def _research_packet(crawl: dict, char_budget: int) -> str:
    """Build a balanced, source-labelled packet from ranked pages.

    The old implementation flattened the crawl then took the first N characters,
    which could hide the best case study behind homepage copy. This allocates a
    slice to every high-value page and keeps its URL attached.
    """
    pages = crawl.get("page_records") or []
    if not pages:
        return (crawl.get("text") or "")[:char_budget]
    # Preserve the strongest proof while guaranteeing a mix of work,
    # methodology/services and company-level context.
    selected = list(pages[:8])
    selected_urls = {p.get("url") for p in selected}
    for kind in ("work", "methodology", "services", "clients", "about", "homepage"):
        page = next((p for p in pages
                     if p.get("page_type") == kind and p.get("url") not in selected_urls), None)
        if page and len(selected) < 12:
            selected.append(page)
            selected_urls.add(page.get("url"))
    for page in pages:
        if len(selected) >= 12:
            break
        if page.get("url") not in selected_urls:
            selected.append(page)
            selected_urls.add(page.get("url"))
    pages = selected
    per_page = max(900, min(4200, char_budget // max(len(pages), 1)))
    chunks, used = [], 0
    for page in pages:
        header = (f"\n[PAGE]\nURL: {page.get('url', '')}\n"
                  f"TYPE: {page.get('page_type', 'other')}\n"
                  f"TITLE: {page.get('title', '')}\nTEXT:\n")
        room = min(per_page, char_budget - used - len(header))
        if room < 250:
            break
        body = _research_excerpt(page.get("text") or "", room)
        chunks.append(header + body)
        used += len(header) + len(body)
    return "\n".join(chunks)[:char_budget]


def _research_excerpt(text: str, room: int) -> str:
    """Keep both page identity and the proof-rich sentences within a small slice."""
    if len(text) <= room:
        return text
    lead_room = max(350, int(room * .52))
    lead = text[:lead_room].rstrip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    proof = []
    pattern = re.compile(
        r"[$€£]|\d+(?:[.,]\d+)?%?|\b(result|increas|grew|growth|reduc|award|"
        r"campaign|client|launch|fund|revenue|donor|enrollment|completed|impact)\b",
        re.I,
    )
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) >= 25 and pattern.search(sentence) and sentence not in lead:
            proof.append(sentence)
    suffix = ""
    for sentence in proof:
        candidate = (suffix + " " + sentence).strip()
        if len(lead) + 3 + len(candidate) > room:
            continue
        suffix = candidate
    return f"{lead}\nPROOF HIGHLIGHTS: {suffix}"[:room] if suffix else text[:room]


# The evidence-bank bucket keys the extractor returns. Used to recover the schema
# whether the model nests it under "facts" or flattens it to the top level.
_FACT_KEYS = ("category", "description", "services", "named_services", "frameworks",
              "named_clients", "case_studies", "measurable_results", "awards",
              "partnerships", "distinctive_projects", "target_industries",
              "decision_makers", "commercial_challenges", "evidence")


def _norm_for_match(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _corroborated(text_norm: str, needle: str) -> bool:
    """Grounded-but-tolerant match: True when the needle's distinctive tokens
    actually appear in the crawled text — so a real fact isn't dropped just because
    the model paraphrased a quote, while still refusing anything not on the site."""
    n = _norm_for_match(needle)
    if not n:
        return False
    if n in text_norm:
        return True
    words = [t for t in n.split() if len(t) >= 3]
    nums = [t for t in n.split() if t.isdigit()]
    distinct = words + nums
    if not words:                       # numeric/short-only → demand exact presence
        return n in text_norm
    if len(distinct) == 1:
        return distinct[0] in text_norm
    hits = sum(1 for t in distinct if t in text_norm)
    return hits >= max(2, int(0.75 * len(distinct)))


# Typed evidence buckets → canonical evidence type, corroborated against the site.
_CORROBORATE_BUCKETS = (
    ("named_clients", "named_client"), ("named_services", "named_service"),
    ("frameworks", "methodology"), ("distinctive_projects", "project"),
    ("awards", "award"), ("measurable_results", "measurable_result"),
)
# Tier B: softer-but-real specifics every ordinary B2B site has — the SPECIFIC
# services it offers and the audience it serves. This is exactly what a human (or
# ChatGPT) personalizes from when a site names no clients or metrics. Counted only
# when specific enough (generic single words like "consulting" are filtered out).
_CORROBORATE_TIER_B = (("services", "service"), ("target_industries", "industry"))

# Generic terms that must not stand alone as a "specific" service/industry.
_GENERIC_TERMS = {
    "consulting", "consultancy", "services", "service", "solutions", "solution",
    "business", "businesses", "companies", "company", "clients", "customers",
    "marketing", "advisory", "support", "management", "technology", "software",
    "development", "design", "products", "product", "strategy", "operations",
    "growth", "digital", "agency", "firm", "team", "work", "industry", "sector",
}


def _specific_phrase(s: str) -> bool:
    """A service/industry is usable evidence only if it's specific — a multi-word
    phrase with a non-generic word, or a single distinctive term. 'M&A advisory',
    'succession planning', 'SaaS companies' pass; 'consulting', 'businesses' fail."""
    n = _norm_for_match(s)
    words = [w for w in n.split() if w]
    if not words or len(n) < 4:
        return False
    non_generic = [w for w in words if w not in _GENERIC_TERMS]
    if len(words) >= 2:
        return len(non_generic) >= 1
    return words[0] not in _GENERIC_TERMS and len(words[0]) >= 5


def _corroborated_evidence(crawl: dict, facts: dict, existing: list) -> list:
    """Recover REAL evidence the strict verbatim-quote pass dropped: every typed-
    bucket fact (named client/service/framework/project/award/result) and case study
    whose distinctive tokens are present in the crawled text becomes a validated
    signal. Grounded in the actual site — never invents. Appends to `existing`."""
    pages = crawl.get("page_records") or []
    all_text = _norm_for_match(" ".join(p.get("text", "") for p in pages) or crawl.get("text", ""))
    out = list(existing or [])
    seen = {(e.get("type"), _norm_for_match(e.get("claim", ""))) for e in out}

    def push(kind, claim, conf=0.7):
        claim = (claim or "").strip()
        key = (kind, _norm_for_match(claim))
        if not claim or key in seen:
            return
        seen.add(key)
        out.append({"id": f"ev_{len(out) + 1}", "type": kind, "claim": claim,
                    "supporting_quote": "", "source_url": "", "source_kind": "html",
                    "confidence": conf, "corroborated": True})
    for field, kind in _CORROBORATE_BUCKETS:
        for v in facts.get(field) or []:
            if isinstance(v, str) and _corroborated(all_text, v):
                push(kind, v)
    for cs in facts.get("case_studies") or []:
        if isinstance(cs, dict):
            who = (cs.get("client") or cs.get("name") or "").strip()
            res = (cs.get("result") or "").strip()
            if who and _corroborated(all_text, who):
                push("case_study", " — ".join([x for x in [who, res] if x]) or who, 0.8)
    # Tier B — specific services + audience the site actually states (grounded, but
    # softer than named clients). Lets ordinary small-business sites generate honest
    # copy instead of falsely reading "insufficient".
    for field, kind in _CORROBORATE_TIER_B:
        for v in facts.get(field) or []:
            if isinstance(v, str) and _specific_phrase(v) and _corroborated(all_text, v):
                push(kind, v, 0.6)
    return out


def _validate_text_evidence(crawl: dict, items: list) -> list:
    """Keep only evidence whose supporting quote exists on its claimed page."""
    pages = crawl.get("page_records") or []
    by_url = {p.get("url", "").rstrip("/"): p for p in pages}
    out, seen = [], set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        quote = str(item.get("supporting_quote") or item.get("quote") or "").strip()
        source = str(item.get("source_url") or "").strip().rstrip("/")
        if not claim or len(quote) < 10:
            continue
        page = by_url.get(source)
        # Models occasionally omit/normalize the URL. Recover it only when the
        # quote itself identifies one unambiguous crawled page.
        if page is None:
            matches = [p for p in pages if _norm(quote) in _norm(p.get("text", ""))]
            if len(matches) == 1:
                page = matches[0]
                source = page.get("url", "")
        if page is None or _norm(quote) not in _norm(page.get("text", "")):
            continue
        kind = str(item.get("type") or "fact").strip().lower().replace(" ", "_")
        key = (kind, _norm(claim))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "id": f"ev_{len(out) + 1}", "type": kind, "claim": claim,
            "supporting_quote": quote, "source_url": source,
            "source_kind": "html", "confidence": 1.0,
        })
    return out


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
                       max_pages=30 if deep else 16, max_chars=76000 if deep else 52000,
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
        system = ("You are an ICP classifier and EVIDENCE extractor. Read the source-labelled website pages and build an "
                  "EVIDENCE BANK of concrete, company-specific signals — NOT themes. Ground everything ONLY "
                  "in the provided pages: copy names/numbers verbatim, and LEAVE A FIELD EMPTY when the "
                  "site does not support it (never invent, never generalize a category into a 'fact'). Do "
                  "NOT record vague themes like 'clarity', 'leadership', 'award-winning', 'bold brands' — "
                  "only named, checkable specifics. Even when the site names no clients or metrics, CAPTURE "
                  "the real specifics it DOES state: every SPECIFIC service/offering by name (e.g. 'M&A "
                  "advisory', 'succession planning'), the SPECIFIC industries/audience it serves (e.g. "
                  "'family-owned manufacturers', 'SaaS scale-ups'), named methodologies, and locations. "
                  "Populate services, named_services, and target_industries fully from what the site says — "
                  "these are checkable specifics too. Only leave a field empty if the site truly omits it. A "
                  "missing private metric (revenue, LTV, employee count, "
                  "demand, sales-cycle complexity) is UNKNOWN, never negative evidence. Return Non-ICP only "
                  "when a positive fact matches a hard exclusion; otherwise use Needs Review when evidence "
                  "is incomplete.\n"
                  "ICP definition (single source of truth):\n"
                  + icp_block
                  + '\nReturn JSON: {"icp_decision": "ICP"|"Non-ICP"|"Needs Review", "icp_score": 0-100, '
                    '"icp_reason": str, "industry": str, "facts": {'
                    '"category": str (what kind of company they are), '
                    '"description": str, '
                    '"services": [str], '
                    '"named_services": [str — signature/branded/named products or services], '
                    '"frameworks": [str — proprietary methodologies/frameworks/tools, by name], '
                    '"named_clients": [str — specific client/brand names they have worked with], '
                    '"case_studies": [ {"name": str, "client": str, "result": str (the measurable outcome, '
                    'verbatim, or "")} ], '
                    '"measurable_results": [str — numbers/percentages/outcomes stated on the site], '
                    '"awards": [str — named awards/recognitions only], '
                    '"partnerships": [str — named partners/affiliations], '
                    '"distinctive_projects": [str — named campaigns/projects], '
                    '"target_industries": [str — the industries/sectors of their customers], '
                    '"decision_makers": [str — the buyer roles they serve], '
                    '"commercial_challenges": [str — the business problems their customers face], '
                    '"evidence": [ {"type": "case_study"|"measurable_result"|"named_client"|'
                    '"methodology"|"named_service"|"project"|"award"|"industry"|"buyer"|"challenge", '
                    '"claim": str, "source_url": str (copy the PAGE URL), '
                    '"supporting_quote": str (short exact quote copied from that page)} ]}}')
        research_chars = 32000 if deep else 18000
        packet = _research_packet(crawl, research_chars)
        try:
            vision_limit = 4 if deep else 2
            visual = ai.analyze_site_images(lead.company, crawl.get("image_candidates") or [],
                                            limit=vision_limit)
            visual_context = ("\n\nVALIDATED VISUAL OBSERVATIONS (keep source_kind=image):\n"
                              + json.dumps(visual)) if visual else ""
            user = (f"Company: {lead.company}\nSite: {crawl.get('url')}\n"
                    f"SOURCE-LABELLED PAGES:\n{packet}{visual_context}")
            out = ai._call_openai(system, user, model=ai.extract_model())
            # Robust unwrap: gpt-4o-mini often FLATTENS the schema, putting services/
            # named_clients/etc. at the top level instead of under "facts". Reading
            # only out["facts"] then loses everything (0 facts despite a good crawl).
            # Merge any bucket keys the model left at the top level back into facts.
            raw_facts = out.get("facts")
            facts = dict(raw_facts) if isinstance(raw_facts, dict) else {}
            for k in _FACT_KEYS:
                if not facts.get(k) and out.get(k):
                    facts[k] = out[k]
            evidence = _validate_text_evidence(crawl, facts.get("evidence") or [])
            strict_n = len(evidence)
            # Recover real facts the strict verbatim-quote pass dropped: corroborate
            # the typed buckets (named clients/services/frameworks/projects/awards/
            # results/case studies) against the crawled text. Grounded, not invented.
            evidence = _corroborated_evidence(crawl, facts, evidence)
            for item in visual:
                item = {**item, "id": f"ev_{len(evidence) + 1}"}
                evidence.append(item)
            facts["evidence"] = evidence
            facts["_evidence_version"] = 2
            out["facts"] = facts
            crawl["diagnostics"]["evidence_strict"] = strict_n
            crawl["diagnostics"]["evidence_corroborated"] = len(evidence) - strict_n - len(visual)
            # What the model actually extracted per bucket — the smoking gun when a
            # site reads "0 facts": empty here → crawl/extraction problem; full here
            # but 0 evidence → corroboration/gate problem.
            crawl["diagnostics"]["facts_by_type"] = {
                k: len(facts.get(k) or [])
                for k in ("named_clients", "named_services", "services", "frameworks",
                          "distinctive_projects", "awards", "measurable_results",
                          "case_studies", "target_industries")
                if facts.get(k)
            }
            reason_low = str(out.get("icp_reason") or "").lower()
            absence_only = any(p in reason_low for p in (
                "does not provide", "no information", "no indication", "not stated",
                "not available", "could not find", "unclear from", "not disclosed",
            ))
            if out.get("icp_decision") == "Non-ICP" and absence_only:
                out["icp_decision"] = "Needs Review"
                out["icp_score"] = max(int(out.get("icp_score") or 0), 40)
                out["icp_reason"] = (
                    "Needs review: the site does not disclose enough information to confirm fit; "
                    "missing private metrics are not treated as evidence of non-fit."
                )
            crawl["diagnostics"]["evidence_validated"] = len(evidence)
            crawl["diagnostics"]["visual_evidence"] = len(visual)
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


# ---------------------------------------------------------------- evidence layer
# Minimum distinct company-specific signals required before we generate any
# personalization. Below this the lead is marked "insufficient", never guessed.
MIN_RESEARCH_SIGNALS = 3


def _research_reason(research: dict, signals: list) -> str:
    """Plain-language 'why this lead produced no copy', shown in the UI up front so
    a failure is instantly actionable instead of a black box. Pinpoints whether the
    break was the crawl (thin/JS text), the extractor (found nothing), or the gate."""
    text_len = int(research.get("signals_text_len") or 0)
    pages = int(research.get("pages_crawled") or 0)
    facts_total = sum((research.get("facts_by_type") or {}).values())
    if pages == 0:
        return ("The website could not be fetched (no page returned) — it may block bots, be down, "
                "or need JavaScript rendering.")
    if text_len < 600:
        return (f"Read {pages} page(s) but only {text_len} characters of usable text — the site is almost "
                "certainly JavaScript-rendered. Set a render key (RENDER_PROVIDER + RENDER_API_KEY) so its "
                "pages can be read.")
    if facts_total == 0:
        return (f"Read {pages} pages ({text_len:,} chars) but the extractor found no named services, clients, "
                "or industries — the page text is generic, or the extractor under-read it. Try the stronger "
                "extractor (EXTRACT_MODEL=gpt-4o).")
    return (f"Extracted {facts_total} detail(s) across {pages} pages, but only {len(signals)} cleared source "
            f"corroboration ({MIN_RESEARCH_SIGNALS} needed) — the specifics may not appear verbatim on the site.")

# Corporate filler / vague praise the writer must never use to REPLACE research.
_BANNED_PHRASES = [
    "award-winning approach", "award winning approach", "commitment to excellence",
    "bold and dynamic", "sets you apart", "very impressive", "impressive",
    "industry-leading", "industry leading", "innovative solutions", "unique approach",
    "enterprise clients", "streamline sales processes", "revenue growth system",
    "clearer reason to progress", "world-class", "world class", "high standard",
    "truly sets", "sets a high standard", "love how", "cutting-edge", "cutting edge",
    "top-notch", "best-in-class", "best in class", "technically sophisticated",
    "client satisfaction", "customer satisfaction", "our integrated approach",
    "your work exceeded expectations", "leveraging this", "revenue ecosystem",
    "opportunity progression", "differentiated capability", "utilize this",
]
# Generic value-nouns that must NOT stand in for a concrete website detail.
_GENERIC_NOUNS = {"quality", "innovation", "expertise", "commitment", "creativity",
                  "leadership", "excellence", "clarity", "passion", "dedication",
                  "professionalism", "reliability", "vision"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _flatten_signals(facts: dict) -> list:
    """Turn the evidence bank into a scored, deduped signal list (highest first).
    Scores follow the operator's ranking: measurable result / named client = 10,
    award / framework = 9, named service / project / partnership = 8, industry
    specialization = 7."""
    facts = facts or {}
    sig = []

    def add(kind, score, text, *, evidence_id="", source_url="", quote="",
            source_kind="html", confidence=1.0):
        text = (text or "").strip()
        key = _norm(text)
        if text and key:
            sig.append(enrich_signal({
                "type": kind, "score": score, "text": text, "key": key,
                "evidence_id": evidence_id, "source_url": source_url,
                "supporting_quote": quote, "source_kind": source_kind,
                "confidence": confidence,
            }))

    score_for = {
        "measurable_result": 10, "result": 10, "case_study": 10,
        "named_client": 9, "client": 9, "award": 9, "methodology": 9,
        "framework": 9, "named_service": 8, "service": 8, "project": 8,
        "partnership": 8, "industry": 7, "buyer": 7, "challenge": 7,
    }
    # Provenance-backed evidence is the canonical path. Legacy fact arrays remain
    # as a compatibility fallback for records generated before this upgrade.
    evidence = [x for x in (facts.get("evidence") or []) if isinstance(x, dict)]
    for ev in evidence:
        raw_kind = str(ev.get("type") or "fact").lower()
        kind = {"measurable_result": "result", "named_client": "client",
                "methodology": "framework", "named_service": "service"}.get(raw_kind, raw_kind)
        add(kind, score_for.get(raw_kind, score_for.get(kind, 7)), ev.get("claim", ""),
            evidence_id=ev.get("id", ""), source_url=ev.get("source_url", ""),
            quote=ev.get("supporting_quote", ""), source_kind=ev.get("source_kind", "html"),
            confidence=float(ev.get("confidence") or 0))
    if evidence or facts.get("_evidence_version"):
        best = {}
        for s in sig:
            # Claim-level dedupe prevents the same John Jay metric being treated
            # as both a case study and a separate result.
            k = s["key"]
            if k not in best or s["quality_score"] > best[k]["quality_score"]:
                best[k] = s
        return sorted(best.values(), key=lambda x: (-x["quality_score"], -x["confidence"]))

    for cs in facts.get("case_studies") or []:
        if isinstance(cs, dict):
            who = (cs.get("client") or cs.get("name") or "").strip()
            res = (cs.get("result") or "").strip()
            label = " — ".join([x for x in [who, res] if x])
            add("case_study", 10 if res else 8, label)
        elif isinstance(cs, str):
            add("case_study", 8, cs)
    for r in facts.get("measurable_results") or []:
        add("result", 10, r)
    for c in facts.get("named_clients") or []:
        add("client", 9, c)
    for a in facts.get("awards") or []:
        add("award", 9, a)
    for f in facts.get("frameworks") or []:
        add("framework", 9, f)
    for s in facts.get("named_services") or []:
        add("service", 8, s)
    for p in facts.get("distinctive_projects") or []:
        add("project", 8, p)
    for p in facts.get("partnerships") or []:
        add("partnership", 8, p)
    for i in facts.get("target_industries") or []:
        add("industry", 7, i)
    # dedupe by claim, not (type, claim), so one fact cannot be assigned twice
    # merely because extraction placed it in two categories.
    best = {}
    for s in sig:
        k = s["key"]
        if k not in best or s["quality_score"] > best[k]["quality_score"]:
            best[k] = s
    return sorted(best.values(), key=lambda x: -x["quality_score"])


def _role_of(fmt: dict) -> str:
    """Map a configured variable to its cold-email JOB by name/label."""
    n = (str(fmt.get("name", "")) + " " + str(fmt.get("label", ""))).lower()
    if "first" in n and "line" in n:
        return "first_line"
    if "value" in n or "proposition" in n or n.strip() == "vp":
        return "value_proposition"
    if "compliment" in n or "complimentary" in n or "product" in n:
        return "product_compliment"
    if "reference" in n:
        return "reference"
    if "pitch" in n:
        return "pitch"
    return "other"


_ROLE_PURPOSE = {
    "first_line": ("Prove we actually researched THEM. Use the strongest memorable achievement available, "
                   "including a measurable case-study result, named project, product, methodology, or "
                   "specific award. Preserve the name plus the detail/number that makes it remarkable. "
                   "One natural sentence; no pitch or greeting."),
    "value_proposition": ("Connect our offer to their STRONGEST commercial proof — a measurable case study "
                          "or a named client result. Tie that proof to why our work helps them get more of it."),
    "product_compliment": ("Start a human conversation about a DIFFERENT named product/project. State the "
                           "exact mechanism, technical feature, measurable detail, or outcome that makes it "
                           "distinctive—never merely call it sophisticated/impressive—then ask ONE genuine "
                           "question about its demand, response, or strategic role."),
    "reference": ("Continue the value-proposition thread from the previous email: expand that SAME proof with "
                  "the practical next steps we would run. Reusing the value-proposition evidence is expected."),
    "pitch": ("Explain plainly what kind of company THEY are, the 2–3 customer/company types we can bring "
              "them, the relevant decision-maker titles inside those customers, which revenue problems WE "
              "solve, and the long-term outcome. Never confuse job titles with customer categories or their "
              "product benefit with the sales problem we solve. Plain language—never branded terms."),
    "other": ("Use a specific, checkable website detail; never generic praise."),
}


def _assign_evidence(facts: dict, formats: list) -> dict:
    """Build the strongest coherent evidence plan across all variables.

    The old greedy policy reserved every measurable result for the value
    proposition and could force the first line onto a weaker award. We now score
    the complete core plan together, while keeping evidence distinct; reference
    deliberately reuses the value-proposition proof.
    """
    signals = _flatten_signals(facts)
    used_keys = set()

    roles = {f.get("name"): _role_of(f) for f in formats}
    core_plan = plan_core_assignments(signals, list(roles.values()))
    core_claimed = set()

    def take_best(role):
        available = [s for s in signals if s["key"] not in used_keys]
        if not available:
            return None
        chosen = max(available, key=lambda s: role_signal_score(role, s))
        used_keys.add(chosen["key"])
        return chosen

    assign = {}
    vp_sig = core_plan.get("value_proposition")
    if vp_sig:
        used_keys.add(vp_sig["key"])
    # Reserve every globally planned core signal before assigning extra variables.
    for sig in core_plan.values():
        used_keys.add(sig["key"])

    for f in formats:
        name = f.get("name")
        role = roles[name]
        sig = None
        if role in core_plan and role not in core_claimed:
            sig = core_plan[role]
            core_claimed.add(role)
            if role == "value_proposition":
                vp_sig = sig
        elif role == "reference":
            if vp_sig is None:
                # A reference without a configured value proposition still gets
                # the strongest commercially relevant proof.
                available = [s for s in signals if s["key"] not in used_keys] or signals
                vp_sig = max(available, key=lambda s: role_signal_score("value_proposition", s),
                             default=None)
            sig = vp_sig
        elif role == "pitch":
            sig = None  # built from audience below
        else:
            sig = take_best(role)
        assign[name] = {
            "role": role,
            "purpose": _ROLE_PURPOSE[role],
            "evidence": (sig or {}).get("text", ""),
            "evidence_type": (sig or {}).get("type", ""),
            "evidence_key": (sig or {}).get("key", ""),
            "evidence_id": (sig or {}).get("evidence_id", ""),
            "source_url": (sig or {}).get("source_url", ""),
            "supporting_quote": (sig or {}).get("supporting_quote", ""),
            "source_kind": (sig or {}).get("source_kind", ""),
            "confidence": (sig or {}).get("confidence", 0),
            "signal_quality": (sig or {}).get("quality_score", 0),
            "selection_score": role_signal_score(role, sig) if sig else 0,
            "reuse_ok": role == "reference",
        }
    # pitch audience packet
    aud = {
        "target_industries": facts.get("target_industries") or [],
        "example_clients": (facts.get("named_clients") or [])[:4],
        "decision_makers": facts.get("decision_makers") or [],
        "commercial_challenges": facts.get("commercial_challenges") or [],
    }
    for name, a in assign.items():
        if a["role"] == "pitch":
            a["evidence"] = json.dumps(aud)
    return assign


def _has_concrete_detail(text: str, facts: dict) -> bool:
    """A line is concrete if it names a real entity from the bank or carries a
    number/percentage — not just a generic value-noun."""
    low = (text or "").lower()
    if not low.strip():
        return False
    for key in ("named_clients", "named_services", "frameworks", "distinctive_projects",
                "awards", "partnerships"):
        for v in facts.get(key) or []:
            tok = _norm(v)
            if len(tok) >= 4 and tok in _norm(text):
                return True
    for cs in facts.get("case_studies") or []:
        if isinstance(cs, dict):
            for v in (cs.get("client"), cs.get("name")):
                tok = _norm(v or "")
                if len(tok) >= 4 and tok in _norm(text):
                    return True
    for ev in facts.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        claim = _norm(ev.get("claim", ""))
        # A meaningful named phrase from a validated claim is a concrete anchor.
        tokens = [x for x in claim.split() if len(x) >= 4 and not x.isdigit()]
        if any(tok in _norm(text) for tok in tokens[:8]):
            return True
    return False


def _uses_assigned_evidence(text: str, assignment: dict) -> bool:
    """Require copy to carry a distinctive anchor from its own assigned proof.

    Merely saying "revenue", "campaign" or "identity" is not grounding. A line
    assigned to the John Jay result must retain John/Jay, its supported number,
    or another uncommon term from that evidence.
    """
    if not (assignment.get("evidence") or assignment.get("supporting_quote")):
        return True
    return bool(anchor_matches(text, assignment))


def _qc_failures(vars_out: dict, assign: dict, facts: dict, formats: list | None = None,
                 reading_level: str = "") -> dict:
    """Return {name: reason} for variables that must be regenerated."""
    fails = {}
    primary_seen = {}   # evidence_key -> first variable that used it
    format_by_name = {f.get("name"): f for f in (formats or [])}
    for name, text in vars_out.items():
        t = (text or "").strip()
        if not t:
            if assign.get(name, {}).get("evidence"):
                fails[name] = "blank despite having assigned evidence"
            continue
        low = t.lower()
        role = assign.get(name, {}).get("role", "other")
        fmt = format_by_name.get(name, {})
        words = re.findall(r"\b[\w'-]+\b", t)
        if fmt.get("min_words") and len(words) < int(fmt["min_words"]):
            fails[name] = f"below configured minimum of {int(fmt['min_words'])} words"
            continue
        if fmt.get("max_words") and len(words) > int(fmt["max_words"]):
            fails[name] = f"above configured maximum of {int(fmt['max_words'])} words"
            continue
        if (reading_level or "b2 business") == "b2 business":
            sentence_lengths = [
                len(re.findall(r"\b[\w'-]+\b", sentence))
                for sentence in re.split(r"(?<=[.!?])\s+", t)
                if sentence.strip()
            ]
            if sentence_lengths and max(sentence_lengths) > 40:
                fails[name] = "contains a sentence longer than 40 words; use clear B2 sentence structure"
                continue
        hit = next((p for p in _BANNED_PHRASES if p in low), None)
        if hit:
            fails[name] = f"uses banned filler '{hit}'"
            continue
        if not _has_concrete_detail(t, facts):
            # tolerate the pitch (it's audience/pain framing, not a single named proof)
            if role != "pitch":
                fails[name] = "no concrete, website-specific detail (named entity or number)"
                continue
        # Numbers are high-risk claims. Every number in generated copy must occur
        # in the validated evidence assigned to that variable.
        assignment = assign.get(name, {})
        nums = set(re.findall(r"\d+(?:[.,]\d+)?%?", t))
        grounding = " ".join([
            str(assignment.get("evidence", "")),
            str(assignment.get("supporting_quote", "")),
        ])
        unsupported = [n for n in nums if n not in grounding]
        if unsupported:
            fails[name] = f"contains unsupported number(s): {', '.join(unsupported)}"
            continue
        if role != "pitch" and assignment.get("evidence") \
                and not _uses_assigned_evidence(t, assignment):
            fails[name] = "does not use a distinctive anchor from its assigned evidence"
            continue
        # A project name alone is not a researched compliment. It must carry at
        # least one feature/outcome from the supporting quote and ask a question.
        if role == "product_compliment":
            extra_details = (
                evidence_terms(assignment.get("supporting_quote", ""))
                - evidence_terms(assignment.get("evidence", ""))
            )
            if extra_details and not supporting_detail_matches(t, assignment):
                fails[name] = "names the product but omits the concrete detail that makes it distinctive"
                continue
            if "?" not in t:
                fails[name] = "product compliment must end with one genuine question"
                continue
        if role == "value_proposition" and re.match(r"^\s*and\b", t, re.I):
            fails[name] = "starts mid-thought with 'And' instead of a complete value sentence"
            continue
        if role == "reference" and assignment.get("evidence") and "your work" in low:
            fails[name] = "uses 'your work' instead of naming the assigned project or proof"
            continue
        # generic value-noun compliment with no concrete anchor
        if role == "product_compliment" and any(g in low for g in _GENERIC_NOUNS) and not _has_concrete_detail(t, facts):
            fails[name] = "compliment is about a broad value, not a named piece of work"
            continue
        # cross-variable evidence duplication (reference may reuse value_proposition)
        key = assign.get(name, {}).get("evidence_key", "")
        if key:
            if key in primary_seen and not assign.get(name, {}).get("reuse_ok"):
                fails[name] = f"reuses the same evidence as '{primary_seen[key]}'"
                continue
            primary_seen.setdefault(key, name)
    return fails


def _augmented_formats(formats: list, assign: dict) -> list:
    """Attach each variable's assigned evidence + distinct purpose for the writer."""
    aug = []
    for f in formats:
        a = assign.get(f.get("name"), {})
        compact = dict(f)
        # Approved outputs are training memory, but two recent examples are enough
        # to teach structure without repeatedly paying to send the whole library.
        compact["examples"] = [str(x)[:1400] for x in (f.get("examples") or [])[-2:]]
        compact["avoid_examples"] = [{
            "text": str(x.get("text") or "")[:1000],
            "reason": str(x.get("reason") or "")[:500],
        } for x in (f.get("rejected_examples") or [])[-2:] if isinstance(x, dict)]
        compact.pop("rejected_examples", None)
        compact["rules"] = [str(x)[:500] for x in (f.get("rules") or [])[:12]]
        aug.append({**compact,
                    "_job": a.get("purpose", ""),
                    "_use_this_evidence": a.get("evidence", ""),
                    "_evidence_type": a.get("evidence_type", ""),
                    "_source_url": a.get("source_url", ""),
                    "_supporting_quote": a.get("supporting_quote", "")})
    return aug


def _compact_profile(profile: dict) -> dict:
    """Keep the client facts the writer actually needs, with bounded list sizes."""
    profile = profile or {}

    def clip(value, depth=0):
        if isinstance(value, str):
            return value[:1200 if depth == 0 else 600]
        if isinstance(value, list):
            return [clip(x, depth + 1) for x in value[:8]]
        if isinstance(value, dict):
            return {str(k)[:80]: clip(v, depth + 1)
                    for k, v in list(value.items())[:12]
                    if v not in (None, "", [], {})}
        return value

    keys = (
        "client_name", "one_liner", "service_brief", "main_offer",
        "what_we_are_pitching", "target_outcome", "icp_summary", "industries",
        "services", "positioning", "methodology", "proof_points", "target_titles",
        "tone", "problem_library", "case_studies",
    )
    out = {}
    for key in keys:
        value = profile.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            capped = value[:8] if key not in ("case_studies", "problem_library") else value[:4]
            out[key] = clip(capped)
        elif isinstance(value, str):
            out[key] = value[:1800]
        else:
            out[key] = clip(value)
    return out


def _prospect_summary(facts: dict) -> dict:
    """Small taxonomy packet used by the pitch; assigned evidence handles proof."""
    return {
        key: facts.get(key)
        for key in (
            "category", "description", "services", "target_industries",
            "decision_makers", "commercial_challenges",
        )
        if facts.get(key)
    }


def _candidate_values(raw: dict, name: str) -> list[str]:
    root = raw.get("candidates") if isinstance(raw.get("candidates"), dict) else raw
    value = root.get(name) if isinstance(root, dict) else None
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()][:3]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _select_candidates(raw: dict, formats: list, assign: dict, facts: dict,
                       reading_level: str = "") -> tuple[dict, int]:
    """Choose the strongest model candidate locally—no extra critic API call."""
    selected, total = {}, 0
    for fmt in formats:
        name = fmt.get("name")
        candidates = _candidate_values(raw if isinstance(raw, dict) else {}, name)
        total += len(candidates)
        role = assign.get(name, {}).get("role", "other")

        def score(text):
            local = local_candidate_score(text, role, assign.get(name, {}), fmt)
            failure = _qc_failures({name: text}, {name: assign.get(name, {})},
                                   facts, [fmt], reading_level)
            return local - (1000 if failure else 0)

        selected[name] = max(candidates, key=score) if candidates else ""
    return selected, total


def _writer_system(cfg, rules, level_line) -> str:
    return ("You are a senior B2B outbound copywriter. Each requested variable includes one verified "
            "evidence assignment and a distinct job. Write TWO meaningfully different candidates per "
            "variable, both fully compliant. Ground prospect claims only in that variable's assigned claim "
            "and quote; never invent or generalize.\n"
            "QUALITY BAR:\n"
            "- Preserve the names, numbers, mechanisms, regulatory facts, and outcomes that make the "
            "assigned evidence valuable. A project name followed by a generic adjective is a failure.\n"
            "- First line: one natural, company-only sentence built around the strongest assigned achievement.\n"
            "- Value proposition: first explain our actual service for this company category; then connect "
            "their assigned proof to a commercial reason buyers should progress. Never start with 'And'.\n"
            "- Product compliment: name the product/project, state exactly what makes it distinctive from "
            "the quote, then ask one genuine question.\n"
            "- Reference: name and continue the value proposition's proof in complete grammatical sentences.\n"
            "- Pitch: separate the prospect's company category, target customer companies, decision-maker "
            "titles, and the revenue problems we solve. Titles are not customer categories.\n"
            "- Approved examples teach style and structure only. Never copy their company names, projects, "
            "numbers, or claims into a different prospect's output.\n"
            "- avoid_examples are rejected anti-examples. Do not copy their wording or repeat the problem "
            "stated in their reason.\n"
            "- First line, value proposition, and compliment use different primary evidence; reference may "
            "reuse value-proposition evidence. Avoid vague praise and branded labels.\n"
            "- BANNED PHRASES: " + "; ".join(_BANNED_PHRASES) + ".\n"
            "- If evidence is inadequate, return an empty candidate instead of guessing.\n"
            'Return only JSON: {"candidates": {"<variable name>": ["candidate 1", "candidate 2"]}}.\n'
            + level_line +
            "\nCLIENT PROFILE / OUR OFFER:\n" + json.dumps(_compact_profile(cfg.profile or {})) +
            "\nGLOBAL RULES (obey every line):\n" + "\n".join(rules))


def _reading_instruction(level: str) -> str:
    level = (level or "b2 business").strip().lower()
    if level == "b2 business":
        return (
            "\nREADING LEVEL: write in clear, natural B2-level business English. Use simple vocabulary "
            "and direct sentence structures. Prefer specific facts over sophisticated wording. Avoid "
            "academic language, corporate jargon, vague flattery, exaggerated or poetic praise, and "
            "unnecessarily complex sentences. First lines and product compliments should sound B1–B2 "
            "when spoken aloud. Value propositions, references, and pitches should be B2. Use an advanced "
            "industry term only when it appears in the prospect evidence and is needed for accuracy."
        )
    return (
        f"\nREADING LEVEL: write so a {level} reader understands it easily — "
        "short sentences, everyday words, no jargon."
    )


def _writer_user(lead: EnrichLead, facts: dict, formats: list) -> str:
    return (
        "LEAD:\n" + json.dumps({
            "first_name": lead.first_name, "company": lead.company, "title": lead.title,
        }) +
        "\nPROSPECT TAXONOMY:\n" + json.dumps(_prospect_summary(facts)) +
        "\nVARIABLE PLAN (follow each _job, exact format guidance, assigned claim, and quote):\n" +
        json.dumps(formats)
    )


def _write_copy(lead: EnrichLead, cfg: EnrichConfig, ctx: dict, enrichments=None) -> dict:
    """Research → evidence bank → signal scoring → per-variable evidence assignment
    → generation → QC/regeneration. `enrichments`: selected output variable names —
    empty/None = all configured."""
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
    facts = ctx.get("facts", {}) or {}

    if not ai.has_ai():
        return {"vars": {}, "source": "failed", "assignments": {},
                "error": "OPENAI_API_KEY is not configured; generation was refused."}

    reading = (getattr(cfg, "reading_level", "") or "b2 business").strip()
    level_line = _reading_instruction(reading)
    assign = _assign_evidence(facts, formats)
    aug = _augmented_formats(formats, assign)
    system = _writer_system(cfg, rules, level_line)
    # The evidence extractor already validated every assigned quote against its
    # source page. Sending the entire crawl again was redundant and dominated cost.
    user = _writer_user(lead, facts, aug)
    calls = 0
    prompt_chars = len(system) + len(user)
    try:
        model = (getattr(cfg, "writer_model", "") or ai.writer_model())
        out = ai._call_openai(system, user, model=model)
        calls += 1
    except Exception as exc:
        return {"vars": {}, "source": "failed", "assignments": assign,
                "error": f"Writer failed: {str(exc)[:240]}"}

    vars_out, candidate_count = _select_candidates(out, formats, assign, facts, reading)
    # Regenerate only failed variables once, then quarantine every remaining
    # failure. No fallback prose and no partially grounded result may be `done`.
    fails = _qc_failures(vars_out, assign, facts, formats, reading)
    if fails:
        fix_formats = [f for f in aug if f["name"] in fails]
        fix_system = (_writer_system(cfg, rules, level_line) +
                      "\nREPAIR: the previous candidates failed the checks below. Correct every stated "
                      "problem while preserving the assigned claim and concrete quote details.\nFAILURES:\n" +
                      "\n".join(f"- {n}: {r}" for n, r in fails.items()))
        fix_user = _writer_user(lead, facts, fix_formats)
        try:
            prompt_chars += len(fix_system) + len(fix_user)
            fixed = ai._call_openai(fix_system, fix_user, model=model)
            calls += 1
            repaired, repair_candidates = _select_candidates(
                fixed, [f for f in formats if f["name"] in fails], assign, facts, reading)
            candidate_count += repair_candidates
            vars_out.update(repaired)
        except Exception:
            pass
    final_fails = _qc_failures(vars_out, assign, facts, formats, reading)
    for name in final_fails:
        vars_out[name] = ""
    return {"vars": vars_out, "source": "openai", "assignments": assign,
            "quality_failures": final_fails,
            "generation": {
                "model": model, "calls": calls, "candidates_considered": candidate_count,
                "prompt_chars": prompt_chars,
                "full_research_resent": False,
            }}


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
    diagnostics = (icp.get("crawl", {}) or {}).get("diagnostics", {})
    if icp.get("error"):
        # Research FAILED at the fetch/render stage — record diagnostics and STOP.
        # Never fabricate "researched" copy on a failed fetch.
        lead.status = "error"
        lead.result = {**(lead.result or {}), "_error": icp["error"], "_research": diagnostics}
        lead.updated_at = datetime.utcnow()
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

    # 3b. RESEARCH SUFFICIENCY GATE — never generate personalization without evidence.
    # Require at least 3 distinct company-specific signals (named client/project/
    # service/framework/award/result). Below that, mark the lead "insufficient" so it
    # can be retried (with a render key / deeper crawl) instead of shipping guesses.
    facts = icp.get("facts", {}) or {}
    signals = _flatten_signals(facts)
    research = {**diagnostics, "signals_collected": len(signals),
                "signal_types": sorted({s["type"] for s in signals})}
    if ai.has_ai() and len(signals) < MIN_RESEARCH_SIGNALS:
        research["reason"] = _research_reason(research, signals)
        lead.result = {**(lead.result or {}), "_facts": facts, "_research": research,
                       "_insufficient": True}
        lead.status = "insufficient"
        lead.updated_at = datetime.utcnow()
        db.commit()
        return lead.status

    # 4. Write copy — reuses icp ctx; no second scrape/extraction
    written = _write_copy(lead, cfg, icp, enrichments=enrichments)
    clean_vars = {k: sanitize_text(v) for k, v in written["vars"].items()}
    lead.result = {**(lead.result or {}), **clean_vars,
                   "_facts": facts, "_writer": written["source"], "_research": research,
                   "_assignments": written.get("assignments") or {},
                   "_quality_failures": written.get("quality_failures") or {},
                   "_generation": written.get("generation") or {}}
    if written.get("error"):
        lead.result = {**lead.result, "_generation_error": written["error"]}
        lead.status = "generation_failed"
    elif written.get("quality_failures"):
        lead.status = "needs_review"
    else:
        lead.status = "done"
    lead.updated_at = datetime.utcnow()
    db.commit()
    return lead.status
