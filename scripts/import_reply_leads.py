"""Import the legacy Reply Manager operational data — the `leads` table — into
RevCadence, and sync each into the CRM. This is the HISTORICAL INBOX migration
(the companion to import_reply_config.py, which imports only configuration).

Legacy `leads` holds everything: replies, intent, confidence, action, the
drafted reply (main_reply), follow-ups, the full thread (conversation/messages),
raw platform lead_data (company/contact), stage (booked/stopped/...), reviewed.
Each legacy lead → one RevCadence ReplyLead (+ CRM contact/company + a deal in
Opportunity or Meeting Booked). Dashboard stats are derived, so they rebuild
themselves from the imported rows.

Read-only on the legacy DB. Idempotent (dedupe_key + legacy_id). Preserves the
original legacy id in ReplyLead.legacy_id. Resolves each legacy workspace_name
to a RevCadence workspace via WorkspaceAlias (source='reply_manager').

Usage:
  Dry run (default): python -m scripts.import_reply_leads --legacy-db-url "<URL>"
  Explicit dry run:  python -m scripts.import_reply_leads --legacy-db-url "<URL>" --dry-run
  Apply:             python -m scripts.import_reply_leads --legacy-db-url "<URL>" --apply
  Only some clients: ... --include-workspace "Ascendly: mainreplybison" --include-workspace "Webaholics"
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


def _classify(rep, lead):
    """Increment the summary buckets for one imported lead."""
    rep["conversations"] += 1
    rep["messages"] += len(lead.thread or [])
    if lead.main_reply:
        rep["replies"] += 1
    if lead.reviewed:
        rep["reviewed"] += 1
    if lead.action in ("skip_enrich", "would_send") and not lead.reviewed:
        rep["needs_review"] += 1
    if (lead.stage or "").lower() in ("booked", "meeting booked", "meeting_booked"):
        rep["meeting_booked"] += 1
    if lead.action == "stop" or (lead.stage or "").lower() == "stopped":
        rep["stopped"] += 1
    if lead.replied:
        rep["replied"] += 1


def run(legacy_db_url, apply=False, include=None):
    legacy = create_engine(_norm(legacy_db_url))
    init_db()
    include_set = set(include or [])
    rep = {
        "include_filter": sorted(include_set),
        "legacy_leads_total": 0, "considered": 0, "skipped_workspace": 0,
        "unmapped_workspaces": [], "skipped_workspaces": [],
        "already_imported": 0, "imported": 0,
        # operational summary
        "conversations": 0, "messages": 0, "replies": 0, "replied": 0,
        "needs_review": 0, "reviewed": 0, "meeting_booked": 0, "stopped": 0,
        # CRM sync
        "crm_contacts": 0, "crm_deals": 0,
        # verification
        "reply_leads_before": 0, "reply_leads_after": 0,
        "apply": apply, "aborted": False,
    }
    _unmapped, _skipped = set(), set()
    with legacy.connect() as lc, session() as db:
        from app.reply.sync import (sync_booked_to_deal, sync_interested_to_opportunity,
                                    sync_reply_lead_to_crm)
        rep["reply_leads_before"] = db.query(ReplyLead).count()
        rows = [dict(r._mapping) for r in lc.execute(text("SELECT * FROM leads ORDER BY id"))]
        rep["legacy_leads_total"] = len(rows)

        # PRE-FLIGHT: resolve every distinct workspace, honoring the include filter.
        names = sorted({r.get("workspace_name") for r in rows if r.get("workspace_name")})
        for name in names:
            if include_set and name not in include_set:
                _skipped.add(name)
            elif resolve_ws(db, name) is None:
                _unmapped.add(name)
        rep["unmapped_workspaces"] = sorted(x for x in _unmapped if x)
        rep["skipped_workspaces"] = sorted(x for x in _skipped if x)
        if _unmapped and apply:
            db.rollback()
            rep["aborted"] = True
            rep["reply_leads_after"] = rep["reply_leads_before"]
            return rep

        for r in rows:
            name = r.get("workspace_name")
            if include_set and name not in include_set:
                rep["skipped_workspace"] += 1
                continue
            wsid = resolve_ws(db, name)
            if wsid is None:
                rep["skipped_workspace"] += 1
                continue
            rep["considered"] += 1
            legacy_id = r.get("id")
            dedupe = r.get("dedupe_key") or f"{r.get('platform')}:{r.get('external_lead_id')}:{r.get('reply_id') or r.get('email')}"
            # idempotency: match by legacy_id OR dedupe_key
            existing = (db.query(ReplyLead)
                        .filter((ReplyLead.legacy_id == legacy_id) | (ReplyLead.dedupe_key == dedupe))
                        .first())
            if existing:
                rep["already_imported"] += 1
                continue
            lead = ReplyLead(
                workspace_id=wsid, reply_workspace=name or "", platform=r.get("platform") or "",
                legacy_id=legacy_id, dedupe_key=dedupe,
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
            _classify(rep, lead)
            # CRM sync — contact/company + Opportunity/Meeting-Booked deal
            s = sync_reply_lead_to_crm(db, lead, queue_enrich=False)
            if s.get("contact_id"):
                rep["crm_contacts"] += 1
            if (lead.stage or "").lower() in ("booked", "meeting booked", "meeting_booked"):
                if sync_booked_to_deal(db, lead).get("deal_id"):
                    rep["crm_deals"] += 1
            elif sync_interested_to_opportunity(db, lead).get("deal_id"):
                rep["crm_deals"] += 1

        # apply: after = before + imported (committed). dry: nothing persists →
        # after == before; the `imported` field is the projection.
        rep["reply_leads_after"] = (rep["reply_leads_before"] + rep["imported"]) if apply \
            else rep["reply_leads_before"]
        if not apply:
            db.rollback()
    return rep


def _print(rep):
    print("\n=== REPLY DATA IMPORT (historical inbox) ===")
    if rep["include_filter"]:
        print(f"  include filter        : {', '.join(rep['include_filter'])}")
    print(f"  legacy leads total     : {rep['legacy_leads_total']}")
    print(f"  considered             : {rep['considered']}")
    print(f"  skipped (workspace)    : {rep['skipped_workspace']}  "
          f"{rep['skipped_workspaces'] or ''}")
    print(f"  UNMAPPED workspaces    : {rep['unmapped_workspaces'] or '—'}")
    print(f"  already imported       : {rep['already_imported']}")
    print(f"  imported               : {rep['imported']}")
    print("  --- operational summary (of imported) ---")
    for k in ("conversations", "messages", "replies", "replied", "needs_review",
              "reviewed", "meeting_booked", "stopped"):
        print(f"    {k:<16}: {rep[k]}")
    print(f"  CRM contacts synced    : {rep['crm_contacts']}")
    print(f"  CRM deals created      : {rep['crm_deals']}")
    print(f"  ReplyLead count before : {rep['reply_leads_before']}")
    print(f"  ReplyLead count after  : {rep['reply_leads_after']}")
    if rep["aborted"]:
        print("\n  ABORTED — unmapped workspace(s) present. Add their reply_manager "
              "aliases or use --include-workspace. Nothing written.")
    elif rep["apply"]:
        print("\n  APPLIED.")
    else:
        print("\n  DRY RUN — nothing written. Add --apply to commit.")
    print(json.dumps(rep, indent=2, default=str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-db-url", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="explicit dry run (default)")
    ap.add_argument("--include-workspace", action="append", default=[], dest="include",
                    metavar="NAME", help="import ONLY this legacy workspace_name; repeatable")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run
    rep = run(args.legacy_db_url, apply=apply, include=args.include)
    _print(rep)
    if rep["aborted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
