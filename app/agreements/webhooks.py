"""Outbound webhook delivery for agreement + invoice lifecycle events.

Configured entirely via environment (Make.com-friendly):
  AGREEMENT_WEBHOOK_URL   — receives agreement.* events
  INVOICE_WEBHOOK_URL     — receives invoice.* events
  PUBLIC_BASE_URL         — e.g. https://engine.revcadence.com (for building links)
  AGREEMENT_PUBLIC_BASE   — optional, e.g. https://agreement.revcadence.com
  INVOICE_PUBLIC_BASE     — optional, e.g. https://invoice.revcadence.com

Payloads carry IDs, public URLs, company/contact, status and timestamps — never
secrets. Delivery is best-effort: failures are swallowed (short timeout) so a
down webhook never blocks signing/execution. Email delivery is NOT included —
see NEXT_STEPS.md for the remaining email-provider requirement.
"""
import os

import requests


def _iso(dt):
    return dt.isoformat() if dt else None


def agreement_public_url(ag) -> str:
    base = os.getenv("AGREEMENT_PUBLIC_BASE", "").rstrip("/")
    if base:
        return f"{base}/{ag.slug}"
    root = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{root}/agreement/{ag.slug}" if root else f"/agreement/{ag.slug}"


def invoice_public_url(inv) -> str:
    base = os.getenv("INVOICE_PUBLIC_BASE", "").rstrip("/")
    if base:
        return f"{base}/{inv.slug}"
    root = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    return f"{root}/invoice/{inv.slug}" if root else f"/invoice/{inv.slug}"


def _post(url, payload):
    if not url:
        return {"delivered": False, "reason": "no webhook url configured"}
    try:
        r = requests.post(url, json=payload, timeout=6)
        return {"delivered": r.ok, "status_code": r.status_code}
    except Exception as e:  # never block the business flow
        return {"delivered": False, "reason": str(e)[:200]}


def agreement_payload(event, ag) -> dict:
    return {
        "event": event,
        "agreement_id": ag.id, "number": ag.number, "title": ag.title,
        "status": ag.status, "version": ag.version,
        "workspace_id": ag.workspace_id, "company_id": ag.company_id,
        "contact_id": ag.contact_id, "deal_id": ag.deal_id,
        "public_url": agreement_public_url(ag),
        "client_signer_name": ag.client_signer_name or None,
        "client_signer_email": ag.client_signer_email or None,
        "client_signed_at": _iso(ag.client_signed_at),
        "countersigned_at": _iso(ag.countersigned_at),
        "executed_at": _iso(ag.executed_at),
        "checksum": ag.checksum or None,
    }


def invoice_payload(event, inv) -> dict:
    return {
        "event": event,
        "invoice_id": inv.id, "number": inv.number, "status": inv.status,
        "workspace_id": inv.workspace_id, "company_id": inv.company_id,
        "contact_id": inv.contact_id, "deal_id": inv.deal_id, "agreement_id": inv.agreement_id,
        "currency": inv.currency, "total": inv.total, "amount_paid": inv.amount_paid,
        "balance_due": inv.balance_due, "issue_date": inv.issue_date, "due_date": inv.due_date,
        "public_url": invoice_public_url(inv),
    }


def fire_agreement(event, ag):
    return _post(os.getenv("AGREEMENT_WEBHOOK_URL", ""), agreement_payload(event, ag))


def fire_invoice(event, inv):
    return _post(os.getenv("INVOICE_WEBHOOK_URL", ""), invoice_payload(event, inv))
