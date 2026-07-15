"""End-to-end tests for the Agreement + Invoice system.

Covers the full spec test matrix: generation from blueprint/deal, no invented
pricing, public routing + 404s, view tracking, client signing + duplicate
prevention, countersign authorization, execution locking, PDF generation/
download, version/amendment preservation, invoice generation from approved terms,
invoice totals, invoice public routing + PDF, Closed-Won automation, Client
Profile creation, idempotent reprocessing, workspace isolation, webhook payloads.

Run:  python -m tests.test_agreements   (throwaway SQLite DB)
"""
import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test_ag.db"
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import init_db, session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.agreements import Agreement, Invoice  # noqa: E402
from app.models.client_profile import ClientProfile  # noqa: E402
from app.models.crm import Company, Contact, Deal, Stage  # noqa: E402
from app.models.documents import Document  # noqa: E402
from app.models.identity import Membership, Organization, User, Workspace  # noqa: E402

client = TestClient(app)
PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond)))
    print(("✓" if cond else "✗ FAIL"), name, detail if not cond else "")
    assert cond, f"{name}: {detail}"


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def token_of(agreement_id):
    with session() as db:
        return db.get(Agreement, agreement_id).public_token


def slug_of(model, oid):
    with session() as db:
        return db.get(model, oid).slug


