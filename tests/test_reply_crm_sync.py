"""Two-way CRM ↔ Reply status sync + Processing cleanup.

- CRM deal stage change (drag/drawer) reflects on the matching ReplyLead.
- ReplyLead stage change (Mark booked / No Show) moves the CRM deal.
- Processing view drops done jobs older than 2h, keeps active + recent.

Run:  python -m tests.test_reply_crm_sync
"""
import os
import tempfile
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test_sync.db"
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import init_db, session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.crm import Company, Contact, Deal, Stage  # noqa: E402
from app.models.identity import Membership, Organization, User, Workspace  # noqa: E402
from app.models.jobs import Job  # noqa: E402
from app.models.reply import ReplyLead  # noqa: E402

client = TestClient(app)
PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond)))
    print(("✓" if cond else "✗ FAIL"), name, detail if not cond else "")
    assert cond, f"{name}: {detail}"


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def main():
    init_db()
    with session() as db:
        org = Organization(name="Ascendly", slug="ascendly"); db.add(org); db.flush()
        owner = User(email="owner@a.one", password_hash=hash_password("master-pw")); db.add(owner); db.flush()
        w1 = Workspace(org_id=org.id, name="WS1", slug="ws1"); db.add(w1); db.flush()
        db.add(Membership(user_id=owner.id, org_id=org.id, role="owner", workspace_ids=[]))
        for name, order, won, lost in [("Opportunity", 1, False, False), ("Meeting Booked", 2, False, False),
                                       ("Meeting Completed", 3, False, False), ("No Show", 4, False, False),
                                       ("Follow-up", 5, False, False), ("Won", 6, True, False), ("Lost", 7, False, True)]:
            db.add(Stage(workspace_id=w1.id, name=name, sort_order=order, is_won=won, is_lost=lost))
        co = Company(workspace_id=w1.id, name="Acme"); db.add(co); db.flush()
        ct = Contact(workspace_id=w1.id, company_id=co.id, first_name="Dana", last_name="Reed",
                     email="dana@acme.test"); db.add(ct); db.flush()
        booked = db.query(Stage).filter(Stage.workspace_id == w1.id, Stage.name == "Meeting Booked").first()
        deal = Deal(workspace_id=w1.id, company_id=co.id, contact_id=ct.id, name="Acme deal",
                    stage_id=booked.id); db.add(deal); db.flush()
        # a matching reply lead (same email) — as if it came from the reply pipeline
        rl = ReplyLead(workspace_id=w1.id, email="dana@acme.test", name="Dana Reed",
                       company="Acme", intent="positive_simple", stage="replied", replied=True)
        db.add(rl); db.flush()
        ids = dict(w1=w1.id, co=co.id, ct=ct.id, deal=deal.id, rl=rl.id,
                   noshow=db.query(Stage).filter(Stage.workspace_id == w1.id, Stage.name == "No Show").first().id,
                   won=db.query(Stage).filter(Stage.workspace_id == w1.id, Stage.name == "Won").first().id,
                   booked=booked.id)

    tok = client.post("/api/auth/login", json={"email": "owner@a.one", "password": "master-pw"}).json()["token"]

    # ---- CRM → Reply: move the deal to No Show → reply lead reflects it ----
    r = client.post(f"/api/deals/{ids['deal']}/move", json={"stage_id": ids["noshow"]}, headers=auth(tok))
    check("deal move to No Show ok", r.status_code == 200, r.text[:120])
    with session() as db:
        check("CRM No Show synced to reply lead", db.get(ReplyLead, ids["rl"]).stage == "no_show")

    # move to Won → reply lead becomes won
    client.post(f"/api/deals/{ids['deal']}/move", json={"stage_id": ids["won"]}, headers=auth(tok))
    with session() as db:
        check("CRM Won synced to reply lead", db.get(ReplyLead, ids["rl"]).stage == "won")

    # ---- Reply → CRM: mark the reply lead booked → deal moves to Meeting Booked ----
    # (won→booked is a downgrade for a non-won target, but Meeting Booked has lower
    #  sort order than Won, so the guard keeps Won. Use a fresh lead/contact instead.)
    with session() as db:
        c2 = Contact(workspace_id=ids["w1"], first_name="Sam", last_name="Lee", email="sam@beta.test"); db.add(c2); db.flush()
        rl2 = ReplyLead(workspace_id=ids["w1"], email="sam@beta.test", name="Sam Lee", company="Beta",
                        intent="positive_simple", stage="replied"); db.add(rl2); db.flush()
        rl2_id = rl2.id
    r = client.post(f"/api/reply/leads/{rl2_id}/action", json={"stage": "booked"}, headers=auth(tok))
    check("reply mark booked ok", r.status_code == 200, r.text[:120])
    with session() as db:
        d2 = db.query(Deal).join(Contact, Deal.contact_id == Contact.id).filter(Contact.email == "sam@beta.test").first()
        st = db.get(Stage, d2.stage_id) if d2 else None
        check("reply booked created/moved CRM deal to Meeting Booked", st and st.name == "Meeting Booked", str(st and st.name))

    # ---- Processing cleanup: old done job drops, recent + active stay ----
    with session() as db:
        old = Job(kind="process_reply", workspace_id=ids["w1"], status="done",
                  finished_at=datetime.utcnow() - timedelta(hours=5), payload={"reply_workspace": "X"})
        recent = Job(kind="process_reply", workspace_id=ids["w1"], status="done",
                     finished_at=datetime.utcnow() - timedelta(minutes=10), payload={"reply_workspace": "X"})
        pending = Job(kind="process_reply", workspace_id=ids["w1"], status="pending",
                      run_at=datetime.utcnow() + timedelta(minutes=5), payload={"reply_workspace": "X"})
        db.add_all([old, recent, pending]); db.flush()
        old_id, recent_id, pending_id = old.id, recent.id, pending.id
    pr = client.get("/api/reply/processing", params={"workspace_id": ids["w1"]}, headers=auth(tok)).json()
    shown = {j["id"] for j in pr["jobs"]}
    check("old done job (5h) drops off processing", old_id not in shown)
    check("recent done job (10m) stays", recent_id in shown)
    check("pending job stays", pending_id in shown)

    # ---- edit reply lead → syncs to CRM contact/company ----
    with session() as db:
        c3 = Contact(workspace_id=ids["w1"], first_name="Old", last_name="Name", email="edit@acme.test"); db.add(c3); db.flush()
        rl3 = ReplyLead(workspace_id=ids["w1"], email="edit@acme.test", name="Old Name", company="OldCo",
                        intent="pricing_question", stage="replied"); db.add(rl3); db.flush()
        rl3_id, c3_id = rl3.id, c3.id
    r = client.put(f"/api/reply/leads/{rl3_id}", json={"name": "New Name", "title": "VP Sales",
                   "location": "Austin", "website": "acme.io"}, headers=auth(tok))
    check("edit reply lead ok", r.status_code == 200, r.text[:120])
    with session() as db:
        c = db.get(Contact, c3_id)
        check("edit synced name+title to CRM contact", c.first_name == "New" and c.title == "VP Sales", f"{c.first_name}/{c.title}")
        rl = db.get(ReplyLead, rl3_id)
        check("edit stored rich details on lead", (rl.lead_data or {}).get("location") == "Austin")

    # ---- delete + block → lead gone, sender blocked, future reply auto-stops ----
    with session() as db:
        rl4 = ReplyLead(workspace_id=ids["w1"], email="spam@bad.test", name="Spammy", stage="replied"); db.add(rl4); db.flush()
        rl4_id = rl4.id
    r = client.delete(f"/api/reply/leads/{rl4_id}?block=true", headers=auth(tok))
    check("delete + block ok", r.status_code == 200 and r.json()["blocked"], r.text[:120])
    with session() as db:
        check("reply lead deleted", db.get(ReplyLead, rl4_id) is None)
        bl = client.get("/api/reply/blocklist", params={"workspace_id": ids["w1"]}, headers=auth(tok)).json()
        check("sender on blocklist", any(b["email"] == "spam@bad.test" for b in bl), str(bl)[:120])
        from app.reply.sync import is_blocked
        check("is_blocked true for blocked email", is_blocked(db, ids["w1"], "spam@bad.test"))
        check("is_blocked false for other email", not is_blocked(db, ids["w1"], "ok@good.test"))

    # ---- stop-type label (out of office) halts without a pipeline move ----
    with session() as db:
        rl5 = ReplyLead(workspace_id=ids["w1"], email="ooo@x.test", name="OOO", stage="replied"); db.add(rl5); db.flush()
        rl5_id = rl5.id
    client.post(f"/api/reply/leads/{rl5_id}/action", json={"stage": "out_of_office"}, headers=auth(tok))
    with session() as db:
        rl = db.get(ReplyLead, rl5_id)
        check("out_of_office label sets action=stop", rl.action == "stop" and rl.stage == "out_of_office")

    print(f"\n{sum(1 for _, ok in PASS if ok)}/{len(PASS)} checks passed")


if __name__ == "__main__":
    main()
