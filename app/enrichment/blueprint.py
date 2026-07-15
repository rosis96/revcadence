"""Blueprint generation: enrichment data → a draft Document (kind=blueprint).
The HTML mirrors the structure of the proven Ascendly blueprint pages; content
sections come from AI when available, template fallback otherwise."""
from datetime import datetime

from ..models.crm import Activity, Company, Contact
from ..models.documents import Document
from . import ai

_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Revenue Blueprint — {company_name}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#111827;max-width:820px;margin:40px auto;padding:0 24px;line-height:1.6}}
 h1{{font-size:2rem;margin-bottom:.25rem}} .sub{{color:#6b7280;margin-bottom:2rem}}
 h2{{font-size:1.15rem;margin-top:2rem;border-bottom:2px solid #4f46e5;padding-bottom:.35rem}}
 ul{{padding-left:1.2rem}} .tag{{display:inline-block;background:#eef2ff;color:#4f46e5;border-radius:6px;padding:2px 10px;font-size:.8rem;margin-right:6px}}
</style></head><body>
<h1>Revenue Blueprint</h1>
<div class="sub">Prepared for {contact_name}{contact_title} · {company_name} · {date}</div>
<div>{industry_tag}{fit_tag}</div>
<h2>Executive Summary</h2><p>{exec_summary}</p>
<h2>Primary Bottleneck</h2><p>{bottleneck}</p>
<h2>Recommended Focus</h2><ul>{recommendations}</ul>
<h2>What Happens Next</h2>
<p>We implement this as a managed revenue system: reply management, meeting
scheduling, and pipeline instrumentation — reviewed together in a working session.</p>
</body></html>"""


def generate_blueprint(db, workspace_id: int, company: Company | None,
                       contact: Contact | None, deal_id: int | None = None) -> Document:
    company_d = {"name": company.name if company else "", "industry": company.industry if company else ""}
    contact_d = {"name": f"{contact.first_name} {contact.last_name}".strip() if contact else "",
                 "title": contact.title if contact else ""}
    enrichment = {k: v.get("value") for k, v in (company.enrichment or {}).items()
                  if isinstance(v, dict)} if company else {}

    content = ai.generate_blueprint_content(company_d, contact_d, enrichment)
    source = content.pop("_source", "template")

    recs = "".join(f"<li>{r}</li>" for r in content.get("recommendations", []))
    html = _HTML.format(
        company_name=company_d["name"] or "Your Company",
        contact_name=contact_d["name"] or "the team",
        contact_title=f", {contact_d['title']}" if contact_d["title"] else "",
        date=datetime.utcnow().strftime("%B %d, %Y"),
        industry_tag=f'<span class="tag">{company.industry}</span>' if company and company.industry else "",
        fit_tag=f'<span class="tag">ICP: {company.icp_fit}</span>' if company and company.icp_fit else "",
        exec_summary=content.get("exec_summary", ""),
        bottleneck=content.get("bottleneck", ""),
        recommendations=recs,
    )

    doc = Document(workspace_id=workspace_id, company_id=company.id if company else None,
                   contact_id=contact.id if contact else None, deal_id=deal_id,
                   kind="blueprint", status="draft", published=False,
                   title=f"Revenue Blueprint — {company_d['name'] or 'Draft'}",
                   slug=unique_slug(db, company_d["name"] or "blueprint"), html=html,
                   fields={"generator": source, "sections": list(content.keys())})
    db.add(doc)
    db.flush()
    db.add(Activity(workspace_id=workspace_id, company_id=doc.company_id, contact_id=doc.contact_id,
                    deal_id=deal_id, kind="doc_created",
                    title=f"Blueprint drafted ({source})", data={"document_id": doc.id}))
    db.commit()
    return doc


# ---------------------------------------------------------------- slugs
def slugify(s: str) -> str:
    base = "".join(c if c.isalnum() else "-" for c in (s or "").lower()).strip("-")
    while "--" in base:
        base = base.replace("--", "-")
    return base[:60] or "blueprint"


def unique_slug(db, name: str, exclude_id: int | None = None) -> str:
    """A URL slug from the company name, unique across all documents
    (blueprint.<domain>/<slug> must resolve to exactly one page)."""
    base = slugify(name)
    slug, n = base, 1
    while True:
        q = db.query(Document).filter(Document.slug == slug)
        if exclude_id:
            q = q.filter(Document.id != exclude_id)
        if not q.first():
            return slug
        n += 1
        slug = f"{base}-{n}"


# ---------------------------------------------------------------- transcript → blueprint
def _esc(s) -> str:
    import html as _h
    return _h.escape(str(s or ""))


def _list_html(items, cls="") -> str:
    return "".join(f'<li class="{cls}">{_esc(i)}</li>' for i in (items or []) if str(i).strip())


def render_public_html(company_name: str, contact_name: str, content: dict) -> str:
    """The client-facing Growth Blueprint page — light editorial, RevCadence
    brand. Internal fields (notes_for_ascendly) are never rendered here."""
    quotes = "".join(f'<blockquote>“{_esc(q)}”</blockquote>' for q in (content.get("their_words") or []) if str(q).strip())
    commercial = content.get("commercial") or ""
    return _PUBLIC_HTML.format(
        company=_esc(company_name or "Your Company"),
        contact=_esc(contact_name or "the team"),
        date=datetime.utcnow().strftime("%B %d, %Y"),
        hero_subtitle=_esc(content.get("hero_subtitle") or "A managed revenue engine, built for you."),
        industry_pill=(f' · <span class="pill">{_esc(content.get("industry"))}</span>'
                       if content.get("industry") else ""),
        exec_summary=_esc(content.get("exec_summary") or ""),
        what_we_see=_esc(content.get("what_we_see") or ""),
        bottlenecks=_list_html(content.get("bottlenecks")),
        what_we_build=_list_html(content.get("what_we_build")),
        roadmap=_list_html(content.get("roadmap")),
        target_outcome=_esc(content.get("target_outcome") or ""),
        quotes_block=(f'<section class="quotes"><h2>In your words</h2>{quotes}</section>' if quotes else ""),
        commercial_block=(f'<section><h2>Investment</h2><p class="commercial">{_esc(commercial)}</p></section>'
                          if commercial.strip() else ""),
    )


def generate_from_transcript(db, workspace_id: int, company: Company | None,
                             contact: Contact | None, transcript: str,
                             deal_id: int | None = None, doc_id: int | None = None) -> Document:
    """Build (or regenerate) a blueprint Document from a Fathom call transcript."""
    company_d = {"name": company.name if company else "", "industry": company.industry if company else ""}
    contact_d = {"name": f"{contact.first_name} {contact.last_name}".strip() if contact else "",
                 "title": contact.title if contact else ""}
    content = ai.blueprint_from_transcript(company_d, contact_d, transcript)
    source = content.pop("_source", "template")
    html = render_public_html(company_d["name"], contact_d["name"], content)

    doc = db.get(Document, doc_id) if doc_id else None
    if doc is None:
        doc = Document(workspace_id=workspace_id, company_id=company.id if company else None,
                       contact_id=contact.id if contact else None, deal_id=deal_id, kind="blueprint")
        doc.slug = unique_slug(db, company_d["name"] or "blueprint")
        db.add(doc)
    doc.status = doc.status if doc.status in ("published", "viewed") else "draft"
    doc.title = f"Revenue Blueprint — {company_d['name'] or 'Draft'}"
    doc.html = html
    # keep internal notes + the raw transcript in fields (never rendered publicly)
    doc.fields = {**(doc.fields or {}), "generator": source, "content": content,
                  "notes_for_ascendly": content.get("notes_for_ascendly", ""),
                  "transcript": (transcript or "")[:40000]}
    db.flush()
    db.add(Activity(workspace_id=workspace_id, company_id=doc.company_id, contact_id=doc.contact_id,
                    deal_id=deal_id, kind="doc_created",
                    title=f"Blueprint from transcript ({source})", data={"document_id": doc.id}))
    db.commit()
    return doc


_PUBLIC_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Growth Blueprint — {company}</title>
<style>
 :root{{--ink:#12131a;--muted:#5b6472;--line:#e7e9ee;--accent:#635BFF;--bg:#fbfbfd}}
 *{{box-sizing:border-box}} body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,Arial,sans-serif;color:var(--ink);background:var(--bg);line-height:1.6}}
 .wrap{{max-width:820px;margin:0 auto;padding:56px 24px 96px}}
 .brand{{font-weight:700;letter-spacing:-.02em;color:var(--accent);font-size:14px;text-transform:uppercase}}
 h1{{font-size:2.4rem;line-height:1.15;letter-spacing:-.02em;margin:.4rem 0 .3rem}}
 .subtitle{{font-size:1.15rem;color:var(--muted);margin-bottom:.6rem}}
 .meta{{color:var(--muted);font-size:.9rem;border-bottom:1px solid var(--line);padding-bottom:22px;margin-bottom:8px}}
 .pill{{display:inline-block;background:#eef0ff;color:var(--accent);border-radius:999px;padding:3px 12px;font-size:.8rem;font-weight:600}}
 section{{padding:26px 0;border-bottom:1px solid var(--line)}}
 h2{{font-size:1.05rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:0 0 10px}}
 p{{margin:.2rem 0 .6rem}} ul{{margin:.2rem 0;padding-left:1.1rem}} li{{margin:.35rem 0}}
 .lead{{font-size:1.12rem;color:var(--ink)}}
 blockquote{{margin:.5rem 0;padding:10px 16px;border-left:3px solid var(--accent);background:#fff;color:#333;font-size:1.05rem;border-radius:0 8px 8px 0}}
 .commercial{{font-size:1.1rem;background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px 18px}}
 .foot{{color:var(--muted);font-size:.85rem;padding-top:26px}}
</style></head><body><div class="wrap">
 <div class="brand">RevCadence · Growth Blueprint</div>
 <h1>{company}</h1>
 <div class="subtitle">{hero_subtitle}</div>
 <div class="meta">Prepared for {contact} · {date}{industry_pill}</div>
 <section><h2>Executive summary</h2><p class="lead">{exec_summary}</p></section>
 <section><h2>What we see in you</h2><p>{what_we_see}</p></section>
 <section><h2>Where revenue leaks today</h2><ul>{bottlenecks}</ul></section>
 <section><h2>What we build & run</h2><ul>{what_we_build}</ul></section>
 <section><h2>Your roadmap</h2><ul>{roadmap}</ul></section>
 {quotes_block}
 <section><h2>The outcome</h2><p class="lead">{target_outcome}</p></section>
 {commercial_block}
 <div class="foot">This blueprint was prepared by RevCadence based on our conversation. Questions? Just reply to our thread.</div>
</div></body></html>"""