def main():
    init_db()

    # ---- seed org, master owner, member, two workspaces, CRM graph ----
    with session() as db:
        org = Organization(name="Ascendly", slug="ascendly")
        db.add(org); db.flush()
        owner = User(email="owner@ascendly.one", password_hash=hash_password("master-pw"))
        member = User(email="member@ascendly.one", password_hash=hash_password("member-pw"))
        db.add_all([owner, member]); db.flush()
        w1 = Workspace(org_id=org.id, name="WS One", slug="ws-one")
        w2 = Workspace(org_id=org.id, name="WS Two", slug="ws-two")
        db.add_all([w1, w2]); db.flush()
        db.add(Membership(user_id=owner.id, org_id=org.id, role="owner", workspace_ids=[]))
        db.add(Membership(user_id=member.id, org_id=org.id, role="member", workspace_ids=[w1.id]))
        # client locked to w2 (isolation)
        cli = User(email="client@wstwo.com", password_hash=hash_password("client-pw"))
        db.add(cli); db.flush()
        db.add(Membership(user_id=cli.id, org_id=org.id, role="client", workspace_ids=[w2.id]))
        # default stages for w1 (incl. Won)
        for name, color, order, won, lost in [
            ("Opportunity", "#64748b", 1, False, False), ("Meeting Booked", "#3b82f6", 2, False, False),
            ("Won", "#22c55e", 6, True, False)]:
            db.add(Stage(workspace_id=w1.id, name=name, color=color, sort_order=order, is_won=won, is_lost=lost))
        # company + contact + deal + blueprint (NO commercial → tests no-invented-pricing)
        co = Company(workspace_id=w1.id, name="Acme Media"); db.add(co); db.flush()
        ct = Contact(workspace_id=w1.id, company_id=co.id, first_name="Dana", last_name="Reed",
                     email="dana@acme.test", title="COO"); db.add(ct); db.flush()
        deal = Deal(workspace_id=w1.id, company_id=co.id, contact_id=ct.id, name="Acme engine", value=0,
                    description="Managed outbound + reply handling")
        db.add(deal); db.flush()
        bp = Document(workspace_id=w1.id, company_id=co.id, kind="blueprint", status="published",
                      published=True, slug="acme-media-bp",
                      fields={"content": {"what_we_build": ["Managed outbound", "Reply handling"],
                                          "exec_summary": "Acme wants a consistent pipeline.",
                                          "commercial": ""}})
        db.add(bp); db.flush()
        ids = dict(w1=w1.id, w2=w2.id, co=co.id, ct=ct.id, deal=deal.id, bp=bp.id)

    tok = client.post("/api/auth/login", json={"email": "owner@ascendly.one", "password": "master-pw"}).json()["token"]
    mtok = client.post("/api/auth/login", json={"email": "member@ascendly.one", "password": "member-pw"}).json()["token"]
    ctok = client.post("/api/auth/login", json={"email": "client@wstwo.com", "password": "client-pw"}).json()["token"]

    # ============================================================ generation
    g = client.post("/api/agreements/generate", json={"company_id": ids["co"], "deal_id": ids["deal"]},
                    headers=auth(tok)).json()
    check("agreement generated from blueprint/deal", g["number"].startswith("AGR-") and g["status"] == "draft", str(g)[:200])
    check("all required sections present",
          {s["key"] for s in g["sections"]} >= {"parties", "scope_of_services", "deliverables", "fees", "governing_terms"},
          str([s["key"] for s in g["sections"]]))
    check("deliverables sourced from blueprint (not invented)",
          any("Managed outbound" in s["body"] for s in g["sections"] if s["key"] == "deliverables"))
    check("NO invented pricing when none supplied",
          g["fields"]["fees"]["setup"] is None and g["fields"]["fees"]["recurring"] is None
          and "fees" in g["missing_flags"], str(g["fields"]["fees"]))
    check("missing effective_date flagged", "effective_date" in g["missing_flags"])
    agid = g["id"]

    # editing a draft works
    e = client.put(f"/api/agreements/{agid}", json={"fields": {"effective_date": "2026-08-01",
                   "governing_law": "State of Delaware"}}, headers=auth(tok)).json()
    check("editing draft clears its missing flag", "effective_date" not in e["missing_flags"])

    # ============================================================ public routing + 404
    slug = slug_of(Agreement, agid)
    r = client.get(f"/agreement/{slug}")
    check("unsent (draft) agreement is 404 publicly", r.status_code == 404)
    r = client.get("/agreement/does-not-exist")
    check("unknown agreement slug is 404", r.status_code == 404)

    # send → public visible + view tracking
    client.post(f"/api/agreements/{agid}/send", headers=auth(tok))
    r = client.get(f"/agreement/{slug}")
    check("sent agreement renders publicly with sign form", r.status_code == 200 and "Adopt" in r.text)
    v1 = client.get(f"/api/agreements/{agid}", headers=auth(tok)).json()["view_count"]
    check("view tracking counts an open", v1 >= 1, str(v1))

    # ============================================================ client signing
    token = token_of(agid)
    r = client.post(f"/agreement/{token}/sign",
                    data={"name": "Dana Reed", "email": "dana@acme.test", "title": "COO",
                          "consent": "yes", "consent_text": "I agree"})
    check("client can sign on the public page", r.status_code == 200 and "recorded" in r.text.lower(), r.text[:160])
    a = client.get(f"/api/agreements/{agid}", headers=auth(tok)).json()
    check("agreement status is client_signed", a["status"] == "client_signed" and a["client_signed_at"])
    # duplicate sign prevented
    r = client.post(f"/agreement/{token}/sign",
                    data={"name": "Someone Else", "email": "x@y.z", "consent": "yes"})
    check("duplicate signing prevented", r.status_code == 409)
    # consent required
    r2 = client.post(f"/api/agreements/generate", json={"company_id": ids["co"]}, headers=auth(tok)).json()
    client.post(f"/api/agreements/{r2['id']}/send", headers=auth(tok))
    tok2 = token_of(r2["id"])
    rc = client.post(f"/agreement/{tok2}/sign", data={"name": "No Consent", "email": "n@c.z"})
    check("signing without consent rejected", rc.status_code == 400)

    # ============================================================ countersign authorization
    r = client.post(f"/api/agreements/{agid}/countersign",
                    json={"name": "Rosis Owner", "title": "Founder"}, headers=auth(mtok))
    check("member (non-master) cannot countersign", r.status_code == 403, r.text[:120])
    r = client.post(f"/api/agreements/{agid}/countersign",
                    json={"name": "Rosis Owner", "title": "Founder"}, headers=auth(tok))
    check("master can countersign → executed", r.status_code == 200 and r.json()["status"] == "executed", r.text[:160])
    a = r.json()
    check("execution set checksum + executed_at + locked", a["checksum"] and a["executed_at"] and a["locked"])

    # ============================================================ execution locking
    r = client.put(f"/api/agreements/{agid}", json={"title": "hacked"}, headers=auth(tok))
    check("executed agreement is locked against edits", r.status_code == 409, r.text[:120])
    # duplicate countersign prevented
    r = client.post(f"/api/agreements/{agid}/countersign", json={"name": "Again"}, headers=auth(tok))
    check("duplicate countersign prevented", r.status_code == 409)

    # ============================================================ Closed-Won automation + profile
    with session() as db:
        d = db.get(Deal, ids["deal"])
        won = db.query(Stage).filter(Stage.workspace_id == ids["w1"], Stage.is_won == True).first()  # noqa: E712
        prof = db.query(ClientProfile).filter(ClientProfile.company_id == ids["co"]).first()
        check("executed → deal moved to Won", d.stage_id == won.id)
        check("executed → client profile created + active", prof is not None and prof.is_active_client)
    # idempotency: re-run execute internally must not duplicate
    with session() as db:
        from app.agreements import service as svc
        ag_obj = db.get(Agreement, agid)
        before = db.query(ClientProfile).filter(ClientProfile.company_id == ids["co"]).count()
        svc.execute(db, ag_obj)  # no-op
        after = db.query(ClientProfile).filter(ClientProfile.company_id == ids["co"]).count()
        check("execute is idempotent (no duplicate profile)", before == after == 1)

    # ============================================================ PDFs
    r = client.get(f"/api/agreements/{agid}/pdf?mode=executed", headers=auth(tok))
    check("executed agreement PDF downloads", r.status_code == 200 and r.content[:4] == b"%PDF"
          and int(r.headers.get("content-length", len(r.content))) > 1500, str(r.status_code))
    r = client.get(f"/agreement/{slug}/pdf")
    check("public executed agreement PDF downloads", r.status_code == 200 and r.content[:4] == b"%PDF")
    r = client.get("/agreement/does-not-exist/pdf")
    check("public PDF 404 for unknown/undexecuted", r.status_code == 404)

    # ============================================================ versioning / amendment
    nv = client.post(f"/api/agreements/{agid}/version", headers=auth(tok)).json()
    check("new version is a fresh draft v2", nv["version"] == 2 and nv["status"] == "draft" and nv["supersedes_id"] == agid)
    old = client.get(f"/api/agreements/{agid}", headers=auth(tok)).json()
    check("original executed version preserved + locked", old["status"] == "executed" and old["locked"])
    vers = client.get(f"/api/agreements/{agid}/versions", headers=auth(tok)).json()
    check("version history lists both versions", len(vers) == 2)

    # ============================================================ invoice from approved terms
    # a priced agreement (fees supplied via overrides — real numbers, not invented)
    pg = client.post("/api/agreements/generate", json={"company_id": ids["co"], "deal_id": ids["deal"],
         "overrides": {"fees": {"setup": 2000, "recurring": 1500, "currency": "USD"},
                       "effective_date": "2026-08-01", "governing_law": "Delaware"}},
         headers=auth(tok)).json()
    check("priced agreement has structured fees + no fees flag",
          pg["fields"]["fees"]["setup"] == 2000 and "fees" not in pg["missing_flags"])
    inv = client.post(f"/api/agreements/{pg['id']}/invoice", json={}, headers=auth(tok)).json()
    check("invoice generated from approved agreement terms",
          len(inv["line_items"]) == 2 and inv["agreement_id"] == pg["id"], str(inv)[:200])
    check("invoice totals correct (2000+1500=3500)", inv["subtotal"] == 3500 and inv["total"] == 3500, str(inv)[:160])
    invid = inv["id"]
    # tax + discount recompute
    ei = client.put(f"/api/invoices/{invid}", json={"tax_rate": 10, "discount_amount": 500}, headers=auth(tok)).json()
    check("invoice tax/discount recompute (3000*1.10=3300)", ei["total"] == 3300 and ei["tax_amount"] == 300, str(ei)[:160])

    # ============================================================ invoice public routing + PDF
    islug = slug_of(Invoice, invid)
    r = client.get(f"/invoice/{islug}")
    check("draft invoice is 404 publicly", r.status_code == 404)
    client.post(f"/api/invoices/{invid}/issue", headers=auth(tok))
    r = client.get(f"/invoice/{islug}")
    check("issued invoice renders publicly", r.status_code == 200 and "Invoice" in r.text)
    iv = client.get(f"/api/invoices/{invid}", headers=auth(tok)).json()
    check("invoice view tracked", iv["view_count"] >= 1)
    r = client.get(f"/invoice/{islug}/pdf")
    check("public invoice PDF downloads", r.status_code == 200 and r.content[:4] == b"%PDF")
    r = client.get(f"/api/invoices/{invid}/pdf", headers=auth(tok))
    check("internal invoice PDF downloads", r.status_code == 200 and r.content[:4] == b"%PDF")

    # ============================================================ payment status
    client.post(f"/api/invoices/{invid}/payment", json={"amount_paid": 1000}, headers=auth(tok))
    iv = client.get(f"/api/invoices/{invid}", headers=auth(tok)).json()
    check("partial payment → partially_paid", iv["status"] == "partially_paid" and iv["balance_due"] == 2300, str(iv)[:160])
    client.post(f"/api/invoices/{invid}/payment", json={"amount_paid": 3300}, headers=auth(tok))
    iv = client.get(f"/api/invoices/{invid}", headers=auth(tok)).json()
    check("full payment → paid, zero balance", iv["status"] == "paid" and iv["balance_due"] == 0)

    # ============================================================ workspace isolation
    r = client.get(f"/api/agreements/{agid}", headers=auth(ctok))
    check("client in another workspace cannot read the agreement", r.status_code == 404, str(r.status_code))
    r = client.get(f"/api/invoices/{invid}", headers=auth(ctok))
    check("client in another workspace cannot read the invoice", r.status_code == 404)
    r = client.get("/api/agreements", params={"workspace_id": ids["w1"]}, headers=auth(ctok))
    check("cross-workspace agreement list is refused", r.status_code == 403)

    # ============================================================ webhook payloads (no secrets)
    from app.agreements import webhooks
    with session() as db:
        ap = webhooks.agreement_payload("agreement.executed", db.get(Agreement, agid))
        ip = webhooks.invoice_payload("invoice.issued", db.get(Invoice, invid))
    check("agreement webhook payload carries ids/status/url, no token",
          ap["agreement_id"] == agid and ap["status"] == "executed" and "public_url" in ap
          and "public_token" not in ap and "checksum" in ap)
    check("invoice webhook payload carries totals + url, no token",
          ip["invoice_id"] == invid and ip["total"] == 3300 and "public_url" in ip and "public_token" not in ip)

    print(f"\n{sum(1 for _, ok in PASS if ok)}/{len(PASS)} checks passed")


if __name__ == "__main__":
    main()
