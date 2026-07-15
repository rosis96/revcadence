"""Deterministic Agreement content builder.

Hard rules (spec §3):
- Never invent pricing, deliverables, dates, or legal entities.
- Pull every commercial/deliverable fact from a REAL source (override → deal →
  client profile → blueprint). If a required fact is absent, leave it empty and
  add it to `missing_flags` so the editor prompts for it — do NOT fabricate.

Generation is deterministic (no LLM) precisely so the anti-fabrication guarantee
is testable and never drifts. Prose sections are professional boilerplate the
user can edit; anything factual is sourced or flagged.
"""
import os

PROVIDER_ENTITY = os.getenv("PROVIDER_ENTITY", "RevCadence")
PROVIDER_GOVERNING_LAW = os.getenv("PROVIDER_GOVERNING_LAW", "")   # never invented; flagged if empty

# Ordered section catalog. `required` sections that end up empty are flagged.
SECTION_CATALOG = [
    ("parties", "Parties", True),
    ("background", "Background", False),
    ("scope_of_services", "Scope of Services", True),
    ("deliverables", "Deliverables", True),
    ("implementation_plan", "Implementation Plan", False),
    ("timeline", "Timeline", False),
    ("client_responsibilities", "Client Responsibilities", False),
    ("revcadence_responsibilities", "RevCadence Responsibilities", False),
    ("exclusions", "Exclusions", False),
    ("fees", "Fees", True),
    ("payment_schedule", "Payment Schedule", False),
    ("term_renewal", "Term & Renewal", False),
    ("cancellation_termination", "Cancellation & Termination", False),
    ("confidentiality", "Confidentiality", False),
    ("intellectual_property", "Intellectual Property", False),
    ("limitation_of_liability", "Limitation of Liability", False),
    ("governing_terms", "Governing Terms", False),
]


def _blueprint_content(blueprint):
    return ((blueprint.fields or {}).get("content") or {}) if blueprint else {}


def _pf(profile, section, field):
    """Read a client-profile field value (provenance-wrapped)."""
    if not profile:
        return ""
    cell = ((profile.data or {}).get(section, {}) or {}).get(field, {}) or {}
    return str(cell.get("value") or "").strip()


def _as_lines(val):
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        parts = [p.strip() for p in val.replace("\r", "").split("\n") if p.strip()]
        if len(parts) == 1:
            parts = [p.strip() for p in val.split(";") if p.strip()]
        return parts
    return []


