"""Public HTML rendering for agreements and invoices.

Everything dynamic is HTML-escaped (no stored-XSS on the public page), internal
notes are never included, and the signing form posts to a token-guarded endpoint.
The same renderer produces the frozen `executed_html` snapshot (with signatures,
no form) that the executed PDF is built from.
"""
import html as _html
from datetime import datetime

BRAND = "RevCadence"
ACCENT = "#635BFF"


def esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _body_html(body: str) -> str:
    """Render a section body: bullet lines (•) become a <ul>, others paragraphs."""
    lines = [ln.rstrip() for ln in str(body or "").replace("\r", "").split("\n")]
    out, bucket = [], []

    def flush_ul():
        if bucket:
            out.append("<ul>" + "".join(f"<li>{esc(b)}</li>" for b in bucket) + "</ul>")
            bucket.clear()

    para = []

    def flush_p():
        if para:
            out.append("<p>" + esc(" ".join(para)) + "</p>")
            para.clear()

    for ln in lines:
        s = ln.strip()
        if s.startswith("•"):
            flush_p()
            bucket.append(s.lstrip("• ").strip())
        elif s == "":
            flush_ul(); flush_p()
        else:
            flush_ul()
            para.append(s)
    flush_ul(); flush_p()
    return "".join(out)


_CSS = f"""
 :root{{--ink:#12131a;--muted:#5b6472;--line:#e7e9ee;--accent:{ACCENT};--bg:#fbfbfd}}
 *{{box-sizing:border-box}} body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,Arial,sans-serif;color:var(--ink);background:var(--bg);line-height:1.6}}
 .wrap{{max-width:820px;margin:0 auto;padding:48px 24px 96px}}
 .brand{{font-weight:700;letter-spacing:-.02em;color:var(--accent);font-size:14px;text-transform:uppercase}}
 h1{{font-size:2rem;line-height:1.15;letter-spacing:-.02em;margin:.4rem 0 .2rem}}
 .meta{{color:var(--muted);font-size:.92rem;border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:6px}}
 .pill{{display:inline-block;background:#eef0ff;color:var(--accent);border-radius:999px;padding:3px 12px;font-size:.78rem;font-weight:600}}
 section{{padding:20px 0;border-bottom:1px solid var(--line)}}
 h2{{font-size:1rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:0 0 8px}}
 p{{margin:.2rem 0 .5rem}} ul{{margin:.2rem 0;padding-left:1.1rem}} li{{margin:.3rem 0}}
 .sig-grid{{display:flex;gap:24px;flex-wrap:wrap;margin-top:12px}}
 .sig-box{{flex:1;min-width:240px;border:1px solid var(--line);border-radius:12px;padding:16px;background:#fff}}
 .sig-name{{font-family:'Segoe Script','Snell Roundhand','Bradley Hand',cursive;font-size:1.7rem;color:#1a1a2e;margin:2px 0}}
 .sig-label{{font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
 .card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:20px;margin-top:20px}}
 label{{display:block;font-size:.85rem;font-weight:600;margin:10px 0 4px}}
 input[type=text],input[type=email]{{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font-size:15px}}
 .consent{{font-size:.82rem;color:var(--muted);margin:12px 0}}
 button{{background:var(--accent);color:#fff;border:0;border-radius:9px;padding:12px 18px;font-size:15px;font-weight:600;cursor:pointer;margin-top:12px}}
 .foot{{color:var(--muted);font-size:.82rem;padding-top:24px}}
 .status{{font-size:.78rem;font-weight:700;padding:3px 10px;border-radius:999px;background:#e8f7ee;color:#1a7f45}}
 table.inv{{width:100%;border-collapse:collapse;margin-top:10px}}
 table.inv th,table.inv td{{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);font-size:.92rem}}
 table.inv td.n,table.inv th.n{{text-align:right}}
 .tot{{margin-top:14px;margin-left:auto;max-width:320px}}
 .tot .row{{display:flex;justify-content:space-between;padding:4px 0;font-size:.95rem}}
 .tot .grand{{font-weight:800;font-size:1.15rem;border-top:2px solid var(--ink);margin-top:6px;padding-top:8px}}
"""


def _sig_block(name, title, when, ip=None):
    who = esc(name or "")
    return (
        '<div class="sig-box">'
        f'<div class="sig-label">Signed by</div>'
        f'<div class="sig-name">{who or "&nbsp;"}</div>'
        f'<div style="font-size:.85rem">{who}{(" · " + esc(title)) if title else ""}</div>'
        f'<div style="font-size:.75rem;color:#5b6472">{esc(when) if when else "Pending"}</div>'
        '</div>')


