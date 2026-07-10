"""Migrate data from the existing Reply Manager database into RevCadence.

What it maps (read-only against the legacy DB — it never writes there):
  legacy workspaces (name strings)  → Workspace (matched via Workspace.legacy_name)
  legacy leads                      → Contact (deduped by email per workspace)
                                      + Company (from the lead's company name)
                                      + Activity timeline (their reply, our reply,
                                        full thread JSON preserved in data)
  legacy opportunities + crm_stages → Deal (stage matched by stage NAME)

Usage:
  1) Dry run (default — prints what would happen, writes nothing):
       python -m scripts.import_legacy --legacy-db-url postgresql://...
  2) Apply:
       python -m scripts.import_legacy --legacy-db-url postgresql://... --apply
  3) Create missing workspaces automatically (org id required):
       ... --apply --create-missing --org-id 1

Idempotent: legacy ids are stored on the new rows (legacy_lead_ids,
legacy_opportunity_id), so re-running skips anything already imported.
"""
import argparse
import json
from datetime import datetime

from sqlalchemy import create_engine, text

from app.db import init_db, session
from app.models.crm import DEFAULT_STAGES, Activity, Company, Contact, Deal, Stage
from app.models.identity import Workspace


def _norm_url(url: str) -> str:
    return url.replace("postgres://", "postgresql://", 1) if url.startswith("postgres://") else url


def _rows(conn, sql):
    return [dict(r._mapping) for r in conn.execute(text(sql))]


def _get_or_create_workspace(db, name, org_id, create_missing, report):
    ws = db.query(Workspace).filter(Workspace.legacy_name == name).first()
    if ws:
        return ws
    if not create_missing:
        report["unmapped_workspaces"].add(name)
        return None
    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    ws = Workspace(org_id=org_id, name=name, slug=slug, legacy_name=name)
    db.add(ws)
    db.flush()
    for sname, color, order, won, lost in DEFAULT_STAGES:
        db.add(Stage(workspace_id=ws.id, name=sname, color=color, sort_order=order, is_won=won, is_lost=lost))
    report["workspaces_created"] += 1
    return ws


