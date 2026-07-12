"""Tests for scripts/import_reply_leads.py — historical inbox migration:
dry-run writes nothing, apply imports + syncs CRM, idempotent, include filter,
abort on unmapped, before/after counts, operational summary."""
import os
import sqlite3
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/rl.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.db import init_db, session, SessionLocal  # noqa: E402
from app.models.crm import Contact, Deal  # noqa: E402
from app.models.identity import Organization, Workspace, WorkspaceAlias  # noqa: E402
from app.models.reply import ReplyLead  # noqa: E402
from app.provision import provision_workspace  # noqa: E402
from scripts.import_reply_leads import run  # noqa: E402

P = []


def check(name, cond):
    P.append(cond)
    print(("✓" if cond else "✗ FAIL"), name)
    assert cond, name


def _legacy(extra_ws=None):
    path = tempfile.mktemp(suffix=".db")
    c = sqlite3.connect(path)
    c.executescript("""
      CREATE TABLE leads (id INTEGER PRIMARY KEY, workspace_name TEXT, platform TEXT,
        dedupe_key TEXT, external_lead_id TEXT, reply_id TEXT, name TEXT, email TEXT,
        company TEXT, campaign TEXT, subject TEXT, intent TEXT, confidence TEXT, action TEXT,
        replied INTEGER, reply_added INTEGER, fup_added INTEGER, reviewed INTEGER, stage TEXT,
        reply_text TEXT, main_reply TEXT, followups TEXT, thread TEXT, lead_data TEXT, send_meta TEXT);
      -- interested + replied
      INSERT INTO leads VALUES (101,'Ascendly: mainreplybison','instantly','i:101','L1','R1',
        'Jane Doe','jane@acme.com','Acme','C1','Re: hi','simple_positive','0.95','send',
        1,1,1,1,'replied','yes interested','Hey Jane...','[]',
        '[{"direction":"in","text":"yes interested"},{"direction":"out","text":"Hey Jane..."}]',
        '{"website":"acme.com","linkedin_url":"https://linkedin.com/in/jane"}','{}');
      -- booked
      INSERT INTO leads VALUES (102,'Ascendly: mainreplybison','instantly','i:102','L2','R2',
        'Bob Smith','bob@beta.com','Beta','C1','Re: call','simple_positive','0.9','send',
        1,1,0,1,'booked','sure lets talk','Great...','[]','[{"direction":"in","text":"sure"}]',
        '{"website":"beta.com"}','{}');
      -- stopped
      INSERT INTO leads VALUES (103,'Ascendly: mainreplybison','instantly','i:103','L3','R3',
        'X','x@z.com','Z','C1','Re','unsubscribe','0.99','stop',0,0,0,0,'stopped',
        'unsubscribe','','[]','[{"direction":"in","text":"unsubscribe"}]','{}','{}');
      -- needs review (pricing, not reviewed)
      INSERT INTO leads VALUES (104,'Ascendly: mainreplybison','instantly','i:104','L4','R4',
        'Kev','kev@k.com','Kco','C1','Re','pricing_question','0.7','skip_enrich',
        0,1,0,0,'new','how much?','Drafted...','[]','[{"direction":"in","text":"how much?"}]','{}','{}');
    """)
    for wid, wsname in (extra_ws or []):
        c.execute("INSERT INTO leads (id, workspace_name, platform, email, intent, action, stage, thread) "
                  "VALUES (?,?,?,?,?,?,?,?)", (wid, wsname, "instantly", f"a{wid}@x.com",
                                              "simple_positive", "send", "replied", "[]"))
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

    url = _legacy()

    # dry run
    dry = run(url)
    check("dry: legacy total 4", dry["legacy_leads_total"] == 4)
    check("dry: would import 4", dry["imported"] == 4)
    check("dry: summary counts (replied/booked/stopped/needs_review)",
          dry["replied"] == 2 and dry["meeting_booked"] == 1 and dry["stopped"] == 1 and dry["needs_review"] == 1)
    check("dry: messages counted from threads", dry["messages"] == 2 + 1 + 1 + 1)
    check("dry: before==after (nothing written)", dry["reply_leads_before"] == dry["reply_leads_after"] == 0)
    check("dry: DB untouched", SessionLocal().query(ReplyLead).count() == 0)

    # apply
    rep = run(url, apply=True)
    check("apply imported 4", rep["imported"] == 4)
    check("apply before/after counts correct", rep["reply_leads_before"] == 0 and rep["reply_leads_after"] == 4)
    db = SessionLocal()
    check("apply preserved legacy ids", sorted(l.legacy_id for l in db.query(ReplyLead).all()) == [101, 102, 103, 104])
    check("thread/conversation preserved", len(db.query(ReplyLead).filter(ReplyLead.legacy_id == 101).first().thread) == 2)
    check("intent + confidence preserved",
          db.query(ReplyLead).filter(ReplyLead.legacy_id == 101).first().intent == "simple_positive"
          and db.query(ReplyLead).filter(ReplyLead.legacy_id == 101).first().confidence == "0.95")
    check("drafted reply preserved", db.query(ReplyLead).filter(ReplyLead.legacy_id == 104).first().main_reply == "Drafted...")
    # CRM sync
    check("CRM contacts synced", db.query(Contact).filter(Contact.email == "jane@acme.com").count() == 1)
    check("stopped lead -> no deal",
          db.query(Deal).join(Contact, Deal.contact_id == Contact.id).filter(Contact.email == "x@z.com").count() == 0)
    check("booked -> Meeting Booked deal exists",
          db.query(Contact).filter(Contact.email == "bob@beta.com").count() == 1)
    db.close()

    # idempotent re-apply
    rep2 = run(url, apply=True)
    check("re-apply imports 0 (idempotent by legacy_id)", rep2["imported"] == 0 and rep2["already_imported"] == 4)
    check("still exactly 4 ReplyLeads", SessionLocal().query(ReplyLead).count() == 4)

    # include filter + abort semantics
    url2 = _legacy(extra_ws=[(201, "Insight Media Labs"), (202, "Webaholics")])
    inc = run(url2, include=["Ascendly: mainreplybison"])
    check("include: others skipped not unmapped",
          set(inc["skipped_workspaces"]) == {"Insight Media Labs", "Webaholics"} and inc["unmapped_workspaces"] == [])
    check("include apply does not abort on skipped", run(url2, apply=True, include=["Ascendly: mainreplybison"])["aborted"] is False)
    bad = run(url2, apply=True, include=["Webaholics"])  # in legacy, no alias
    check("included-unmapped aborts", bad["aborted"] and "Webaholics" in bad["unmapped_workspaces"])

    print(f"\n{sum(P)}/{len(P)} checks passed")


if __name__ == "__main__":
    main()
