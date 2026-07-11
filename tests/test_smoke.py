"""End-to-end smoke test: seed → login → workspaces → users → deals → isolation.
Run:  python -m tests.test_smoke   (uses a throwaway SQLite DB)"""
import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import init_db, session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.identity import Membership, Organization, User  # noqa: E402

client = TestClient(app)
PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond)))
    print(("✓" if cond else "✗ FAIL"), name, detail if not cond else "")
    assert cond, f"{name}: {detail}"


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    init_db()
    # seed master org + owner directly
    with session() as db:
        org = Organization(name="Ascendly", slug="ascendly")
        db.add(org)
        db.flush()
        u = User(email="rosis@ascendly.one", password_hash=hash_password("master-pw"))
        db.add(u)
        db.flush()
        db.add(Membership(user_id=u.id, org_id=org.id, role="owner", workspace_ids=[]))

    check("healthz", client.get("/healthz").json()["ok"])

    r = client.post("/api/auth/login", json={"email": "rosis@ascendly.one", "password": "wrong"})
    check("wrong password rejected", r.status_code == 401)

    tok = client.post("/api/auth/login", json={"email": "rosis@ascendly.one", "password": "master-pw"}).json()["token"]

    # master creates two client workspaces
    w1 = client.post("/api/admin/workspaces", json={"name": "Webaholics", "legacy_name": "Webaholics"}, headers=auth(tok)).json()
    w2 = client.post("/api/admin/workspaces", json={"name": "Shimahara"}, headers=auth(tok)).json()
    check("workspaces created", w1["id"] != w2["id"])

    # master creates a client login locked to workspace 1
    r = client.post("/api/admin/users", json={
        "email": "client@webaholics.com", "password": "client-pw", "role": "client",
        "workspace_ids": [w1["id"]]}, headers=auth(tok))
    check("client user created", r.status_code == 200, r.text)

    r = client.post("/api/admin/users", json={
        "email": "bad@x.com", "password": "x", "role": "client",
        "workspace_ids": [w1["id"], w2["id"]]}, headers=auth(tok))
    check("client with 2 workspaces rejected", r.status_code == 422)

    ctok = client.post("/api/auth/login", json={"email": "client@webaholics.com", "password": "client-pw"}).json()["token"]

    me = client.get("/api/auth/me", headers=auth(ctok)).json()
    check("client sees exactly 1 workspace (no switcher)", len(me["workspaces"]) == 1 and not me["is_master"])

    r = client.get("/api/admin/workspaces", headers=auth(ctok))
    check("client blocked from admin", r.status_code == 403)

    # master creates deals in both workspaces
    d1 = client.post("/api/deals", json={"workspace_id": w1["id"], "name": "Webaholics deal", "value": 5000}, headers=auth(tok))
    d2 = client.post("/api/deals", json={"workspace_id": w2["id"], "name": "Shimahara deal", "value": 9000}, headers=auth(tok))
    check("deals created", d1.status_code == 200 and d2.status_code == 200, d1.text + d2.text)

    # THE isolation test: client must see only their workspace's deal
    deals = client.get("/api/deals", headers=auth(ctok)).json()
    check("client sees only own deals", len(deals) == 1 and deals[0]["name"] == "Webaholics deal", str(deals))

    r = client.get("/api/deals", params={"workspace_id": w2["id"]}, headers=auth(ctok))
    check("client requesting other workspace → 403", r.status_code == 403)

    master_deals = client.get("/api/deals", headers=auth(tok)).json()
    check("master sees all workspaces' deals", len(master_deals) == 2)

    board = client.get("/api/deals/board", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    booked = [c for c in board if c["stage"]["name"] == "Opportunity"]
    check("board has default stages + totals", len(board) == 7 and booked and booked[0]["total_value"] == 5000, str(board)[:200])

    stage_meeting = next(c["stage"]["id"] for c in board if c["stage"]["name"] == "Meeting Booked")
    deal_id = booked[0]["deals"][0]["id"]
    r = client.post(f"/api/deals/{deal_id}/move", json={"stage_id": stage_meeting}, headers=auth(tok))
    check("deal moved stage", r.status_code == 200)

    summary = client.get("/api/dashboard/summary", headers=auth(ctok)).json()
    check("client dashboard summary works", summary["open_value"] == 5000 and summary["recent_activity"], str(summary)[:200])

    # ---------------- workspace aliases (the migration-mapping system)
    r = client.post("/api/admin/aliases", json={
        "workspace_id": w1["id"], "source_system": "reply_manager",
        "external_name": "Ascendly: mainreplybison"}, headers=auth(tok))
    check("alias created", r.status_code == 200, r.text)
    r2 = client.post("/api/admin/aliases", json={
        "workspace_id": w1["id"], "source_system": "enrichment", "external_name": "Ascendly"},
        headers=auth(tok))
    check("2nd alias (different source) → same workspace", r2.status_code == 200, r2.text)

    r = client.post("/api/admin/aliases", json={
        "workspace_id": w2["id"], "source_system": "reply_manager",
        "external_name": "Ascendly: mainreplybison"}, headers=auth(tok))
    check("duplicate (source, name) rejected 409", r.status_code == 409)

    r = client.post("/api/admin/aliases", json={
        "workspace_id": w1["id"], "source_system": "bogus", "external_name": "x"}, headers=auth(tok))
    check("unknown source rejected", r.status_code == 422)

    aliases = client.get("/api/admin/aliases", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    check("one workspace holds multiple aliases", len(aliases) == 2, str(aliases))

    r = client.get("/api/admin/aliases", headers=auth(ctok))
    check("client blocked from aliases", r.status_code == 403)

    # resolution honors source_system + never guesses similar names
    from app.db import SessionLocal as _SL
    from scripts.import_legacy import resolve_workspaces
    db2 = _SL()
    res = resolve_workspaces(db2, ["Ascendly: mainreplybison", "Ascendly", "Ascendlyy"], source="reply_manager")
    check("alias resolves exact name", res["Ascendly: mainreplybison"]["workspace"].id == w1["id"])
    check("enrichment-only alias NOT visible to reply_manager source",
          res["Ascendly"]["workspace"] is None)
    check("similar name is NOT guessed", res["Ascendlyy"]["workspace"] is None)
    db2.close()

    # ---------------- importer end-to-end against a fixture legacy DB
    import sqlite3 as _sq
    import tempfile as _tf
    legacy_path = _tf.mktemp(suffix=".db")
    lc = _sq.connect(legacy_path)
    lc.executescript("""
      CREATE TABLE crm_stages (id INTEGER PRIMARY KEY, name TEXT);
      INSERT INTO crm_stages VALUES (1,'Opportunity'),(2,'Meeting Booked');
      CREATE TABLE leads (id INTEGER PRIMARY KEY, workspace_name TEXT, email TEXT, name TEXT,
        company TEXT, reply_text TEXT, main_reply TEXT, replied INTEGER, thread TEXT,
        intent TEXT, confidence TEXT, campaign TEXT, created_at TIMESTAMP);
      INSERT INTO leads VALUES
        (11,'Ascendly: mainreplybison','amy@acme.com','Amy Pond','Acme Co','yes interested',
         'great, here are times',1,'[]','simple_positive','high','C1','2026-06-01 10:00:00'),
        (12,'Old Unknown Client','bob@beta.com','Bob','Beta LLC','tell me more','',0,'[]',
         'question','med','C2','2026-06-02 10:00:00');
      CREATE TABLE opportunities (id INTEGER PRIMARY KEY, workspace_name TEXT, lead_id TEXT,
        deal_name TEXT, contact_name TEXT, email TEXT, company TEXT, website TEXT,
        stage_id INTEGER, lead_intent TEXT, status TEXT, value REAL, owner TEXT,
        description TEXT, next_action_date TEXT, tag_ids TEXT, close_date TEXT, source TEXT,
        next_step TEXT, meeting_outcome TEXT, location TEXT, contact_linkedin TEXT,
        company_linkedin TEXT, created_at TIMESTAMP);
      INSERT INTO opportunities VALUES (21,'Ascendly: mainreplybison','11','Acme deal','Amy Pond',
        'amy@acme.com','Acme Co','',2,'simple_positive','hot',7500,'','','','[]','','','','','','','',
        '2026-06-03 10:00:00');
    """)
    lc.commit(); lc.close()

    from scripts.import_legacy import run_import
    # apply with an unmapped name must ABORT before writing anything
    rep = run_import(f"sqlite:///{legacy_path}", dry_run=False)
    check("apply aborts on unmapped workspace", rep["aborted"] and rep["unmapped_workspaces"] == ["Old Unknown Client"], str(rep))
    db3 = _SL()
    from app.models.crm import Contact as _C
    check("abort wrote nothing", db3.query(_C).count() == 0, str(db3.query(_C).count()))
    db3.close()

    # map the second name via alias → apply succeeds
    client.post("/api/admin/aliases", json={
        "workspace_id": w2["id"], "source_system": "reply_manager",
        "external_name": "Old Unknown Client"}, headers=auth(tok))
    rep = run_import(f"sqlite:///{legacy_path}", dry_run=False)
    check("import applied via aliases",
          not rep["aborted"] and rep["contacts_created"] == 2 and rep["deals_created"] == 1, str(rep))
    db3 = _SL()
    amy = db3.query(_C).filter(_C.email == "amy@acme.com").first()
    bob = db3.query(_C).filter(_C.email == "bob@beta.com").first()
    check("contacts landed in correct canonical workspaces",
          amy.workspace_id == w1["id"] and bob.workspace_id == w2["id"])
    rep2 = run_import(f"sqlite:///{legacy_path}", dry_run=False)
    check("re-run is idempotent", rep2["contacts_created"] == 0 and rep2["deals_created"] == 0, str(rep2))
    db3.close()

    # job queue: enqueue + run one job through the worker inline
    r = client.post("/api/jobs", json={"kind": "noop", "workspace_id": w1["id"], "payload": {"hello": 1}}, headers=auth(tok))
    check("job enqueued", r.status_code == 200, r.text)
    from app.db import SessionLocal
    from app.workers.runner import _claim, run_one
    db = SessionLocal()
    job = _claim(db)
    run_one(db, job)
    check("worker ran job", job.status == "done" and job.result.get("ok"), job.error)
    db.close()

    print(f"\n{sum(1 for _, ok in PASS if ok)}/{len(PASS)} checks passed")


if __name__ == "__main__":
    main()
