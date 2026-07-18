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

    # ---------------- bootstrap deadlock fix: works ONLY on an empty users table
    r = client.post("/api/auth/bootstrap", json={
        "org": "Bootstrap Co", "email": "boot@x.com", "password": "a-long-password-123"})
    check("bootstrap works when no users exist", r.status_code == 200 and r.json()["role"] == "owner", r.text)
    r = client.post("/api/auth/login", json={"email": "boot@x.com", "password": "a-long-password-123"})
    check("bootstrapped admin can log in", r.status_code == 200)
    r = client.post("/api/auth/bootstrap", json={
        "org": "Evil Co", "email": "evil@x.com", "password": "another-long-password"})
    check("bootstrap permanently 403 once users exist", r.status_code == 403)

    # deactivate the bootstrap user so the rest of the suite runs unchanged
    with session() as db:
        bu = db.query(User).filter(User.email == "boot@x.com").first()
        bu.active = False

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

    # ---------------- enrichment engine E2E (demo mode, no network)
    FAKE_HTML = """<html><head><title>Acme Landscaping — Commercial Grounds</title>
      <meta name="description" content="Acme provides commercial landscaping for businesses across Utah.">
      </head><body><p>We offer commercial mowing, snow removal and grounds care.
      Our clients are businesses, HOAs and property management companies.</p></body></html>"""

    co = client.post("/api/companies", json={"workspace_id": w1["id"], "name": "Acme Landscaping",
                                             "website": "acme-landscaping.example"}, headers=auth(tok)).json()
    ct = client.post("/api/contacts", json={"workspace_id": w1["id"], "email": "jane@acme.example",
                                            "first_name": "Jane", "last_name": "Doe",
                                            "title": "Founder & CEO", "company_id": co["id"]},
                     headers=auth(tok)).json()
    r = client.post("/api/enrich", json={"workspace_id": w1["id"], "company_ids": [co["id"]],
                                         "contact_ids": [ct["id"]], "html_override": FAKE_HTML},
                    headers=auth(tok))
    check("enrichment jobs queued", r.status_code == 200 and r.json()["queued"] == 2, r.text)

    r = client.post("/api/enrich", json={"workspace_id": w2["id"], "company_ids": [co["id"]]}, headers=auth(tok))
    check("cross-workspace enrich rejected", r.status_code == 404)

    from app.db import SessionLocal as _SL2
    from app.workers.runner import _claim as _claim2, run_one as _run2
    dbw = _SL2()
    for _ in range(3):
        jb = _claim2(dbw)
        if jb:
            _run2(dbw, jb)
    dbw.close()

    cdet = client.get(f"/api/companies/{co['id']}", headers=auth(tok)).json()
    check("company enriched (industry + icp + provenance)",
          cdet["industry"] and cdet["icp_fit"] and "last_crawl" in cdet["enrichment"], str(cdet)[:200])
    tdet = client.get(f"/api/contacts/{ct['id']}", headers=auth(tok)).json()
    check("contact scored (senior founder + valid company)", (tdet["revenue_score"] or 0) >= 60, str(tdet)[:200])

    jid = r2j = client.post("/api/blueprints/generate", json={"workspace_id": w1["id"],
                                                              "company_id": co["id"], "contact_id": ct["id"]},
                            headers=auth(tok)).json()["job_id"]
    dbw = _SL2()
    jb = _claim2(dbw)
    _run2(dbw, jb)
    dbw.close()
    st = client.get(f"/api/jobs/{jid}/status", headers=auth(tok)).json()
    check("blueprint job done with progress", st["status"] == "done" and st["result"].get("document_id"), str(st)[:200])
    doc = client.get(f"/api/documents/{st['result']['document_id']}", headers=auth(tok)).json()
    check("blueprint document generated",
          doc["kind"] == "blueprint" and "Acme Landscaping" in doc["html"] and "Executive Summary" in doc["html"])

    docs_client = client.get("/api/documents", headers=auth(ctok)).json()
    check("client sees only own-workspace documents", all(d["workspace_id"] == w1["id"] for d in docs_client))

    # --- custom blueprint upload: BYO HTML → its own slug + public link, like a generated one
    up = client.post("/api/blueprints/upload", json={
        "workspace_id": w1["id"], "title": "Acme Custom Page",
        "html": "<!doctype html><html><body><h1>Custom Landing</h1></body></html>"}, headers=auth(tok)).json()
    check("custom blueprint uploaded", up["kind"] == "blueprint" and up["slug"] and up["fields"].get("generator") == "uploaded", str(up)[:200])
    pub = client.put(f"/api/documents/{up['id']}", json={"published": True}, headers=auth(tok)).json()
    page = client.get(f"/p/{pub['slug']}")
    check("uploaded blueprint served on public link", page.status_code == 200 and "Custom Landing" in page.text, f"{page.status_code}")
    rep = client.post("/api/blueprints/upload", json={
        "doc_id": up["id"], "html": "<!doctype html><html><body><h1>Replaced</h1></body></html>"}, headers=auth(tok)).json()
    check("uploaded blueprint HTML replaced in place", rep["slug"] == up["slug"] and "Replaced" in rep["html"], str(rep)[:160])

    # --- manual CRM entry: add a company, a contact, then a deal (website/referral lead path)
    co = client.post("/api/companies", json={"workspace_id": w1["id"], "name": "Website Lead Co", "website": "weblead.com"}, headers=auth(tok)).json()
    ct = client.post("/api/contacts", json={"workspace_id": w1["id"], "first_name": "Web", "last_name": "Lead",
                                            "email": "web@weblead.com", "title": "Founder", "company_id": co["id"]}, headers=auth(tok)).json()
    check("manual contact created", bool(ct.get("id")), str(ct)[:160])
    contacts_now = client.get("/api/contacts", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    mine = next((c for c in contacts_now if c["id"] == ct["id"]), None)
    check("new contact starts as 'No deal'", mine and mine["status"]["key"] == "none", str(mine)[:160])
    nd = client.post("/api/deals", json={"workspace_id": w1["id"], "name": "Web Lead deal", "company_id": co["id"],
                                         "contact_id": ct["id"], "stage_id": stage_meeting, "value": 4200}, headers=auth(tok)).json()
    check("manual deal created", bool(nd.get("id")), str(nd)[:160])
    contacts_after = client.get("/api/contacts", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    mine2 = next((c for c in contacts_after if c["id"] == ct["id"]), None)
    check("contact now shows Meeting Booked after deal", mine2 and mine2["status"]["key"] == "meeting_booked", str(mine2)[:160])
    upco = client.post("/api/blueprints/upload", json={"workspace_id": w1["id"], "company_id": co["id"],
                                                       "html": "<h1>Co Blueprint</h1>"}, headers=auth(tok)).json()
    check("blueprint upload tied to company", upco["company_id"] == co["id"] and upco["fields"].get("generator") == "uploaded", str(upco)[:160])

    # documents filtered by company + surfaced on the company hub
    codocs = client.get("/api/documents", params={"company_id": co["id"]}, headers=auth(tok)).json()
    check("documents filter by company", len(codocs) == 1 and codocs[0]["id"] == upco["id"] and codocs[0]["public_path"], str(codocs)[:160])
    codetail = client.get(f"/api/companies/{co['id']}", headers=auth(tok)).json()
    check("company hub carries documents + status", codetail.get("documents") and codetail["documents"][0]["id"] == upco["id"]
          and codetail.get("status", {}).get("key") == "meeting_booked", str(codetail.get("status"))[:120])

    # one-shot lead: new company + new contact + deal all created together
    lead = client.post("/api/leads", json={"workspace_id": w1["id"], "company_name": "Referral Inc",
                                            "first_name": "Ref", "last_name": "Lead", "email": "ref@referral.com",
                                            "title": "COO", "stage_id": stage_meeting, "value": 3000}, headers=auth(tok)).json()
    check("lead created company+contact+deal", lead.get("deal_id") and lead.get("company_id") and lead.get("contact_id"), str(lead)[:160])
    lead_contacts = client.get("/api/contacts", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    lc = next((c for c in lead_contacts if c["id"] == lead["contact_id"]), None)
    check("lead contact shows in Contacts as Meeting Booked",
          lc and lc["status"]["key"] == "meeting_booked" and lc["company_name"] == "Referral Inc", str(lc)[:160])

    # ---- password reset (forgot + owner reset-link + reset) ----
    ru = client.post("/api/admin/users", json={"email": "reset@webaholics.com", "password": "old-password-1234",
                     "role": "client", "workspace_ids": [w1["id"]]}, headers=auth(tok)).json()
    check("reset test user created", bool(ru.get("id")), str(ru)[:120])
    fg = client.post("/api/auth/forgot", json={"email": "reset@webaholics.com"})
    check("forgot returns generic ok", fg.status_code == 200 and fg.json()["ok"])
    fg2 = client.post("/api/auth/forgot", json={"email": "nobody@nowhere.test"})
    check("forgot does not reveal unknown accounts", fg2.status_code == 200 and fg2.json()["ok"])
    rl = client.post(f"/api/admin/users/{ru['id']}/reset-link", headers=auth(tok)).json()
    token = rl["reset_path"].split("/reset/")[-1]
    check("owner gets a reset link", "/reset/" in rl["reset_path"] and token)
    bad = client.post("/api/auth/reset", json={"token": "not-a-real-token", "password": "brand-new-password-1"})
    check("invalid reset token rejected", bad.status_code == 400)
    short = client.post("/api/auth/reset", json={"token": token, "password": "short"})
    check("short new password rejected", short.status_code == 422)
    ok = client.post("/api/auth/reset", json={"token": token, "password": "brand-new-password-1"})
    check("reset with valid token succeeds", ok.status_code == 200)
    li = client.post("/api/auth/login", json={"email": "reset@webaholics.com", "password": "brand-new-password-1"})
    check("can log in with the new password", li.status_code == 200 and li.json().get("token"))
    reuse = client.post("/api/auth/reset", json={"token": token, "password": "another-new-password-9"})
    check("reset token is one-time (reuse fails)", reuse.status_code == 400)

    print(f"\n{sum(1 for _, ok in PASS if ok)}/{len(PASS)} checks passed")


if __name__ == "__main__":
    main()
