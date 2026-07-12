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


def run(legacy_db_url, apply=False):
    legacy = create_engine(_norm(legacy_db_url))
    init_db()
    rep = {"workspaces_seen": 0, "reply_spaces_created": 0, "reply_spaces_updated": 0,
           "unmapped": set(), "global_settings": 0, "apply": apply}
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
                row = db.get(AppSetting, f"reply.{rkey}")
                if row is None:
                    row = AppSetting(key=f"reply.{rkey}", is_secret=1 if secret else 0)
                    db.add(row)
                row.value = encrypt(settings[lkey]) if secret else str(settings[lkey])
                rep["global_settings"] += 1
        global_rules = settings.get("ai_rules", "")

        # ---- legacy workspaces → reply spaces
        try:
            wrows = [dict(r._mapping) for r in lc.execute(text("SELECT * FROM workspaces ORDER BY id"))]
        except Exception as e:
            raise SystemExit(f"Could not read legacy workspaces table: {e}")
        for w in wrows:
            rep["workspaces_seen"] += 1
            name = w.get("name")
            wsid = resolve_ws(db, name)
            if wsid is None:
                rep["unmapped"].add(name)
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
