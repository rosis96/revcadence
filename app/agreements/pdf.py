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
INV_ACCENT = colors.HexColor("#244a68")
INV_LINE = colors.HexColor("#d9e1e8")
INV_SOFT = colors.HexColor("#f6f8fa")
INV_SOFT_STRONG = colors.HexColor("#edf3f7")
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
        ("Beneficiary", "Rosis Sitoula"),
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


def _address_lines(value) -> list[str]:
    """Return intentional postal-address lines instead of relying on wrapping.

    Explicit newlines always win. For a comma-separated single-line address,
    keep suite/unit information with the street and city with state/ZIP.
    """
    raw = str(value or "").replace("\r", "").strip()
    if not raw:
        return []
    if "\n" in raw:
        return [line.strip() for line in raw.split("\n") if line.strip()]

    parts = [part.strip() for part in raw.split(",") if part.strip()]
    countries = {
        "usa", "us", "united states", "united states of america",
        "uk", "united kingdom", "canada", "australia", "nepal",
    }
    country = parts.pop() if parts and parts[-1].lower() in countries else ""
    if len(parts) >= 3:
        lines = [", ".join(parts[:-2]), f"{parts[-2]}, {parts[-1]}"]
    elif len(parts) == 2 and country:
        lines = [f"{parts[0]}, {parts[1]}"]
    else:
        lines = parts
    if country:
        lines.append(country)
    return [line for line in lines if line] or [raw]


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


