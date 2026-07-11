"""Migrate data from the existing Reply Manager database into RevCadence.

What it maps (read-only against the legacy DB — it never writes there):
  legacy workspaces (name strings)  → Workspace, resolved via WorkspaceAlias
    (source_system='reply_manager', exact external_name match — the source of
    truth). Workspace.legacy_name is only a backward-compat fallback. Names are
    NEVER guessed from similarity. A pre-flight mapping review prints every
    MAPPED/UNMAPPED name before any write; --apply ABORTS if anything is
    unmapped. Future importers (enrichment, client_portals) use the same
    resolve_workspaces() with their own source_system.
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
from app.models.identity import Workspace, WorkspaceAlias

SOURCE = "reply_manager"  # this importer's source_system for alias lookups


def _norm_url(url: str) -> str:
    return url.replace("postgres://", "postgresql://", 1) if url.startswith("postgres://") else url


def _rows(conn, sql):
    return [dict(r._mapping) for r in conn.execute(text(sql))]


def _to_dt(value):
    """Coerce a legacy timestamp (datetime from Postgres, string from SQLite,
    or None) to a datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        for candidate in (value.replace(" ", "T", 1), value):
            try:
                return datetime.fromisoformat(candidate)
            except ValueError:
                pass
    return datetime.utcnow()


def resolve_workspaces(db, names, source=SOURCE):
    """Resolve legacy workspace names → canonical Workspace via WorkspaceAlias
    (source of truth). Falls back to Workspace.legacy_name for backward
    compatibility. NEVER guesses from similar names — an unresolved name stays
    unresolved until a human creates the alias."""
    out = {}
    for name in sorted(set(names)):
        alias = (db.query(WorkspaceAlias)
                 .filter(WorkspaceAlias.source_system == source,
                         WorkspaceAlias.external_name == name).first())
        if alias:
            out[name] = {"workspace": db.get(Workspace, alias.workspace_id), "via": "alias"}
            continue
        legacy = db.query(Workspace).filter(Workspace.legacy_name == name).first()
        out[name] = {"workspace": legacy, "via": "legacy_name" if legacy else None}
    return out


def _create_workspace_with_alias(db, name, org_id, report):
    """Explicit opt-in only (--create-missing): creates a workspace named exactly
    like the legacy name, plus the alias. No name similarity guessing, ever."""
    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    ws = Workspace(org_id=org_id, name=name, slug=slug, legacy_name=name)
    db.add(ws)
    db.flush()
    for sname, color, order, won, lost in DEFAULT_STAGES:
        db.add(Stage(workspace_id=ws.id, name=sname, color=color, sort_order=order, is_won=won, is_lost=lost))
    db.add(WorkspaceAlias(workspace_id=ws.id, source_system=SOURCE, external_name=name))
    report["workspaces_created"] += 1
    return ws


def run_import(legacy_db_url: str, dry_run: bool = True, create_missing: bool = False, org_id: int = 0) -> dict:
    if not legacy_db_url:
        raise SystemExit("--legacy-db-url is required (the old Reply Manager DATABASE_URL)")
    legacy = create_engine(_norm_url(legacy_db_url))
    init_db()
    report = {"leads_seen": 0, "contacts_created": 0, "contacts_merged": 0, "companies_created": 0,
              "activities_created": 0, "deals_created": 0, "deals_skipped_existing": 0,
              "workspaces_created": 0, "unmapped_workspaces": [], "mapping": {},
              "aborted": False, "dry_run": dry_run}

    with legacy.connect() as lconn, session() as db:
        def _safe_rows(sql, missing_note):
            """Tolerate legacy DBs that predate a table (e.g. a dev copy without
            the CRM tables) — report it instead of crashing the dry run."""
            try:
                return _rows(lconn, sql)
            except Exception:
                notes = report.setdefault("notes", [])
                if missing_note not in notes:
                    notes.append(missing_note)
                return []

        old_stages = {s["id"]: s["name"] for s in _safe_rows(
            "SELECT id, name FROM crm_stages", "crm_stages table missing — deals will have no stage mapping")}

        # ---------------- PRE-FLIGHT: mapping review BEFORE anything is written
        lead_names = [r["workspace_name"] for r in _safe_rows(
            "SELECT DISTINCT workspace_name FROM leads WHERE workspace_name IS NOT NULL",
            "leads table missing")]
        opp_names = [r["workspace_name"] for r in _safe_rows(
            "SELECT DISTINCT workspace_name FROM opportunities WHERE workspace_name IS NOT NULL",
            "opportunities table missing — no deals to import")]
        mapping = resolve_workspaces(db, lead_names + opp_names)

        print("\n=== WORKSPACE MAPPING REVIEW (source: reply_manager) ===")
        for name, res in mapping.items():
            if res["workspace"]:
                print(f"  MAPPED    {name!r} → workspace #{res['workspace'].id} "
                      f"{res['workspace'].name!r} (via {res['via']})")
            else:
                print(f"  UNMAPPED  {name!r} → create an alias: "
                      f"POST /api/admin/aliases {{source_system: 'reply_manager', external_name: {name!r}}}")
        unmapped = [n for n, r in mapping.items() if r["workspace"] is None]
        report["mapping"] = {n: (r["workspace"].id if r["workspace"] else None) for n, r in mapping.items()}
        report["unmapped_workspaces"] = sorted(unmapped)

        if unmapped and create_missing:
            for name in unmapped:
                mapping[name] = {"workspace": _create_workspace_with_alias(db, name, org_id, report),
                                 "via": "created"}
            unmapped = []
        if unmapped and not dry_run:
            db.rollback()
            print(f"\nABORTED before writing: {len(unmapped)} unmapped workspace name(s). "
                  "Create aliases (or pass --create-missing) and re-run.")
            report["aborted"] = True
            return report
        print("=== end mapping review ===\n")

        def ws_for(name):
            return mapping.get(name, {}).get("workspace")

        # ---------------- leads → contacts/companies/activities
        for lead in _safe_rows("SELECT * FROM leads ORDER BY id", "leads table missing"):
            report["leads_seen"] += 1
            ws = ws_for(lead["workspace_name"])
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

            occurred = _to_dt(lead.get("created_at"))
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
        for opp in _safe_rows("SELECT * FROM opportunities ORDER BY id",
                              "opportunities table missing — no deals to import"):
            ws = ws_for(opp["workspace_name"])
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