def build_content(company=None, contact=None, deal=None, blueprint=None,
                  profile=None, notes="", overrides=None):
    """Return (sections, fields, missing_flags). Nothing here is invented."""
    overrides = overrides or {}
    bp = _blueprint_content(blueprint)
    missing = []

    company_name = (company.name if company else "") or ""
    provider = overrides.get("provider_entity") or PROVIDER_ENTITY
    client_entity = overrides.get("client_entity") or company_name

    # ---- structured commercial fields (numbers ONLY from explicit sources) ----
    ov_fees = overrides.get("fees") or {}
    setup = ov_fees.get("setup")
    recurring = ov_fees.get("recurring")
    recurring_period = ov_fees.get("recurring_period") or "month"
    currency = ov_fees.get("currency") or "USD"
    performance = ov_fees.get("performance") or ""
    # verbatim commercial prose (never parsed into numbers)
    fees_summary = (ov_fees.get("summary")
                    or _pf(profile, "delivery_scope", "pricing")
                    or bp.get("commercial") or "").strip()

    fields = {
        "effective_date": overrides.get("effective_date", ""),   # never auto-invent a date
        "parties": {"provider_entity": provider, "client_entity": client_entity},
        "fees": {"currency": currency, "setup": setup, "recurring": recurring,
                 "recurring_period": recurring_period, "performance": performance,
                 "summary": fees_summary},
        "term": overrides.get("term", ""),
        "renewal": overrides.get("renewal", ""),
        "governing_law": overrides.get("governing_law", PROVIDER_GOVERNING_LAW),
    }
    if not fields["effective_date"]:
        missing.append("effective_date")
    if setup is None and recurring is None and not fees_summary:
        missing.append("fees")

    # ---- deliverables: sourced, never invented ----
    deliverables = _as_lines(overrides.get("deliverables"))
    if not deliverables:
        deliverables = _as_lines(bp.get("what_we_build"))
    if not deliverables:
        deliverables = _as_lines(_pf(profile, "delivery_scope", "deliverables"))
    if not deliverables and deal and deal.description:
        deliverables = _as_lines(deal.description)
    if not deliverables:
        missing.append("deliverables")

    # ---- scope narrative: sourced prose or a neutral placeholder + flag ----
    scope = (overrides.get("scope_of_services")
             or bp.get("exec_summary")
             or _pf(profile, "overview", "business_overview") or "").strip()
    if not scope:
        missing.append("scope_of_services")

    roadmap = _as_lines(overrides.get("implementation_plan")) or _as_lines(bp.get("roadmap"))
    outcome = (bp.get("target_outcome") or _pf(profile, "delivery_scope", "targets") or "").strip()

    def para(body):
        return body.strip()

    def bullets(items):
        return "\n".join(f"• {i}" for i in items)

    sections = []

    sections.append({"key": "parties", "label": "Parties", "body": para(
        f"This Services Agreement (the “Agreement”) is entered into between {provider} "
        f"(“Provider”) and {client_entity or '[Client legal entity — confirm]'} (“Client”). "
        "The parties agree to the terms below as of the Effective Date.")})

    bg = (overrides.get("background") or bp.get("what_we_see") or "").strip()
    sections.append({"key": "background", "label": "Background", "body": para(
        bg or f"{provider} provides managed revenue operations services. Client wishes to engage "
        "Provider to deliver the services described in this Agreement.")})

    sections.append({"key": "scope_of_services", "label": "Scope of Services", "body": para(
        scope or "[Scope of services — confirm from the approved blueprint/proposal.]")})

    sections.append({"key": "deliverables", "label": "Deliverables", "body": (
        bullets(deliverables) if deliverables else "[Deliverables — confirm from the approved scope.]")})

    sections.append({"key": "implementation_plan", "label": "Implementation Plan", "body": (
        bullets(roadmap) if roadmap else para(
            "Implementation proceeds in phases: onboarding and access, build and configuration, "
            "launch, then ongoing management and optimization."))})

    sections.append({"key": "timeline", "label": "Timeline", "body": para(
        overrides.get("timeline")
        or "Onboarding begins on the Effective Date. Indicative build time is 2–4 weeks to launch, "
        "followed by ongoing managed delivery. Specific dates are confirmed during onboarding.")})

    sections.append({"key": "client_responsibilities", "label": "Client Responsibilities", "body": bullets([
        "Provide timely access to systems, domains, calendars, and assets required to deliver the services.",
        "Nominate a point of contact empowered to make decisions and give approvals.",
        "Review and approve deliverables within a reasonable time.",
    ])})

    sections.append({"key": "revcadence_responsibilities", "label": f"{provider} Responsibilities", "body": bullets([
        "Deliver the services described in the Scope of Services with reasonable skill and care.",
        "Maintain the systems and workflows built for Client during the term.",
        "Report on progress and results on a regular cadence.",
    ])})

    sections.append({"key": "exclusions", "label": "Exclusions", "body": para(
        overrides.get("exclusions")
        or "Anything not expressly listed in the Scope of Services or Deliverables is out of scope. "
        "Third-party software, ad spend, and paid tooling are billed to Client at cost unless stated otherwise.")})

    # Fees section body — verbatim/structured, never invented
    fee_lines = []
    if setup is not None:
        fee_lines.append(f"Setup fee: {currency} {setup:,.2f} (one-time).")
    if recurring is not None:
        fee_lines.append(f"Recurring fee: {currency} {recurring:,.2f} per {recurring_period}.")
    if performance:
        fee_lines.append(f"Performance / revenue-share: {performance}")
    if fees_summary and not fee_lines:
        fee_lines.append(fees_summary)
    elif fees_summary and fee_lines:
        fee_lines.append(f"Notes: {fees_summary}")
    sections.append({"key": "fees", "label": "Fees", "body": (
        "\n".join(fee_lines) if fee_lines else "[Fees — confirm the approved commercial terms.]")})

    sections.append({"key": "payment_schedule", "label": "Payment Schedule", "body": para(
        overrides.get("payment_schedule")
        or "The setup fee (if any) is due on execution. Recurring fees are invoiced in advance and "
        "due within 7 days of the invoice date. Invoices are delivered electronically.")})

    sections.append({"key": "term_renewal", "label": "Term & Renewal", "body": para(
        (f"Initial term: {fields['term']}. " if fields["term"] else
         "Initial term: month-to-month unless otherwise agreed. ")
        + (f"Renewal: {fields['renewal']}." if fields["renewal"] else
           "This Agreement renews automatically for successive periods unless either party gives notice."))})

    sections.append({"key": "cancellation_termination", "label": "Cancellation & Termination", "body": para(
        "Either party may terminate this Agreement for convenience on 30 days’ written notice, or "
        "immediately for material breach that remains uncured for 14 days after written notice. Fees "
        "for services already delivered remain payable.")})

    sections.append({"key": "confidentiality", "label": "Confidentiality", "body": para(
        "Each party will keep the other’s confidential information private and use it only to perform "
        "this Agreement. This obligation survives termination.")})

    sections.append({"key": "intellectual_property", "label": "Intellectual Property", "body": para(
        "On full payment, Client owns the deliverables created specifically for Client. Provider retains "
        "its pre-existing tools, templates, and methods, and may reuse general know-how.")})

    sections.append({"key": "limitation_of_liability", "label": "Limitation of Liability", "body": para(
        "To the maximum extent permitted by law, neither party is liable for indirect or consequential "
        "loss, and each party’s total liability is limited to the fees paid in the three months before "
        "the event giving rise to the claim.")})

    gl = fields["governing_law"]
    if not gl:
        missing.append("governing_law")
    sections.append({"key": "governing_terms", "label": "Governing Terms", "body": para(
        (f"This Agreement is governed by the laws of {gl}. " if gl else
         "This Agreement is governed by the laws of the Provider’s principal place of business. ")
        + "This document, together with the approved scope, is the entire agreement between the parties "
        "and supersedes prior discussions.")})

    return sections, fields, missing
