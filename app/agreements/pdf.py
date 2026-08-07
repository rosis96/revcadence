"""Professional PDF generation with ReportLab (pure Python — no headless browser,
so it runs reliably on Railway). Produces agreement PDFs (draft / client-signed /
executed) and invoice PDFs, both with branding, numbering, page numbers and a
confidentiality footer.

The executed agreement PDF is built from the LOCKED agreement (sections can no
longer change once executed), so it always reflects the executed version — never
later edits.
"""
import html as _html
import io
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

ACCENT = colors.HexColor("#635BFF")
INK = colors.HexColor("#12131a")
MUTED = colors.HexColor("#5b6472")
LINE = colors.HexColor("#e2e4ea")
BRAND = "RevCadence"

# Who the invoice is FROM, and how to pay it. Env-overridable so they can change
# without a code deploy. INVOICE_PAYMENT_DETAILS is a JSON array of [label, value].
INVOICE_ISSUER = os.getenv("INVOICE_ISSUER") or (
    "Email Frost ltd\n85 Great Portland Street\nLondon\nW1W 7LT\nUnited Kingdom")
INVOICE_PAYMENT_TITLE = os.getenv(
    "INVOICE_PAYMENT_TITLE",
    "PAYMENT DETAILS (US Domestic Bank Transfer via ACH / Wire)")


def _payment_details() -> list:
    raw = os.getenv("INVOICE_PAYMENT_DETAILS")
    if raw:
        try:
            import json as _j
            rows = _j.loads(raw)
            return [(str(a), str(b)) for a, b in rows]
        except Exception:
            pass
    return [
        ("Bank Name", "Citibank"),
        ("Bank Address", "111 Wall Street, New York, NY 10043, USA"),
        ("Routing (ABA) Number", "031100209"),
        ("Account Number", "70581260000915865"),
        ("Account Type", "CHECKING"),
        ("Beneficiary / Account Holder", "Rosis Sitoula (or Email Frost)"),
    ]


def _fmt_date(iso) -> str:
    """ISO date string -> 'July 8, 2026'. Leaves anything else as-is."""
    from datetime import datetime as _dt
    try:
        d = _dt.strptime(str(iso)[:10], "%Y-%m-%d")
        return f"{d.strftime('%B')} {d.day}, {d.year}"
    except Exception:
        return str(iso or "")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("RCBrand", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=13, textColor=ACCENT, spaceAfter=2))
    ss.add(ParagraphStyle("RCTitle", parent=ss["Title"], fontName="Helvetica-Bold",
                          fontSize=20, textColor=INK, spaceAfter=4, leading=24))
    ss.add(ParagraphStyle("RCMeta", parent=ss["Normal"], fontSize=9, textColor=MUTED, spaceAfter=10))
    ss.add(ParagraphStyle("RCH2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                          fontSize=11, textColor=INK, spaceBefore=12, spaceAfter=4))
    ss.add(ParagraphStyle("RCBody", parent=ss["Normal"], fontSize=10, textColor=INK,
                          leading=15, spaceAfter=5))
    ss.add(ParagraphStyle("RCBullet", parent=ss["Normal"], fontSize=10, textColor=INK,
                          leading=15, leftIndent=14, bulletIndent=4, spaceAfter=2))
    ss.add(ParagraphStyle("RCSig", parent=ss["Normal"], fontName="Helvetica-Oblique",
                          fontSize=17, textColor=INK, spaceAfter=2))
    ss.add(ParagraphStyle("RCRight", parent=ss["Normal"], fontSize=10, alignment=TA_RIGHT))
    return ss


def _e(s):
    return _html.escape(str(s if s is not None else ""))


def _footer(canvas, doc, note):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.9 * inch, 0.55 * inch, note)
    canvas.drawRightString(LETTER[0] - 0.9 * inch, 0.55 * inch, f"Page {doc.page}")
    canvas.setStrokeColor(LINE)
    canvas.line(0.9 * inch, 0.72 * inch, LETTER[0] - 0.9 * inch, 0.72 * inch)
    canvas.restoreState()


def _doc(buf, footer_note):
    doc = BaseDocTemplate(buf, pagesize=LETTER,
                          leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                          topMargin=0.8 * inch, bottomMargin=0.9 * inch,
                          title=footer_note)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="t", frames=[frame],
                                       onPage=lambda c, d: _footer(c, d, footer_note))])
    return doc


def _body_flowables(body, ss):
    out = []
    for raw in str(body or "").replace("\r", "").split("\n"):
        s = raw.strip()
        if not s:
            continue
        if s.startswith("•"):
            out.append(Paragraph(_e(s.lstrip("• ").strip()), ss["RCBullet"], bulletText="•"))
        else:
            out.append(Paragraph(_e(s), ss["RCBody"]))
    return out


