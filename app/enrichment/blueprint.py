"""Blueprint generation: enrichment data → a draft Document (kind=blueprint).
The HTML mirrors the structure of the proven Ascendly blueprint pages; content
sections come from AI when available, template fallback otherwise."""
import os
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


# ---------------------------------------------------------------- premium template
_TPL_PATH = os.path.join(os.path.dirname(__file__), "blueprint_template.html")
_TPL_CACHE = None


def _template() -> str:
    """The fixed RevCadence blueprint design (cover, cadence logo, positioning,
    calculator). Client-specific parts are [[TOKENS]] filled per render."""
    global _TPL_CACHE
    if _TPL_CACHE is None or os.getenv("BLUEPRINT_TPL_NOCACHE"):
        with open(_TPL_PATH, encoding="utf-8") as f:
            _TPL_CACHE = f.read()
    return _TPL_CACHE


def _money(n) -> str:
    try:
        return "$" + format(int(round(float(n))), ",")
    except Exception:
        return ""


def _kfmt(n) -> str:
    try:
        n = int(round(float(n)))
    except Exception:
        return ""
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M".replace(".0M", "M")
    return f"${int(round(n / 1000))}k"


# The calculator script, injected only when the economics numbers exist. PRICE is
# baked in; UNIT is the word for one close ("campaign", "deal", "client").
_CALC_JS = '''  var money = function(n){ return "$" + Math.round(n).toLocaleString("en-US"); };
  var UNIT = "__UNIT__", PRICE = __PRICE__;
  var rM=document.getElementById("rM"),oM=document.getElementById("oM");
  var rC=document.getElementById("rC"),oC=document.getElementById("oC");
  var rV=document.getElementById("rV"),oV=document.getElementById("oV");
  var rMo=document.getElementById("rMo"),oMo=document.getElementById("oMo");
  function calc(){
    var meetings=+rM.value, rate=+rC.value, value=+rV.value, months=+rMo.value;
    var won=meetings*rate/100, pipe=won*value, perMeet=PRICE/meetings, perWin=won>0?PRICE/won:0;
    oM.textContent=meetings; oC.textContent=rate+"%"; oV.textContent=money(value);
    document.getElementById("cPipe").textContent=money(pipe);
    document.getElementById("cWon").textContent="about "+(won>=2?Math.round(won):won.toFixed(1))+" signed "+UNIT+(Math.round(won)===1?"":"s")+" from one month of meetings";
    document.getElementById("cPerMeet").textContent=money(perMeet);
    document.getElementById("cPerWin").textContent=perWin?money(perWin):"n/a";
    var invest=months*PRICE;
    oMo.textContent=months+" months";
    document.getElementById("rIn").textContent=money(invest);
    document.getElementById("rInMo").textContent=months;
    document.getElementById("rOut").textContent=money(value);
    document.getElementById("rMult").innerHTML=Math.round(value/invest)+"&#215;";
  }
  [rM,rC,rV,rMo].forEach(function(el){el.addEventListener("input",calc);}); calc();'''


