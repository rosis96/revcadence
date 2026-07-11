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

    slug_base = (company_d["name"] or "blueprint").lower()
    slug = "".join(c if c.isalnum() else "-" for c in slug_base).strip("-")[:60]
    doc = Document(workspace_id=workspace_id, company_id=company.id if company else None,
                   contact_id=contact.id if contact else None, deal_id=deal_id,
                   kind="blueprint", status="draft", published=False,
                   title=f"Revenue Blueprint — {company_d['name'] or 'Draft'}",
                   slug=slug, html=html,
                   fields={"generator": source, "sections": list(content.keys())})
    db.add(doc)
    db.flush()
    db.add(Activity(workspace_id=workspace_id, company_id=doc.company_id, contact_id=doc.contact_id,
                    deal_id=deal_id, kind="doc_created",
                    title=f"Blueprint drafted ({source})", data={"document_id": doc.id}))
    db.commit()
    return doc
