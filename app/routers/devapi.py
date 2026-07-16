"""Internal management API for Settings → Developers and Settings → CRM.
Session-authenticated (dashboard users), workspace-scoped. The external
/api/v1 surface lives in app/extapi/routes.py."""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthContext, get_ctx
from ..models.devapi import (API_SCOPES, WEBHOOK_EVENTS, ApiKey, ApiRequestLog,
                             SyncConnection, SyncMapping, WebhookDelivery, WebhookEndpoint)
from ..extapi import events as ev
from ..extapi import sync as sync_mod
from ..extapi.security import (encrypt_credentials, decrypt_credentials,
                               generate_api_key, generate_webhook_secret,
                               is_safe_webhook_url)

router = APIRouter(prefix="/api/devapi", tags=["devapi"])


def _ws(ctx: AuthContext, workspace_id: int | None):
    ids = ctx.workspace_ids_for_query(workspace_id)
    if not ids:
        raise HTTPException(403, "No workspace access")
    return ids[0] if len(ids) == 1 else (workspace_id or ids[0])


# ---------------------------------------------------------------- API keys
class KeyIn(BaseModel):
    name: str = ""
    scopes: list[str] = []
    expires_days: int | None = None
    workspace_id: int | None = None


def _key_out(k: ApiKey):
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "scopes": k.scopes or [],
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "created_at": k.created_at.isoformat() if k.created_at else None}


@router.get("/meta")
def meta(_: AuthContext = Depends(get_ctx)):
    return {"scopes": API_SCOPES, "events": WEBHOOK_EVENTS,
            "providers": sync_mod.PROVIDERS, "native_ready": sorted(sync_mod.NATIVE_READY),
            "conflict_policies": sync_mod.CONFLICT_POLICIES}