def _econ_block(econ: dict, price: int, meetings: int):
    """Build the math + calculator + investment sections from the numbers that
    came off the call. Returns ('','') when there is no deal value to work with,
    so the whole economics block is simply omitted rather than guessed."""
    try:
        low = int(econ.get("deal_value_low"))
    except Exception:
        return "", ""
    if low <= 0:
        return "", ""
    try:
        high = int(econ.get("deal_value_high") or low)
    except Exception:
        high = low
    if high < low:
        high = low
    rate = max(10, min(45, int(econ.get("close_rate_expected") or 25)))
    unit = (econ.get("unit_word") or "deal").strip() or "deal"
    basis = _esc(econ.get("deal_basis") or "")
    step = 20000 if (high - low) >= 40000 else max(5000, (high - low) // 8 or 5000)
    won = meetings * rate / 100
    won_disp = str(round(won)) if won >= 2 else f"{won:.1f}"
    plural = "" if round(won) == 1 else "s"
    per_meet = _money(price / meetings)
    pipe0 = _money(won * low)
    per_win0 = _money(price / won) if won else "n/a"
    invest0 = _money(4 * price)
    mult0 = int(round(low / (4 * price))) if price else 0
    u = _esc(unit)
    html = f'''<!-- THE MATH -->
<section class="band band-soft" id="math">
  <div class="wrap">
    <span class="eyebrow">The economics, in plain numbers</span>
    <h2>Start from one signed {u}, then count back to the meetings.</h2>
    <p class="lead narrow" style="margin-top:14px">Here they are in order. We begin with what one {u} is worth to you, and work back to how few conversations it takes.</p>
    <div class="g-3" style="margin-top:30px">
      <div class="card"><h3>One {u} is about {_kfmt(low)} to {_kfmt(high)}</h3><p>{basis}</p></div>
      <div class="card"><h3>{meetings} meetings is a few real chances</h3><p>Based on your expectation that about {rate}% of properly qualified conversations could become clients, a target of {meetings} qualified meetings a month is about {won_disp} genuine chances at a {_money(low)}-plus {u}, every month.</p></div>
      <div class="card"><h3>Each meeting costs {per_meet}</h3><p>{_money(price)} divided by {meetings} qualified meetings is {per_meet} a meeting. Weigh {per_meet} against a {u} worth {_money(low)} or more in contract revenue. That is the trade.</p></div>
    </div>
  </div>
</section>

<!-- CALCULATOR -->
<section class="band" id="calc">
  <div class="wrap">
    <span class="eyebrow">Run your own numbers</span>
    <h2>Move the sliders. The math updates as you go.</h2>
    <div class="calc" style="margin-top:26px">
      <div class="calc-controls">
        <div class="fgrp"><div class="frow"><label>Qualified meetings a month</label><span class="out" id="oM">{meetings}</span></div><input type="range" id="rM" min="{meetings}" max="{meetings + 7}" step="1" value="{meetings}" /></div>
        <div class="fgrp"><div class="frow"><label>Expected close rate</label><span class="out" id="oC">{rate}%</span></div><input type="range" id="rC" min="10" max="45" step="1" value="{rate}" /></div>
        <div class="fgrp"><div class="frow"><label>Contract value of one signed {u}</label><span class="out" id="oV">{_money(low)}</span></div><input type="range" id="rV" min="{low}" max="{high}" step="{step}" value="{low}" /></div>
      </div>
      <div class="calc-out">
        <div class="ck">New contract value entering your pipeline each month</div>
        <div class="cv blue" id="cPipe">{pipe0}</div>
        <div class="csub" id="cWon">about {won_disp} signed {u}{plural} from one month of meetings</div>
        <div class="cdiv"></div>
        <div class="crow"><span>Cost per qualified meeting</span><b id="cPerMeet">{per_meet}</b></div>
        <div class="crow"><span>Cost per signed {u}</span><b id="cPerWin">{per_win0}</b></div>
        <div class="crow"><span>Your monthly investment</span><b>{_money(price)}</b></div>
      </div>
    </div>
    <p class="calc-note">These figures are illustrative and depend on qualification, response, attendance and how many conversations you convert. A single signed {u}, from any one month of meetings, more than covers this partnership.</p>
  </div>
</section>

<!-- INVESTMENT VS RETURN -->
<section class="band band-tint" id="return">
  <div class="wrap">
    <span class="eyebrow">The whole decision on one screen</span>
    <h2>A few months of {_money(price)} on the left. One {u} on the right.</h2>
    <div class="calc-controls" style="max-width:420px;margin-top:22px">
      <div class="fgrp" style="margin-bottom:0"><div class="frow"><label>Months of investment</label><span class="out" id="oMo">4 months</span></div><input type="range" id="rMo" min="3" max="6" step="1" value="4" /></div>
    </div>
    <div class="vs">
      <div class="vs-card"><div class="k">You invest</div><div class="v" id="rIn">{invest0}</div><div class="s"><span id="rInMo">4</span> months at {_money(price)} a month, flat</div></div>
      <div class="vs-mid">vs</div>
      <div class="vs-card"><div class="k">One signed {u} is worth</div><div class="v green" id="rOut">{_money(low)}</div><div class="s">in contract revenue, at the low end</div></div>
    </div>
    <p class="vs-mult">The contract value of a single {u} is about <b id="rMult">{mult0}&#215;</b> your investment over those months. This compares contract revenue to cost, not profit.</p>
  </div>
</section>'''
    js = _CALC_JS.replace("__PRICE__", str(int(price))).replace("__UNIT__", unit.replace('"', "'"))
    return html, js


def render_public_html(company_name: str, contact_name: str, content: dict) -> str:
    """Fill the fixed premium template with this client's details. The design and
    RevCadence logo never change; only the [[TOKENS]] do. Economics sections are
    rendered only when the numbers exist, otherwise they are omitted."""
    c = content or {}
    client = _esc(c.get("client_name") or company_name or "Your Company")
    econ = c.get("economics") or {}
    try:
        price = int(econ.get("price_monthly") or 2000)
    except Exception:
        price = 2000
    try:
        meetings = int(econ.get("meetings_target") or 8)
    except Exception:
        meetings = 8
    if meetings < 1:
        meetings = 8

    logo_url = (c.get("client_logo_url") or "").strip()
    logo_img = f'<img src="{_esc(logo_url)}" alt="{client}" />' if logo_url else ""
    contact_line = _esc(c.get("contact_line") or (f"For {contact_name}" if contact_name else ""))
    who_list = "".join(f"      <li>{_esc(i)}</li>\n" for i in (c.get("who_list") or []) if str(i).strip()).strip("\n")
    jq = (c.get("journey_quote") or "").strip()
    journey_block = f'<div class="quote">{_esc(jq)}</div>' if jq else ""
    geo = (c.get("geography_line") or "").strip()
    geo_line = f"<b>Geography, in order.</b> {_esc(geo)}" if geo else ""
    econ_html, calc_js = _econ_block(econ, price, meetings)
    book = (c.get("book_url") or "https://calendly.com/rosis/new-meeting").strip()

    repl = {
        "[[CLIENT]]": client,
        "[[CLIENT_LOGO_IMG]]": logo_img,
        "[[CONTACT_LINE]]": contact_line,
        "[[ONELINER]]": _esc(c.get("cover_oneliner")
                             or "How we would build and run the revenue system that turns the right prospects into signed revenue, and stays on every opportunity until it closes."),
        "[[HIGH_TICKET_DESC]]": _esc(c.get("high_ticket_desc") or "a high-value engagement"),
        "[[WHO_H2]]": _esc(c.get("who_h2") or "We do not contact everyone. We find the ones that fit."),
        "[[WHO_INTRO]]": _esc(c.get("who_intro")
                             or "We build the list around organizations that fit your standard, not everyone with an inbox."),
        "[[WHO_LIST]]": who_list or "      <li>Organizations that match your ideal profile and can act on what you offer</li>",
        "[[GEO_LINE]]": geo_line,
        "[[QUALIFIED_DEF]]": _esc(c.get("qualified_definition")
                                 or "A real decision-maker who read a message written for them, replied that they are interested, and booked time to see if there is a fit."),
        "[[JOURNEY_QUOTE_BLOCK]]": journey_block,
        "[[MEETINGS]]": str(meetings),
        "[[PRICE]]": _money(price),
        "[[CTA_HEADING]]": _esc(c.get("cta_heading") or "One signed engagement covers this many times over. Let us begin."),
        "[[CTA_BODY]]": _esc(c.get("cta_body")
                            or "When you are ready, we spend the first three weeks building and preparing, then launch in week four, with the first conversations landing shortly after and a target of qualified, attended meetings by month two."),
        "[[BOOK_URL]]": _esc(book),
        "[[ECON_BLOCK]]": econ_html,
        "[[CALC_JS]]": calc_js,
    }
    html = _template()
    for k, v in repl.items():
        html = html.replace(k, v)
    return html


def generate_from_transcript(db, workspace_id: int, company: Company | None,
                             contact: Contact | None, transcript: str,
                             deal_id: int | None = None, doc_id: int | None = None,
                             instructions: str = "") -> Document:
    """Build (or regenerate) a blueprint Document from a Fathom call transcript.
    instructions: optional operator steering (emphasis, angle, corrections)."""
    company_d = {"name": company.name if company else "", "industry": company.industry if company else ""}
    contact_d = {"name": f"{contact.first_name} {contact.last_name}".strip() if contact else "",
                 "title": contact.title if contact else ""}
    content = ai.blueprint_from_transcript(company_d, contact_d, transcript, instructions=instructions)
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