def _doc(buf, footer_note, *, top_margin=0.8 * inch, bottom_margin=0.9 * inch):
    doc = BaseDocTemplate(buf, pagesize=LETTER,
                          leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                          topMargin=top_margin, bottomMargin=bottom_margin,
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
    doc = _doc(buf, f"RevCadence LLC  ·  {inv.number}",
               top_margin=0.62 * inch, bottom_margin=0.82 * inch)
    # Invoices have compact, table-oriented content and should remain a single
    # page for normal line-item counts. Keep the footer clearance, but reclaim
    # a little vertical space from the agreement-oriented default margins.
    cur = inv.currency or "USD"
    W = doc.width

    title = ParagraphStyle("INVTitle", parent=ss["Normal"], fontName="Helvetica-Bold",
                           fontSize=27, textColor=INK, leading=30)
    metaLbl = ParagraphStyle("INVMetaLbl", parent=ss["Normal"], fontSize=8.5, textColor=MUTED,
                             leading=11, spaceAfter=3)
    metaVal = ParagraphStyle("INVMetaVal", parent=ss["Normal"], fontSize=10.5, textColor=INK,
                             leading=13)
    secLbl = ParagraphStyle("INVSecLbl", parent=ss["Normal"], fontName="Helvetica-Bold",
                            fontSize=9.5, textColor=INK, spaceAfter=6)
    body = ParagraphStyle("INVBody", parent=ss["Normal"], fontSize=10, textColor=INK, leading=15)
    big = ParagraphStyle("INVBig", parent=ss["Normal"], fontName="Helvetica-Bold",
                         fontSize=22, textColor=INK, leading=26)
    payh = ParagraphStyle("INVPayH", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=10.5, textColor=INK, spaceAfter=0)

    def money(n):
        return f"{float(n or 0):,.2f}"

    def headline_money(n):
        value = float(n or 0)
        return f"{value:,.0f}" if value.is_integer() else f"{value:,.2f}"

    # Reference-style header: title at left, invoice number and issue date in
    # two equal columns at right.
    meta = Table([
        [Paragraph("Invoice number", metaLbl), Paragraph("Issue date", metaLbl)],
        [Paragraph(_e(inv.number or ""), metaVal), Paragraph(_fmt_date(inv.issue_date), metaVal)],
    ], colWidths=[W * 0.22, W * 0.22])
    meta.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), INV_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.55, INV_LINE),
        ("LINEBEFORE", (1, 0), (1, -1), 0.45, INV_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ("TOPPADDING", (0, 1), (-1, 1), 1),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
    ]))
    header = Table([[Paragraph("Invoice", title), meta]], colWidths=[W * 0.56, W * 0.44])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story = [header, Spacer(1, 10), HRFlowable(width="100%", thickness=0.6, color=LINE), Spacer(1, 12)]

    # billed to | issued by
    client = inv.bill_to_company or inv.bill_to_name or (company.name if company else "")
    left_cell = [Paragraph("Billed to", secLbl), Paragraph(_e(client) or "&nbsp;", body)]
    if inv.bill_to_name and inv.bill_to_company:
        left_cell.append(Paragraph(_e(inv.bill_to_name), body))
    for line in _address_lines(inv.bill_to_address):
        left_cell.append(Paragraph(_e(line), body))
    if inv.bill_to_email:
        left_cell.append(Paragraph(_e(inv.bill_to_email), body))
    right_cell = [Paragraph("Issued by", secLbl)]
    for line in _address_lines(INVOICE_ISSUER):
        right_cell.append(Paragraph(_e(line), body))
    party_gap = 0.16 * inch
    party_width = (W - party_gap) / 2.0
    parties = Table([[left_cell, "", right_cell]],
                    colWidths=[party_width, party_gap, party_width])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("BACKGROUND", (0, 0), (0, 0), INV_SOFT),
                                 ("BACKGROUND", (2, 0), (2, 0), INV_SOFT),
                                 ("BOX", (0, 0), (0, 0), 0.55, INV_LINE),
                                 ("BOX", (2, 0), (2, 0), 0.55, INV_LINE),
                                 ("LEFTPADDING", (0, 0), (0, 0), 12),
                                 ("RIGHTPADDING", (0, 0), (0, 0), 12),
                                 ("LEFTPADDING", (1, 0), (1, 0), 0),
                                 ("RIGHTPADDING", (1, 0), (1, 0), 0),
                                 ("LEFTPADDING", (2, 0), (2, 0), 12),
                                 ("RIGHTPADDING", (2, 0), (2, 0), 12),
                                 ("TOPPADDING", (0, 0), (-1, -1), 11),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 11)]))
    story += [parties, Spacer(1, 13)]

    # amount due by (aligned to the left margin, large)
    story += [Paragraph(f"{headline_money(inv.total)} {_e(cur)} due by {_fmt_date(inv.due_date)}", big),
              Spacer(1, 8)]

    # line items (with a Tax column, matching the reference)
    right_p = ParagraphStyle("INVCellR", parent=body, alignment=TA_RIGHT, fontSize=9.5)
    head_l = ParagraphStyle("INVHeadL", parent=body, fontName="Helvetica-Bold",
                            fontSize=9.5, textColor=INV_ACCENT)
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
        ("BACKGROUND", (0, 0), (-1, 0), INV_SOFT_STRONG),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, INV_SOFT]),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, INV_LINE),
        ("BOX", (0, 0), (-1, -1), 0.55, INV_LINE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, INV_ACCENT),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, INV_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 9), ("BOTTOMPADDING", (0, 1), (-1, -1), 9),
    ]))
    story.append(t)

    # totals, right-aligned under the Total column
    tl_l = ParagraphStyle("INVTotL", parent=body, alignment=TA_RIGHT, textColor=MUTED, fontSize=10)
    tl_r = ParagraphStyle("INVTotR", parent=body, alignment=TA_RIGHT, textColor=MUTED, fontSize=10)
    grand_l = ParagraphStyle("INVGrL", parent=body, alignment=TA_RIGHT,
                             fontName="Helvetica-Bold", fontSize=12.5,
                             textColor=INV_ACCENT)
    totals = [[Paragraph("Total excluding tax", tl_l), Paragraph(f"{money(inv.subtotal)} {cur}", tl_r)]]
    if inv.discount_amount:
        totals.append([Paragraph("Discount", tl_l), Paragraph(f"-{money(inv.discount_amount)} {cur}", tl_r)])
    totals.append([Paragraph("Total tax", tl_l), Paragraph(f"{money(inv.tax_amount)} {cur}", tl_r)])
    totals.append([Paragraph("Invoice Total", grand_l), Paragraph(f"{money(inv.total)} {cur}", grand_l)])
    tt = Table(totals, colWidths=[2.2 * inch, 1.55 * inch], hAlign="RIGHT")
    tt.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, INV_LINE),
        ("LINEBELOW", (0, 0), (-1, -2), 0.35, INV_LINE),
        ("BACKGROUND", (0, -1), (-1, -1), INV_SOFT_STRONG),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, INV_ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -2), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -2), 6),
        ("TOPPADDING", (0, -1), (-1, -1), 10),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
    ]))
    story += [tt, Spacer(1, 18), Paragraph(_e(INVOICE_PAYMENT_TITLE), payh),
              Spacer(1, 9), HRFlowable(width="100%", thickness=0.45, color=LINE),
              Spacer(1, 11)]

    # Three equal-width columns mirror the supplied reference while keeping all
    # supplied payment data. No QR or international details are invented.
    pay_head = ParagraphStyle("INVPayColHead", parent=body, fontName="Helvetica-Bold",
                              fontSize=9.3, textColor=INK, leading=12, spaceAfter=6)
    pay_copy = ParagraphStyle("INVPayCopy", parent=body, fontSize=8.5, textColor=MUTED,
                              leading=11, spaceAfter=7)
    pay_key = ParagraphStyle("INVPayKey", parent=body, fontSize=8.2, textColor=MUTED,
                             leading=10.5)
    pay_val = ParagraphStyle("INVPayVal", parent=body, fontSize=8.5, textColor=INK,
                             leading=10.5)
    column_width = W / 3.0
    payment_content_width = column_width - 24

    def detail_table(rows):
        table = Table(
            [[Paragraph(_e(k), pay_key),
              Paragraph(_e(v).replace("\n", "<br/>") or "&nbsp;", pay_val)]
             for k, v in rows],
            colWidths=[0.70 * inch, payment_content_width - 0.70 * inch],
        )
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (0, -1), INV_SOFT),
            ("LINEBELOW", (0, 0), (-1, -2), 0.35, INV_LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, -1), 6),
            ("RIGHTPADDING", (1, 0), (1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]))
        return table

    payment_rows = _payment_details()
    beneficiary_rows = []
    bank_rows = []
    beneficiary_name = ""
    for key, value in payment_rows:
        lowered = key.lower()
        if "beneficiary" in lowered:
            beneficiary_name = value
        elif lowered == "note":
            beneficiary_rows.append(("Note", value))
        else:
            bank_rows.append((key, value))
    beneficiary_rows.append(("Profile address", INVOICE_ISSUER))
    method = [
        Paragraph("Bank transfer", pay_head),
        Paragraph("Use these details to pay USD from a US business account by ACH or wire.", pay_copy),
        detail_table([("Reference", inv.number or ""), ("Currency", cur)]),
    ]
    bank = [Paragraph("Bank details", pay_head), detail_table(bank_rows)]
    beneficiary = [
        Paragraph("Beneficiary", pay_head),
        Paragraph(_e(beneficiary_name) or "&nbsp;", pay_val),
        Spacer(1, 6),
        detail_table(beneficiary_rows),
    ]

    pay = Table([[method, bank, beneficiary]], colWidths=[column_width] * 3)
    pay.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbfcfd")),
        ("BOX", (0, 0), (-1, -1), 0.5, INV_LINE),
        ("LINEBEFORE", (1, 0), (1, 0), 0.5, INV_LINE),
        ("LINEBEFORE", (2, 0), (2, 0), 0.5, INV_LINE),
        ("LEFTPADDING", (0, 0), (0, -1), 12),
        ("RIGHTPADDING", (0, 0), (0, -1), 12),
        ("LEFTPADDING", (1, 0), (1, -1), 12),
        ("RIGHTPADDING", (1, 0), (1, -1), 12),
        ("LEFTPADDING", (2, 0), (2, -1), 12),
        ("RIGHTPADDING", (2, 0), (2, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(pay)

    if inv.notes:
        story += [Spacer(1, 10)] + _body_flowables(inv.notes, ss)

    doc.build(story)
    return buf.getvalue()
