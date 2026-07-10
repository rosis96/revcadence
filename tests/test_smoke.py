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
