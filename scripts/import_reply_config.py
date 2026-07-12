"""Import the legacy Reply Manager CONFIG into RevCadence — the reply spaces
(client profile, reply format, AI provider, keys, Calendly, campaign id) plus
global reply settings (keys, models, webhook, delay, trigger tags) and the
global ai_rules.

Reads the legacy `workspaces` + `app_settings` tables (read-only). Secrets are
ENCRYPTED at rest on arrival. Each legacy workspace maps to a RevCadence client
workspace via a WorkspaceAlias (source_system='reply_manager'). Idempotent —
matches an existing reply space by name and updates it.

Usage:
  Dry run: python -m scripts.import_reply_config --legacy-db-url "postgresql://..."
  Apply:   python -m scripts.import_reply_config --legacy-db-url "..." --apply
"""
import argparse
import json

from sqlalchemy import create_engine, text

from app.crypto import encrypt
from app.db import init_db, session
from app.models.identity import Workspace, WorkspaceAlias
from app.models.reply import ReplyWorkspace
from app.models.settings import AppSetting


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


# legacy reply_format may be a flat single-main_reply shape; normalize to
# {response_types:[], followups:[]} so the structured editor reads it.
def _normalize_reply_format(rf):
    rf = _json(rf)
    if not isinstance(rf, dict):
        return {"response_types": [], "followups": []}
    if "response_types" in rf or "followups" in rf:
        rf.setdefault("response_types", [])
        rf.setdefault("followups", [])
        return rf
    # legacy variants: {reply_types:[...]} / {types:[...]} / {main_reply:...}
    rts = rf.get("reply_types") or rf.get("types") or []
    fus = rf.get("followups") or rf.get("follow_ups") or []
    if not rts and rf.get("main_reply"):
        rts = [{"id": "simple_positive", "auto_send": True, "template": rf["main_reply"]}]
    return {"response_types": rts, "followups": fus}


def run(legacy_db_url, apply=False, include=None):
    """include: optional list of legacy workspace names to import. When given,
    ONLY those are considered; every other legacy workspace is reported under
    `skipped` (never blocks --apply). --apply still aborts if an *included*
    workspace is unmapped."""
    legacy = create_engine(_norm(legacy_db_url))
    init_db()
    include_set = set(include or [])
    rep = {"workspaces_seen": 0, "mapped": [], "unmapped": [], "skipped": [],
           "include_filter": sorted(include_set), "reply_formats_found": 0,
           "rules_found": False, "settings_found": [], "reply_spaces_created": 0,
           "reply_spaces_updated": 0, "global_settings": 0, "apply": apply, "aborted": False}
    _unmapped = set()
    with legacy.connect() as lc, session() as db:
        # ---- global app_settings → AppSetting + ai_rules text
        settings = {}
        try:
            for r in lc.execute(text("SELECT key, value FROM app_settings")):
                settings[r[0]] = r[1]
        except Exception:
            pass
        smap = {  # legacy key → (revcadence key, is_secret)
            "openai_key": ("openai_api_key", True), "gemini_key": ("gemini_api_key", True),
            "openai_model": ("openai_model", False), "gemini_model": ("gemini_model", False),
            "human_review_webhook": ("review_webhook_url", False),
            "reply_delay_seconds": ("reply_delay_seconds", False),
            "reply_trigger_tag": ("reply_trigger_tag", False),
            "followup_trigger_tag": ("followup_trigger_tag", False),
        }
        for lkey, (rkey, secret) in smap.items():
            if lkey in settings and settings[lkey]:
                rep["settings_found"].append(rkey)
                row = db.get(AppSetting, f"reply.{rkey}")
                if row is None:
                    row = AppSetting(key=f"reply.{rkey}", is_secret=1 if secret else 0)
                    db.add(row)
                row.value = encrypt(settings[lkey]) if secret else str(settings[lkey])
                rep["global_settings"] += 1
        global_rules = settings.get("ai_rules", "")
        rep["rules_found"] = bool(global_rules.strip())

        # ---- legacy workspaces → reply spaces
        try:
            wrows = [dict(r._mapping) for r in lc.execute(text("SELECT * FROM workspaces ORDER BY id"))]
        except Exception as e:
            raise SystemExit(f"Could not read legacy workspaces table: {e}")

        # PRE-FLIGHT: resolve every workspace first so we can abort BEFORE writing.
        # When an include filter is set, only included names are "considered";
        # all others are `skipped` (they never affect the abort decision).
        for w in wrows:
            rep["workspaces_seen"] += 1
            name = w.get("name")
            if include_set and name not in include_set:
                rep["skipped"].append(name)
                continue
            if resolve_ws(db, name) is None:
                _unmapped.add(name)
            else:
                rep["mapped"].append(name)
            if _normalize_reply_format(w.get("reply_format")).get("response_types"):
                rep["reply_formats_found"] += 1
        rep["unmapped"] = sorted(x for x in _unmapped if x)
        rep["skipped"] = sorted(x for x in rep["skipped"] if x)

        # Abort only when an INCLUDED (considered) workspace is unmapped.
        if _unmapped and apply:
            db.rollback()
            rep["aborted"] = True
            return rep

        for w in wrows:
            name = w.get("name")
            if include_set and name not in include_set:
                continue  # skipped — not imported
            wsid = resolve_ws(db, name)
            if wsid is None:
                continue
            rws = db.query(ReplyWorkspace).filter(ReplyWorkspace.name == name).first()
            new = rws is None
            if new:
                rws = ReplyWorkspace(workspace_id=wsid, name=name)
                db.add(rws)
            rws.workspace_id = wsid
            rws.platform = w.get("platform") or "bison"
            rws.mode = w.get("mode") or "reply"
            rws.active = bool(w.get("active", True))
            rws.base_url = w.get("base_url") or ""
            rws.reply_followup_campaign_id = str(w.get("reply_followup_campaign_id") or "")
            rws.website = w.get("website") or ""
            rws.sender_name = w.get("sender_name") or ""
            rws.default_sender_email = w.get("default_sender_email") or ""
            rws.calendly_scheduling_url = w.get("calendly_scheduling_url") or ""
            rws.ai_provider = w.get("ai_provider") or "openai"
            rws.ai_fallback = bool(w.get("ai_fallback"))
            rws.client_profile = _json(w.get("client_profile"))
            rws.reply_format = _normalize_reply_format(w.get("reply_format"))
            rws.ai_rules = global_rules  # legacy rules were global; seed each space
            # secrets — encrypt on arrival, only if present
            if w.get("api_key"):
                rws.api_key_enc = encrypt(w["api_key"])
            if w.get("calendly_token"):
                rws.calendly_token_enc = encrypt(w["calendly_token"])
            if w.get("openai_key"):
                rws.openai_key_enc = encrypt(w["openai_key"])
            if w.get("gemini_key"):
                rws.gemini_key_enc = encrypt(w["gemini_key"])
            db.flush()
            rep["reply_spaces_created" if new else "reply_spaces_updated"] += 1

        if not apply:
            db.rollback()
    return rep