def render_agreement(ag, company=None, contact=None, *, signing=False, provider=None):
    """Full public agreement page. When `signing` and no client signature yet,
    include the sign form (token in the action URL). When executed, show both
    signature blocks and no form (this is also the frozen executed snapshot)."""
    provider = provider or (ag.fields or {}).get("parties", {}).get("provider_entity") or BRAND
    eff = (ag.fields or {}).get("effective_date") or "To be confirmed"
    secs = "".join(
        f'<section><h2>{esc(s.get("label"))}</h2>{_body_html(s.get("body"))}</section>'
        for s in (ag.sections or []))

    client_signed = bool(ag.client_signed_at)
    counter_signed = bool(ag.countersigned_at)
    executed = bool(ag.executed_at)

    # signature area
    if client_signed or counter_signed or executed:
        client = _sig_block(ag.client_signer_name, ag.client_signer_title,
                            ag.client_signed_at.strftime("%B %d, %Y %H:%M UTC") if ag.client_signed_at else None)
        counter = _sig_block(ag.counter_signer_name, ag.counter_signer_title,
                             ag.countersigned_at.strftime("%B %d, %Y %H:%M UTC") if ag.countersigned_at else None)
        sig_html = (f'<section><h2>Signatures</h2>'
                    f'<div class="sig-grid">{client}{counter}</div>')
        if executed:
            sig_html += (f'<p style="margin-top:14px"><span class="status">EXECUTED</span> '
                         f'&nbsp;{esc(ag.number)} · checksum {esc((ag.checksum or "")[:16])}…</p>')
        sig_html += "</section>"
    elif signing:
        consent = (f"By signing, I, on behalf of {esc((ag.fields or {}).get('parties', {}).get('client_entity') or (company.name if company else 'the Client'))}, "
                   f"agree to the terms of this Agreement ({esc(ag.number)}, version {ag.version}). "
                   "I confirm I am authorized to sign, and I consent to electronic signature.")
        pre_name = esc((contact and f"{contact.first_name} {contact.last_name}".strip()) or "")
        pre_email = esc(contact.email if contact else "")
        sig_html = (
            f'<div class="card"><h2 style="color:var(--ink)">Sign this agreement</h2>'
            f'<form method="post" action="/agreement/{esc(ag.public_token)}/sign">'
            f'<label>Full name</label><input type="text" name="name" value="{pre_name}" required>'
            f'<label>Email</label><input type="email" name="email" value="{pre_email}" required>'
            f'<label>Title (optional)</label><input type="text" name="title" value="">'
            f'<label style="display:flex;gap:8px;align-items:flex-start;font-weight:400" class="consent">'
            f'<input type="checkbox" name="consent" value="yes" required style="margin-top:3px;width:auto">'
            f'<span>{consent}</span></label>'
            f'<input type="hidden" name="consent_text" value="{esc(consent)}">'
            f'<button type="submit">Adopt &amp; sign</button>'
            f'</form></div>')
    else:
        sig_html = ('<section><h2>Signatures</h2><p style="color:#5b6472">This agreement has not been '
                    'sent for signature yet.</p></section>')

    title = esc(ag.title or f"Services Agreement — {company.name if company else ''}")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{title}</title><style>{_CSS}</style></head>
<body><div class="wrap">
 <div class="brand">{esc(provider)} · Agreement</div>
 <h1>{title}</h1>
 <div class="meta">{esc(ag.number)} · version {ag.version} · Effective date: {esc(eff)}
   {" · " + esc(company.name) if company else ""}</div>
 {secs}
 {sig_html}
 <div class="foot">Confidential — {esc(provider)}. This document is intended only for the named Client.</div>
</div></body></html>"""


_INVOICE_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#fff;color:#0d1424;
  font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
.sheet{max-width:820px;margin:0 auto;padding:56px 56px 60px}
.row{display:flex;justify-content:space-between;gap:30px}
.brand b{font-size:26px;font-weight:800;letter-spacing:-.02em}
.rt{text-align:right;font-size:13px;color:#3b4557}
.rt .k{color:#697586;font-size:11.5px;text-transform:uppercase;letter-spacing:.05em}
hr{border:0;border-top:1px solid #e6e9ef;margin:20px 0 24px}
.lbl{font-size:11.5px;color:#697586;text-transform:uppercase;letter-spacing:.05em;font-weight:700;margin-bottom:5px}
.amtdue{font-size:23px;font-weight:800;letter-spacing:-.02em;margin:26px 0 18px}
table{width:100%;border-collapse:collapse;margin-top:4px}
th{font-size:12.5px;color:#0d1424;text-align:right;font-weight:700;border-bottom:1.4px solid #0d1424;padding:0 0 8px}
th.l,td.l{text-align:left}
td{font-size:13.5px;padding:12px 0;border-bottom:1px solid #e6e9ef;vertical-align:top}
.num{font-variant-numeric:tabular-nums}
.totals{margin-top:8px;margin-left:auto;width:300px}
.totals .tr{display:flex;justify-content:space-between;padding:6px 0;font-size:13.5px;color:#3b4557}
.totals .tr.big{border-top:1.4px solid #0d1424;margin-top:6px;padding-top:12px;font-weight:800;color:#0d1424;font-size:16px}
.pay{margin-top:40px}
.pay h4{margin:0 0 12px;font-size:13px;letter-spacing:.02em}
.pay .grid{display:grid;grid-template-columns:220px 1fr;row-gap:7px;column-gap:14px;font-size:13px}
.pay .grid .k{color:#697586}
.pay .grid .v{color:#0d1424;font-weight:600}
.foot{margin-top:44px;padding-top:16px;border-top:1px solid #e6e9ef;color:#697586;font-size:12px}
@media print{.sheet{padding:26px 30px}@page{margin:14mm}}
"""


