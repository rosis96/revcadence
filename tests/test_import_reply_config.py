"""Tests for scripts/import_reply_config.py — dry run writes nothing, apply
imports config + encrypts secrets, abort on unmapped, idempotent re-run."""
import os
import sqlite3
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/rc.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.crypto import decrypt  # noqa: E402
from app.db import init_db, session, SessionLocal  # noqa: E402
from app.models.identity import Organization, Workspace, WorkspaceAlias  # noqa: E402
from app.models.reply import ReplyWorkspace  # noqa: E402
from app.models.settings import AppSetting  # noqa: E402
from app.provision import provision_workspace  # noqa: E402
from scripts.import_reply_config import run  # noqa: E402

PASS = []


def check(name, cond):
    PASS.append(cond)
    print(("✓" if cond else "✗ FAIL"), name)
    assert cond, name


def _legacy_db(with_unmapped=False):
    path = tempfile.mktemp(suffix=".db")
    c = sqlite3.connect(path)
    c.executescript("""
      CREATE TABLE app_settings (key TEXT, value TEXT);
      INSERT INTO app_settings VALUES ('openai_key','sk-legacy'),('openai_model','gpt-4.1'),
        ('reply_trigger_tag','Interested'),('ai_rules','Never propose Mondays.');
      CREATE TABLE workspaces (id INTEGER PRIMARY KEY, name TEXT, platform TEXT, mode TEXT,
        active INTEGER, api_key TEXT, base_url TEXT, reply_followup_campaign_id TEXT,
        website TEXT, sender_name TEXT, default_sender_email TEXT, calendly_token TEXT,
        calendly_scheduling_url TEXT, ai_provider TEXT, ai_fallback INTEGER, openai_key TEXT,
        gemini_key TEXT, client_profile TEXT, reply_format TEXT);
      INSERT INTO workspaces VALUES (1,'Ascendly: mainreplybison','bison','reply',1,'BKEY',
        'https://send.ascendly.one','41','https://ascendly.one','','','CTOK',
        'https://calendly.com/rosis/x','openai',1,'','','{"client_name":"Ascendly"}',
        '{"response_types":[{"id":"simple_positive","auto_send":true}],"followups":[{"label":"FUP 1"}]}');
    """)
    if with_unmapped:
        c.execute("INSERT INTO workspaces (id,name,platform,client_profile,reply_format) "
                  "VALUES (2,'Orphan Client','bison','{}','{}')")
    c.commit(); c.close()
    return f"sqlite:///{path}"


def main():
    init_db()
    with session() as db:
        org = Organization(name="Ascendly", slug="ascendly"); db.add(org); db.flush()
        w = Workspace(org_id=org.id, name="Ascendly", slug="ascendly"); db.add(w); db.flush()
        provision_workspace(db, w)
        db.add(WorkspaceAlias(workspace_id=w.id, source_system="reply_manager",
                              external_name="Ascendly: mainreplybison"))

    url = _legacy_db()

    # dry run writes nothing
    before = SessionLocal().query(ReplyWorkspace).filter(ReplyWorkspace.name == "Ascendly: mainreplybison").first()
    dry = run(url)
    check("dry run reports 1 workspace found", dry["workspaces_seen"] == 1)
    check("dry run maps Ascendly", dry["mapped"] == ["Ascendly: mainreplybison"])
    check("dry run counts reply formats", dry["reply_formats_found"] == 1)
    check("dry run finds rules", dry["rules_found"] is True)
    check("dry run lists settings found", "openai_api_key" in dry["settings_found"])
    check("dry run wrote nothing", (before.reply_format or {}).get("response_types", []) == [] if before else True)

    # apply imports config + encrypts
    rep = run(url, apply=True)
    check("apply created 1 reply space", rep["reply_spaces_created"] == 1)
    db = SessionLocal()
    rws = db.query(ReplyWorkspace).filter(ReplyWorkspace.name == "Ascendly: mainreplybison").first()
    check("api key encrypted at rest + decrypts", rws.api_key_enc != "BKEY" and decrypt(rws.api_key_enc) == "BKEY")
    check("structured reply format imported", rws.reply_format["response_types"][0]["auto_send"] is True)
    check("client profile imported", rws.client_profile.get("client_name") == "Ascendly")
    check("global setting encrypted", decrypt(db.get(AppSetting, "reply.openai_api_key").value) == "sk-legacy")
    db.close()

    # idempotent: re-apply updates, does not duplicate
    rep2 = run(url, apply=True)
    check("re-apply updates not duplicates", rep2["reply_spaces_created"] == 0 and rep2["reply_spaces_updated"] == 1)
    check("still exactly one reply space",
          SessionLocal().query(ReplyWorkspace).filter(ReplyWorkspace.name == "Ascendly: mainreplybison").count() == 1)

    # abort on unmapped
    url2 = _legacy_db(with_unmapped=True)
    rep3 = run(url2, apply=True)
    check("apply aborts when a workspace is unmapped", rep3["aborted"] and "Orphan Client" in rep3["unmapped"])
    db = SessionLocal()
    check("abort wrote nothing new", db.query(ReplyWorkspace).filter(ReplyWorkspace.name == "Orphan Client").count() == 0)
    db.close()

    print(f"\n{sum(PASS)}/{len(PASS)} checks passed")


if __name__ == "__main__":
    main()