def _print_report(rep):
    print("\n=== REPLY CONFIG IMPORT ===")
    print(f"  legacy workspaces found : {rep['workspaces_seen']}")
    if rep["include_filter"]:
        print(f"  include filter          : {', '.join(rep['include_filter'])}")
    print(f"  mapped ({len(rep['mapped'])}): {', '.join(rep['mapped']) or '—'}")
    print(f"  skipped ({len(rep['skipped'])}): {', '.join(rep['skipped']) or '—'}")
    print(f"  UNMAPPED ({len(rep['unmapped'])}): {', '.join(rep['unmapped']) or '—'}")
    print(f"  reply formats found     : {rep['reply_formats_found']}")
    print(f"  ai rules found          : {'yes' if rep['rules_found'] else 'no'}")
    print(f"  global settings found   : {', '.join(rep['settings_found']) or '—'}")
    if rep["aborted"]:
        print("\n  ABORTED — an INCLUDED workspace is unmapped: "
              f"{', '.join(rep['unmapped'])}. Create its reply_manager alias "
              "(Admin → Workspace aliases) and re-run. Nothing was written.")
    elif rep["apply"]:
        print(f"\n  APPLIED · reply spaces created {rep['reply_spaces_created']} · "
              f"updated {rep['reply_spaces_updated']} · global settings {rep['global_settings']}")
    else:
        would = rep["reply_spaces_created"] + rep["reply_spaces_updated"]
        print(f"\n  DRY RUN — would create/update {would} reply space(s) + "
              f"{rep['global_settings']} global setting(s). Nothing written. Add --apply to commit.")
    print(json.dumps(rep, indent=2, default=str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-db-url", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--include-workspace", action="append", default=[], dest="include",
                    metavar="NAME",
                    help="import ONLY this legacy workspace name; repeatable. "
                         "All others are skipped (not unmapped).")
    args = ap.parse_args()
    rep = run(args.legacy_db_url, apply=args.apply, include=args.include)
    _print_report(rep)
    if rep["aborted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