def build_agreement_pdf(ag, company=None, contact=None, mode="draft") -> bytes:
    """mode: draft | client_signed | executed. Content comes from the (locked once
    executed) agreement fields."""
    ss = _styles()
    buf = io.BytesIO()
    provider = (ag.fields or {}).get("parties", {}).get("provider_entity") or BRAND
    doc = _doc(buf, f"Confidential — {provider} · {ag.number}")
    story = [
        Paragraph(f"{_e(provider)} · Services Agreement", ss["RCBrand"]),
        Paragraph(_e(ag.title or "Services Agreement"), ss["RCTitle"]),
        Paragraph(f"{_e(ag.number)} &nbsp;·&nbsp; version {ag.version} &nbsp;·&nbsp; "
                  f"Effective date: {_e((ag.fields or {}).get('effective_date') or 'To be confirmed')}"
                  + (f" &nbsp;·&nbsp; {_e(company.name)}" if company else ""), ss["RCMeta"]),
    ]
    for s in (ag.sections or []):
        story.append(Paragraph(_e(s.get("label")), ss["RCH2"]))
        story += _body_flowables(s.get("body"), ss)

    # signatures
    story.append(Spacer(1, 14))
    story.append(Paragraph("Signatures", ss["RCH2"]))

    def sig_cell(title_lbl, name, who_title, when):
        cell = [Paragraph(title_lbl, ss["RCMeta"])]
        if name:
            cell.append(Paragraph(_e(name), ss["RCSig"]))
            cell.append(Paragraph(_e(name) + (f" · {_e(who_title)}" if who_title else ""), ss["RCBody"]))
            cell.append(Paragraph(_e(when) if when else "", ss["RCMeta"]))
        else:
            cell.append(Paragraph("&nbsp;", ss["RCSig"]))
            cell.append(Paragraph("_______________________________", ss["RCBody"]))
            cell.append(Paragraph("Pending", ss["RCMeta"]))
        return cell

    client = sig_cell("CLIENT", ag.client_signer_name, ag.client_signer_title,
                      ag.client_signed_at.strftime("%B %d, %Y %H:%M UTC") if ag.client_signed_at else None)
    counter = sig_cell(provider.upper(), ag.counter_signer_name, ag.counter_signer_title,
                       ag.countersigned_at.strftime("%B %d, %Y %H:%M UTC") if ag.countersigned_at else None)
    tbl = Table([[client, counter]], colWidths=[doc.width / 2.0 - 6, doc.width / 2.0 - 6])
    tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("BOX", (0, 0), (0, 0), 0.5, LINE),
                             ("BOX", (1, 0), (1, 0), 0.5, LINE),
                             ("LEFTPADDING", (0, 0), (-1, -1), 10),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                             ("TOPPADDING", (0, 0), (-1, -1), 8),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story.append(tbl)

    # execution / audit certificate
    if ag.executed_at:
        story.append(Spacer(1, 16))
        story.append(Paragraph("Execution Certificate", ss["RCH2"]))
        cert = [
            ["Status", "EXECUTED"],
            ["Agreement", f"{ag.number} (version {ag.version})"],
            ["Executed at", ag.executed_at.strftime("%B %d, %Y %H:%M UTC")],
            ["Client signer", f"{ag.client_signer_name} <{ag.client_signer_email}>"],
            ["Client signed", ag.client_signed_at.strftime("%B %d, %Y %H:%M UTC") if ag.client_signed_at else "—"],
            ["Client IP", ag.client_ip or "—"],
            ["Countersigner", f"{ag.counter_signer_name} <{ag.counter_signer_email}>"],
            ["Countersigned", ag.countersigned_at.strftime("%B %d, %Y %H:%M UTC") if ag.countersigned_at else "—"],
            ["Document checksum (SHA-256)", ag.checksum or "—"],
        ]
        ct = Table([[Paragraph(_e(k), ss["RCMeta"]), Paragraph(_e(v), ss["RCBody"])] for k, v in cert],
                   colWidths=[2.1 * inch, doc.width - 2.1 * inch])
        ct.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                                ("TOPPADDING", (0, 0), (-1, -1), 3),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story.append(ct)

    doc.build(story)
    return buf.getvalue()


