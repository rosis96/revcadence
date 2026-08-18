"""Client Space → Email Sequences: the read-only mirror of the sending platform.

Covers: normalizing a vendor campaign into the ladder shape, snapshot persistence
(idempotent, survives an outage), the client-readable payload, and the guarantee
this feature rests on — a client can READ their sequences and cannot EDIT any of
them. Platform HTTP is monkeypatched (no network).

Run:  python -m tests.test_live_sequence
"""
import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test_live_seq.db"
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.crypto import encrypt  # noqa: E402
from app.db import init_db, session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.identity import Membership, Organization, User, Workspace  # noqa: E402
from app.models.reply import ReplyWorkspace  # noqa: E402
from app.models.sequences import (EmailAngle, EmailSequence, EmailSequenceStep,  # noqa: E402
                                  EmailSequenceVariant)
from app.reply import campaigns as C  # noqa: E402

client = TestClient(app)
PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond)))
    print(("✓" if cond else "✗ FAIL"), name, detail if not cond else "")
    assert cond, f"{name}: {detail}"


def auth(t):
    return {"Authorization": f"Bearer {t}"}


# A campaign shaped the way Instantly v2 is expected to return one. When a real
# payload lands, correct FIELDS in app/reply/campaigns.py and this fixture — the
# assertions below are about behavior and should not need to move.
CAMPAIGN = {
    "id": "camp-1", "name": "Dormant retainer", "status": 1,
    "sequences": [{"steps": [
        {"delay": 0, "type": "email", "variants": [
            {"subject": "Hey {{firstName}}",
             "body": "<p>Hi {{firstName}},</p><p>{{opening_line}}</p>",
             "sent": 312, "replies": 23, "enabled": True},
            {"subject": "Quick one", "body": "<p>B variant</p>",
             "sent": 0, "replies": 0, "enabled": False}]},
        {"delay": 2, "variants": [{"subject": "Re: {{subject}}", "body": "bump",
                                   "sent": 200, "replies": 6}]},
        {"delay": 3, "variants": [{"subject": "A different thought", "body": "{{proof_line}}"}]},
        {"delay": 6, "variants": [{"subject": "Close the loop?", "body": "last one"}]}]}],
}
ANALYTICS = [{"campaign_id": "camp-1", "sent": 512, "replies": 29, "opportunities": 7}]


def platform_up(url, headers, params=None):
    if "analytics" in url:
        return ANALYTICS, ""
    if "/campaigns/camp-1" in url:
        return CAMPAIGN, ""
    return None, "unexpected url"


def platform_down(url, headers, params=None):
    return None, "HTTP 503: upstream down"


