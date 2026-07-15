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
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

ACCENT = colors.HexColor("#635BFF")
INK = colors.HexColor("#12131a")
MUTED = colors.HexColor("#5b6472")
LINE = colors.HexColor("#e2e4ea")
BRAND = "RevCadence"


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
    ss = _styles()
    buf = io.BytesIO()
    doc = _doc(buf, f"Confidential — {BRAND} · {inv.number}")
    cur = inv.currency
    story = [
        Paragraph(f"{BRAND} · Invoice", ss["RCBrand"]),
        Paragraph(f"Invoice {_e(inv.number)}", ss["RCTitle"]),
        Paragraph(f"Issued {_e(inv.issue_date or '—')} &nbsp;·&nbsp; Due {_e(inv.due_date or '—')} "
                  f"&nbsp;·&nbsp; Status: {_e(inv.status)}", ss["RCMeta"]),
        Paragraph("Bill To", ss["RCH2"]),
        Paragraph(_e(inv.bill_to_company or (company.name if company else "")), ss["RCBody"]),
    ]
    if inv.bill_to_name:
        story.append(Paragraph(_e(inv.bill_to_name), ss["RCBody"]))
    if inv.bill_to_email:
        story.append(Paragraph(_e(inv.bill_to_email), ss["RCBody"]))
    if inv.agreement_id:
        story.append(Paragraph(f"Ref: Agreement #{inv.agreement_id}", ss["RCMeta"]))

    story.append(Spacer(1, 8))
    data = [["Description", "Qty", "Rate", "Amount"]]
    for li in (inv.line_items or []):
        qty = li.get("quantity", 1) or 0
        rate = li.get("rate", 0) or 0
        amt = li.get("amount", qty * rate) or 0
        data.append([Paragraph(_e(li.get("description", "")), ss["RCBody"]),
                     f"{qty:g}", f"{cur} {rate:,.2f}", f"{cur} {amt:,.2f}"])
    t = Table(data, colWidths=[doc.width - 3.3 * inch, 0.7 * inch, 1.2 * inch, 1.4 * inch])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)

    totals = [["Subtotal", f"{cur} {inv.subtotal:,.2f}"]]
    if inv.discount_amount:
        totals.append(["Discount", f"-{cur} {inv.discount_amount:,.2f}"])
    if inv.tax_amount:
        totals.append([f"Tax ({inv.tax_rate:g}%)", f"{cur} {inv.tax_amount:,.2f}"])
    totals.append(["Total", f"{cur} {inv.total:,.2f}"])
    if inv.amount_paid:
        totals.append(["Paid", f"{cur} {inv.amount_paid:,.2f}"])
    totals.append(["Balance due", f"{cur} {inv.balance_due:,.2f}"])
    tt = Table(totals, colWidths=[1.6 * inch, 1.6 * inch], hAlign="RIGHT")
    style = [("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 10),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
             ("LINEABOVE", (0, -1), (-1, -1), 1, INK),
             ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]
    tt.setStyle(TableStyle(style))
    story.append(Spacer(1, 10))
    story.append(tt)

    if inv.payment_instructions:
        story.append(Paragraph("Payment Instructions", ss["RCH2"]))
        story += _body_flowables(inv.payment_instructions, ss)
    if inv.notes:
        story.append(Paragraph("Notes", ss["RCH2"]))
        story += _body_flowables(inv.notes, ss)

    doc.build(story)
    return buf.getvalue()
