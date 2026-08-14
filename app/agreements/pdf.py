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
    "RevCadence LLC\n30 N Gould St, Ste N\nSheridan, WY 82801\nUSA")
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
        ("Bank Name", "Citibank, N.A."),
        ("Routing Number", "031100209"),
        ("Account Number", "70581260000915865"),
        ("Account Type", "CHECKING"),
        ("Beneficiary / Account Holder Name", "Rosis Sitoula"),
        ("Note", "RevCadence LLC payment processing profile"),
    ]


def _guidelines() -> list:
    """Short payment rules shown beside the bank details. Env-overridable
    (INVOICE_GUIDELINES as a JSON array of short strings)."""
    raw = os.getenv("INVOICE_GUIDELINES")
    if raw:
        try:
            import json as _j
            return [str(x) for x in _j.loads(raw)]
        except Exception:
            pass
    return [
        "Business accounts only. Payments from a personal account will be declined.",
        "The beneficiary name must match Rosis Sitoula.",
        "Local: USD inside the US via ACH or FEDWIRE, usually 1 to 3 business days.",
        "International and non-USD transfers are not supported and will be declined.",
        "Paying in a non-USD currency? Contact the sender of this invoice first.",
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
    doc = _doc(buf, f"RevCadence LLC  ·  {inv.number}")
    cur = inv.currency or "USD"
    W = doc.width

    title = ParagraphStyle("INVTitle", parent=ss["Normal"], fontName="Helvetica-Bold",
                           fontSize=27, textColor=INK, leading=30)
    metaLbl = ParagraphStyle("INVMetaLbl", parent=ss["Normal"], fontSize=8.5, textColor=MUTED,
                             alignment=TA_RIGHT, spaceAfter=1)
    metaVal = ParagraphStyle("INVMetaVal", parent=ss["Normal"], fontSize=10.5, textColor=INK,
                             alignment=TA_RIGHT, spaceAfter=9)
    secLbl = ParagraphStyle("INVSecLbl", parent=ss["Normal"], fontName="Helvetica-Bold",
                            fontSize=9.5, textColor=INK, spaceAfter=6)
    body = ParagraphStyle("INVBody", parent=ss["Normal"], fontSize=10, textColor=INK, leading=15)
    big = ParagraphStyle("INVBig", parent=ss["Normal"], fontName="Helvetica-Bold",
                         fontSize=22, textColor=INK, leading=26)
    payh = ParagraphStyle("INVPayH", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=11, textColor=INK, spaceAfter=12)
    pkey = ParagraphStyle("INVPKey", parent=body, textColor=MUTED, fontSize=9.5, leading=13)
    pval = ParagraphStyle("INVPVal", parent=body, textColor=INK, fontSize=9.5, leading=13)

    def money(n):
        return f"{float(n or 0):,.2f}"

    # header: "Invoice" left, number + issue date right (sentence-case labels)
    right = [Paragraph("Invoice number", metaLbl), Paragraph(_e(inv.number or ""), metaVal),
             Paragraph("Issue date", metaLbl), Paragraph(_fmt_date(inv.issue_date), metaVal)]
    header = Table([[Paragraph("Invoice", title), right]], colWidths=[W * 0.58, W * 0.42])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story = [header, Spacer(1, 15), HRFlowable(width="100%", thickness=0.6, color=LINE), Spacer(1, 18)]

    # billed to | issued by
    client = inv.bill_to_company or inv.bill_to_name or (company.name if company else "")
    left_cell = [Paragraph("Billed to", secLbl), Paragraph(_e(client) or "&nbsp;", body)]
    if inv.bill_to_name and inv.bill_to_company:
        left_cell.append(Paragraph(_e(inv.bill_to_name), body))
    if inv.bill_to_address:
        for ln in str(inv.bill_to_address).splitlines():
            if ln.strip():
                left_cell.append(Paragraph(_e(ln), body))
    if inv.bill_to_email:
        left_cell.append(Paragraph(_e(inv.bill_to_email), body))
    right_cell = [Paragraph("Issued by", secLbl)]
    for ln in INVOICE_ISSUER.splitlines():
        right_cell.append(Paragraph(_e(ln), body))
    parties = Table([[left_cell, right_cell]], colWidths=[W * 0.5, W * 0.5])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("RIGHTPADDING", (0, 0), (0, 0), 14)]))
    story += [parties, Spacer(1, 20)]

    # amount due by (aligned to the left margin, large)
    story += [Paragraph(f"{money(inv.total)} {_e(cur)} due by {_fmt_date(inv.due_date)}", big),
              Spacer(1, 12)]

    # line items (with a Tax column, matching the reference)
    right_p = ParagraphStyle("INVCellR", parent=body, alignment=TA_RIGHT, fontSize=9.5)
    head_l = ParagraphStyle("INVHeadL", parent=body, fontName="Helvetica-Bold", fontSize=9.5)
    head_r = ParagraphStyle("INVHeadR", parent=head_l, alignment=TA_RIGHT)
    data = [[Paragraph("Product or service", head_l), Paragraph("Quantity", head_r),
             Paragraph("Unit price", head_r), Paragraph("Tax", head_r), Paragraph("Total", head_r)]]
    for li in (inv.line_items or []):
        qty = li.get("quantity", 1) or 0
        rate = li.get("rate", 0) or 0
        amt = li.get("amount", (qty or 0) * (rate or 0)) or 0
        data.append([Paragraph(_e(li.get("description", "")), body),
                     Paragraph(f"{qty:g}", right_p), Paragraph(f"{money(rate)} {cur}", right_p),
                     Paragraph("", right_p), Paragraph(f"{money(amt)} {cur}", right_p)])
    t = Table(data, colWidths=[W - 4.15 * inch, 0.9 * inch, 1.2 * inch, 0.7 * inch, 1.35 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, 0), 0), ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        ("TOPPADDING", (0, 1), (-1, -1), 9), ("BOTTOMPADDING", (0, 1), (-1, -1), 9),
    ]))
    story.append(t)

    # totals, right-aligned under the Total column
    tl_l = ParagraphStyle("INVTotL", parent=body, alignment=TA_RIGHT, textColor=MUTED, fontSize=10)
    tl_r = ParagraphStyle("INVTotR", parent=body, alignment=TA_RIGHT, textColor=MUTED, fontSize=10)
    grand_l = ParagraphStyle("INVGrL", parent=body, alignment=TA_RIGHT, fontName="Helvetica-Bold", fontSize=12.5, textColor=INK)
    totals = [[Paragraph("Total excluding tax", tl_l), Paragraph(f"{money(inv.subtotal)} {cur}", tl_r)]]
    if inv.discount_amount:
        totals.append([Paragraph("Discount", tl_l), Paragraph(f"-{money(inv.discount_amount)} {cur}", tl_r)])
    totals.append([Paragraph("Total tax", tl_l), Paragraph(f"{money(inv.tax_amount)} {cur}", tl_r)])
    totals.append([Paragraph("Amount Due", grand_l), Paragraph(f"{money(inv.total)} {cur}", grand_l)])
    tt = Table(totals, colWidths=[2.4 * inch, 1.35 * inch], hAlign="RIGHT")
    tt.setStyle(TableStyle([
        ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEABOVE", (0, -1), (-1, -1), 1.0, INK),
        ("TOPPADDING", (0, -1), (-1, -1), 12), ("BOTTOMPADDING", (0, -1), (-1, -1), 4),
    ]))
    story += [tt, Spacer(1, 26)]

    # Payment details (left) + Guidelines (right). Details are stacked label-above-
    # value with tight spacing (no big gaps); guidelines sit in their own column so
    # they never crowd the bank details.
    pLabel = ParagraphStyle("INVPLabel", parent=body, fontName="Helvetica-Bold",
                            fontSize=9.5, textColor=INK, leading=12, spaceAfter=0)
    pValTight = ParagraphStyle("INVPValT", parent=body, fontSize=9.5, textColor=INK,
                               leading=12, spaceAfter=7)
    gHead = ParagraphStyle("INVGHead", parent=body, fontName="Helvetica-Bold",
                           fontSize=10.5, textColor=INK, spaceAfter=8)
    gItem = ParagraphStyle("INVGItem", parent=body, fontSize=8.6, textColor=MUTED,
                           leading=12, spaceAfter=7, leftIndent=10, firstLineIndent=-10)

    left = [Paragraph(_e(INVOICE_PAYMENT_TITLE), payh)]
    for k, v in _payment_details():
        left.append(Paragraph(_e(k), pLabel))
        left.append(Paragraph(_e(v), pValTight))
    right = [Paragraph("Guidelines", gHead)]
    for g in _guidelines():
        right.append(Paragraph("&bull;&nbsp;&nbsp;" + _e(g), gItem))

    pay = Table([[left, right]], colWidths=[W * 0.54, W * 0.46])
    pay.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 0), ("LEFTPADDING", (1, 0), (1, -1), 26),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(pay)

    if inv.notes:
        story += [Spacer(1, 18)] + _body_flowables(inv.notes, ss)

    doc.build(story)
    return buf.getvalue()