def main():
    init_db()
    C._get = platform_up

    with session() as db:
        org = Organization(name="Ascendly", slug="ascendly"); db.add(org); db.flush()
        owner = User(email="owner@a.one", password_hash=hash_password("pw")); db.add(owner); db.flush()
        ws = Workspace(org_id=org.id, name="Acme", slug="acme"); db.add(ws); db.flush()
        db.add(Membership(user_id=owner.id, org_id=org.id, role="owner", workspace_ids=[]))
        cli = User(email="client@acme.test", password_hash=hash_password("pw")); db.add(cli); db.flush()
        db.add(Membership(user_id=cli.id, org_id=org.id, role="client", workspace_ids=[ws.id]))

        db.add(ReplyWorkspace(
            workspace_id=ws.id, name="Acme Replies", platform="instantly", mode="reply",
            api_key_enc=encrypt("fake-key"), reply_delay_seconds=420, sender_name="Rosis Sitoula",
            mirror_campaign_ids=["camp-1"],
            reply_format={
                "response_types": [
                    {"id": "simple_positive", "intent": "clearly interested", "auto_send": True},
                    {"id": "asks_pricing", "intent": "wants a number", "auto_send": False}],
                "followups": [
                    {"label": "FUP 1", "intent": "nudge on the times", "max_words": 80},
                    {"label": "FUP 2", "intent": "fresh angle", "max_words": 60}]}))
        db.flush()

        # A sequence in OUR tables, so the client-edit checks have a real target.
        angle = EmailAngle(org_id=org.id, workspace_id=ws.id, name="Primary angle")
        db.add(angle); db.flush()
        seq = EmailSequence(org_id=org.id, workspace_id=ws.id, angle_id=angle.id, name="Seq")
        db.add(seq); db.flush()
        step = EmailSequenceStep(sequence_id=seq.id, position=0, name="Opener")
        db.add(step); db.flush()
        var = EmailSequenceVariant(step_id=step.id, label="A", subject="s", body="b")
        db.add(var); db.flush()
        ids = dict(ws=ws.id, seq=seq.id, step=step.id, var=var.id)

    tok = client.post("/api/auth/login", json={"email": "owner@a.one", "password": "pw"}).json()["token"]
    ctok = client.post("/api/auth/login", json={"email": "client@acme.test", "password": "pw"}).json()["token"]

    # ---- normalize: the ladder shape ----
    norm = C.normalize(CAMPAIGN, "instantly")
    check("campaign status maps to a live/paused vocabulary", norm["status"] == "live", norm["status"])
    check("day offsets accumulate from the waits", [s["day_offset"] for s in norm["steps"]] == [0, 2, 5, 11],
          str([s["day_offset"] for s in norm["steps"]]))
    check("step 1 always sends on day 0", norm["steps"][0]["wait_days"] == 0)
    check("HTML body becomes text with {{tokens}} intact",
          norm["steps"][0]["variants"][0]["body"] == "Hi {{firstName}},\n{{opening_line}}",
          repr(norm["steps"][0]["variants"][0]["body"]))
    check("a paused variant reads as disabled", norm["steps"][0]["variants"][1]["enabled"] is False)
    check("reply rate is computed per variant", norm["steps"][0]["variants"][0]["reply_rate"] == 7.4,
          str(norm["steps"][0]["variants"][0]["reply_rate"]))
    check("nothing went unmapped on a well-formed payload", norm["_unmapped"] == [], str(norm["_unmapped"]))

    # ---- refresh: operator-only, idempotent ----
    r = client.post("/api/reply/live-sequence/refresh", params={"workspace_id": ids["ws"]}, headers=auth(ctok))
    check("client cannot spend the platform rate limit", r.status_code == 403, r.text[:120])
    r = client.post("/api/reply/live-sequence/refresh", params={"workspace_id": ids["ws"]}, headers=auth(tok))
    check("operator refresh pulls the campaign", r.status_code == 200 and r.json()["ok"], r.text[:200])
    client.post("/api/reply/live-sequence/refresh", params={"workspace_id": ids["ws"]}, headers=auth(tok))

    # ---- the client's payload ----
    r = client.get("/api/reply/live-sequence", params={"workspace_id": ids["ws"]}, headers=auth(ctok))
    check("client can READ their live sequences", r.status_code == 200, r.text[:200])
    data = r.json()
    check("refreshing twice does not duplicate the campaign", len(data["campaigns"]) == 1,
          str(len(data["campaigns"])))
    camp = data["campaigns"][0]
    check("campaign carries name, status and ladder",
          camp["name"] == "Dormant retainer" and camp["status"] == "live" and len(camp["steps"]) == 4)
    check("campaign totals come from analytics", camp["stats"]["sent"] == 512
          and camp["stats"]["opportunities"] == 7, str(camp["stats"]))
    b = data["behavior"]
    check("reply delay is shown to the client", b["reply_delay_seconds"] == 420)
    check("auto-send reflects the kill switch", b["auto_send_enabled"] is False)
    check("the intent playbook is included", [t["id"] for t in b["response_types"]]
          == ["simple_positive", "asks_pricing"])
    check("the follow-up ladder is included", [f["label"] for f in b["followups"]] == ["FUP 1", "FUP 2"])
    check("no secret leaks into the client payload",
          "fake-key" not in r.text and "api_key" not in r.text)

    # ---- outage: stale beats blank ----
    C._get = platform_down
    client.post("/api/reply/live-sequence/refresh", params={"workspace_id": ids["ws"]}, headers=auth(tok))
    camp = client.get("/api/reply/live-sequence", params={"workspace_id": ids["ws"]},
                      headers=auth(ctok)).json()["campaigns"][0]
    check("a failed refresh is recorded, not raised", camp["fetch_status"] == "error"
          and "503" in camp["fetch_error"], str(camp["fetch_error"])[:120])
    check("the last good ladder survives an outage", len(camp["steps"]) == 4, str(len(camp["steps"])))
    C._get = platform_up

    # ---- the read-only guarantee: a client edits nothing ----
    edits = [
        ("rewrite copy", "patch", f"/api/sequences/variants/{ids['var']}", {"body": "hacked"}),
        ("enable a variant", "patch", f"/api/sequences/variants/{ids['var']}", {"enabled": True}),
        ("add a step", "post", f"/api/sequences/{ids['seq']}/steps", {"name": "X", "purpose": "bump"}),
        ("change a wait", "patch", f"/api/sequences/steps/{ids['step']}", {"wait_days": 99}),
        ("delete a step", "delete", f"/api/sequences/steps/{ids['step']}", None),
        ("add a variant", "post", f"/api/sequences/steps/{ids['step']}/variants", {}),
        ("archive a variant", "post", f"/api/sequences/variants/{ids['var']}/archive", {}),
        ("promote a variant", "post", f"/api/sequences/variants/{ids['var']}/promote", {}),
        ("rename the sequence", "patch", f"/api/sequences/{ids['seq']}", {"name": "renamed"}),
        ("duplicate it", "post", f"/api/sequences/{ids['seq']}/duplicate", {}),
        ("create a sequence", "post", "/api/sequences",
         {"workspace_id": ids["ws"], "name": "new", "template_key": "founder-four"}),
        ("reorder steps", "post", f"/api/sequences/{ids['seq']}/steps/reorder", {"ordered_ids": [ids["step"]]}),
        ("run a quality check", "post", f"/api/sequences/variants/{ids['var']}/quality", {}),
        ("edit an enrichment format", "patch", f"/api/sequences/formats/{ids['ws']}/opening_line", {}),
    ]
    refused = []
    for label, method, url, body in edits:
        call = getattr(client, method)
        r = call(url, json=body, headers=auth(ctok)) if body is not None else call(url, headers=auth(ctok))
        if r.status_code != 403:
            refused.append(f"{label} -> {r.status_code}")
    check(f"client is refused all {len(edits)} sequence edits", not refused, "; ".join(refused))

    # The one deliberate exception: supplying your own case study is evidence FOR
    # the copy, not an edit OF it, and library.py stamps the source server-side.
    r = client.post("/api/sequences/proof",
                    json={"workspace_id": ids["ws"], "name": "Acme",
                          "outcome": "3x qualified replies"}, headers=auth(ctok))
    check("client can still add their own proof", r.status_code == 200, r.text[:160])

    # the copy the client tried to rewrite is untouched
    with session() as db:
        check("variant copy survived the attempts",
              db.get(EmailSequenceVariant, ids["var"]).body == "b")

    # ---- operators still work ----
    r = client.patch(f"/api/sequences/variants/{ids['var']}", json={"body": "operator edit"}, headers=auth(tok))
    check("operator can still edit copy", r.status_code == 200, r.text[:160])

    print(f"\n{sum(1 for _, ok in PASS if ok)}/{len(PASS)} checks passed")


if __name__ == "__main__":
    main()
