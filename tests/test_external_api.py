"""External API + webhooks + CRM sync foundation tests.
Run:  python -m tests.test_external_api   (throwaway SQLite DB)"""
import json
import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["JWT_SECRET"] = "test-secret"

from datetime import datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.identity import Membership, Organization, User  # noqa: E402
from app.models.devapi import ApiKey, SyncConnection, WebhookDelivery, WebhookEndpoint  # noqa: E402
from app.extapi import events, security, sync as sync_mod  # noqa: E402

client = TestClient(app)
PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond)))
    print(("✓" if cond else "✗ FAIL"), name, detail if not cond else "")
    assert cond, f"{name}: {detail}"


def setup():
    init_db()
    db = SessionLocal()
    org = Organization(name="T", slug="t")
    db.add(org); db.flush()
    u = User(email="owner@test.com", password_hash=hash_password("pw"), name="Owner")
    db.add(u); db.flush()
    db.add(Membership(user_id=u.id, org_id=org.id, role="owner", workspace_ids=[]))
    db.commit(); db.close()


def main():
    setup()
    tok = client.post("/api/auth/login", json={"email": "owner@test.com", "password": "pw"}).json()["token"]
    H = {"Authorization": f"Bearer {tok}"}
    ws1 = client.post("/api/admin/workspaces", json={"name": "WS1"}, headers=H).json()["id"]
    ws2 = client.post("/api/admin/workspaces", json={"name": "WS2"}, headers=H).json()["id"]

    # ---- key creation + one-time secret + hashed storage
    r = client.post("/api/devapi/keys", headers=H, json={
        "name": "Test key", "scopes": ["companies:read", "companies:write", "contacts:read",
                                       "contacts:write", "deals:read", "deals:write",
                                       "activities:read", "activities:write"],
        "workspace_id": ws1})
    check("key created", r.status_code == 200, r.text)
    full = r.json()["key"]
    key_id = r.json()["id"]
    check("full key returned once", full.startswith("rck_"))
    db = SessionLocal()
    row = db.get(ApiKey, key_id)
    check("raw key never stored", full not in (row.key_hash or "") and row.key_hash != full)
    check("hash verifies", security.verify_api_key(full, row.key_hash))
    db.close()
    A = {"Authorization": f"Bearer {full}"}

    # ---- auth paths
    check("valid key works", client.get("/api/v1/companies", headers=A).status_code == 200)
    check("garbage key 401", client.get("/api/v1/companies",
          headers={"Authorization": "Bearer rck_dead_beef"}).status_code == 401)
    check("no key 401", client.get("/api/v1/companies").status_code == 401)

    # ---- scope enforcement
    r = client.get("/api/v1/invoices", headers=A)
    check("missing scope 403", r.status_code == 403 and r.json()["error"]["code"] == "missing_scope", r.text)

    # ---- writes + idempotency + external_id dedupe
    r = client.post("/api/v1/companies", headers={**A, "Idempotency-Key": "idem-1"},
                    json={"name": "Acme", "external_id": "hs_1", "external_source": "hubspot"})
    check("company created", r.status_code == 201, r.text)
    co_id = r.json()["data"]["id"]
    r2 = client.post("/api/v1/companies", headers={**A, "Idempotency-Key": "idem-1"},
                     json={"name": "Acme", "external_id": "hs_1"})
    check("idempotent replay returns same company",
          r2.json()["data"]["id"] == co_id and r2.status_code in (200, 201), r2.text)
    r3 = client.post("/api/v1/companies", headers=A, json={"name": "Acme2", "external_id": "hs_1"})
    check("external_id dedupe 409", r3.status_code == 409 and
          r3.json()["error"]["code"] == "duplicate_external_id", r3.text)
    r = client.get("/api/v1/companies?external_id=hs_1", headers=A)
    check("external_id lookup", r.json()["data"][0]["id"] == co_id)

    # ---- contacts + pagination/filtering + safe payloads
    for i in range(3):
        client.post("/api/v1/contacts", headers=A,
                    json={"email": f"p{i}@acme.com", "first_name": f"P{i}", "company_id": co_id})
    r = client.get("/api/v1/contacts?page=1&page_size=2&sort=created_at:asc", headers=A)
    check("pagination works", len(r.json()["data"]) == 2 and r.json()["pagination"]["total"] == 3, r.text)
    check("no internal fields leak", "legacy_lead_ids" not in json.dumps(r.json()))
    dup = client.post("/api/v1/contacts", headers=A, json={"email": "p0@acme.com"})
    check("email dedupe 409", dup.status_code == 409)

    # ---- deals + stage mapping via names
    r = client.post("/api/v1/deals", headers=A, json={"name": "Big deal", "value": 9000, "company_id": co_id})
    check("deal created", r.status_code == 201, r.text)
    r = client.post("/api/v1/deals", headers=A, json={"name": "X", "stage": "No Such Stage"})
    check("unknown stage 422", r.status_code == 422)

    # ---- workspace isolation: a key for WS2 must not see WS1 data
    r = client.post("/api/devapi/keys", headers=H, json={
        "name": "WS2", "scopes": ["companies:read"], "workspace_id": ws2})
    B = {"Authorization": f"Bearer {r.json()['key']}"}
    r = client.get("/api/v1/companies", headers=B)
    check("workspace isolation", r.json()["pagination"]["total"] == 0, r.text)
    check("cross-ws 404", client.get(f"/api/v1/companies/{co_id}", headers=B).status_code == 404)

    # ---- revoked / expired
    client.post(f"/api/devapi/keys/{key_id}/revoke", headers=H)
    check("revoked key 401", client.get("/api/v1/companies", headers=A).status_code == 401)
    db = SessionLocal()
    row = db.get(ApiKey, key_id)
    row.revoked_at = None
    row.expires_at = datetime.utcnow() - timedelta(days=1)
    db.commit(); db.close()
    check("expired key 401", client.get("/api/v1/companies", headers=A).status_code == 401)
    db = SessionLocal(); row = db.get(ApiKey, key_id); row.expires_at = None; db.commit(); db.close()

    # ---- rate limiting
    security.reset_rate_limits()
    old = security.RATE_LIMIT_PER_MINUTE
    security.RATE_LIMIT_PER_MINUTE = 3
    codes = [client.get("/api/v1/companies", headers=A).status_code for _ in range(5)]
    security.RATE_LIMIT_PER_MINUTE = old
    security.reset_rate_limits()
    check("rate limit 429", 429 in codes, str(codes))

    # ---- request logs recorded
    r = client.get(f"/api/devapi/keys/{key_id}/requests", headers=H)
    check("request logs recorded", len(r.json()) > 0)

    # ---- webhook signing + verification
    body = b'{"hello":"world"}'
    sig = security.sign_webhook("sec", "123", body)
    import hashlib, hmac as _hmac
    check("hmac signature correct",
          sig == _hmac.new(b"sec", b"123." + body, hashlib.sha256).hexdigest())

    # ---- SSRF guard (direct unit checks — IP literals need no DNS)
    check("SSRF blocks loopback ip", security.is_safe_webhook_url("http://127.0.0.1/x")[0] is False)
    check("SSRF blocks private ip", security.is_safe_webhook_url("https://10.0.0.5/x")[0] is False)
    check("SSRF blocks non-http", security.is_safe_webhook_url("ftp://example.com/x")[0] is False)

    # sandbox has no DNS: stub the resolver-dependent gate for endpoint CRUD
    import app.routers.devapi as devapi_router
    devapi_router.is_safe_webhook_url = lambda url: ((False, "Private or local addresses are not allowed")
                                                     if "localhost" in url else (True, ""))
    events.is_safe_webhook_url = lambda url: (True, "")
    sync_mod.is_safe_webhook_url = lambda url: (True, "")

    # ---- webhook endpoint + emit + retry + replay + duplicate event ids
    r = client.post("/api/devapi/webhooks", headers=H, json={
        "url": "https://example.com/hook", "events": ["company.created"], "workspace_id": ws1})
    check("hook created w/ secret", r.status_code == 200 and r.json()["secret"].startswith("whsec_"), r.text)
    bad = client.post("/api/devapi/webhooks", headers=H, json={
        "url": "http://localhost/hook", "events": ["company.created"], "workspace_id": ws1})
    check("SSRF url rejected", bad.status_code == 422)

    db = SessionLocal()
    events.emit(db, ws1, "company.created", {"id": 1, "name": "Acme"})
    d = db.query(WebhookDelivery).order_by(WebhookDelivery.id.desc()).first()
    check("delivery queued with event id", d is not None and d.event_id.startswith("evt_"))

    sent = {}
    import requests as _rq
    def fake_post(url, data=None, timeout=None, headers=None):
        sent["url"] = url; sent["headers"] = headers; sent["body"] = data
        class R: status_code = 500; text = "boom"
        return R()
    real_post = _rq.post
    _rq.post = fake_post
    events.deliver(db, d.id)
    db.refresh(d)
    check("failed delivery retries scheduled", d.status == "failed" and d.attempts == 1 and d.next_attempt_at)
    check("signature header sent", "X-RevCadence-Signature" in (sent.get("headers") or {}))
    payload = json.loads(sent["body"])
    check("payload has id/type/attempt", payload["id"] == d.event_id and payload["type"] == "company.created"
          and payload["attempt"] == 1 and "data" in payload)
    def ok_post(url, data=None, timeout=None, headers=None):
        class R: status_code = 200; text = "ok"; content = b""
        return R()
    _rq.post = ok_post
    events.replay(db, d.id)
    events.deliver(db, d.id)
    db.refresh(d)
    check("replay then delivered", d.status == "delivered")
    events_before = d.event_id
    r2again = events.deliver(db, d.id)
    check("duplicate delivery skipped", r2again.get("skipped") is True and d.event_id == events_before)

    # ---- CRM sync: generic provider, mapping, idempotent upserts, failure retry
    conn = SyncConnection(workspace_id=ws1, provider="generic", name="t",
                          config_encrypted=security.encrypt_credentials(
                              json.dumps({"url": "https://example.com/sync", "secret": "s"})),
                          direction="outbound", entities=["companies"],
                          stage_mappings={}, field_mappings={})
    db.add(conn); db.commit()

    calls = []
    def sync_post(url, data=None, timeout=None, headers=None):
        calls.append(json.loads(data))
        class R:
            status_code = 200; content = b'{"external_id": "EXT-9"}'
            def json(self): return {"external_id": "EXT-9"}
        return R()
    _rq.post = sync_post
    res = sync_mod.run_sync(db, conn.id)
    check("generic sync ran", res["synced"] >= 1 and res["failed"] == 0, str(res))
    from app.models.devapi import SyncMapping
    m = db.query(SyncMapping).filter(SyncMapping.workspace_id == ws1).first()
    check("mapping recorded", m is not None and m.external_entity_id == "EXT-9" and m.sync_status == "synced")
    n_maps = db.query(SyncMapping).count()
    sync_mod.run_sync(db, conn.id)
    check("re-sync creates no duplicate mappings", db.query(SyncMapping).count() == n_maps)

    def fail_post(url, data=None, timeout=None, headers=None):
        raise RuntimeError("down")
    _rq.post = fail_post
    res = sync_mod.run_sync(db, conn.id)
    db.refresh(m)
    check("failed sync recorded", res["failed"] >= 1 and m.sync_status == "failed" and m.last_error)
    _rq.post = sync_post
    res = sync_mod.run_sync(db, conn.id)
    db.refresh(m)
    check("failed-sync retry recovers", m.sync_status == "synced")
    _rq.post = real_post
    db.close()

    # ---- conflict policies stored + validated
    r = client.post("/api/devapi/sync/connections", headers=H, json={
        "provider": "generic", "conflict_policy": "not_a_policy", "workspace_id": ws1})
    check("bad conflict policy 422", r.status_code == 422)

    # ---- client-facing OpenAPI excludes internal routes
    spec = client.get("/api/v1/openapi.json").json()
    paths = json.dumps(list(spec["paths"].keys()))
    check("openapi only external", "devapi" not in paths and "reply/leads" not in paths
          and "admin" not in paths, paths)

    print(f"\n{sum(1 for _, ok in PASS if ok)}/{len(PASS)} passed")


if __name__ == "__main__":
    main()