def run_import(legacy_db_url: str, dry_run: bool = True, create_missing: bool = False, org_id: int = 0) -> dict:
    if not legacy_db_url:
        raise SystemExit("--legacy-db-url is required (the old Reply Manager DATABASE_URL)")
    legacy = create_engine(_norm_url(legacy_db_url))
    init_db()
    report = {"leads_seen": 0, "contacts_created": 0, "contacts_merged": 0, "companies_created": 0,
              "activities_created": 0, "deals_created": 0, "deals_skipped_existing": 0,
              "workspaces_created": 0, "unmapped_workspaces": set(), "dry_run": dry_run}

    with legacy.connect() as lconn, session() as db:
        old_stages = {s["id"]: s["name"] for s in _rows(lconn, "SELECT id, name FROM crm_stages")}

        # ---------------- leads → contacts/companies/activities
        for lead in _rows(lconn, "SELECT * FROM leads ORDER BY id"):
            report["leads_seen"] += 1
            ws = _get_or_create_workspace(db, lead["workspace_name"], org_id, create_missing, report)
            if ws is None:
                continue
            email = (lead.get("email") or "").lower().strip()
            contact = None
            if email:
                contact = db.query(Contact).filter(Contact.workspace_id == ws.id, Contact.email == email).first()
            already = contact and lead["id"] in (contact.legacy_lead_ids or [])
            if already:
                continue

            company = None
            cname = (lead.get("company") or "").strip()
            if cname:
                company = db.query(Company).filter(Company.workspace_id == ws.id, Company.name == cname).first()
                if not company:
                    company = Company(workspace_id=ws.id, name=cname)
                    db.add(company)
                    db.flush()
                    report["companies_created"] += 1

            full = (lead.get("name") or "").strip()
            first, _, last = full.partition(" ")
            if contact is None:
                contact = Contact(workspace_id=ws.id, company_id=company.id if company else None,
                                  email=email, first_name=first, last_name=last,
                                  source="cold_email", legacy_lead_ids=[lead["id"]])
                db.add(contact)
                db.flush()
                report["contacts_created"] += 1
            else:
                contact.legacy_lead_ids = (contact.legacy_lead_ids or []) + [lead["id"]]
                if company and not contact.company_id:
                    contact.company_id = company.id
                report["contacts_merged"] += 1

            occurred = lead.get("created_at") or datetime.utcnow()
            if lead.get("reply_text"):
                db.add(Activity(workspace_id=ws.id, contact_id=contact.id, company_id=contact.company_id,
                                kind="email_in", title=f"Reply · intent: {lead.get('intent') or 'unknown'}",
                                body=lead["reply_text"], occurred_at=occurred,
                                data={"legacy_lead_id": lead["id"], "intent": lead.get("intent"),
                                      "confidence": lead.get("confidence"), "campaign": lead.get("campaign")}))
                report["activities_created"] += 1
            if lead.get("main_reply"):
                db.add(Activity(workspace_id=ws.id, contact_id=contact.id, company_id=contact.company_id,
                                kind="email_out" if lead.get("replied") else "reply_drafted",
                                title="Our reply (sent)" if lead.get("replied") else "Our reply (draft)",
                                body=lead["main_reply"], occurred_at=occurred,
                                data={"legacy_lead_id": lead["id"]}))
                report["activities_created"] += 1
            thread = lead.get("thread")
            if thread:
                try:
                    tdata = json.loads(thread) if isinstance(thread, str) else thread
                except Exception:
                    tdata = None
                if tdata:
                    db.add(Activity(workspace_id=ws.id, contact_id=contact.id, kind="import",
                                    title="Full legacy thread", occurred_at=occurred,
                                    data={"legacy_lead_id": lead["id"], "thread": tdata}))
                    report["activities_created"] += 1

        # ---------------- opportunities → deals
        for opp in _rows(lconn, "SELECT * FROM opportunities ORDER BY id"):
            ws = _get_or_create_workspace(db, opp["workspace_name"], org_id, create_missing, report)
            if ws is None:
                continue
            if db.query(Deal).filter(Deal.workspace_id == ws.id,
                                     Deal.legacy_opportunity_id == opp["id"]).first():
                report["deals_skipped_existing"] += 1
                continue
            stage_name = old_stages.get(opp.get("stage_id"))
            stage = (db.query(Stage).filter(Stage.workspace_id == ws.id, Stage.name == stage_name).first()
                     if stage_name else None)
            email = (opp.get("email") or "").lower().strip()
            contact = (db.query(Contact).filter(Contact.workspace_id == ws.id, Contact.email == email).first()
                       if email else None)
            company = None
            if opp.get("company"):
                company = db.query(Company).filter(Company.workspace_id == ws.id,
                                                   Company.name == opp["company"].strip()).first()
            d = Deal(workspace_id=ws.id, legacy_opportunity_id=opp["id"],
                     name=opp.get("deal_name") or opp.get("contact_name") or opp.get("company") or "Imported deal",
                     contact_id=contact.id if contact else None,
                     company_id=company.id if company else None,
                     stage_id=stage.id if stage else None,
                     value=float(opp.get("value") or 0), lead_intent=opp.get("lead_intent") or "",
                     status_label=opp.get("status") or "", source=opp.get("source") or "legacy_crm",
                     next_step=opp.get("next_step") or "", next_action_date=opp.get("next_action_date") or "",
                     close_date=opp.get("close_date") or "", meeting_outcome=opp.get("meeting_outcome") or "",
                     description=opp.get("description") or "")
            db.add(d)
            db.flush()
            db.add(Activity(workspace_id=ws.id, deal_id=d.id, contact_id=d.contact_id, kind="import",
                            title="Imported from legacy CRM", data={"legacy_opportunity_id": opp["id"]}))
            report["deals_created"] += 1

        report["unmapped_workspaces"] = sorted(report["unmapped_workspaces"])
        if dry_run:
            db.rollback()
            print("DRY RUN — nothing written. Re-run with --apply to commit.")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-db-url", required=True)
    ap.add_argument("--apply", action="store_true", help="actually write (default is dry run)")
    ap.add_argument("--create-missing", action="store_true",
                    help="auto-create workspaces for unmapped legacy names")
    ap.add_argument("--org-id", type=int, default=0, help="org to create workspaces under")
    args = ap.parse_args()
    if args.create_missing and not args.org_id:
        raise SystemExit("--create-missing requires --org-id")
    report = run_import(args.legacy_db_url, dry_run=not args.apply,
                        create_missing=args.create_missing, org_id=args.org_id)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