def build_invoice_pdf(inv, company=None) -> bytes:
    """Clean, professional invoice: no logo, no QR. Billed-to and issued-by, an
    'Amount due by DATE' headline, line items, totals, and the ACH/Wire payment
    details. Payment details and issuer are env-overridable."""
    ss = _styles()
    buf = io.BytesIO()
    doc = _doc(buf, f"Confidential — {BRAND} · {inv.number}")
    cur = inv.currency or "USD"
    W = doc.width

    title = ParagraphStyle("INVTitle", parent=ss["Normal"], fontName="Helvetica-Bold",
                           fontSize=25, textColor=INK, leading=28)
    lblR = ParagraphStyle("INVLblR", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=7.5, textColor=MUTED, alignment=TA_RIGHT, spaceAfter=1)
    valR = ParagraphStyle("INVValR", parent=ss["Normal"], fontSize=10, textColor=INK,
                          alignment=TA_RIGHT, spaceAfter=8)
    lbl = ParagraphStyle("INVLbl", parent=ss["Normal"], fontName="Helvetica-Bold",
                         fontSize=7.5, textColor=MUTED, spaceAfter=3)
    body = ParagraphStyle("INVBody", parent=ss["Normal"], fontSize=10, textColor=INK, leading=14)
    big = ParagraphStyle("INVBig", parent=ss["Normal"], fontName="Helvetica-Bold",
                         fontSize=16.5, textColor=INK, leading=20)
    payh = ParagraphStyle("INVPayH", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=9.5, textColor=INK, spaceAfter=8)

    def money(n):
        return f"{float(n or 0):,.2f}"

    # header: "Invoice" left, number + issue date right
    right = [Paragraph("INVOICE NUMBER", lblR), Paragraph(_e(inv.number or ""), valR),
             Paragraph("ISSUE DATE", lblR), Paragraph(_fmt_date(inv.issue_date), valR)]
    header = Table([[Paragraph("Invoice", title), right]], colWidths=[W * 0.55, W * 0.45])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story = [header, Spacer(1, 14), HRFlowable(width="100%", thickness=0.7, color=LINE), Spacer(1, 18)]

    # billed to | issued by
    client = inv.bill_to_company or inv.bill_to_name or (company.name if company else "")
    left_cell = [Paragraph("BILLED TO", lbl), Paragraph(_e(client) or "&nbsp;", body)]
    if inv.bill_to_name and inv.bill_to_company:
        left_cell.append(Paragraph(_e(inv.bill_to_name), body))
    if inv.bill_to_address:
        for ln in str(inv.bill_to_address).splitlines():
            if ln.strip():
                left_cell.append(Paragraph(_e(ln), body))
    if inv.bill_to_email:
        left_cell.append(Paragraph(_e(inv.bill_to_email), body))
    right_cell = [Paragraph("ISSUED BY", lbl)]
    for ln in INVOICE_ISSUER.splitlines():
        right_cell.append(Paragraph(_e(ln), body))
    parties = Table([[left_cell, right_cell]], colWidths=[W * 0.5, W * 0.5])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("RIGHTPADDING", (0, 0), (0, 0), 14)]))
    story += [parties, Spacer(1, 22)]

    # amount due by
    story += [Paragraph(f"{money(inv.total)} {_e(cur)} due by {_fmt_date(inv.due_date)}", big),
              Spacer(1, 14)]

    # line items
    data = [["Product or service", "Quantity", "Unit price", "Total"]]
    for li in (inv.line_items or []):
        qty = li.get("quantity", 1) or 0
        rate = li.get("rate", 0) or 0
        amt = li.get("amount", (qty or 0) * (rate or 0)) or 0
        data.append([Paragraph(_e(li.get("description", "")), body),
                     f"{qty:g}", f"{money(rate)} {cur}", f"{money(amt)} {cur}"])
    t = Table(data, colWidths=[W - 3.5 * inch, 0.9 * inch, 1.25 * inch, 1.35 * inch])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 1.1, INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story.append(t)

    totals = [["Total excluding tax", f"{money(inv.subtotal)} {cur}"]]
    if inv.discount_amount:
        totals.append(["Discount", f"-{money(inv.discount_amount)} {cur}"])
    totals.append([f"Total tax", f"{money(inv.tax_amount)} {cur}"])
    totals.append(["Amount Due", f"{money(inv.total)} {cur}"])
    tt = Table(totals, colWidths=[1.9 * inch, 1.6 * inch], hAlign="RIGHT")
    tt.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -2), MUTED),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEABOVE", (0, -1), (-1, -1), 1.1, INK),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 12), ("TEXTCOLOR", (0, -1), (-1, -1), INK),
        ("TOPPADDING", (0, -1), (-1, -1), 10),
    ]))
    story += [Spacer(1, 8), tt, Spacer(1, 34)]

    # payment details (ACH / Wire)
    story.append(Paragraph(_e(INVOICE_PAYMENT_TITLE), payh))
    pd = [[Paragraph(_e(k), ParagraphStyle("pk", parent=body, textColor=MUTED, fontSize=9.5)),
           Paragraph(_e(v), ParagraphStyle("pv", parent=body, fontName="Helvetica-Bold", fontSize=9.5))]
          for k, v in _payment_details()]
    pt = Table(pd, colWidths=[2.2 * inch, W - 2.2 * inch])
    pt.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f7f9")),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#eceef2")),
    ]))
    story.append(pt)

    if inv.notes:
        story += [Spacer(1, 16)] + _body_flowables(inv.notes, ss)

    doc.build(story)
    return buf.getvalue()
