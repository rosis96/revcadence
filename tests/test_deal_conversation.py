"""T14 — Deal Conversation (same-thread relationship management).

Covers: connect mailbox, send in-thread (threading headers), record inbound reply
cancelling scheduled follow-ups, inbound matching by RFC refs + by email, the AI
briefing, workspace isolation. SMTP/IMAP transport is monkeypatched (no network).

Run:  python -m tests.test_deal_conversation
"""
import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test_conv.db"
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import init_db, session  # noqa: E402
from app.mailbox import service, transport  # noqa: E402
from app.main import app  # noqa: E402
from app.models.crm import Company, Contact, Deal, Stage  # noqa: E402
from app.models.identity import Membership, Organization, User, Workspace  # noqa: E402
from app.models.mailbox import ConversationMessage, DealConversation  # noqa: E402

client = TestClient(app)
PASS = []
SENT = []   # captures outgoing MIME so we can assert threading headers


def check(name, cond, detail=""):
    PASS.append((name, bool(cond)))
    print(("✓" if cond else "✗ FAIL"), name, detail if not cond else "")
    assert cond, f"{name}: {detail}"


def auth(t):
    return {"Authorization": f"Bearer {t}"}


def main():
    init_db()
    # transport stubs — no real network
    transport.smtp_test = lambda host, port, user, pw: (True, "")
    transport.smtp_send = lambda host, port, user, pw, msg: SENT.append(msg)

    with session() as db:
        org = Organization(name="Ascendly", slug="ascendly"); db.add(org); db.flush()
        owner = User(email="owner@a.one", password_hash=hash_password("pw")); db.add(owner); db.flush()
        w1 = Workspace(org_id=org.id, name="WS1", slug="ws1")
        w2 = Workspace(org_id=org.id, name="WS2", slug="ws2"); db.add_all([w1, w2]); db.flush()
        db.add(Membership(user_id=owner.id, org_id=org.id, role="owner", workspace_ids=[]))
        cli = User(email="c@w2.com", password_hash=hash_password("pw")); db.add(cli); db.flush()
        db.add(Membership(user_id=cli.id, org_id=org.id, role="client", workspace_ids=[w2.id]))
        st = Stage(workspace_id=w1.id, name="Meeting Completed", sort_order=3); db.add(st); db.flush()
        co = Company(workspace_id=w1.id, name="Acme"); db.add(co); db.flush()
        ct = Contact(workspace_id=w1.id, company_id=co.id, first_name="Dana", last_name="Reed",
                     email="dana@acme.test"); db.add(ct); db.flush()
        deal = Deal(workspace_id=w1.id, company_id=co.id, contact_id=ct.id, name="Acme deal",
                    stage_id=st.id, lead_intent="high"); db.add(deal); db.flush()
        ids = dict(w1=w1.id, w2=w2.id, deal=deal.id, co=co.id, ct=ct.id)

    tok = client.post("/api/auth/login", json={"email": "owner@a.one", "password": "pw"}).json()["token"]
    ctok = client.post("/api/auth/login", json={"email": "c@w2.com", "password": "pw"}).json()["token"]

    # ---- connect mailbox ----
    r = client.post("/api/mailbox/connect", json={"workspace_id": ids["w1"], "provider": "gmail",
                    "email": "rep@ascendly.one", "app_password": "app-pw-1234", "from_name": "Rosis"},
                    headers=auth(tok))
    check("mailbox connects (gmail defaults + verify)", r.status_code == 200 and r.json()["status"] == "connected"
          and r.json()["smtp_host"] == "smtp.gmail.com", r.text[:160])
    m = client.get("/api/mailbox", params={"workspace_id": ids["w1"]}, headers=auth(tok)).json()
    check("mailbox reads back, no secret exposed", m["email"] == "rep@ascendly.one" and "app_password" not in m and "secret" not in str(m))

    # ---- conversation exists per deal ----
    conv = client.get(f"/api/deals/{ids['deal']}/conversation", headers=auth(tok)).json()
    check("conversation auto-created for deal", conv["conversation"]["deal_id"] == ids["deal"]
          and conv["conversation"]["prospect_email"] == "dana@acme.test" and conv["mailbox_connected"])

    # ---- send first email (new thread) ----
    r = client.post(f"/api/deals/{ids['deal']}/conversation/send",
                    json={"body": "Great meeting you, Dana. Here's the recap…"}, headers=auth(tok))
    check("first email sends", r.status_code == 200 and r.json()["direction"] == "out", r.text[:160])
    first_mid = SENT[-1]["Message-ID"]
    check("first email has a Message-ID, no In-Reply-To", bool(first_mid) and SENT[-1]["In-Reply-To"] is None)

    # ---- send again → same thread (In-Reply-To + References set) ----
    client.post(f"/api/deals/{ids['deal']}/conversation/send",
                json={"body": "Following up with the proposal link."}, headers=auth(tok))
    check("second email threads onto the first (In-Reply-To)", SENT[-1]["In-Reply-To"] == first_mid)
    check("second email subject is Re: (same thread)", SENT[-1]["Subject"].lower().startswith("re:"), SENT[-1]["Subject"])
    check("References carries the thread", first_mid in (SENT[-1]["References"] or ""))

    # ---- schedule follow-ups, then a reply cancels them all ----
    with session() as db:
        conv_row = db.query(DealConversation).filter(DealConversation.deal_id == ids["deal"]).first()
        service.schedule_followups(db, conv_row, [{"body": "day 5 check-in"}, {"body": "day 9 check-in"}])
        sched = db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conv_row.id,
                                                     ConversationMessage.status == "scheduled").count()
        check("two follow-ups scheduled", sched == 2)

    # inbound reply arrives (matched by RFC References → same conversation)
    with session() as db:
        conv_row = db.query(DealConversation).filter(DealConversation.deal_id == ids["deal"]).first()
        matched = service.match_inbound_to_conversation(db, ids["w1"], from_email="dana@acme.test",
                                                        in_reply_to=first_mid, references=first_mid)
        check("inbound matched to conversation by RFC refs", matched and matched.id == conv_row.id)
        cm, cancelled = service.record_inbound(db, conv_row, from_email="dana@acme.test",
                                               subject="Re: Acme", body_text="Give me two weeks.",
                                               rfc_message_id="<reply-1@acme.test>", in_reply_to=first_mid)
        check("prospect reply recorded as inbound", cm.direction == "in")
        check("reply CANCELS all scheduled follow-ups", cancelled == 2)
        still = db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conv_row.id,
                                                     ConversationMessage.status == "scheduled").count()
        check("no scheduled follow-ups remain", still == 0)

    # match by email when no refs
    with session() as db:
        conv_row = db.query(DealConversation).filter(DealConversation.deal_id == ids["deal"]).first()
        m2 = service.match_inbound_to_conversation(db, ids["w1"], from_email="dana@acme.test")
        check("inbound also matches by prospect email", m2 and m2.id == conv_row.id)

    # ---- poll worker: fetch unseen → land into the same thread ----
    transport.imap_fetch_unseen = lambda host, port, user, pw, limit=25: [{
        "from_email": "dana@acme.test", "to_email": "rep@ascendly.one", "subject": "Re: Acme",
        "rfc_message_id": "<reply-2@acme.test>", "in_reply_to": first_mid, "references": first_mid,
        "body_text": "Actually, let's talk sooner."}]
    with session() as db:
        summary = service.poll_and_sync(db, ids["w1"])
        check("poll matched the reply into its conversation", summary["matched"] == 1, str(summary))

    # ---- AI briefing ----
    b = client.get(f"/api/deals/{ids['deal']}/conversation/briefing", headers=auth(tok)).json()
    check("briefing returns decision context", b["stage"] == "Meeting Completed" and "recommendation" in b
          and b["next_action"] and b["awaiting_us"] is True, str(b)[:200])

    # ---- parse a raw MIME (threading fields) ----
    raw = (b"From: Dana <dana@acme.test>\r\nTo: rep@ascendly.one\r\nSubject: Re: Acme\r\n"
           b"Message-ID: <x@acme.test>\r\nIn-Reply-To: " + first_mid.encode() + b"\r\n\r\nSounds good.\r\n")
    parsed = transport.parse_message(raw)
    check("MIME parse extracts threading + body", parsed["from_email"] == "dana@acme.test"
          and parsed["in_reply_to"] == first_mid and "Sounds good" in parsed["body_text"])

    # ---- Revenue Inbox: CC'd thread with a KNOWN contact surfaces as a candidate ----
    # a brand-new inbound from a known contact (Dana) but on a DIFFERENT thread with
    # no matching conversation refs → should become a pending candidate.
    transport.imap_fetch_unseen = lambda host, port, user, pw, limit=25: [{
        "from_email": "someoneelse@partner.test", "to_email": "rep@ascendly.one",
        "participants": ["someoneelse@partner.test", "rep@ascendly.one", "dana@acme.test"],
        "subject": "Intro + question", "rfc_message_id": "<cc-thread-1@partner.test>",
        "in_reply_to": "", "references": "", "body_text": "Looping in Dana — can you help?"}]
    with session() as db:
        summary = service.poll_and_sync(db, ids["w1"])
        check("CC'd thread with known contact becomes a candidate", summary["candidates"] == 1, str(summary))
    inbox = client.get("/api/revenue-inbox", params={"workspace_id": ids["w1"]}, headers=auth(tok)).json()
    check("revenue inbox lists the candidate with matched contact + deal options",
          len(inbox) == 1 and inbox[0]["contact"]["email"] == "dana@acme.test" and len(inbox[0]["deals"]) >= 1, str(inbox)[:220])
    # attach it to the deal → becomes part of that deal's conversation
    r = client.post(f"/api/revenue-inbox/{inbox[0]['id']}/attach", json={"deal_id": ids["deal"]}, headers=auth(tok))
    check("attach candidate to deal ok", r.status_code == 200, r.text[:160])
    conv2 = client.get(f"/api/deals/{ids['deal']}/conversation", headers=auth(tok)).json()
    check("attached thread now appears in the deal conversation",
          any("Looping in Dana" in (m.get("body_text") or "") for m in conv2["messages"]))
    left = client.get("/api/revenue-inbox", params={"workspace_id": ids["w1"]}, headers=auth(tok)).json()
    check("attached candidate leaves the pending list", len(left) == 0)

    # ---- WOW on connect: backfill imports recent mail + surfaces known contacts ----
    # a known contact who does NOT yet have a conversation → should surface; a
    # stranger → skipped.
    with session() as db:
        p = Contact(workspace_id=ids["w1"], first_name="Priya", last_name="N", email="priya@newco.test")
        db.add(p); db.flush()
    transport.imap_fetch_since = lambda host, port, user, pw, days=60, limit=200, folder="INBOX": [
        {"from_email": "priya@newco.test", "to_email": "rep@ascendly.one",
         "participants": ["priya@newco.test", "rep@ascendly.one"], "subject": "from last month",
         "rfc_message_id": "<backfill-1@newco.test>", "in_reply_to": "", "references": "",
         "body_text": "Great chatting a few weeks ago."},
        {"from_email": "stranger@nobody.test", "to_email": "rep@ascendly.one",
         "participants": ["stranger@nobody.test", "rep@ascendly.one"], "subject": "cold pitch",
         "rfc_message_id": "<backfill-2@nobody.test>", "in_reply_to": "", "references": "",
         "body_text": "buy my thing"}]
    with session() as db:
        summary = service.backfill(db, ids["w1"], days=60)
        check("backfill surfaces known contact, skips stranger",
              summary["candidates"] == 1 and summary["scanned"] == 2, str(summary))
    inbox2 = client.get("/api/revenue-inbox", params={"workspace_id": ids["w1"]}, headers=auth(tok)).json()
    check("backfilled candidate is in the Revenue Inbox",
          any(it["from_email"] == "priya@newco.test" for it in inbox2))

    # ---- workspace isolation ----
    r = client.get(f"/api/deals/{ids['deal']}/conversation", headers=auth(ctok))
    check("client in another workspace cannot read the conversation", r.status_code == 404)
    r = client.get("/api/mailbox", params={"workspace_id": ids["w1"]}, headers=auth(ctok))
    check("cross-workspace mailbox read refused", r.status_code == 403)

    print(f"\n{sum(1 for _, ok in PASS if ok)}/{len(PASS)} checks passed")


if __name__ == "__main__":
    main()