@router.get("/keys")
def list_keys(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    ws = _ws(ctx, workspace_id)
    rows = ctx.db.query(ApiKey).filter(ApiKey.workspace_id == ws).order_by(ApiKey.id.desc()).all()
    return [_key_out(k) for k in rows]


@router.post("/keys")
def create_key(body: KeyIn, ctx: AuthContext = Depends(get_ctx)):
    ws = _ws(ctx, body.workspace_id)
    bad = [s for s in body.scopes if s not in API_SCOPES]
    if bad:
        raise HTTPException(422, f"Unknown scopes: {', '.join(bad)}")
    full, prefix, key_hash = generate_api_key()
    k = ApiKey(workspace_id=ws, name=body.name or "API key", prefix=prefix,
               key_hash=key_hash, scopes=body.scopes or API_SCOPES,
               expires_at=(datetime.utcnow() + timedelta(days=body.expires_days))
               if body.expires_days else None,
               created_by_user_id=ctx.user.id)
    ctx.db.add(k)
    ctx.db.commit()
    # the ONLY time the raw key ever leaves the server
    return {"key": full, **_key_out(k)}


@router.post("/keys/{key_id}/revoke")
def revoke_key(key_id: int, ctx: AuthContext = Depends(get_ctx)):
    k = ctx.db.get(ApiKey, key_id)
    if not k or k.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Key not found")
    k.revoked_at = datetime.utcnow()
    ctx.db.commit()
    return _key_out(k)


@router.post("/keys/{key_id}/rotate")
def rotate_key(key_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Revoke the old key and mint a replacement with the same name/scopes."""
    k = ctx.db.get(ApiKey, key_id)
    if not k or k.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Key not found")
    k.revoked_at = datetime.utcnow()
    full, prefix, key_hash = generate_api_key()
    nk = ApiKey(workspace_id=k.workspace_id, name=k.name, prefix=prefix,
                key_hash=key_hash, scopes=k.scopes, expires_at=k.expires_at,
                created_by_user_id=ctx.user.id)
    ctx.db.add(nk)
    ctx.db.commit()
    return {"key": full, **_key_out(nk)}


@router.get("/keys/{key_id}/requests")
def key_requests(key_id: int, ctx: AuthContext = Depends(get_ctx)):
    k = ctx.db.get(ApiKey, key_id)
    if not k or k.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Key not found")
    rows = (ctx.db.query(ApiRequestLog).filter(ApiRequestLog.api_key_id == key_id)
            .order_by(ApiRequestLog.id.desc()).limit(100).all())
    return [{"method": r.method, "path": r.path, "status": r.status,
             "latency_ms": r.latency_ms, "at": r.at.isoformat() if r.at else None} for r in rows]


# ---------------------------------------------------------------- webhook endpoints
class HookIn(BaseModel):
    url: str = ""
    events: list[str] = []
    active: bool | None = None
    workspace_id: int | None = None


def _hook_out(h: WebhookEndpoint):
    return {"id": h.id, "url": h.url, "events": h.events or [], "active": h.active,
            "failure_count": h.failure_count,
            "last_delivery_at": h.last_delivery_at.isoformat() if h.last_delivery_at else None,
            "created_at": h.created_at.isoformat() if h.created_at else None}


@router.get("/webhooks")
def list_hooks(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    ws = _ws(ctx, workspace_id)
    rows = ctx.db.query(WebhookEndpoint).filter(WebhookEndpoint.workspace_id == ws).all()
    return [_hook_out(h) for h in rows]


@router.post("/webhooks")
def create_hook(body: HookIn, ctx: AuthContext = Depends(get_ctx)):
    ws = _ws(ctx, body.workspace_id)
    ok, why = is_safe_webhook_url(body.url)
    if not ok:
        raise HTTPException(422, f"Webhook URL rejected: {why}")
    bad = [e for e in body.events if e not in WEBHOOK_EVENTS]
    if bad:
        raise HTTPException(422, f"Unknown events: {', '.join(bad)}")
    h = WebhookEndpoint(workspace_id=ws, url=body.url, events=body.events,
                        secret=generate_webhook_secret(), active=True)
    ctx.db.add(h)
    ctx.db.commit()
    # signing secret is shown ONCE
    return {"secret": h.secret, **_hook_out(h)}


@router.put("/webhooks/{hook_id}")
def update_hook(hook_id: int, body: HookIn, ctx: AuthContext = Depends(get_ctx)):
    h = ctx.db.get(WebhookEndpoint, hook_id)
    if not h or h.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Endpoint not found")
    if body.url:
        ok, why = is_safe_webhook_url(body.url)
        if not ok:
            raise HTTPException(422, f"Webhook URL rejected: {why}")
        h.url = body.url
    if body.events:
        h.events = body.events
    if body.active is not None:
        h.active = body.active
    ctx.db.commit()
    return _hook_out(h)


@router.delete("/webhooks/{hook_id}")
def delete_hook(hook_id: int, ctx: AuthContext = Depends(get_ctx)):
    h = ctx.db.get(WebhookEndpoint, hook_id)
    if not h or h.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Endpoint not found")
    ctx.db.delete(h)
    ctx.db.commit()
    return {"ok": True}


@router.get("/webhooks/{hook_id}/deliveries")
def hook_deliveries(hook_id: int, ctx: AuthContext = Depends(get_ctx)):
    h = ctx.db.get(WebhookEndpoint, hook_id)
    if not h or h.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Endpoint not found")
    rows = (ctx.db.query(WebhookDelivery).filter(WebhookDelivery.endpoint_id == hook_id)
            .order_by(WebhookDelivery.id.desc()).limit(100).all())
    return [{"id": d.id, "event_id": d.event_id, "event_type": d.event_type,
             "status": d.status, "attempts": d.attempts, "response_status": d.response_status,
             "error": d.error, "created_at": d.created_at.isoformat() if d.created_at else None,
             "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None} for d in rows]


@router.post("/webhooks/deliveries/{delivery_id}/replay")
def replay_delivery(delivery_id: int, ctx: AuthContext = Depends(get_ctx)):
    d = ctx.db.get(WebhookDelivery, delivery_id)
    if not d or d.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Delivery not found")
    ev.replay(ctx.db, delivery_id)
    return {"ok": True}


@router.post("/webhooks/{hook_id}/test")
def test_hook(hook_id: int, ctx: AuthContext = Depends(get_ctx)):
    h = ctx.db.get(WebhookEndpoint, hook_id)
    if not h or h.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Endpoint not found")
    from ..models.jobs import Job
    d = WebhookDelivery(workspace_id=h.workspace_id, endpoint_id=h.id,
                        event_id="evt_test", event_type="test.ping",
                        payload={"ping": True}, status="pending",
                        next_attempt_at=datetime.utcnow())
    ctx.db.add(d)
    ctx.db.flush()
    ctx.db.add(Job(workspace_id=h.workspace_id, kind="webhook_delivery",
                   payload={"delivery_id": d.id}, max_attempts=1))
    ctx.db.commit()
    return {"ok": True, "delivery_id": d.id}


# ---------------------------------------------------------------- CRM sync connections
class ConnIn(BaseModel):
    provider: str = "generic"
    name: str = ""
    config: dict = {}          # e.g. {"url": "...", "secret": "..."} — encrypted at rest
    direction: str = "outbound"
    conflict_policy: str = "newest_wins"
    entities: list[str] = ["companies", "contacts", "deals"]
    field_mappings: dict = {}
    stage_mappings: dict = {}
    active: bool | None = None
    workspace_id: int | None = None


def _conn_out(c: SyncConnection, db):
    n_map = db.query(SyncMapping).filter(SyncMapping.workspace_id == c.workspace_id,
                                         SyncMapping.provider == c.provider).count()
    n_fail = db.query(SyncMapping).filter(SyncMapping.workspace_id == c.workspace_id,
                                          SyncMapping.provider == c.provider,
                                          SyncMapping.sync_status == "failed").count()
    return {"id": c.id, "provider": c.provider, "name": c.name, "direction": c.direction,
            "conflict_policy": c.conflict_policy, "entities": c.entities or [],
            "field_mappings": c.field_mappings or {}, "stage_mappings": c.stage_mappings or {},
            "active": c.active, "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
            "last_error": c.last_error, "mapped_records": n_map, "failed_records": n_fail,
            "has_config": bool(c.config_encrypted),
            "native_ready": c.provider in sync_mod.NATIVE_READY}


@router.get("/sync/connections")
def list_conns(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    ws = _ws(ctx, workspace_id)
    rows = ctx.db.query(SyncConnection).filter(SyncConnection.workspace_id == ws).all()
    return [_conn_out(c, ctx.db) for c in rows]


@router.post("/sync/connections")
def create_conn(body: ConnIn, ctx: AuthContext = Depends(get_ctx)):
    ws = _ws(ctx, body.workspace_id)
    if body.provider not in sync_mod.PROVIDERS:
        raise HTTPException(422, f"Unknown provider. Choose one of: {', '.join(sync_mod.PROVIDERS)}")
    if body.conflict_policy not in sync_mod.CONFLICT_POLICIES:
        raise HTTPException(422, "Unknown conflict policy.")
    c = SyncConnection(workspace_id=ws, provider=body.provider, name=body.name or body.provider,
                       config_encrypted=encrypt_credentials(json.dumps(body.config)) if body.config else "",
                       direction=body.direction, conflict_policy=body.conflict_policy,
                       entities=body.entities, field_mappings=body.field_mappings,
                       stage_mappings=body.stage_mappings, active=True)
    ctx.db.add(c)
    ctx.db.commit()
    return _conn_out(c, ctx.db)


@router.put("/sync/connections/{conn_id}")
def update_conn(conn_id: int, body: ConnIn, ctx: AuthContext = Depends(get_ctx)):
    c = ctx.db.get(SyncConnection, conn_id)
    if not c or c.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Connection not found")
    if body.config:
        c.config_encrypted = encrypt_credentials(json.dumps(body.config))
    for f in ("name", "direction", "conflict_policy", "entities", "field_mappings", "stage_mappings"):
        v = getattr(body, f)
        if v:
            setattr(c, f, v)
    if body.active is not None:
        c.active = body.active
    ctx.db.commit()
    return _conn_out(c, ctx.db)


@router.delete("/sync/connections/{conn_id}")
def delete_conn(conn_id: int, ctx: AuthContext = Depends(get_ctx)):
    c = ctx.db.get(SyncConnection, conn_id)
    if not c or c.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Connection not found")
    ctx.db.delete(c)
    ctx.db.commit()
    return {"ok": True}


@router.post("/sync/connections/{conn_id}/test")
def test_conn(conn_id: int, ctx: AuthContext = Depends(get_ctx)):
    c = ctx.db.get(SyncConnection, conn_id)
    if not c or c.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Connection not found")
    try:
        provider = sync_mod.get_provider(c)
    except RuntimeError as ex:
        return {"ok": False, "error": str(ex)}
    ok, why = provider.test_connection()
    return {"ok": ok, "error": why}


@router.post("/sync/connections/{conn_id}/run")
def run_conn(conn_id: int, ctx: AuthContext = Depends(get_ctx)):
    c = ctx.db.get(SyncConnection, conn_id)
    if not c or c.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Connection not found")
    sync_mod.queue_sync(ctx.db, c.id, c.workspace_id)
    return {"ok": True, "queued": True}


@router.post("/sync/connections/{conn_id}/retry-failed")
def retry_failed(conn_id: int, ctx: AuthContext = Depends(get_ctx)):
    c = ctx.db.get(SyncConnection, conn_id)
    if not c or c.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Connection not found")
    failed = (ctx.db.query(SyncMapping)
              .filter(SyncMapping.workspace_id == c.workspace_id,
                      SyncMapping.provider == c.provider,
                      SyncMapping.sync_status == "failed").all())
    ids = {"companies": [], "contacts": [], "deals": []}
    for m in failed:
        ids.setdefault(m.local_entity_type + "s" if not m.local_entity_type.endswith("s")
                       else m.local_entity_type, []).append(m.local_entity_id)
        m.sync_status = "pending"
    ctx.db.commit()
    sync_mod.queue_sync(ctx.db, c.id, c.workspace_id, {
        "companies": ids.get("companys", []) + ids.get("companies", []),
        "contacts": ids.get("contacts", []),
        "deals": ids.get("deals", []),
    })
    return {"ok": True, "retrying": len(failed)}


@router.get("/sync/connections/{conn_id}/mappings")
def conn_mappings(conn_id: int, ctx: AuthContext = Depends(get_ctx)):
    c = ctx.db.get(SyncConnection, conn_id)
    if not c or c.workspace_id not in ctx.workspace_ids_for_query(None):
        raise HTTPException(404, "Connection not found")
    rows = (ctx.db.query(SyncMapping)
            .filter(SyncMapping.workspace_id == c.workspace_id,
                    SyncMapping.provider == c.provider)
            .order_by(SyncMapping.id.desc()).limit(200).all())
    return [{"id": m.id, "type": m.local_entity_type, "local_id": m.local_entity_id,
             "external_id": m.external_entity_id, "status": m.sync_status,
             "error": m.last_error,
             "last_synced_at": m.last_synced_at.isoformat() if m.last_synced_at else None}
            for m in rows]