def render_invoice(inv, company=None, provider=None):
    """Client-facing invoice page: clean, pure white, Email Frost issuer and the
    ACH/Wire payment details. Same layout as the downloadable PDF."""
    from .pdf import INVOICE_ISSUER, INVOICE_PAYMENT_TITLE, _fmt_date, _payment_details
    cur = esc(inv.currency or "USD")

    def money(n):
        return f"{float(n or 0):,.2f}"

    rows = ""
    for li in (inv.line_items or []):
        qty = li.get("quantity", 1) or 0
        rate = li.get("rate", 0) or 0
        amt = li.get("amount", (qty or 0) * (rate or 0)) or 0
        rows += (f'<tr><td class="l">{esc(li.get("description", ""))}</td>'
                 f'<td class="num">{qty:g}</td>'
                 f'<td class="num">{money(rate)} {cur}</td>'
                 f'<td class="num">{money(amt)} {cur}</td></tr>')
    client = esc(inv.bill_to_company or inv.bill_to_name or (company.name if company else ""))
    billed_extra = ""
    if inv.bill_to_company and inv.bill_to_name:
        billed_extra += f"<br>{esc(inv.bill_to_name)}"
    if inv.bill_to_address:
        billed_extra += "<br>" + esc(str(inv.bill_to_address)).replace("\n", "<br>")
    if inv.bill_to_email:
        billed_extra += f"<br>{esc(inv.bill_to_email)}"
    issued_by = esc(INVOICE_ISSUER).replace("\n", "<br>")
    disc = (f'<div class="tr"><span>Discount</span><span class="num">-{money(inv.discount_amount)} {cur}</span></div>'
            if inv.discount_amount else "")
    pay_rows = "".join(f'<div class="k">{esc(k)}</div><div class="v">{esc(v)}</div>' for k, v in _payment_details())
    notes = (f'<div class="pay"><h4>Notes</h4>{_body_html(inv.notes)}</div>' if inv.notes else "")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Invoice {esc(inv.number)}</title><style>{_INVOICE_CSS}</style></head>
<body><div class="sheet">
  <div class="row">
    <div class="brand"><b>Invoice</b></div>
    <div class="rt">
      <div class="k">Invoice number</div><div>{esc(inv.number)}</div>
      <div class="k" style="margin-top:10px">Issue date</div><div>{esc(_fmt_date(inv.issue_date))}</div>
    </div>
  </div>
  <hr>
  <div class="row">
    <div style="max-width:46%"><div class="lbl">Billed to</div><div>{client}{billed_extra}</div></div>
    <div style="max-width:46%"><div class="lbl">Issued by</div><div>{issued_by}</div></div>
  </div>
  <div class="amtdue"><span class="num">{money(inv.total)} {cur}</span> due by {esc(_fmt_date(inv.due_date))}</div>
  <table>
    <thead><tr><th class="l">Product or service</th><th>Quantity</th><th>Unit price</th><th>Total</th></tr></thead>
    <tbody>{rows or '<tr><td class="l" colspan="4" style="color:#697586">No line items.</td></tr>'}</tbody>
  </table>
  <div class="totals">
    <div class="tr"><span>Total excluding tax</span><span class="num">{money(inv.subtotal)} {cur}</span></div>
    {disc}
    <div class="tr"><span>Total tax</span><span class="num">{money(inv.tax_amount)} {cur}</span></div>
    <div class="tr big"><span>Amount Due</span><span class="num">{money(inv.total)} {cur}</span></div>
  </div>
  <div class="pay">
    <h4>{esc(INVOICE_PAYMENT_TITLE)}</h4>
    <div class="grid">{pay_rows}</div>
  </div>
  {notes}
  <div class="foot">Email Frost LTD. Please include the invoice number {esc(inv.number)} as your payment reference.</div>
</div></body></html>"""
