"""Import the legacy Reply Manager `leads` table into RevCadence ReplyLead rows
— exactly as they were — and sync each into the CRM (contact/company +
Opportunity/Meeting-Booked deal by stage).

Read-only on the legacy DB. Idempotent (dedupe_key). Resolves each legacy
workspace_name to a RevCadence workspace via WorkspaceAlias
(source_system='reply_manager'), the same mapping used by import_legacy.

Usage:
  Dry run:  python -m scripts.import_reply_leads --legacy-db-url "postgresql://..."
  Apply:    python -m scripts.import_reply_leads --legacy-db-url "..." --apply
"""
import argparse
import json

from sqlalchemy import create_engine, text

from app.db import init_db, session
from app.models.identity import Workspace, WorkspaceAlias
from app.models.reply import ReplyLead


def _norm(url):
    return url.replace("postgres://", "postgresql://", 1) if url.startswith("postgres://") else url


def _json(v):
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return json.loads(v)
        except Exception:
            return {}
    return {}


def resolve_ws(db, name):
    a = (db.query(WorkspaceAlias)
         .filter(WorkspaceAlias.source_system == "reply_manager",
                 WorkspaceAlias.external_name == name).first())
    if a:
        return a.workspace_id
    w = db.query(Workspace).filter(Workspace.legacy_name == name).first()
    return w.id if w else None


def run(legacy_db_url, apply=False):
    legacy = create_engine(_norm(legacy_db_url))
    init_db()
    rep = {"seen": 0, "imported": 0, "skipped_dupe": 0, "unmapped": set(),
           "crm_contacts": 0, "deals": 0, "apply": apply}
    with legacy.connect() as lc, session() as db:
        from app.reply.sync import sync_interested_to_opportunity, sync_reply_lead_to_crm, sync_booked_to_deal
        rows = [dict(r._mapping) for r in lc.execute(text("SELECT * FROM leads ORDER BY id"))]
        for r in rows:
            rep["seen"] += 1
            wsid = resolve_ws(db, r.get("workspace_name"))
            if wsid is None:
                rep["unmapped"].add(r.get("workspace_name"))
                continue
            dedupe = r.get("dedupe_key") or f"{r.get('platform')}:{r.get('external_lead_id')}:{r.get('reply_id') or r.get('email')}"
            if db.query(ReplyLead).filter(ReplyLead.dedupe_key == dedupe).first():
                rep["skipped_dupe"] += 1
                continue
            lead = ReplyLead(
                workspace_id=wsid, reply_workspace=r.get("workspace_name") or "",
                platform=r.get("platform") or "", dedupe_key=dedupe,
                external_lead_id=str(r.get("external_lead_id") or ""), reply_id=str(r.get("reply_id") or ""),
                name=r.get("name") or "", email=(r.get("email") or "").lower(), company=r.get("company") or "",
                campaign=str(r.get("campaign") or ""), subject=r.get("subject") or "",
                intent=r.get("intent") or "", confidence=str(r.get("confidence") or ""),
                action=r.get("action") or "", replied=bool(r.get("replied")),
                reply_added=bool(r.get("reply_added")), fup_added=bool(r.get("fup_added")),
                reviewed=bool(r.get("reviewed")), stage=r.get("stage") or "new",
                reply_text=r.get("reply_text") or "", main_reply=r.get("main_reply") or "",
                followups=_json(r.get("followups")) or [], thread=_json(r.get("thread")) or [],
                lead_data=_json(r.get("lead_data")), send_meta=_json(r.get("send_meta")))
            db.add(lead)
            db.flush()
            rep["imported"] += 1
            # sync into CRM exactly as a live reply would
            s = sync_reply_lead_to_crm(db, lead, queue_enrich=False)
            if s.get("contact_id"):
                rep["crm_contacts"] += 1
            if (lead.stage or "").lower() in ("booked", "meeting booked", "meeting_booked"):
                if sync_booked_to_deal(db, lead).get("deal_id"):
                    rep["deals"] += 1
            elif sync_interested_to_opportunity(db, lead).get("deal_id"):
                rep["deals"] += 1
        rep["unmapped"] = sorted(x for x in rep["unmapped"] if x)
        if not apply:
            db.rollback()
            print("DRY RUN — nothing written. Add --apply to commit.")
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-db-url", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    print(json.dumps(run(args.legacy_db_url, apply=args.apply), indent=2, default=str))


if __name__ == "__main__":
    main()
