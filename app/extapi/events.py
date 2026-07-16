"""Outbound webhook events. emit() fans an event out to every matching active
endpoint as a WebhookDelivery row + a queued worker job; deliver() sends one
delivery with an HMAC signature, exponential-backoff retries and a dead state.

Signature header:  X-RevCadence-Signature: t=<unix>,v1=<hex>
Verify with:       hex == HMAC_SHA256(endpoint_secret, f"{t}.{raw_body}")
"""
import json
import secrets
from datetime import datetime, timedelta

import requests

from ..models.devapi import WebhookDelivery, WebhookEndpoint
from ..models.jobs import Job
from .security import is_safe_webhook_url, sign_webhook

API_VERSION = "2026-07-01"
BACKOFF_MINUTES = [1, 5, 30, 120, 720]   # 5 attempts, then dead
TIMEOUT_S = 10


def emit(db, workspace_id: int, event_type: str, data: dict):
    """Queue the event for every active endpoint subscribed to it. Never raises
    (a webhook must never break a business action)."""
    try:
        eps = (db.query(WebhookEndpoint)
               .filter(WebhookEndpoint.workspace_id == workspace_id,
                       WebhookEndpoint.active == True).all())  # noqa: E712
        eps = [e for e in eps if event_type in (e.events or [])]
        if not eps:
            return
        event_id = "evt_" + secrets.token_hex(12)
        for e in eps:
            d = WebhookDelivery(workspace_id=workspace_id, endpoint_id=e.id,
                                event_id=event_id, event_type=event_type,
                                payload=data, status="pending",
                                next_attempt_at=datetime.utcnow())
            db.add(d)
            db.flush()
            db.add(Job(workspace_id=workspace_id, kind="webhook_delivery",
                       payload={"delivery_id": d.id}, max_attempts=1))
        db.commit()
    except Exception:
        db.rollback()


def deliver(db, delivery_id: int) -> dict:
    d = db.get(WebhookDelivery, delivery_id)
    if not d or d.status in ("delivered", "dead"):
        return {"skipped": True}
    ep = db.get(WebhookEndpoint, d.endpoint_id)
    if not ep or not ep.active:
        d.status = "dead"; d.error = "endpoint inactive"; db.commit()
        return {"dead": True}

    ok, why = is_safe_webhook_url(ep.url)
    if not ok:
        d.status = "dead"; d.error = f"unsafe url: {why}"; db.commit()
        return {"dead": True}

    d.attempts = (d.attempts or 0) + 1
    body_obj = {
        "id": d.event_id,
        "type": d.event_type,
        "created_at": (d.created_at or datetime.utcnow()).isoformat() + "Z",
        "api_version": API_VERSION,
        "workspace_id": d.workspace_id,
        "attempt": d.attempts,
        "data": d.payload or {},
    }
    body = json.dumps(body_obj, separators=(",", ":")).encode()
    ts = str(int(datetime.utcnow().timestamp()))
    sig = sign_webhook(ep.secret or "", ts, body)
    try:
        r = requests.post(ep.url, data=body, timeout=TIMEOUT_S, headers={
            "Content-Type": "application/json",
            "User-Agent": "RevCadence-Webhooks/1.0",
            "X-RevCadence-Event": d.event_type,
            "X-RevCadence-Delivery": str(d.id),
            "X-RevCadence-Signature": f"t={ts},v1={sig}",
        })
        d.response_status = r.status_code
        if 200 <= r.status_code < 300:
            d.status = "delivered"; d.error = ""
            d.delivered_at = datetime.utcnow()
            ep.last_delivery_at = datetime.utcnow()
            ep.failure_count = 0
            db.commit()
            return {"delivered": True, "status": r.status_code}
        raise RuntimeError(f"HTTP {r.status_code}")
    except Exception as ex:
        d.error = str(ex)[:500]
        ep.failure_count = (ep.failure_count or 0) + 1
        if d.attempts >= len(BACKOFF_MINUTES):
            d.status = "dead"
        else:
            d.status = "failed"
            d.next_attempt_at = datetime.utcnow() + timedelta(minutes=BACKOFF_MINUTES[d.attempts - 1])
            db.add(Job(workspace_id=d.workspace_id, kind="webhook_delivery",
                       payload={"delivery_id": d.id}, max_attempts=1,
                       run_at=d.next_attempt_at))
        db.commit()
        return {"delivered": False, "error": d.error, "status": d.status}


def replay(db, delivery_id: int):
    """Manual replay from the UI: reset to pending and queue immediately."""
    d = db.get(WebhookDelivery, delivery_id)
    if not d:
        return None
    d.status = "pending"
    d.next_attempt_at = datetime.utcnow()
    db.add(Job(workspace_id=d.workspace_id, kind="webhook_delivery",
               payload={"delivery_id": d.id}, max_attempts=1))
    db.commit()
    return d
