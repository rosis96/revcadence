"""End-to-end smoke test: seed → login → workspaces → users → deals → isolation.
Run:  python -m tests.test_smoke   (uses a throwaway SQLite DB)"""
import os
import tempfile

TEST_ROOT = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT}/test.db"
os.environ["JWT_SECRET"] = "test-secret"
# System mail stays OFF here. Set to "" rather than deleted: app.config loads a
# local .env with override=False, so an ABSENT key would be filled in from the
# developer's real SMTP credentials — and this suite would start sending live
# email to its own fixture addresses. An empty key is present, so the file loses.
for _smtp in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"):
    os.environ[_smtp] = ""
os.environ["WHITEBOARD_ASSET_DIR"] = os.path.join(TEST_ROOT, "whiteboard-assets")
os.environ["FORM_UPLOAD_DIR"] = os.path.join(TEST_ROOT, "form-uploads")

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.db import init_db, session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.identity import Membership, Organization, User  # noqa: E402

client = TestClient(app)
PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond)))
    print(("✓" if cond else "✗ FAIL"), name, detail if not cond else "")
    assert cond, f"{name}: {detail}"


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    init_db()

    # ---------------- bootstrap deadlock fix: works ONLY on an empty users table
    r = client.post("/api/auth/bootstrap", json={
        "org": "Bootstrap Co", "email": "boot@x.com", "password": "a-long-password-123"})
    check("bootstrap works when no users exist", r.status_code == 200 and r.json()["role"] == "owner", r.text)
    r = client.post("/api/auth/login", json={"email": "boot@x.com", "password": "a-long-password-123"})
    check("bootstrapped admin can log in", r.status_code == 200)
    r = client.post("/api/auth/bootstrap", json={
        "org": "Evil Co", "email": "evil@x.com", "password": "another-long-password"})
    check("bootstrap permanently 403 once users exist", r.status_code == 403)

    # deactivate the bootstrap user so the rest of the suite runs unchanged
    with session() as db:
        bu = db.query(User).filter(User.email == "boot@x.com").first()
        bu.active = False

    # seed master org + owner directly
    with session() as db:
        org = Organization(name="Ascendly", slug="ascendly")
        db.add(org)
        db.flush()
        u = User(email="rosis@ascendly.one", password_hash=hash_password("master-pw"))
        db.add(u)
        db.flush()
        db.add(Membership(user_id=u.id, org_id=org.id, role="owner", workspace_ids=[]))

    check("healthz", client.get("/healthz").json()["ok"])

    r = client.post("/api/auth/login", json={"email": "rosis@ascendly.one", "password": "wrong"})
    check("wrong password rejected", r.status_code == 401)

    login = client.post("/api/auth/login", json={"email": "rosis@ascendly.one", "password": "master-pw"})
    tok = login.json()["token"]
    refresh_cookie = client.cookies.get(config.REFRESH_COOKIE_NAME)
    set_cookie = login.headers.get("set-cookie", "")
    check("login stores a persistent HttpOnly refresh session",
          bool(refresh_cookie) and "HttpOnly" in set_cookie and "Max-Age=" in set_cookie, set_cookie)

    refreshed = client.post("/api/auth/refresh")
    check("refresh cookie restores an admin access token", refreshed.status_code == 200, refreshed.text)
    refreshed_me = client.get("/api/auth/me", headers=auth(refreshed.json()["token"])).json()
    check("refreshed session keeps the same admin", refreshed_me["user"]["email"] == "rosis@ascendly.one")

    # Existing production browsers initially have only their old access token.
    # They should be upgraded to a refresh-cookie session without another login.
    legacy_browser = TestClient(app)
    migrated = legacy_browser.post("/api/auth/refresh", headers=auth(tok))
    check("existing access-token session migrates without re-login",
          migrated.status_code == 200 and bool(legacy_browser.cookies.get(config.REFRESH_COOKIE_NAME)), migrated.text)

    # A refresh credential must never be usable directly as an API bearer token.
    r = client.get("/api/auth/me", headers=auth(refresh_cookie))
    check("refresh token cannot be used as an access token", r.status_code == 401, r.text)

    cookie_before_bad_login = client.cookies.get(config.REFRESH_COOKIE_NAME)
    r = client.post("/api/auth/login", json={"email": "rosis@ascendly.one", "password": "wrong"})
    check("failed login does not erase an existing browser session",
          r.status_code == 401 and client.cookies.get(config.REFRESH_COOKIE_NAME) == cookie_before_bad_login, r.text)

    # master creates two client workspaces
    w1 = client.post("/api/admin/workspaces", json={"name": "Webaholics", "legacy_name": "Webaholics"}, headers=auth(tok)).json()
    w2 = client.post("/api/admin/workspaces", json={"name": "Shimahara"}, headers=auth(tok)).json()
    check("workspaces created", w1["id"] != w2["id"])

    # master creates a client login locked to workspace 1
    r = client.post("/api/admin/users", json={
        "email": "client@webaholics.com", "password": "client-pw", "role": "client",
        "workspace_ids": [w1["id"]]}, headers=auth(tok))
    check("client user created", r.status_code == 200, r.text)

    r = client.post("/api/admin/users", json={
        "email": "bad@x.com", "password": "x", "role": "client",
        "workspace_ids": [w1["id"], w2["id"]]}, headers=auth(tok))
    check("client with 2 workspaces rejected", r.status_code == 422)

    # A login on another browser/device gets its own cookie and must not replace
    # or revoke the admin's session on this device.
    client_device = TestClient(app)
    ctok = client_device.post("/api/auth/login", json={
        "email": "client@webaholics.com", "password": "client-pw"}).json()["token"]
    admin_still_here = client.post("/api/auth/refresh")
    admin_me = client.get("/api/auth/me", headers=auth(admin_still_here.json()["token"])).json()
    check("another device login does not log out admin",
          admin_still_here.status_code == 200 and admin_me["user"]["email"] == "rosis@ascendly.one")

    me = client.get("/api/auth/me", headers=auth(ctok)).json()
    check("client sees exactly 1 workspace (no switcher)", len(me["workspaces"]) == 1 and not me["is_master"])

    r = client.get("/api/admin/workspaces", headers=auth(ctok))
    check("client blocked from admin", r.status_code == 403)

    # master creates deals in both workspaces
    d1 = client.post("/api/deals", json={"workspace_id": w1["id"], "name": "Webaholics deal", "value": 5000}, headers=auth(tok))
    d2 = client.post("/api/deals", json={"workspace_id": w2["id"], "name": "Shimahara deal", "value": 9000}, headers=auth(tok))
    check("deals created", d1.status_code == 200 and d2.status_code == 200, d1.text + d2.text)

    # THE isolation test: client must see only their workspace's deal
    deals = client.get("/api/deals", headers=auth(ctok)).json()
    check("client sees only own deals", len(deals) == 1 and deals[0]["name"] == "Webaholics deal", str(deals))

    r = client.get("/api/deals", params={"workspace_id": w2["id"]}, headers=auth(ctok))
    check("client requesting other workspace → 403", r.status_code == 403)

    master_deals = client.get("/api/deals", headers=auth(tok)).json()
    check("master sees all workspaces' deals", len(master_deals) == 2)

    # ---------------- Reply Management is the client's own (decision D8)
    # The client configures their connection, formats and rules without us. That
    # moved a block of endpoints off `require_master`, so the workspace check is
    # now the ONLY thing standing between one client and another's reply space —
    # and these are the checks that say so.
    rws1 = client.get(f"/api/reply/workspaces/for/{w1['id']}", headers=auth(ctok))
    check("client reads their own reply space", rws1.status_code == 200, rws1.text)
    rws1 = rws1.json()
    check("reply space carries a server-built webhook url",
          "workspace_name=" in rws1["webhook_url"] or "reply_workspace=" in rws1["webhook_url"],
          rws1.get("webhook_url", ""))
    check("the webhook url never leaks a secret",
          "api_key" not in rws1["webhook_url"] and "api_key" not in rws1)

    r = client.get(f"/api/reply/workspaces/for/{w2['id']}", headers=auth(ctok))
    check("client refused another workspace's reply space", r.status_code == 403, r.text)

    rws2 = client.get(f"/api/reply/workspaces/for/{w2['id']}", headers=auth(tok)).json()
    r = client.get(f"/api/reply/workspaces/{rws2['id']}", headers=auth(ctok))
    check("client refused another reply space by id", r.status_code == 403, r.text)

    spaces = client.get("/api/reply/workspaces", headers=auth(ctok))
    check("client lists only their own reply spaces",
          spaces.status_code == 200
          and {x["workspace_id"] for x in spaces.json()} == {w1["id"]}, spaces.text)

    # The edit path. `_apply` copies `workspace_id` straight off the body, so a
    # client moving their own space into another workspace would be a cross-tenant
    # write through an endpoint that passed its own access check.
    def rws_body(**over):
        body = {k: rws1[k] for k in (
            "workspace_id", "name", "platform", "mode", "active", "base_url",
            "reply_followup_campaign_id", "website", "sender_name", "default_sender_email",
            "calendly_scheduling_url", "ai_provider", "ai_fallback", "client_profile",
            "reply_format", "ai_rules", "reply_delay_seconds")}
        body.update(over)
        return body

    r = client.put(f"/api/reply/workspaces/{rws1['id']}",
                   json=rws_body(sender_name="Priya at Acme"), headers=auth(ctok))
    check("client edits their own reply space",
          r.status_code == 200 and r.json()["sender_name"] == "Priya at Acme", r.text)

    r = client.put(f"/api/reply/workspaces/{rws1['id']}",
                   json=rws_body(workspace_id=w2["id"]), headers=auth(ctok))
    check("client cannot move their reply space to another workspace", r.status_code == 403, r.text)

    r = client.put(f"/api/reply/workspaces/{rws1['id']}",
                   json=rws_body(name=rws2["name"]), headers=auth(ctok))
    check("a colliding reply-space rename is a 409, not a 500", r.status_code == 409, r.text)

    still = client.get(f"/api/reply/workspaces/for/{w1['id']}", headers=auth(ctok)).json()
    check("the refused edits left the reply space untouched",
          still["workspace_id"] == w1["id"] and still["name"] == rws1["name"], str(still)[:200])

    # Extra Channels: a second platform or a separate follow-up space is the
    # client's own sending setup, so they may add one — in their workspace only.
    r = client.post("/api/reply/workspaces",
                    json=rws_body(name="Acme follow-up", mode="followup", platform="instantly"),
                    headers=auth(ctok))
    check("client adds an extra channel in their own workspace",
          r.status_code == 200 and r.json()["workspace_id"] == w1["id"], r.text)
    extra_id = r.json()["id"]

    r = client.post("/api/reply/workspaces",
                    json=rws_body(name="Channel in someone else's", workspace_id=w2["id"]),
                    headers=auth(ctok))
    check("client cannot add a channel to another workspace", r.status_code == 403, r.text)

    r = client.post("/api/reply/workspaces", json=rws_body(name=rws1["name"]), headers=auth(ctok))
    check("a duplicate channel name is refused", r.status_code == 409, r.text)

    r = client.post(f"/api/reply/workspaces/{extra_id}/duplicate", headers=auth(ctok))
    check("a duplicated channel stays in the same workspace",
          r.status_code == 200 and r.json()["workspace_id"] == w1["id"], r.text)

    r = client.post(f"/api/reply/workspaces/{rws2['id']}/duplicate", headers=auth(ctok))
    check("client cannot duplicate another workspace's channel", r.status_code == 403, r.text)

    spaces = client.get("/api/reply/workspaces", headers=auth(ctok)).json()
    check("the client's channel list is still only theirs",
          {x["workspace_id"] for x in spaces} == {w1["id"]}, str(spaces)[:200])

    # Reply Settings: one screen, two scopes. Every value in it is a single value,
    # so the org row is the one thing a client must never reach — otherwise their
    # model, their key and their delay become everybody's.
    r = client.get("/api/reply/settings", headers=auth(tok))
    check("master with no workspace edits the org row",
          r.status_code == 200 and r.json()["scope"] == "org", r.text)

    r = client.get("/api/reply/settings", headers=auth(ctok))
    check("client's reply settings are scoped to their workspace",
          r.status_code == 200 and r.json()["scope"] == "workspace"
          and r.json()["scope_label"] == "Webaholics", r.text)

    r = client.put("/api/reply/settings",
                   json={"openai_model": "gpt-4o-mini", "reply_delay_seconds": "600",
                         "reply_trigger_tag": "Interested"}, headers=auth(ctok))
    check("client saves their own reply settings",
          r.status_code == 200 and r.json()["scope"] == "workspace", r.text)

    got = client.get("/api/reply/settings", headers=auth(ctok)).json()
    check("the client's settings persisted on their reply space",
          got["openai_model"] == "gpt-4o-mini" and got["reply_delay_seconds"] == "600", str(got)[:200])

    # The whole point of the scoping: the org row and the other client are untouched.
    org = client.get("/api/reply/settings", headers=auth(tok)).json()
    check("a client's save never reaches the org row", org["openai_model"] == "", str(org)[:200])
    other = client.get("/api/reply/settings", params={"workspace_id": w2["id"]}, headers=auth(tok)).json()
    check("a client's save never reaches another client", other["openai_model"] == "", str(other)[:200])

    r = client.get("/api/reply/settings", params={"workspace_id": w2["id"]}, headers=auth(ctok))
    check("client refused another workspace's reply settings", r.status_code == 403, r.text)
    r = client.put("/api/reply/settings", params={"workspace_id": w2["id"]},
                   json={"openai_model": "sneaky"}, headers=auth(ctok))
    check("client cannot write another workspace's reply settings", r.status_code == 403, r.text)

    # Setup and Settings edit the same row, so saving one must not blank the other.
    setup = client.get(f"/api/reply/workspaces/for/{w1['id']}", headers=auth(ctok)).json()
    check("Setup sees what Settings wrote", setup["openai_model"] == "gpt-4o-mini", str(setup)[:200])
    r = client.put(f"/api/reply/workspaces/{rws1['id']}",
                   json=rws_body(sender_name="Priya", openai_model=setup["openai_model"],
                                 gemini_model=setup["gemini_model"],
                                 review_webhook_url=setup["review_webhook_url"],
                                 reply_trigger_tag=setup["reply_trigger_tag"],
                                 followup_trigger_tag=setup["followup_trigger_tag"]),
                   headers=auth(ctok))
    check("saving Setup round-trips the Settings values",
          r.status_code == 200 and r.json()["openai_model"] == "gpt-4o-mini"
          and r.json()["reply_trigger_tag"] == "Interested", r.text)

    # ---------------- Outbound is the client's own too
    # Lists, Database and the whole Build group — Client Profile through
    # Workspace Training. The enrichment endpoints were already workspace-scoped;
    # what changed is the training bridge, which additionally demanded
    # owner/admin, and `reoon/balance`, which demanded nothing at all.
    r = client.get("/api/enrich-lists", params={"workspace_id": w1["id"]}, headers=auth(ctok))
    check("client reads their own lists", r.status_code == 200, r.text)
    r = client.get("/api/enrich-lists", params={"workspace_id": w2["id"]}, headers=auth(ctok))
    check("client refused another workspace's lists", r.status_code == 403, r.text)

    r = client.get(f"/api/enrich-lists/config/{w1['id']}", headers=auth(ctok))
    check("client reads their own brain config", r.status_code == 200, r.text)
    check("the brain config never returns the Reoon secret",
          "reoon_api_key" not in r.json() and r.json().get("reoon_api_key_set") in (True, False))
    # Put the ICP back afterwards: the whiteboard-promotion checks further down
    # read this same row and expect the JSON shape the brain writes, not a
    # sentence typed by a test.
    original_icp = r.json()["icp_definition"]

    r = client.put(f"/api/enrich-lists/config/{w1['id']}",
                   json={"icp_definition": "Agencies, 10-50 staff, UK."}, headers=auth(ctok))
    check("client edits their own ICP", r.status_code == 200, r.text)
    got = client.get(f"/api/enrich-lists/config/{w1['id']}", headers=auth(ctok)).json()
    check("the client's ICP persisted",
          got["icp_definition"] == "Agencies, 10-50 staff, UK.", str(got)[:160])

    r = client.get(f"/api/enrich-lists/config/{w2['id']}", headers=auth(ctok))
    check("client refused another workspace's brain config", r.status_code == 403, r.text)
    other = client.get(f"/api/enrich-lists/config/{w2['id']}", headers=auth(tok)).json()
    check("a client's ICP edit never reached the other workspace",
          other["icp_definition"] != "Agencies, 10-50 staff, UK.", str(other)[:160])

    client.put(f"/api/enrich-lists/config/{w1['id']}",
               json={"icp_definition": original_icp}, headers=auth(ctok))
    check("the ICP was restored for the checks that follow",
          client.get(f"/api/enrich-lists/config/{w1['id']}",
                     headers=auth(ctok)).json()["icp_definition"] == original_icp)

    # Workspace Training: was owner/admin-only, now workspace-scoped.
    r = client.get(f"/api/enrich-lists/config/{w1['id']}/training/export", headers=auth(ctok))
    check("client can export their own training package", r.status_code == 200, r.text)
    r = client.get(f"/api/enrich-lists/config/{w2['id']}/training/export", headers=auth(ctok))
    check("client refused another workspace's training package", r.status_code == 403, r.text)
    r = client.get(f"/api/enrich-lists/config/{w1['id']}/training/revisions", headers=auth(ctok))
    check("client reads their own training revisions", r.status_code == 200, r.text)
    r = client.get(f"/api/enrich-lists/config/{w2['id']}/training/revisions", headers=auth(ctok))
    check("client refused another workspace's training revisions", r.status_code == 403, r.text)

    # `reoon/balance` took a workspace_id and checked nothing, so any signed-in
    # account could read any workspace's credit balance off their key.
    r = client.get("/api/enrich-lists/reoon/balance",
                   params={"workspace_id": w2["id"]}, headers=auth(ctok))
    check("client refused another workspace's Reoon balance", r.status_code == 403, r.text)
    r = client.get("/api/enrich-lists/reoon/balance",
                   params={"workspace_id": w1["id"]}, headers=auth(ctok))
    check("client reads their own Reoon balance", r.status_code == 200, r.text)

    # ---------------- Website Visitors lives in the client's Client Space
    # The capture key is the client's: they paste the form URL on their own site,
    # so it is theirs to read. Rotating it stays ours — a rotation silently breaks
    # a live form until someone re-pastes the snippet.
    r = client.get("/api/inbound/config", params={"workspace_id": w1["id"]}, headers=auth(ctok))
    check("client reads their own inbound capture key", r.status_code == 200, r.text)
    own_key = r.json()["inbound_key"]
    check("the capture URL carries that key and a public origin",
          own_key and own_key in r.json()["form_url"]
          and r.json()["form_url"].startswith("http"), r.json().get("form_url", ""))

    r = client.get("/api/inbound/config", params={"workspace_id": w2["id"]}, headers=auth(ctok))
    check("client refused another workspace's capture key", r.status_code == 403, r.text)

    other_key = client.get("/api/inbound/config", params={"workspace_id": w2["id"]},
                           headers=auth(tok)).json()["inbound_key"]
    check("each workspace gets its own capture key", own_key != other_key)

    r = client.get("/api/inbound/visitors", headers=auth(ctok))
    check("client reads their own inbound events", r.status_code == 200, r.text)
    r = client.get("/api/inbound/visitors", params={"workspace_id": w2["id"]}, headers=auth(ctok))
    check("client refused another workspace's inbound events", r.status_code == 403, r.text)

    r = client.post("/api/inbound/rotate", params={"workspace_id": w1["id"]}, headers=auth(ctok))
    check("rotating the capture key stays ours", r.status_code == 403, r.text)

    # ---------------- CRM is the client's own too
    # Pipeline through Onboarding, plus Email Accounts and Client Profile. Most of
    # these were already workspace-scoped; Onboarding additionally demanded
    # owner/admin, which is what kept the screen out of the client's hands.
    for path in ("/api/deals", "/api/companies", "/api/contacts", "/api/activities",
                 "/api/reports/summary", "/api/documents", "/api/invoices",
                 "/api/mailbox", "/api/revenue-inbox", "/api/onboarding"):
        r = client.get(path, params={"workspace_id": w1["id"]}, headers=auth(ctok))
        check(f"client reads {path}", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        r = client.get(path, params={"workspace_id": w2["id"]}, headers=auth(ctok))
        check(f"client refused {path} for another workspace", r.status_code == 403, r.text[:120])

    # Onboarding: create is theirs now, and it lands in their workspace only.
    r = client.post("/api/onboarding", json={"workspace_id": w1["id"]}, headers=auth(ctok))
    check("client starts an onboarding in their own workspace",
          r.status_code == 200 and r.json().get("token"), r.text)
    oid = r.json()["id"]
    r = client.get(f"/api/onboarding/{oid}", headers=auth(ctok))
    check("client opens their own onboarding", r.status_code == 200, r.text)
    r = client.post("/api/onboarding", json={"workspace_id": w2["id"]}, headers=auth(ctok))
    check("client cannot start an onboarding elsewhere", r.status_code == 403, r.text)

    other_onboarding = client.post("/api/onboarding", json={"workspace_id": w2["id"]},
                                   headers=auth(tok)).json()["id"]
    r = client.get(f"/api/onboarding/{other_onboarding}", headers=auth(ctok))
    check("client cannot open another workspace's onboarding", r.status_code == 403, r.text)

    listed = client.get("/api/onboarding", headers=auth(ctok)).json()
    check("the client's onboarding list is only theirs",
          {o["workspace_id"] for o in listed} == {w1["id"]}, str(listed)[:200])

    # Countersigning is RevCadence's signature on an agreement, so it stays ours
    # even though the client owns everything else about the record.
    d1_id = client.get("/api/deals", params={"workspace_id": w1["id"]},
                       headers=auth(ctok)).json()[0]["id"]
    ag = client.post("/api/agreements/generate", json={"deal_id": d1_id}, headers=auth(tok))
    if ag.status_code == 200:
        r = client.post(f"/api/agreements/{ag.json()['id']}/countersign",
                        json={"name": "Client", "title": "Ops"}, headers=auth(ctok))
        check("countersigning an agreement stays ours", r.status_code == 403, r.text)

    board = client.get("/api/deals/board", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    booked = [c for c in board if c["stage"]["name"] == "Opportunity"]
    check("board has default stages + totals", len(board) == 7 and booked and booked[0]["total_value"] == 5000, str(board)[:200])

    stage_meeting = next(c["stage"]["id"] for c in board if c["stage"]["name"] == "Meeting Booked")
    deal_id = booked[0]["deals"][0]["id"]
    r = client.post(f"/api/deals/{deal_id}/move", json={"stage_id": stage_meeting}, headers=auth(tok))
    check("deal moved stage", r.status_code == 200)

    summary = client.get("/api/dashboard/summary", headers=auth(ctok)).json()
    check("client dashboard summary works", summary["open_value"] == 5000 and summary["recent_activity"], str(summary)[:200])

    # ---------------- email sequences: template → quality → preview → approval → rotation
    with session() as _db:
        from app.models.enrich import EnrichConfig as _SeqConfig, EnrichLead as _SeqLead, EnrichList as _SeqList
        cfg = _db.query(_SeqConfig).filter(_SeqConfig.workspace_id == w1["id"]).first()
        cfg.profile = {**(cfg.profile or {}), "case_studies": [{
            "name": "Acme pipeline proof", "outcome": "Acme booked qualified meetings from founder outreach",
        }]}
        prospect_list = _SeqList(workspace_id=w1["id"], name="Sequence preview prospects")
        _db.add(prospect_list); _db.flush()
        for index in range(10):
            _db.add(_SeqLead(
                workspace_id=w1["id"], list_id=prospect_list.id,
                first_name=f"Prospect{index + 1}", last_name="Example",
                title="Founder", company=f"Company {index + 1}",
                website=f"company{index + 1}.example", email=f"p{index + 1}@example.com",
                result={"subject_line": "Founder Outreach",
                        "personalized_first_line": f"Loved how Company {index + 1} explains its specialist work.",
                        "product_complimentary_1": "Your client process is clearly organized. Is that central to delivery?",
                        "product_complimentary_2": "Your specialist offer stays concrete. Is that what clients value most?"},
            ))
        preview_list_id = prospect_list.id

    seq_context = client.get("/api/sequences/context", params={"workspace_id": w1["id"]},
                             headers=auth(tok)).json()
    proof_key = seq_context["proof"][0]["key"]
    r = client.post("/api/sequences", json={
        "workspace_id": w1["id"], "name": "Founder sequence",
        "template_key": "system:founder-four", "angle_name": "Founder relevance",
        "hypothesis": "Specific observations will make the opener worth answering.",
        "proof_key": proof_key,
    }, headers=auth(tok))
    check("sequence created from reusable four-step template",
          r.status_code == 200 and len(r.json()["steps"]) == 4, r.text)
    seq = r.json(); sequence_id = seq["id"]
    r = client.patch(f"/api/sequences/{sequence_id}", json={"current_list_id": preview_list_id},
                     headers=auth(tok))
    check("sequence tied to its current real-prospect list", r.status_code == 200, r.text)
    seq = r.json()

    opener = seq["steps"][0]
    variant_a = opener["variants"][0]
    r = client.patch(f"/api/sequences/variants/{variant_a['id']}", json={
        "subject": "{{subject_line}}",
        "body": "Hi {{first_name}},\n\n{{personalized_first_line}}\n\nWorth comparing notes?",
    }, headers=auth(tok))
    check("operator writes a plain-text opener", r.status_code == 200 and not r.json()["enabled"], r.text)

    missing_note = client.post(f"/api/sequences/steps/{opener['id']}/variants", json={
        "from_variant_id": variant_a["id"],
    }, headers=auth(tok))
    check("a B+ variant cannot be created without its change note", missing_note.status_code == 422,
          missing_note.text)

    variants = []
    for note in ("adds a direct question", "leads with the researched observation"):
        made = client.post(f"/api/sequences/steps/{opener['id']}/variants", json={
            "from_variant_id": variant_a["id"], "change_note": note,
        }, headers=auth(tok))
        check(f"variant {made.json().get('label', '?')} stores its required change note",
              made.status_code == 200 and made.json()["change_note"] == note, made.text)
        variants.append(made.json())

    # Every step must have at least one checked, enabled send candidate. Enable A
    # throughout, plus the two tested opener variants.
    current = client.get(f"/api/sequences/{sequence_id}", headers=auth(tok)).json()
    to_enable = [step["variants"][0]["id"] for step in current["steps"]] + [v["id"] for v in variants]
    for variant_id in to_enable:
        checked = client.post(f"/api/sequences/variants/{variant_id}/quality", headers=auth(tok))
        check("variant passes existing send-quality gates", checked.status_code == 200 and checked.json()["passed"], checked.text)
        enabled = client.patch(f"/api/sequences/variants/{variant_id}", json={"enabled": True}, headers=auth(tok))
        check("only a checked variant can enter rotation", enabled.status_code == 200 and enabled.json()["enabled"], enabled.text)

    preview = client.get(f"/api/sequences/{sequence_id}/preview", params={
        "list_id": preview_list_id, "variant_id": variant_a["id"],
    }, headers=auth(tok))
    check("sequence previews against ten real prospects",
          preview.status_code == 200 and preview.json()["count"] == 10
          and all(row["lead_id"] for row in preview.json()["prospects"]), preview.text[:300])
    check("preview marks enrichment output as generated",
          any(part["kind"] == "generated" for part in preview.json()["prospects"][0]["body_parts"]),
          str(preview.json()["prospects"][0]["body_parts"]))

    submitted = client.post(f"/api/sequences/{sequence_id}/submit-approval",
                            json={"note": "Ready for client review"}, headers=auth(tok))
    check("operator submits the entire sequence tree for approval",
          submitted.status_code == 200 and submitted.json()["status"] == "in_review", submitted.text)
    client_view = client.get(f"/api/sequences/{sequence_id}", headers=auth(ctok))
    check("client reads the same four-email sequence", client_view.status_code == 200
          and len(client_view.json()["steps"]) == 4, client_view.text)
    approved = client.post(f"/api/sequences/{sequence_id}/approve", json={"note": "Approved"},
                           headers=auth(ctok))
    check("client approval pins the sequence", approved.status_code == 200
          and approved.json()["status"] == "approved", approved.text)

    performance = client.post(f"/api/sequences/variants/{variants[1]['id']}/performance", json={
        "sent": 100, "replies": 12, "positive": 7, "meetings": 3,
    }, headers=auth(tok))
    check("variant performance stores real counts and computed rates",
          performance.status_code == 200 and performance.json()["performance"]["reply_rate"] == 12.0,
          performance.text)
    promoted = client.post(f"/api/sequences/variants/{variant_a['id']}/promote", headers=auth(tok))
    check("operator can promote the winning variant", promoted.status_code == 200
          and promoted.json()["promoted"], promoted.text)
    archived = client.post(f"/api/sequences/variants/{variants[1]['id']}/archive", headers=auth(tok))
    check("losing variant is archived, never deleted", archived.status_code == 200, archived.text)
    after_archive = client.get(f"/api/sequences/{sequence_id}", headers=auth(tok)).json()
    archived_copy = next(v for s in after_archive["steps"] for v in s["variants"]
                         if v["id"] == variants[1]["id"])
    check("archived loser stays visible with statistics intact",
          archived_copy["archived"] and archived_copy["performance"]["meetings"] == 3,
          str(archived_copy))

    disabled_id = variants[0]["id"]
    disabled = client.patch(f"/api/sequences/variants/{disabled_id}", json={"enabled": False},
                            headers=auth(tok))
    check("a tested variant can be disabled without deletion",
          disabled.status_code == 200 and not disabled.json()["enabled"], disabled.text)
    rotated = [client.post(f"/api/sequences/steps/{opener['id']}/next-variant", headers=auth(tok)).json()["id"]
               for _ in range(6)]
    check("next-send rotation excludes a disabled variant", disabled_id not in rotated, str(rotated))
    with session() as _db:
        from app.models.sequences import EmailSequenceApproval as _SeqApproval
        pinned = _db.query(_SeqApproval).filter(_SeqApproval.sequence_id == sequence_id,
                                                _SeqApproval.status == "approved").first()
        pinned_b = next(v for s in pinned.snapshot["steps"] for v in s["variants"] if v["id"] == disabled_id)
        check("approval snapshot stays immutable after later copy changes", pinned_b["enabled"] is True,
              str(pinned_b))

    other_sequence = client.post("/api/sequences", json={
        "workspace_id": w2["id"], "name": "Other org-facing sequence",
        "template_key": "system:founder-four",
    }, headers=auth(tok)).json()
    cross_workspace = client.get(f"/api/sequences/{other_sequence['id']}", headers=auth(ctok))
    check("cross-workspace sequence ids fail closed with 404", cross_workspace.status_code == 404,
          cross_workspace.text)
    added_proof = client.post("/api/sequences/proof", json={
        "workspace_id": w1["id"], "name": "Client-provided launch proof",
        "outcome": "The client confirmed the launch generated qualified replies",
    }, headers=auth(ctok))
    check("client can add missing evidence at the linked proof library",
          added_proof.status_code == 200 and added_proof.json()["proof"]["label"] == "Client-provided launch proof",
          added_proof.text)
    check("evidence added by a client is tagged client_supplied, not verified",
          added_proof.json()["proof"]["source"] == "client_supplied"
          and added_proof.json()["proof"]["named_claim_allowed"] is False,
          str(added_proof.json()["proof"]))

    # ---------------- library: provenance, usage, verification, exclusions
    lib = client.get("/api/library", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    check("library reads the three tabs plus its inbox in one request",
          {"case_studies", "segments", "icp_tests", "unfiled", "counts"} <= set(lib)
          and lib["counts"]["case_studies"] == 1, str(lib.get("counts")))
    check("proof still sitting in the client brain shows as unfiled",
          any(item["label"] == "Acme pipeline proof" for item in lib["unfiled"]), str(lib["unfiled"]))

    # `source` is never client-settable: the body asks for `verified` and is ignored.
    claimed = client.post("/api/library/case-studies", json={
        "workspace_id": w1["id"], "client_name": "Harlow Group",
        "engagement": "brand sprint", "segment": "Professional services", "year": 2025,
        "outcome": "Client reports doubled close rate.", "source": "verified",
        "source_url": "https://example.test/not-real"}, headers=auth(ctok))
    check("a client cannot promote its own evidence to verified",
          claimed.status_code == 200
          and next(c for c in claimed.json()["case_studies"]
                   if c["client_name"] == "Harlow Group")["source"] == "client_supplied",
          claimed.text)
    harlow = next(c for c in claimed.json()["case_studies"] if c["client_name"] == "Harlow Group")
    check("an unverified record says what it may still be used for",
          harlow["named_claim_allowed"] is False and "background" in harlow["limitation"].lower(),
          str(harlow))

    no_link = client.post("/api/library/case-studies", json={
        "workspace_id": w1["id"], "client_name": "Northline", "outcome": "180k of pipeline.",
        "source": "verified"}, headers=auth(tok))
    check("verified evidence without a checkable link is refused", no_link.status_code == 422,
          no_link.text)
    client_verify = client.post(f"/api/library/case-studies/{harlow['id']}/verify",
                                json={"source_url": "https://example.test/harlow"}, headers=auth(ctok))
    check("a client cannot verify evidence", client_verify.status_code == 403, client_verify.text)

    # The rule with teeth: a client-supplied fact must never become a named claim.
    named_seq = client.post("/api/sequences", json={
        "workspace_id": w1["id"], "name": "Named-claim guard", "template_key": "system:founder-four",
        "angle_name": "Harlow proof", "hypothesis": "A peer result earns a reply.",
        "proof_key": harlow["proof_key"]}, headers=auth(tok)).json()
    named_variant = named_seq["steps"][0]["variants"][0]
    client.patch(f"/api/sequences/variants/{named_variant['id']}", json={
        "subject": "A question about your close rate",
        "body": "Hi {{first_name}},\n\nHarlow Group doubled their close rate with the same "
                "programme. Worth a look?"}, headers=auth(tok))
    guarded = client.post(f"/api/sequences/variants/{named_variant['id']}/quality",
                          headers=auth(tok)).json()
    check("client-supplied evidence cannot become a named claim in copy",
          guarded["passed"] is False
          and any(i["code"] == "unverified_named_claim" for i in guarded["issues"]),
          str(guarded["issues"]))
    blocked_enable = client.patch(f"/api/sequences/variants/{named_variant['id']}",
                                  json={"enabled": True}, headers=auth(tok))
    check("a variant naming unverified evidence cannot be enabled",
          blocked_enable.status_code == 422, blocked_enable.text[:200])

    verified = client.post(f"/api/library/case-studies/{harlow['id']}/verify",
                           json={"source_url": "https://harlow.example/case-study"},
                           headers=auth(tok))
    check("verifying stamps the source, the link and who checked it",
          verified.status_code == 200
          and next(c for c in verified.json()["case_studies"]
                   if c["id"] == harlow["id"])["verified"] is True
          and next(c for c in verified.json()["case_studies"]
                   if c["id"] == harlow["id"])["verified_by"], verified.text[:200])
    now_ok = client.post(f"/api/sequences/variants/{named_variant['id']}/quality",
                         headers=auth(tok)).json()
    check("the same copy passes once the evidence is verified",
          not any(i["code"] == "unverified_named_claim" for i in now_ok["issues"]),
          str(now_ok["issues"]))
    check("quality reports the evidence it judged against",
          now_ok["evidence"]["verified"] is True
          and now_ok["evidence"]["proof_key"] == harlow["proof_key"], str(now_ok["evidence"]))

    # Editing what somebody checked retires the verification rather than keeping it.
    reworded = client.patch(f"/api/library/case-studies/{harlow['id']}",
                            json={"outcome": "Close rate went from 12% to 24%."},
                            headers=auth(tok)).json()
    check("rewriting a verified claim drops it back to unverified",
          next(c for c in reworded["case_studies"] if c["id"] == harlow["id"])["source"] == "operator",
          str(next(c for c in reworded["case_studies"] if c["id"] == harlow["id"])))
    client.post(f"/api/library/case-studies/{harlow['id']}/verify",
                json={"source_url": "https://harlow.example/case-study"}, headers=auth(tok))

    in_use = client.delete(f"/api/library/case-studies/{harlow['id']}", headers=auth(tok))
    check("evidence under a live angle cannot be removed silently",
          in_use.status_code == 409 and "Harlow proof" in in_use.text, in_use.text[:200])

    # Usage is counted from the angles and variants that exist, never stored.
    client.post(f"/api/sequences/variants/{named_variant['id']}/performance",
                json={"sent": 312, "replies": 9, "positive": 4, "meetings": 2}, headers=auth(tok))
    counted = client.get("/api/library", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    harlow_now = next(c for c in counted["case_studies"] if c["id"] == harlow["id"])
    check("a case study reports the angles and emails leaning on it",
          harlow_now["usage"]["angles"] == 1 and harlow_now["usage"]["emails"] == 312,
          str(harlow_now["usage"]))

    # Segments: the in-list figure is counted from the linked list, not typed in.
    seg = client.post("/api/library/segments", json={
        "workspace_id": w1["id"], "name": "Founder-led agencies, 10-50 staff",
        "company_type": "Independent creative agencies", "headcount": "10-50",
        "geography": "UK & Ireland", "tam_estimate": 400, "source": "operator",
        "enrich_list_id": preview_list_id}, headers=auth(tok))
    made_seg = seg.json()["segments"][0]
    check("a segment counts its in-list prospects from the real list",
          seg.status_code == 200 and made_seg["in_list"] == 10 and made_seg["coverage"] == 2.5,
          str(made_seg))
    foreign_list = client.post("/api/library/segments", json={
        "workspace_id": w1["id"], "name": "Cross-tenant probe", "source": "operator",
        "enrich_list_id": 999999}, headers=auth(tok))
    check("a segment cannot borrow another workspace's list", foreign_list.status_code == 422,
          foreign_list.text[:160])

    # ICP tests: a verdict is a record of what happened, so it needs the result.
    undecided = client.post("/api/library/icp-tests", json={
        "workspace_id": w1["id"], "hypothesis": "Ops leads reply more than founders.",
        "verdict": "validated", "source": "operator"}, headers=auth(tok))
    check("a decided ICP test needs its result written down", undecided.status_code == 422,
          undecided.text[:160])
    test_made = client.post("/api/library/icp-tests", json={
        "workspace_id": w1["id"], "hypothesis": "Ops leads reply more than founders.",
        "verdict": "testing", "sample_size": 120, "segment_id": made_seg["id"],
        "source": "operator"}, headers=auth(tok))
    check("an open ICP test records the question and the segment it runs on",
          test_made.status_code == 200
          and test_made.json()["icp_tests"][0]["verdict"] == "testing"
          and test_made.json()["icp_tests"][0]["segment_name"] == made_seg["name"],
          test_made.text[:200])

    # Exclusions: client-owned, and applied before research spends anything.
    excluded = client.post("/api/library/exclusions", json={
        "workspace_id": w1["id"], "value": "https://WWW.Blocked-Co.com/about",
        "label": "Blocked Co", "reason": "existing customer"}, headers=auth(ctok))
    check("an excluded account is normalised to its domain",
          excluded.status_code == 200 and excluded.json()["exclusions"][0]["value"] == "blocked-co.com",
          excluded.text[:200])
    with session() as _db:
        from app.enrichment.pipeline import process_lead as _process
        from app.library.store import exclusion_reason as _reason
        from app.models.enrich import EnrichConfig as _EC2, EnrichLead as _EL2
        check("the exclusion matches the whole domain and not a substring",
              bool(_reason(_db, w1["id"], website="blocked-co.com"))
              and not _reason(_db, w1["id"], website="notblocked-co.com"))
        excluded_lead = _EL2(workspace_id=w1["id"], list_id=preview_list_id,
                             first_name="Do", last_name="NotContact", title="Founder",
                             company="Blocked Co", website="blocked-co.com",
                             email="chief@blocked-co.com")
        _db.add(excluded_lead); _db.flush()
        cfg2 = _db.query(_EC2).filter(_EC2.workspace_id == w1["id"]).first()
        # No network is reachable from this check: the exclusion has to stop the
        # lead BEFORE the first verify call, which is the only version of a
        # do-not-contact list that costs nothing.
        status = _process(_db, excluded_lead, cfg2)
        check("research skips a do-not-contact account before it spends anything",
              status == "skipped" and not excluded_lead.free_status
              and "do-not-contact" in (excluded_lead.icp_reason or ""),
              f"{status} / {excluded_lead.free_status} / {excluded_lead.icp_reason}")

    # Objections stay in the brain, which already stores and merges them.
    objected = client.post("/api/library/objections", json={
        "workspace_id": w1["id"], "objection": "We already have an SDR team.",
        "response": "This runs alongside them and hands over booked calls."}, headers=auth(ctok))
    check("an objection lands in the client brain with its source",
          objected.status_code == 200
          and any(o["objection"].startswith("We already have")
                  and o["source"] == "client_supplied" for o in objected.json()["objections"]),
          str(objected.json()["objections"]))

    # Filing the brain inbox moves the angle with its proof, instead of orphaning it.
    with session() as _db:
        from app.models.sequences import EmailAngle as _Angle
        legacy_angle = (_db.query(_Angle).filter(_Angle.workspace_id == w1["id"],
                                                 _Angle.proof_key.like("case_studies:%")).first())
        legacy_key = legacy_angle.proof_key if legacy_angle else ""
    filed = client.post("/api/library/import-unfiled", json={"workspace_id": w1["id"]},
                        headers=auth(tok))
    check("filing the brain inbox creates records and empties it",
          filed.status_code == 200 and filed.json()["imported"]["imported"] >= 1
          and not filed.json()["unfiled"], filed.text[:200])
    with session() as _db:
        from app.models.sequences import EmailAngle as _Angle2
        moved = (_db.query(_Angle2).filter(_Angle2.workspace_id == w1["id"],
                                           _Angle2.proof_key == legacy_key).first())
        check("filing repoints the angle onto the record instead of orphaning it",
              legacy_key.startswith("case_studies:") and moved is None, legacy_key)
    still_ok = client.get("/api/library", params={"workspace_id": w1["id"]},
                          headers=auth(tok)).json()
    check("the imported record carries the angle's usage with it",
          any(c["client_name"] == "Acme pipeline proof" and c["usage"]["angles"] == 1
              for c in still_ok["case_studies"]),
          str([(c["client_name"], c["usage"]) for c in still_ok["case_studies"]]))

    # Multi-tenancy, in the data layer: a bare record id must not leak existence.
    other_study = client.post("/api/library/case-studies", json={
        "workspace_id": w2["id"], "client_name": "Other tenant", "outcome": "Not yours.",
        "source": "operator"}, headers=auth(tok)).json()["case_studies"][0]
    cross = client.patch(f"/api/library/case-studies/{other_study['id']}",
                         json={"outcome": "Rewritten from another tenant."}, headers=auth(ctok))
    check("cross-workspace library ids fail closed with 404", cross.status_code == 404, cross.text)
    cross_read = client.get("/api/library", params={"workspace_id": w2["id"]}, headers=auth(ctok))
    check("a client cannot read another workspace's library", cross_read.status_code == 403,
          cross_read.text[:160])

    # What the screen branches on: a client may add but never verify, and the
    # brain inbox is ours — showing a client "9 unfiled items" reads as a mess
    # they caused.
    client_view = client.get("/api/library", params={"workspace_id": w1["id"]},
                             headers=auth(ctok)).json()
    check("a client can contribute but cannot verify",
          client_view["is_client"] is True and client_view["can_edit"] is True
          and client_view["can_verify"] is False and client_view["unfiled"] == [],
          str({k: client_view[k] for k in ("is_client", "can_edit", "can_verify")}))
    previewed = client.get("/api/library", params={"workspace_id": w1["id"]},
                           headers={**auth(tok), "X-Client-Preview": "1"}).json()
    check("previewing as the client is read-only and hides the inbox",
          previewed["can_edit"] is False and previewed["unfiled"] == [], str(previewed["can_edit"]))
    preview_write = client.post("/api/library/case-studies", json={
        "workspace_id": w1["id"], "client_name": "Written from a preview",
        "outcome": "Should not exist.", "source": "operator"},
        headers={**auth(tok), "X-Client-Preview": "1"})
    check("the client preview cannot be acted through", preview_write.status_code == 403,
          preview_write.text[:160])

    # ---------------- shared documents: workspace scoping + client visibility
    # Every page below is created by the master in w1. The client is locked to
    # w1, so these prove the visibility filter, not just the workspace filter.
    # Pages live inside folders, so each workspace needs one first.
    r = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "strategy", "kind": "folder",
        "title": "Strategy", "icon": "Target"}, headers=auth(tok))
    check("root folder created", r.status_code == 200 and r.json()["kind"] == "folder", r.text)
    home = r.json()

    r = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "strategy", "title": "Loose page"}, headers=auth(tok))
    check("a page cannot be created outside a folder", r.status_code == 422, r.text)

    r = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "strategy", "kind": "folder",
        "parent_id": home["id"], "title": "Nested folder"}, headers=auth(tok))
    check("folders do not nest", r.status_code == 422, r.text)

    r = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "strategy", "parent_id": home["id"],
        "title": "ICP Definition"}, headers=auth(tok))
    check("page created blank inside a folder", r.status_code == 200
          and r.json()["visibility"] == "internal" and r.json()["parent_id"] == home["id"], r.text)
    page1 = r.json()

    blocks = client.get(f"/api/workspace/pages/{page1['id']}", headers=auth(tok)).json()["blocks"]
    check("blank page starts with one text block",
          len(blocks) == 1 and blocks[0]["type"] == "text", str(blocks))

    w2_home = client.post("/api/workspace/pages", json={
        "workspace_id": w2["id"], "section": "strategy", "kind": "folder",
        "title": "Strategy"}, headers=auth(tok)).json()
    r = client.post("/api/workspace/pages", json={
        "workspace_id": w2["id"], "section": "strategy", "parent_id": w2_home["id"],
        "title": "Other workspace page"}, headers=auth(tok))
    check("page created in the other workspace", r.status_code == 200, r.text)
    other_page = r.json()

    # THE isolation test: a bare page id from another workspace must 404, not 403 —
    # a 403 would confirm the id exists.
    r = client.get(f"/api/workspace/pages/{other_page['id']}", headers=auth(ctok))
    check("client requesting another workspace's page id → 404", r.status_code == 404, r.text)

    # An internal page in the client's OWN workspace must be equally invisible.
    r = client.get(f"/api/workspace/pages/{page1['id']}", headers=auth(ctok))
    check("client requesting an internal page → 404", r.status_code == 404, r.text)

    tree = client.get("/api/workspace/pages/tree", headers=auth(ctok)).json()
    check("client tree hides internal pages", tree["pages"] == [] and tree["can_share"] is False, str(tree))

    r = client.post(f"/api/workspace/pages/{page1['id']}/share", headers=auth(tok))
    check("share flips visibility + status", r.status_code == 200
          and r.json()["visibility"] == "shared" and r.json()["status"] == "in_review", r.text)

    r = client.get(f"/api/workspace/pages/{page1['id']}", headers=auth(ctok))
    check("client reads the page once shared", r.status_code == 200, r.text)

    # ---------------- the sidebar must show every page its reader may open
    #
    # `page1` is shared, and it lives in a folder we kept internal. Grouping it
    # under a parent the client cannot see would drop it from their sidebar
    # entirely: they would read "No folders yet" while we look at a full tree of
    # the same workspace. This mirrors what PageTree draws — a page renders when
    # it is a root, or when its folder is in the same list.
    def rendered(tree):
        pages = tree["pages"]
        visible = {p["id"] for p in pages}
        roots, kids = [], {}
        for p in pages:
            if p["parent_id"] and p["parent_id"] in visible:
                kids.setdefault(p["parent_id"], []).append(p)
            else:
                roots.append(p)
        out = []
        for r in roots:
            out.append(r["id"])
            out.extend(k["id"] for k in kids.get(r["id"], []))
        return out

    ctree = client.get("/api/workspace/pages/tree", headers=auth(ctok)).json()
    check("a shared page in an internal folder still reaches the client sidebar",
          page1["id"] in rendered(ctree), str(ctree["pages"]))
    check("every page the client may open is one the sidebar draws",
          rendered(ctree) and len(rendered(ctree)) == len(ctree["pages"]), str(ctree["pages"]))

    # ---------------- pulse: the change-stamp both shells poll to stay in step
    #
    # The stamps are opaque. What has to hold is that each moves when the other
    # side needs to refetch, and stays put otherwise — a stamp that moves on our
    # internal work would tell a client that something changed, and a stamp that
    # sits still would leave their screen stale.
    def pulse(token, **params):
        return client.get("/api/workspace/pulse", params=params, headers=auth(token)).json()

    before = pulse(ctok, page_id=page1["id"])
    check("the client gets a stamp for the page they have open", before["page"] is not None, str(before))

    client.patch(f"/api/workspace/blocks/{blocks[0]['id']}",
                 json={"content": {"html": "<p>Who we sell to.</p>"}}, headers=auth(tok))
    edited = pulse(ctok, page_id=page1["id"])
    check("our edit moves the client's page stamp", edited["page"] != before["page"],
          f"{before['page']} -> {edited['page']}")
    check("our edit does not move the client's tree stamp — the sidebar is unchanged",
          edited["tree"] == before["tree"], f"{before['tree']} -> {edited['tree']}")

    hidden = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "strategy", "parent_id": home["id"],
        "title": "What this costs us"}, headers=auth(tok)).json()
    quiet = pulse(ctok, page_id=page1["id"])
    check("an internal page does not tell the client anything changed",
          quiet["tree"] == edited["tree"], f"{edited['tree']} -> {quiet['tree']}")
    check("the same page does move our own tree stamp",
          pulse(tok, workspace_id=w1["id"])["tree"] != quiet["tree"])

    client.post(f"/api/workspace/pages/{hidden['id']}/share", headers=auth(tok))
    shared = pulse(ctok, page_id=page1["id"])
    check("sharing is what moves the client's tree stamp",
          shared["tree"] != quiet["tree"], f"{quiet['tree']} -> {shared['tree']}")
    check("and the newly shared page is one their sidebar draws",
          hidden["id"] in rendered(client.get("/api/workspace/pages/tree", headers=auth(ctok)).json()))

    client.post("/api/workspace/comments", json={
        "page_id": page1["id"], "block_id": blocks[0]["id"], "body": "Can we add verticals?"},
        headers=auth(ctok))
    check("a comment from the client moves the stamp we are watching",
          pulse(tok, workspace_id=w1["id"], page_id=page1["id"])["page"] != edited["page"])

    check("another client's workspace is invisible to this one's stamp",
          pulse(ctok, page_id=page1["id"])["tree"] == shared["tree"])
    check("a page id out of reach reports no page rather than an error",
          pulse(ctok, page_id=other_page["id"])["page"] is None)

    # ---------------- embedded whiteboard: conflict safety, promotion, generation
    #
    # The board is a tldraw document snapshot. The server does not own the record
    # schema — tldraw does — so these fixtures mirror tldraw's shape exactly where
    # we read meaning out of it: `meta.note_type` for the tag, `props.richText`
    # for the words, and binding rows for what an arrow connects.
    def rich(text):
        return {"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}]}

    def card(key, note_type, text, x, y):
        return {"id": f"shape:{key}", "typeName": "shape", "type": "geo", "x": x, "y": y,
                "parentId": "page:page", "index": "a1", "rotation": 0, "isLocked": False,
                "opacity": 1, "meta": {"note_type": note_type},
                "props": {"geo": "rectangle", "w": 240, "h": 144, "fill": "solid",
                          "color": "blue", "richText": rich(text)}}

    def arrow(key, start, end):
        return {f"shape:{key}": {"id": f"shape:{key}", "typeName": "shape", "type": "arrow",
                                 "x": 0, "y": 0, "parentId": "page:page", "index": "a1",
                                 "rotation": 0, "isLocked": False, "opacity": 1, "meta": {},
                                 "props": {"color": "grey"}},
                f"binding:{key}s": {"id": f"binding:{key}s", "typeName": "binding", "type": "arrow",
                                    "fromId": f"shape:{key}", "toId": f"shape:{start}",
                                    "meta": {}, "props": {"terminal": "start"}},
                f"binding:{key}e": {"id": f"binding:{key}e", "typeName": "binding", "type": "arrow",
                                    "fromId": f"shape:{key}", "toId": f"shape:{end}",
                                    "meta": {}, "props": {"terminal": "end"}}}

    board_store = {shape["id"]: shape for shape in [
        card("seg1", "segment", "B2B agencies", 48, 48),
        card("seg2", "segment", "Specialist consultancies", 336, 48),
        card("seg3", "segment", "Founder-led SaaS", 624, 48),
        card("seg4", "segment", "Revenue operations firms", 912, 48),
        card("proof1", "proof", "Acme added 31 qualified meetings", 48, 288),
        card("trigger1", "trigger", "Hiring the first SDR", 336, 288),
        card("reject1", "reject", "Consumer-only business", 624, 288),
    ]}
    board_store.update(arrow("link1", "seg1", "proof1"))
    board_store.update(arrow("link2", "seg1", "trigger1"))
    board_content = {"kind": "tldraw",
                     "snapshot": {"store": board_store, "schema": {"schemaVersion": 2}}}

    r = client.post(f"/api/workspace/pages/{page1['id']}/blocks", json={
        "type": "whiteboard", "content": board_content}, headers=auth(tok))
    check("whiteboard is an ordinary document block", r.status_code == 200
          and r.json()["type"] == "whiteboard" and r.json()["revision"] == 1, r.text)
    board = r.json()

    rejected = client.post(f"/api/workspace/pages/{page1['id']}/blocks", json={
        "type": "whiteboard", "content": {"shapes": [], "connectors": []}}, headers=auth(tok))
    check("a board in an unknown format is refused, not half-stored",
          rejected.status_code == 422, rejected.text)

    moved_store = {**board_store}
    moved_store["shape:seg1"] = {**moved_store["shape:seg1"], "x": 72}
    moved_content = {"kind": "tldraw", "snapshot": {"store": moved_store,
                                                    "schema": {"schemaVersion": 2}}}
    moved = client.patch(f"/api/workspace/blocks/{board['id']}", json={
        "content": moved_content, "base_revision": 1}, headers=auth(tok))
    check("whiteboard save advances its optimistic revision",
          moved.status_code == 200 and moved.json()["revision"] == 2, moved.text)
    stale = client.patch(f"/api/workspace/blocks/{board['id']}", json={
        "content": board["content"], "base_revision": 1}, headers=auth(tok))
    check("stale whiteboard save is stopped instead of overwriting",
          stale.status_code == 409 and stale.json()["detail"]["current"]["revision"] == 2, stale.text)

    image = client.post(f"/api/workspace/blocks/{board['id']}/whiteboard/images",
                        files={"file": ("clipboard.png", b"\x89PNG\r\n\x1a\nboard-image", "image/png")},
                        headers=auth(tok))
    check("pasted whiteboard image is accepted as a private asset",
          image.status_code == 200 and image.json()["content_type"] == "image/png", image.text)
    asset_id = image.json()["id"]
    check("upload answers with the only src a board may store",
          image.json()["src"] == f"/api/workspace/whiteboard/assets/{asset_id}", image.text)

    with_image = {"kind": "tldraw", "snapshot": {"schema": {"schemaVersion": 2}, "store": {
        **moved_store,
        f"asset:{asset_id}": {"id": f"asset:{asset_id}", "typeName": "asset", "type": "image",
                              "meta": {}, "props": {"src": image.json()["src"], "w": 288, "h": 240}},
    }}}
    image_saved = client.patch(f"/api/workspace/blocks/{board['id']}", json={
        "content": with_image, "base_revision": 2}, headers=auth(tok))
    check("pasted image becomes a board asset", image_saved.status_code == 200, image_saved.text)
    revision = image_saved.json()["revision"]

    # An image is the one place a board can be told to fetch something. Both the
    # inline blob (which would bloat the row) and the foreign host (which would
    # leak the board through a referer) are refused at the boundary.
    for label, src in (("a data: blob", "data:image/png;base64,iVBORw0KGgo="),
                       ("someone else's host", "https://example.com/leak.png"),
                       ("an asset from another workspace", "/api/workspace/whiteboard/assets/99999")):
        hostile = {"kind": "tldraw", "snapshot": {"schema": {"schemaVersion": 2}, "store": {
            "asset:x": {"id": "asset:x", "typeName": "asset", "type": "image",
                        "meta": {}, "props": {"src": src}}}}}
        blocked_asset = client.patch(f"/api/workspace/blocks/{board['id']}", json={
            "content": hostile, "base_revision": revision}, headers=auth(tok))
        check(f"a board image may not point at {label}",
              blocked_asset.status_code == 422, blocked_asset.text)

    shown = client.get(f"/api/workspace/whiteboard/assets/{asset_id}", headers=auth(ctok))
    check("shared-page client can view the authenticated board image",
          shown.status_code == 200 and shown.headers["content-type"].startswith("image/png"), str(shown.status_code))
    presence = client.post(f"/api/workspace/blocks/{board['id']}/whiteboard/presence", headers=auth(ctok))
    check("client and operator share the board permission model",
          presence.status_code == 200 and any(v["is_you"] for v in presence.json()["viewers"]), presence.text)

    promoted = []
    for shape_id in ("shape:seg1", "shape:seg2", "shape:seg3", "shape:seg4", "shape:proof1"):
        r = client.post(f"/api/workspace/blocks/{board['id']}/whiteboard/promote", json={
            "shape_id": shape_id, "base_revision": revision}, headers=auth(tok))
        check(f"whiteboard note {shape_id} promoted", r.status_code == 200, r.text)
        promoted.append(r.json()["promotion"])
        revision = r.json()["block"]["revision"]
    check("four segment records and one case-study record created",
          [p["kind"] for p in promoted].count("segment") == 4
          and [p["kind"] for p in promoted].count("case_study") == 1, str(promoted))
    with session() as _db:
        import json as _json
        from app.models.enrich import EnrichConfig as _EC
        cfg = _db.query(_EC).filter(_EC.workspace_id == w1["id"]).first()
        icp = _json.loads(cfg.icp_definition)
        check("promoted segments feed the real ICP source of truth",
              all(value in icp["icp_categories"] for value in
                  ("B2B agencies", "Specialist consultancies", "Founder-led SaaS", "Revenue operations firms")),
              cfg.icp_definition)
        # A promoted proof note becomes a Library record, not another entry in the
        # brain's JSON: it carries a mandatory source and a stable id an angle can
        # point at. Whiteboard shorthand lands as `operator` — usable as
        # background, not nameable in an email until somebody verifies it.
        from app.models.library import LibraryCaseStudy as _LibCase
        promoted_rows = (_db.query(_LibCase)
                         .filter(_LibCase.workspace_id == w1["id"],
                                 _LibCase.note.like("Promoted from a whiteboard%")).all())
        check("promoted proof becomes a Library record with mandatory provenance",
              len(promoted_rows) == 1 and promoted_rows[0].source == "operator"
              and promoted_rows[0].source != "verified",
              str([(r.client_name, r.source) for r in promoted_rows]))

    generated = client.post(f"/api/workspace/blocks/{board['id']}/whiteboard/generate-page",
                            json={}, headers=auth(tok))
    check("board deterministically generates a new editable shared draft",
          generated.status_code == 200 and generated.json()["status"] == "draft"
          and generated.json()["visibility"] == "shared", generated.text)
    generated_doc = client.get(f"/api/workspace/pages/{generated.json()['id']}", headers=auth(ctok))
    generated_blocks = generated_doc.json()["blocks"] if generated_doc.status_code == 200 else []
    check("client can read and comment on the generated document",
          generated_doc.status_code == 200 and any(block["type"] == "table" for block in generated_blocks)
          and any("B2B agencies" in str(block["content"]) for block in generated_blocks), generated_doc.text)

    other_board = client.post(f"/api/workspace/pages/{other_page['id']}/blocks", json={
        "type": "whiteboard", "content": {"kind": "tldraw", "snapshot": None}},
        headers=auth(tok)).json()
    blocked = client.patch(f"/api/workspace/blocks/{other_board['id']}", json={
        "content": other_board["content"], "base_revision": 1}, headers=auth(ctok))
    check("client cannot discover another workspace's whiteboard block", blocked.status_code == 404, blocked.text)

    # ---------------- the workspace whiteboard: one canvas, opened not created
    opened = client.get("/api/workspace/whiteboard", params={"workspace_id": w1["id"]},
                        headers=auth(tok))
    check("opening the section brings the workspace's one board into being",
          opened.status_code == 200 and opened.json()["board"]["type"] == "whiteboard"
          and opened.json()["board"]["content"] == {"kind": "tldraw", "snapshot": None},
          opened.text)
    board_page_id = opened.json()["page_id"]
    again = client.get("/api/workspace/whiteboard", params={"workspace_id": w1["id"]},
                       headers=auth(tok))
    check("opening it a second time returns the same board, never another",
          again.status_code == 200 and again.json()["board"]["id"] == opened.json()["board"]["id"]
          and again.json()["page_id"] == board_page_id, again.text)

    # The client draws on the *same* canvas. An internal board would be invisible
    # to them, and they would quietly end up with a second one.
    client_opened = client.get("/api/workspace/whiteboard", headers=auth(ctok))
    check("the client opens the same board the team does",
          client_opened.status_code == 200
          and client_opened.json()["board"]["id"] == opened.json()["board"]["id"]
          and client_opened.json()["can_share"] is False, client_opened.text)

    board_page = client.get(f"/api/workspace/pages/{board_page_id}", headers=auth(tok))
    check("the board is one whiteboard block on a shared page of its own",
          board_page.status_code == 200
          and [b["type"] for b in board_page.json()["blocks"]] == ["whiteboard"]
          and board_page.json()["page"]["kind"] == "whiteboard"
          and board_page.json()["page"]["visibility"] == "shared", board_page.text)

    tree = client.get("/api/workspace/pages/tree", params={"workspace_id": w1["id"]},
                      headers=auth(tok))
    check("the board stays out of the page tree — it has its own section",
          tree.status_code == 200
          and board_page_id not in [p["id"] for p in tree.json()["pages"]], tree.text)
    refused = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "kind": "whiteboard", "title": "A second canvas",
        "section": "strategy"}, headers=auth(tok))
    check("there is no second path to a second board", refused.status_code == 422, refused.text)

    # ---------------- the canvas has no edge: negative coordinates survive
    far_card = card("far1", "question", "Off to the left", -2400, -1200)
    far = {"kind": "tldraw", "snapshot": {"schema": {"schemaVersion": 2},
                                          "store": {far_card["id"]: far_card}}}
    placed = client.patch(f"/api/workspace/blocks/{opened.json()['board']['id']}", json={
        "content": far, "base_revision": opened.json()["board"]["revision"]}, headers=auth(tok))
    saved = (placed.json()["content"]["snapshot"]["store"]["shape:far1"]
             if placed.status_code == 200 else {})
    check("a shape sits where it was put, including far off the origin",
          placed.status_code == 200 and (saved.get("x"), saved.get("y")) == (-2400, -1200), placed.text)

    # The store is tldraw's, so the guard that matters is what a board may cost —
    # not a field-by-field check this side could only get wrong.
    huge = {"kind": "tldraw", "snapshot": {"schema": {"schemaVersion": 2}, "store": {
        f"shape:bulk{i}": card(f"bulk{i}", "question", "x" * 200, i, i) for i in range(21000)}}}
    refused_size = client.patch(f"/api/workspace/blocks/{opened.json()['board']['id']}", json={
        "content": huge, "base_revision": placed.json()["revision"]}, headers=auth(tok))
    check("a runaway board is refused rather than stored",
          refused_size.status_code in (413, 422), str(refused_size.status_code))

    # ---------------- invite-only forms: hostile token boundary + mapping + org isolation
    form = client.post("/api/forms", json={"name": "Client onboarding"}, headers=auth(tok))
    check("org-level form created from scratch", form.status_code == 200, form.text)
    form_id = form.json()["id"]
    question = client.post(f"/api/forms/{form_id}/questions", json={
        "type": "short_text", "label": "Positioning to confirm", "required": True,
        "maps_to": "brain.positioning", "prefill_source": "crawl.positioning",
    }, headers=auth(tok))
    check("mapped form question created", question.status_code == 200, question.text)
    question_id = question.json()["id"]
    # The two Library-bound mappings: an onboarding answer is client-supplied by
    # definition, and the do-not-contact answer arrives as a mix of addresses,
    # domains and company names.
    proof_q = client.post(f"/api/forms/{form_id}/questions", json={
        "type": "long_text", "label": "A result you are happy for us to reference",
        "maps_to": "library.case_study"}, headers=auth(tok))
    dnc_q = client.post(f"/api/forms/{form_id}/questions", json={
        "type": "long_text", "label": "Anyone we should never contact",
        "maps_to": "library.do_not_contact"}, headers=auth(tok))
    check("Library-bound form questions created",
          proof_q.status_code == 200 and dnc_q.status_code == 200,
          f"{proof_q.text[:80]} / {dnc_q.text[:80]}")
    proof_qid, dnc_qid = proof_q.json()["id"], dnc_q.json()["id"]
    published = client.post(f"/api/forms/{form_id}/publish", headers=auth(tok))
    check("form published with a pinned version", published.status_code == 200
          and published.json()["version"] == 1, published.text)

    import secrets as _secrets
    from datetime import UTC as _UTC, datetime as _datetime, timedelta as _timedelta
    _now = _datetime.now(_UTC).replace(tzinfo=None)
    with session() as _db:
        from app.models.forms import FormInvite as _FI
        good_token = _secrets.token_urlsafe(32)
        expired_token = _secrets.token_urlsafe(32)
        _db.add(_FI(form_id=form_id, form_version=1, workspace_id=w1["id"],
                    recipient_email="client@webaholics.com", recipient_name="Client",
                    known_context={"invite.contact_name": "Client",
                                   "invite.contact_email": "client@webaholics.com",
                                   "crawl.positioning": "Old positioning"},
                    token=good_token, status="sent",
                    expires_at=_now + _timedelta(days=30)))
        _db.add(_FI(form_id=form_id, form_version=1, workspace_id=w1["id"],
                    recipient_email="expired@webaholics.com", recipient_name="Expired",
                    known_context={}, token=expired_token, status="expired",
                    expires_at=_now - _timedelta(seconds=1)))

    invalid_form = client.get("/api/public/forms/" + ("x" * 43))
    expired_form = client.get(f"/api/public/forms/{expired_token}")
    check("invalid public form token rejected", invalid_form.status_code == 404, invalid_form.text)
    check("expired public form token rejected identically", expired_form.status_code == 404
          and expired_form.json() == invalid_form.json(), expired_form.text)
    expired_write = client.post(f"/api/public/forms/{expired_token}/save",
                                json={"answers": {str(question_id): "x"}})
    check("an expired token cannot write either", expired_write.status_code == 404
          and expired_write.json() == invalid_form.json(), expired_write.text)

    # The unauthenticated page must load the invite and the form and nothing
    # else. It renders inside the client dashboard, so "it is only a form" has
    # to be true of the payload, not just of the screen.
    opened = client.get(f"/api/public/forms/{good_token}")
    check("token route returns only the form, details and answers",
          opened.status_code == 200
          and set(opened.json()) == {"form", "space_name", "details", "answers",
                                     "edited_question_ids", "status"},
          str(sorted(opened.json()))[:200])
    check("the routing target of an answer never reaches the filler",
          all("maps_to" not in q for q in opened.json()["form"]["questions"]),
          str(opened.json()["form"]["questions"][0])[:200])
    check("what we already know arrives pre-filled, as a confirm",
          any(q.get("prefill_value") == "Old positioning" and q.get("display_mode") == "confirm"
              for q in opened.json()["form"]["questions"]),
          str(opened.json()["form"]["questions"])[:200])

    # Started on the emailed link, finished after logging in: one response, not
    # two. This is the whole reason both routes resolve the same invite.
    part = client.post(f"/api/public/forms/{good_token}/save", json={
        "answers": {str(question_id): "Half-written positioning"},
        "details": {}, "edited_question_ids": [question_id]})
    check("a partial answer saves from the token route", part.status_code == 200
          and part.json()["response_version"] == 1, part.text)
    resumed = client_device.get("/api/client-space/onboarding-form/fill", headers=auth(ctok))
    check("logging in continues the same half-finished response",
          resumed.status_code == 200
          and resumed.json()["answers"].get(str(question_id)) == "Half-written positioning",
          resumed.text[:200])
    with session() as _db:
        from app.models.forms import FormResponse as _FR
        check("continuing did not open a second response",
              _db.query(_FR).filter(_FR.form_id == form_id).count() == 1)

    # The builder is ours. A client must not reach it, by nav or by URL.
    check("a client cannot list forms", client_device.get(
        "/api/forms", headers=auth(ctok)).status_code == 403)
    check("a client cannot open the builder", client_device.get(
        f"/api/forms/{form_id}", headers=auth(ctok)).status_code == 403)
    check("a client cannot reach the internal Setup screen", client_device.get(
        "/api/client-space/onboarding-form", params={"workspace_id": w1["id"]},
        headers=auth(ctok)).status_code == 404)

    submitted = client.post(f"/api/public/forms/{good_token}/submit", json={
        "answers": {str(question_id): "Pipeline clarity for specialist firms",
                    str(proof_qid): "Ridgeway cut cost per meeting by 40% in one quarter.",
                    # What a real answer looks like: a pasted blob, one per line,
                    # with the punctuation a copy-paste drags along.
                    str(dnc_qid): "- rival-co.com\n\"someone@bigcustomer.test\",\nBigcustomer Group"},
        "details": {"name": "Client", "email": "client@webaholics.com"},
        "edited_question_ids": [question_id, proof_qid, dnc_qid],
    })
    check("public submission applies a mapped answer", submitted.status_code == 200
          and submitted.json()["mapping"]["applied"] >= 1, submitted.text)
    with session() as _db:
        from app.models.enrich import EnrichConfig as _FormEC
        cfg = _db.query(_FormEC).filter(_FormEC.workspace_id == w1["id"]).first()
        check("form mapping merged into the client brain",
              "Pipeline clarity for specialist firms" in (cfg.profile.get("positioning") or []),
              str(cfg.profile.get("positioning")))
        from app.models.library import (LibraryCaseStudy as _FormCase,
                                        LibraryExclusion as _FormExcl)
        from app.models.reply import ReplyBlock as _FormBlock
        form_case = (_db.query(_FormCase)
                     .filter(_FormCase.workspace_id == w1["id"],
                             _FormCase.note == "From the onboarding form.").first())
        check("an onboarding answer becomes a client_supplied Library record",
              form_case is not None and form_case.source == "client_supplied"
              and "40%" in (form_case.outcome or ""),
              str(form_case and (form_case.client_name, form_case.source)))
        form_excl = {(r.kind, r.value) for r in _db.query(_FormExcl)
                     .filter(_FormExcl.workspace_id == w1["id"]).all()}
        check("the do-not-contact answer lands as domain, email and company exclusions",
              {("domain", "rival-co.com"), ("email", "someone@bigcustomer.test"),
               ("company", "Bigcustomer Group")} <= form_excl, str(sorted(form_excl)))
        check("an excluded address is mirrored into inbound reply blocking",
              _db.query(_FormBlock).filter(_FormBlock.workspace_id == w1["id"],
                                           _FormBlock.email == "someone@bigcustomer.test").first()
              is not None)

        other_org = Organization(name="Other tenant", slug="other-tenant")
        _db.add(other_org); _db.flush()
        other_owner = User(email="owner@other.test", password_hash=hash_password("other-owner-password"))
        _db.add(other_owner); _db.flush()
        _db.add(Membership(user_id=other_owner.id, org_id=other_org.id,
                           role="owner", workspace_ids=[]))
    other_login = client.post("/api/auth/login", json={
        "email": "owner@other.test", "password": "other-owner-password"})
    other_token = other_login.json()["token"]
    cross_org_form = client.get(f"/api/forms/{form_id}", headers=auth(other_token))
    check("cross-org form access fails closed with 404", cross_org_form.status_code == 404,
          cross_org_form.text)

    # Duplicate is the reuse mechanism, in place of a template library: it copies
    # the questions and nothing else follows the copy afterwards.
    copy = client.post(f"/api/forms/{form_id}/duplicate", headers=auth(tok))
    check("a form duplicates into an independent draft", copy.status_code == 200
          and copy.json()["status"] == "draft" and copy.json()["version"] == 1
          and copy.json()["duplicated_from_id"] == form_id, copy.text)
    copy_id = copy.json()["id"]
    copied = client.get(f"/api/forms/{copy_id}", headers=auth(tok))
    check("the copy carries every question",
          len(copied.json()["questions"]) == len(
              client.get(f"/api/forms/{form_id}", headers=auth(tok)).json()["questions"]),
          copied.text[:160])

    # A mapping target that is not implemented yet must be a logged skip, never a
    # failed submission — most targets are null in this version, and the client
    # has done their part either way.
    unmapped_q = client.post(f"/api/forms/{copy_id}/questions", json={
        "type": "short_text", "label": "Who signs off copy?",
        "maps_to": "approval.copy_approver"}, headers=auth(tok))
    client.post(f"/api/forms/{copy_id}/publish", headers=auth(tok))
    with session() as _db:
        from app.models.forms import FormInvite as _FI2
        unmapped_token = _secrets.token_urlsafe(32)
        _db.add(_FI2(form_id=copy_id, form_version=1, workspace_id=w1["id"],
                     recipient_email="ops@webaholics.com", recipient_name="Ops",
                     known_context={}, token=unmapped_token, status="sent",
                     expires_at=_now + _timedelta(days=30)))
    # The copy inherited the original's required questions, so answer them all —
    # what is under test here is the mapping, not the required-field gate.
    copy_answers = {str(q["id"]): "Dana"
                    for q in client.get(f"/api/forms/{copy_id}", headers=auth(tok)).json()["questions"]}
    unmapped = client.post(f"/api/public/forms/{unmapped_token}/submit", json={
        "answers": copy_answers, "details": {}, "edited_question_ids": []})
    check("an unimplemented mapping target is skipped, not fatal",
          unmapped.status_code == 200 and unmapped.json()["mapping"]["skipped"] >= 1,
          unmapped.text[:200])

    # Editing a published form must not reshape a response already in flight.
    client.patch(f"/api/forms/{form_id}", json={"name": "Client onboarding v2"},
                 headers=auth(tok))
    still = client.get(f"/api/public/forms/{good_token}")
    check("an in-flight invite keeps rendering the version it was sent",
          still.status_code == 200 and still.json()["form"]["version"] == 1,
          str(still.json()["form"].get("version")))

    r = client.post(f"/api/workspace/pages/{page1['id']}/share", headers=auth(ctok))
    check("client cannot share", r.status_code == 403)

    r = client.post("/api/workspace/pages", json={
        "section": "internal", "kind": "folder", "title": "Sneaky"}, headers=auth(ctok))
    check("client cannot create an internal page", r.status_code == 403, r.text)

    # The client needs a folder they can actually see, so share one first.
    shared_home = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "operations", "kind": "folder",
        "title": "Shared with you"}, headers=auth(tok)).json()
    client.post(f"/api/workspace/pages/{shared_home['id']}/share", headers=auth(tok))

    r = client.post("/api/workspace/pages", json={
        "section": "operations", "parent_id": home["id"], "title": "Into an internal folder"},
        headers=auth(ctok))
    check("client cannot add a page to an internal folder", r.status_code == 404, r.text)

    r = client.post("/api/workspace/pages", json={
        "section": "operations", "parent_id": shared_home["id"], "title": "Client note"},
        headers=auth(ctok))
    check("client page is born shared + client-owned", r.status_code == 200
          and r.json()["visibility"] == "shared" and r.json()["owner_role"] == "client", r.text)

    # ---------------- folders: a page nests in a folder, never in a document
    r = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "strategy", "kind": "folder",
        "title": "Targeting", "icon": "Target"}, headers=auth(tok))
    check("folder created with an icon", r.status_code == 200 and r.json()["kind"] == "folder"
          and r.json()["icon"] == "Target", r.text)
    folder = r.json()

    folder_doc = client.get(f"/api/workspace/pages/{folder['id']}", headers=auth(tok)).json()
    check("a folder holds no blocks", folder_doc["blocks"] == [], str(folder_doc["blocks"]))

    r = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "strategy", "parent_id": folder["id"],
        "title": "Segments", "icon": "Users"}, headers=auth(tok))
    check("page created inside the folder", r.status_code == 200
          and r.json()["parent_id"] == folder["id"] and r.json()["icon"] == "Users", r.text)
    nested = r.json()

    r = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "strategy", "parent_id": page1["id"], "title": "Nope"},
        headers=auth(tok))
    check("a page cannot nest inside a document", r.status_code == 422, r.text)

    r = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "strategy", "kind": "folder",
        "template_id": 1, "title": "Bad folder"}, headers=auth(tok))
    check("a folder cannot be built from a template", r.status_code in (404, 422), r.text)

    r = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "strategy", "kind": "bogus", "title": "x"}, headers=auth(tok))
    check("unknown page kind rejected", r.status_code == 422)

    r = client.post(f"/api/workspace/pages/{folder['id']}/archive", headers=auth(tok))
    check("archiving a folder archives what it holds",
          r.status_code == 200 and r.json()["archived_children"] == 1, r.text)
    ids = [p["id"] for p in client.get("/api/workspace/pages/tree", headers=auth(tok)).json()["pages"]]
    check("no orphaned page left behind", nested["id"] not in ids and folder["id"] not in ids, str(ids))

    # ---------------- blocks: create, edit, reorder, delete
    b1 = client.post(f"/api/workspace/pages/{page1['id']}/blocks", json={
        "type": "heading", "content": {"level": 2, "text": "Who we target"}}, headers=auth(tok))
    b2 = client.post(f"/api/workspace/pages/{page1['id']}/blocks", json={
        "type": "table", "content": {"columns": ["Segment", "Size"], "rows": [["Agencies", "50"]]}},
        headers=auth(tok))
    check("blocks created", b1.status_code == 200 and b2.status_code == 200, b1.text + b2.text)

    r = client.post(f"/api/workspace/pages/{page1['id']}/blocks", json={
        "type": "not_a_block", "content": {}}, headers=auth(tok))
    check("unknown block type rejected", r.status_code == 422)

    r = client.patch(f"/api/workspace/blocks/{b1.json()['id']}", json={
        "content": {"level": 2, "text": "Who we actually target"}}, headers=auth(tok))
    check("block content saved", r.status_code == 200
          and r.json()["content"]["text"] == "Who we actually target", r.text)

    ids = [b["id"] for b in client.get(
        f"/api/workspace/pages/{page1['id']}", headers=auth(tok)).json()["blocks"]]
    r = client.post(f"/api/workspace/pages/{page1['id']}/blocks/reorder",
                    json={"ordered_ids": list(reversed(ids))}, headers=auth(tok))
    check("blocks reordered", r.status_code == 200, r.text)
    after = [b["id"] for b in client.get(
        f"/api/workspace/pages/{page1['id']}", headers=auth(tok)).json()["blocks"]]
    check("reorder persisted", after == list(reversed(ids)), f"{ids} -> {after}")

    r = client.post(f"/api/workspace/pages/{other_page['id']}/blocks/reorder",
                    json={"ordered_ids": ids}, headers=auth(tok))
    check("blocks from another page rejected", r.status_code == 422)

    # ---------------- versions: snapshot, mutate, restore
    r = client.post(f"/api/workspace/pages/{page1['id']}/versions",
                    json={"note": "before edits"}, headers=auth(tok))
    check("version saved", r.status_code == 200 and r.json()["version"] == 1, r.text)
    vid = client.get(f"/api/workspace/pages/{page1['id']}/versions", headers=auth(tok)).json()[0]["id"]

    client.delete(f"/api/workspace/blocks/{b1.json()['id']}", headers=auth(tok))
    shrunk = client.get(f"/api/workspace/pages/{page1['id']}", headers=auth(tok)).json()["blocks"]
    check("block deleted", len(shrunk) == len(after) - 1, str(len(shrunk)))

    r = client.post(f"/api/workspace/pages/{page1['id']}/restore/{vid}", headers=auth(tok))
    check("version restored", r.status_code == 200, r.text)
    restored = client.get(f"/api/workspace/pages/{page1['id']}", headers=auth(tok)).json()["blocks"]
    check("restore brought the block back", len(restored) == len(after), str(len(restored)))
    check("restore is itself undoable (snapshot taken first)",
          len(client.get(f"/api/workspace/pages/{page1['id']}/versions", headers=auth(tok)).json()) == 2)

    # ---------------- comments: anchored, threaded, resolvable, author-only delete
    heading_id = next(b["id"] for b in restored if b["type"] == "heading")
    r = client.post("/api/workspace/comments", json={
        "page_id": page1["id"], "block_id": heading_id, "body": "Can we widen this?"}, headers=auth(ctok))
    check("client comments on a shared block", r.status_code == 200, r.text)
    thread_root = r.json()

    r = client.post("/api/workspace/comments", json={
        "page_id": page1["id"], "block_id": heading_id,
        "parent_id": thread_root["id"], "body": "Yes — updated."}, headers=auth(tok))
    check("reply threads under the root", r.status_code == 200
          and r.json()["parent_id"] == thread_root["id"], r.text)

    r = client.delete(f"/api/workspace/comments/{thread_root['id']}", headers=auth(tok))
    check("non-author cannot delete a comment", r.status_code == 403)

    r = client.post(f"/api/workspace/comments/{thread_root['id']}/resolve", headers=auth(tok))
    check("comment resolved", r.status_code == 200 and r.json()["resolved_at"], r.text)

    r = client.get("/api/workspace/comments", params={"page_id": other_page["id"]}, headers=auth(ctok))
    check("client cannot list comments on another workspace's page", r.status_code == 404)

    # ---------------- templates: unticked text stripped, entity_id dropped
    with session() as _db:
        from app.models.workspace_docs import Block as _B
        bound = _B(page_id=page1["id"], position=99, type="live",
                   content={"display": "ICP"}, entity_type="icp", entity_id=4242,
                   field_path="icp_definition")
        _db.add(bound)

    r = client.post("/api/workspace/page-templates", json={
        "from_page_id": page1["id"], "name": "ICP starter",
        "keep_text_block_ids": [heading_id]}, headers=auth(tok))
    check("template saved", r.status_code == 200, r.text)

    with session() as _db:
        from app.models.workspace_docs import PageTemplate as _T
        tpl = _db.query(_T).filter(_T.name == "ICP starter").first()
        by_type = {b["type"]: b for b in tpl.blocks}
        check("ticked block keeps its text",
              by_type["heading"]["content"]["text"] == "Who we actually target", str(by_type["heading"]))
        check("unticked table keeps columns, loses rows",
              by_type["table"]["content"]["columns"] == ["Segment", "Size"]
              and by_type["table"]["content"]["rows"] == [], str(by_type["table"]))
        check("bound block keeps entity_type + field_path",
              by_type["live"]["entity_type"] == "icp"
              and by_type["live"]["field_path"] == "icp_definition", str(by_type["live"]))
        check("template drops entity_id (never point at another workspace's record)",
              "entity_id" not in by_type["live"], str(by_type["live"]))
        tpl_id = tpl.id

    r = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "template_id": tpl_id, "section": "strategy",
        "parent_id": home["id"], "title": "From template"}, headers=auth(tok))
    check("page created from template", r.status_code == 200, r.text)
    from_tpl = client.get(f"/api/workspace/pages/{r.json()['id']}", headers=auth(tok)).json()
    check("template blocks copied", len(from_tpl["blocks"]) == len(tpl.blocks), str(len(from_tpl["blocks"])))

    r = client.post("/api/workspace/page-templates", json={
        "from_page_id": page1["id"], "name": "Nope"}, headers=auth(ctok))
    check("client cannot save templates", r.status_code == 403)

    # ---------------- duplicate, sanitised
    r = client.post(f"/api/workspace/pages/{page1['id']}/duplicate",
                    json={"sanitize": True}, headers=auth(tok))
    check("page duplicated", r.status_code == 200 and r.json()["title"].endswith("(copy)"), r.text)
    dup = client.get(f"/api/workspace/pages/{r.json()['id']}", headers=auth(tok)).json()
    dup_by_type = {b["type"]: b for b in dup["blocks"]}
    check("sanitised duplicate keeps headings whole",
          dup_by_type["heading"]["content"]["text"] == "Who we actually target", str(dup_by_type["heading"]))
    check("sanitised duplicate drops table rows",
          dup_by_type["table"]["content"]["rows"] == []
          and dup_by_type["table"]["content"]["columns"] == ["Segment", "Size"], str(dup_by_type["table"]))
    check("sanitised duplicate is internal again", dup["page"]["visibility"] == "internal", str(dup["page"]))

    r = client.post(f"/api/workspace/pages/{page1['id']}/archive", headers=auth(tok))
    check("page archived (soft)", r.status_code == 200, r.text)
    titles = [p["title"] for p in client.get(
        "/api/workspace/pages/tree", headers=auth(tok)).json()["pages"]]
    check("archived page leaves the tree", "ICP Definition" not in titles, str(titles))

    # ---------------- workspace aliases (the migration-mapping system)
    r = client.post("/api/admin/aliases", json={
        "workspace_id": w1["id"], "source_system": "reply_manager",
        "external_name": "Ascendly: mainreplybison"}, headers=auth(tok))
    check("alias created", r.status_code == 200, r.text)
    r2 = client.post("/api/admin/aliases", json={
        "workspace_id": w1["id"], "source_system": "enrichment", "external_name": "Ascendly"},
        headers=auth(tok))
    check("2nd alias (different source) → same workspace", r2.status_code == 200, r2.text)

    r = client.post("/api/admin/aliases", json={
        "workspace_id": w2["id"], "source_system": "reply_manager",
        "external_name": "Ascendly: mainreplybison"}, headers=auth(tok))
    check("duplicate (source, name) rejected 409", r.status_code == 409)

    r = client.post("/api/admin/aliases", json={
        "workspace_id": w1["id"], "source_system": "bogus", "external_name": "x"}, headers=auth(tok))
    check("unknown source rejected", r.status_code == 422)

    aliases = client.get("/api/admin/aliases", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    check("one workspace holds multiple aliases", len(aliases) == 2, str(aliases))

    r = client.get("/api/admin/aliases", headers=auth(ctok))
    check("client blocked from aliases", r.status_code == 403)

    # resolution honors source_system + never guesses similar names
    from app.db import SessionLocal as _SL
    from scripts.import_legacy import resolve_workspaces
    db2 = _SL()
    res = resolve_workspaces(db2, ["Ascendly: mainreplybison", "Ascendly", "Ascendlyy"], source="reply_manager")
    check("alias resolves exact name", res["Ascendly: mainreplybison"]["workspace"].id == w1["id"])
    check("enrichment-only alias NOT visible to reply_manager source",
          res["Ascendly"]["workspace"] is None)
    check("similar name is NOT guessed", res["Ascendlyy"]["workspace"] is None)
    db2.close()

    # ---------------- importer end-to-end against a fixture legacy DB
    import sqlite3 as _sq
    import tempfile as _tf
    legacy_path = _tf.mktemp(suffix=".db")
    lc = _sq.connect(legacy_path)
    lc.executescript("""
      CREATE TABLE crm_stages (id INTEGER PRIMARY KEY, name TEXT);
      INSERT INTO crm_stages VALUES (1,'Opportunity'),(2,'Meeting Booked');
      CREATE TABLE leads (id INTEGER PRIMARY KEY, workspace_name TEXT, email TEXT, name TEXT,
        company TEXT, reply_text TEXT, main_reply TEXT, replied INTEGER, thread TEXT,
        intent TEXT, confidence TEXT, campaign TEXT, created_at TIMESTAMP);
      INSERT INTO leads VALUES
        (11,'Ascendly: mainreplybison','amy@acme.com','Amy Pond','Acme Co','yes interested',
         'great, here are times',1,'[]','simple_positive','high','C1','2026-06-01 10:00:00'),
        (12,'Old Unknown Client','bob@beta.com','Bob','Beta LLC','tell me more','',0,'[]',
         'question','med','C2','2026-06-02 10:00:00');
      CREATE TABLE opportunities (id INTEGER PRIMARY KEY, workspace_name TEXT, lead_id TEXT,
        deal_name TEXT, contact_name TEXT, email TEXT, company TEXT, website TEXT,
        stage_id INTEGER, lead_intent TEXT, status TEXT, value REAL, owner TEXT,
        description TEXT, next_action_date TEXT, tag_ids TEXT, close_date TEXT, source TEXT,
        next_step TEXT, meeting_outcome TEXT, location TEXT, contact_linkedin TEXT,
        company_linkedin TEXT, created_at TIMESTAMP);
      INSERT INTO opportunities VALUES (21,'Ascendly: mainreplybison','11','Acme deal','Amy Pond',
        'amy@acme.com','Acme Co','',2,'simple_positive','hot',7500,'','','','[]','','','','','','','',
        '2026-06-03 10:00:00');
    """)
    lc.commit(); lc.close()

    from scripts.import_legacy import run_import
    # apply with an unmapped name must ABORT before writing anything
    rep = run_import(f"sqlite:///{legacy_path}", dry_run=False)
    check("apply aborts on unmapped workspace", rep["aborted"] and rep["unmapped_workspaces"] == ["Old Unknown Client"], str(rep))
    db3 = _SL()
    from app.models.crm import Contact as _C
    check("abort wrote nothing", db3.query(_C).count() == 0, str(db3.query(_C).count()))
    db3.close()

    # map the second name via alias → apply succeeds
    client.post("/api/admin/aliases", json={
        "workspace_id": w2["id"], "source_system": "reply_manager",
        "external_name": "Old Unknown Client"}, headers=auth(tok))
    rep = run_import(f"sqlite:///{legacy_path}", dry_run=False)
    check("import applied via aliases",
          not rep["aborted"] and rep["contacts_created"] == 2 and rep["deals_created"] == 1, str(rep))
    db3 = _SL()
    amy = db3.query(_C).filter(_C.email == "amy@acme.com").first()
    bob = db3.query(_C).filter(_C.email == "bob@beta.com").first()
    check("contacts landed in correct canonical workspaces",
          amy.workspace_id == w1["id"] and bob.workspace_id == w2["id"])
    rep2 = run_import(f"sqlite:///{legacy_path}", dry_run=False)
    check("re-run is idempotent", rep2["contacts_created"] == 0 and rep2["deals_created"] == 0, str(rep2))
    db3.close()

    # job queue: enqueue + run one job through the worker inline
    r = client.post("/api/jobs", json={"kind": "noop", "workspace_id": w1["id"], "payload": {"hello": 1}}, headers=auth(tok))
    check("job enqueued", r.status_code == 200, r.text)
    from app.db import SessionLocal
    from app.workers.runner import _claim, run_one
    db = SessionLocal()
    job = _claim(db)
    run_one(db, job)
    check("worker ran job", job.status == "done" and job.result.get("ok"), job.error)
    db.close()

    # ---------------- enrichment engine E2E (demo mode, no network)
    FAKE_HTML = """<html><head><title>Acme Landscaping — Commercial Grounds</title>
      <meta name="description" content="Acme provides commercial landscaping for businesses across Utah.">
      </head><body><p>We offer commercial mowing, snow removal and grounds care.
      Our clients are businesses, HOAs and property management companies.</p></body></html>"""

    co = client.post("/api/companies", json={"workspace_id": w1["id"], "name": "Acme Landscaping",
                                             "website": "acme-landscaping.example"}, headers=auth(tok)).json()
    ct = client.post("/api/contacts", json={"workspace_id": w1["id"], "email": "jane@acme.example",
                                            "first_name": "Jane", "last_name": "Doe",
                                            "title": "Founder & CEO", "company_id": co["id"]},
                     headers=auth(tok)).json()
    r = client.post("/api/enrich", json={"workspace_id": w1["id"], "company_ids": [co["id"]],
                                         "contact_ids": [ct["id"]], "html_override": FAKE_HTML},
                    headers=auth(tok))
    check("enrichment jobs queued", r.status_code == 200 and r.json()["queued"] == 2, r.text)

    r = client.post("/api/enrich", json={"workspace_id": w2["id"], "company_ids": [co["id"]]}, headers=auth(tok))
    check("cross-workspace enrich rejected", r.status_code == 404)

    from app.db import SessionLocal as _SL2
    from app.workers.runner import _claim as _claim2, run_one as _run2
    dbw = _SL2()
    for _ in range(3):
        jb = _claim2(dbw)
        if jb:
            _run2(dbw, jb)
    dbw.close()

    cdet = client.get(f"/api/companies/{co['id']}", headers=auth(tok)).json()
    check("company enriched (industry + icp + provenance)",
          cdet["industry"] and cdet["icp_fit"] and "last_crawl" in cdet["enrichment"], str(cdet)[:200])
    tdet = client.get(f"/api/contacts/{ct['id']}", headers=auth(tok)).json()
    check("contact scored (senior founder + valid company)", (tdet["revenue_score"] or 0) >= 60, str(tdet)[:200])

    jid = r2j = client.post("/api/blueprints/generate", json={"workspace_id": w1["id"],
                                                              "company_id": co["id"], "contact_id": ct["id"]},
                            headers=auth(tok)).json()["job_id"]
    dbw = _SL2()
    jb = _claim2(dbw)
    _run2(dbw, jb)
    dbw.close()
    st = client.get(f"/api/jobs/{jid}/status", headers=auth(tok)).json()
    check("blueprint job done with progress", st["status"] == "done" and st["result"].get("document_id"), str(st)[:200])
    doc = client.get(f"/api/documents/{st['result']['document_id']}", headers=auth(tok)).json()
    check("blueprint document generated",
          doc["kind"] == "blueprint" and "Acme Landscaping" in doc["html"] and "Executive Summary" in doc["html"])

    docs_client = client.get("/api/documents", headers=auth(ctok)).json()
    check("client sees only own-workspace documents", all(d["workspace_id"] == w1["id"] for d in docs_client))

    # --- custom blueprint upload: BYO HTML → its own slug + public link, like a generated one
    up = client.post("/api/blueprints/upload", json={
        "workspace_id": w1["id"], "title": "Acme Custom Page",
        "html": "<!doctype html><html><body><h1>Custom Landing</h1></body></html>"}, headers=auth(tok)).json()
    check("custom blueprint uploaded", up["kind"] == "blueprint" and up["slug"] and up["fields"].get("generator") == "uploaded", str(up)[:200])
    pub = client.put(f"/api/documents/{up['id']}", json={"published": True}, headers=auth(tok)).json()
    page = client.get(f"/p/{pub['slug']}")
    check("uploaded blueprint served on public link", page.status_code == 200 and "Custom Landing" in page.text, f"{page.status_code}")
    rep = client.post("/api/blueprints/upload", json={
        "doc_id": up["id"], "html": "<!doctype html><html><body><h1>Replaced</h1></body></html>"}, headers=auth(tok)).json()
    check("uploaded blueprint HTML replaced in place", rep["slug"] == up["slug"] and "Replaced" in rep["html"], str(rep)[:160])

    # --- manual CRM entry: add a company, a contact, then a deal (website/referral lead path)
    co = client.post("/api/companies", json={"workspace_id": w1["id"], "name": "Website Lead Co", "website": "weblead.com"}, headers=auth(tok)).json()
    ct = client.post("/api/contacts", json={"workspace_id": w1["id"], "first_name": "Web", "last_name": "Lead",
                                            "email": "web@weblead.com", "title": "Founder", "company_id": co["id"]}, headers=auth(tok)).json()
    check("manual contact created", bool(ct.get("id")), str(ct)[:160])
    contacts_now = client.get("/api/contacts", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    mine = next((c for c in contacts_now if c["id"] == ct["id"]), None)
    check("new contact starts as 'No deal'", mine and mine["status"]["key"] == "none", str(mine)[:160])
    nd = client.post("/api/deals", json={"workspace_id": w1["id"], "name": "Web Lead deal", "company_id": co["id"],
                                         "contact_id": ct["id"], "stage_id": stage_meeting, "value": 4200}, headers=auth(tok)).json()
    check("manual deal created", bool(nd.get("id")), str(nd)[:160])
    contacts_after = client.get("/api/contacts", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    mine2 = next((c for c in contacts_after if c["id"] == ct["id"]), None)
    check("contact now shows Meeting Booked after deal", mine2 and mine2["status"]["key"] == "meeting_booked", str(mine2)[:160])
    upco = client.post("/api/blueprints/upload", json={"workspace_id": w1["id"], "company_id": co["id"],
                                                       "html": "<h1>Co Blueprint</h1>"}, headers=auth(tok)).json()
    check("blueprint upload tied to company", upco["company_id"] == co["id"] and upco["fields"].get("generator") == "uploaded", str(upco)[:160])

    # Boards & Tables is three fixed projections over live records — not a
    # second database. A meeting arrives as an activity, and the client can set
    # the two human fields without gaining a write path into the rest of CRM.
    booked_activity = client.post("/api/activities", json={
        "workspace_id": w1["id"], "company_id": co["id"], "contact_id": ct["id"],
        "deal_id": nd["id"], "kind": "meeting_booked", "title": "Website Lead discovery call",
    }, headers=auth(tok)).json()
    records = client.get("/api/client-space/boards", params={"workspace_id": w1["id"]},
                         headers=auth(tok)).json()
    meeting_row = next((m for m in records["meetings"] if m["id"] == booked_activity["id"]), None)
    check("fixed client tables read live prospects, meetings, and deals",
          bool(records["prospects"]) and meeting_row and
          any(d["id"] == nd["id"] for d in records["deals"]), str(records)[:240])
    r = client.patch(f"/api/client-space/boards/meetings/{booked_activity['id']}",
                     json={"quality": "qualified", "remarks": "Strong fit — send proposal"},
                     headers=auth(ctok))
    check("client updates meeting quality and remarks in one place",
          r.status_code == 200 and r.json()["quality"] == "qualified"
          and r.json()["remarks"] == "Strong fit — send proposal", r.text)
    reread = client.get("/api/client-space/boards", headers=auth(ctok)).json()
    saved_meeting = next((m for m in reread["meetings"] if m["id"] == booked_activity["id"]), None)
    check("meeting outcome persists on the live meeting row",
          saved_meeting and saved_meeting["quality"] == "qualified"
          and saved_meeting["remarks"] == "Strong fit — send proposal", str(saved_meeting))
    r = client.patch(f"/api/client-space/boards/meetings/{booked_activity['id']}",
                     json={"quality": "no_update"},
                     headers={**auth(tok), "X-Client-Preview": "1"})
    check("client preview cannot write a meeting outcome", r.status_code == 403, r.text)
    r = client.get("/api/client-space/boards", params={"workspace_id": w2["id"]}, headers=auth(ctok))
    check("client cannot read another workspace's fixed tables", r.status_code == 403, r.text)

    # documents filtered by company + surfaced on the company hub
    codocs = client.get("/api/documents", params={"company_id": co["id"]}, headers=auth(tok)).json()
    check("documents filter by company", len(codocs) == 1 and codocs[0]["id"] == upco["id"] and codocs[0]["public_path"], str(codocs)[:160])
    codetail = client.get(f"/api/companies/{co['id']}", headers=auth(tok)).json()
    check("company hub carries documents + status", codetail.get("documents") and codetail["documents"][0]["id"] == upco["id"]
          and codetail.get("status", {}).get("key") == "meeting_booked", str(codetail.get("status"))[:120])

    # one-shot lead: new company + new contact + deal all created together
    lead = client.post("/api/leads", json={"workspace_id": w1["id"], "company_name": "Referral Inc",
                                            "first_name": "Ref", "last_name": "Lead", "email": "ref@referral.com",
                                            "title": "COO", "stage_id": stage_meeting, "value": 3000}, headers=auth(tok)).json()
    check("lead created company+contact+deal", lead.get("deal_id") and lead.get("company_id") and lead.get("contact_id"), str(lead)[:160])
    lead_contacts = client.get("/api/contacts", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    lc = next((c for c in lead_contacts if c["id"] == lead["contact_id"]), None)
    check("lead contact shows in Contacts as Meeting Booked",
          lc and lc["status"]["key"] == "meeting_booked" and lc["company_name"] == "Referral Inc", str(lc)[:160])

    # ---------------- Client Space: launch plan, preview-as-client, cross-client rollup
    from datetime import datetime as _dt, timedelta as _timedelta

    # A plan is built from scratch — there is no template to instantiate.
    empty = client.get("/api/client-space/plan", params={"workspace_id": w1["id"]},
                       headers=auth(tok)).json()
    check("a new workspace starts with an empty plan",
          empty["tasks"] == [] and empty["counts"]["total"] == 0, str(empty["counts"]))

    def add(title, stage, owner, start, due, deps=(), milestone=False, status="backlog"):
        return client.post("/api/client-space/plan/tasks", json={
            "workspace_id": w1["id"], "title": title, "stage": stage, "owner": owner,
            "status": status, "start_at": start, "due_at": due,
            "is_milestone": milestone, "depends_on": list(deps)}, headers=auth(tok)).json()

    plan = add("Onboarding form completed", "intake", "client", "2026-08-16", "2026-08-17")
    check("first task creates the plan", len(plan["tasks"]) == 1, str(plan["counts"]))
    t_form = plan["tasks"][-1]["id"]
    t_crawl = add("Website crawl", "intake", "system", "2026-08-17", "2026-08-19",
                  [t_form])["tasks"][-1]["id"]
    t_icp = add("ICP approved", "icp", "client", "2026-08-20", "2026-08-21",
                [t_crawl])["tasks"][-1]["id"]
    plan = add("First send", "live", "us", "2026-08-24", "2026-08-24", [t_icp], milestone=True)
    check("tasks land in their phases", len(plan["phases"]) == 7 and len(plan["tasks"]) == 4,
          str([(p["short"], p["total"]) for p in plan["phases"]])[:200])

    # The critical path is a real chain through the graph, ending at the launch.
    chain = plan["critical_path"]
    by_id = {t["id"]: t for t in plan["tasks"]}
    check("critical path is a connected chain ending at the milestone",
          len(chain) == 4 and by_id[chain[-1]]["is_milestone"]
          and all(chain[i] in by_id[chain[i + 1]]["depends_on"] for i in range(len(chain) - 1)),
          str([by_id[i]["title"] for i in chain])[:220])

    first_send = (_dt.utcnow() + _timedelta(days=21)).date().isoformat()
    r = client.put("/api/client-space/plan",
                   json={"workspace_id": w1["id"], "stage": "icp", "first_send_at": first_send},
                   headers=auth(tok))
    check("launch stage and first-send date save",
          r.status_code == 200 and r.json()["launch"]["stage"] == "icp"
          and r.json()["launch"]["days_to_first_send"] == 21, r.text[:200])

    # Blocked is DERIVED: finishing the blocker unblocks the dependant, with
    # nobody having to remember to clear a flag.
    dependant = next(t for t in plan["tasks"] if t["depends_on"])
    blocker_id = dependant["depends_on"][0]
    check("a task with an unfinished dependency is blocked",
          dependant["blocked"] and dependant["blocked_by"][0]["id"] == blocker_id,
          str(dependant["blocked_by"])[:160])
    r = client.patch(f"/api/client-space/plan/tasks/{blocker_id}",
                     json={"status": "done"}, headers=auth(tok)).json()
    after = next(t for t in r["tasks"] if t["id"] == dependant["id"])
    check("finishing the blocker unblocks it automatically", not after["blocked"], str(after)[:160])

    # The inverse edge is what the List's Blocks column reads.
    blocker = next(t for t in r["tasks"] if t["id"] == blocker_id)
    check("the blocker knows what it blocks", bool(blocker["blocks"]), str(blocker["blocks"]))

    # An operator can still block something the system cannot see.
    r = client.patch(f"/api/client-space/plan/tasks/{dependant['id']}",
                     json={"blocked_note": "Their legal team is reviewing it"}, headers=auth(tok)).json()
    again = next(t for t in r["tasks"] if t["id"] == dependant["id"])
    check("an explicit reason blocks a task with no unfinished dependency",
          again["blocked"] and not again["blocked_by"], str(again)[:160])

    r = client.patch(f"/api/client-space/plan/tasks/{blocker_id}",
                     json={"depends_on": [dependant["id"]]}, headers=auth(tok))
    check("a dependency loop is refused", r.status_code == 422, r.text[:160])

    r = client.patch(f"/api/client-space/plan/tasks/{dependant['id']}",
                     json={"status": "nonsense"}, headers=auth(tok))
    check("an unknown status is refused", r.status_code == 422, r.text[:120])

    r = client.post("/api/client-space/plan/baseline", json={"workspace_id": w1["id"]}, headers=auth(tok))
    check("baseline freezes the agreed dates",
          r.status_code == 200 and r.json()["launch"]["baseline_at"]
          and all(t["baseline_due_at"] for t in r.json()["tasks"]), r.text[:160])

    r = client.get("/api/client-space/plan/export", params={"workspace_id": w1["id"]}, headers=auth(tok))
    check("the plan exports as CSV",
          r.status_code == 200 and "text/csv" in r.headers.get("content-type", "")
          and "Phase,Task,Owner" in r.text, r.text[:120])

    ov = client.get("/api/client-space/overview", params={"workspace_id": w1["id"]}, headers=auth(tok)).json()
    check("overview says what is blocked and on whose side",
          ov["health"] == "blocked" and ov["blocked_side"] in ("us", "client", "both")
          and ov["counts"]["blocked"] > 0, str(ov["counts"])[:200])
    check("overview names the next thing on the critical path",
          ov["critical_note"].startswith("Critical path:"), ov["critical_note"])
    check("overview stage rail reports each phase", len(ov["stages"]) == 7
          and all(s["state"] in ("done", "now", "next") for s in ov["stages"]),
          str(ov["stages"])[:200])
    check("overview counts days to first send", ov["days_to_first_send"] == 21, str(ov["days_to_first_send"]))
    check("overview separates our work from theirs",
          ov["counts"]["ours"] > 0 and ov["counts"]["theirs"] > 0, str(ov["counts"]))

    r = client.get("/api/client-space/overview", headers=auth(tok)).json()
    check("a master on All workspaces is asked to pick a client", r["workspace"] is None, str(r)[:160])

    # The client's own side: read their launch, write nothing, see nothing else.
    cov = client.get("/api/client-space/overview", headers=auth(ctok))
    check("client reads their own overview",
          cov.status_code == 200 and cov.json()["workspace"]["id"] == w1["id"], cov.text)
    check("client is not told how much is hidden from them",
          cov.json()["hidden_from_client"] is None, str(cov.json())[:160])
    r = client.get("/api/client-space/overview", params={"workspace_id": w2["id"]}, headers=auth(ctok))
    check("client asking for another workspace's overview → 403", r.status_code == 403, r.text)
    r = client.post("/api/client-space/plan/tasks",
                    json={"workspace_id": w1["id"], "title": "Added by the client"}, headers=auth(ctok))
    check("client cannot write the launch plan", r.status_code == 403, r.text)
    r = client.get("/api/client-space/launches", headers=auth(ctok))
    check("client cannot read the cross-client rollup", r.status_code == 403, r.text)

    roll = client.get("/api/client-space/launches", headers=auth(tok)).json()["launches"]
    row = next((x for x in roll if x["workspace_id"] == w1["id"]), None)
    check("master dashboard rollup shows the launch and its side",
          bool(row) and row["health"] == "blocked"
          and row["blocked_side"] in ("us", "client", "both")
          and row["blocked_count"] > 0 and row["days_to_first_send"] == 21, str(roll)[:220])

    # Preview as client: the SAME filter a client hits, applied to an operator.
    # One shared page and one internal folder, so the comparison below is a real
    # subset rather than two empty lists agreeing with each other.
    preview = {**auth(tok), "X-Client-Preview": "1"}
    cs_folder = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "strategy", "kind": "folder",
        "title": "Client Space checks"}, headers=auth(tok)).json()
    cs_page = client.post("/api/workspace/pages", json={
        "workspace_id": w1["id"], "section": "strategy", "parent_id": cs_folder["id"],
        "title": "Shared with the client"}, headers=auth(tok)).json()
    r = client.post(f"/api/workspace/pages/{cs_page['id']}/share", headers=auth(tok))
    check("page shared for the preview checks", r.status_code == 200, r.text)

    master_tree = client.get("/api/workspace/pages/tree", params={"workspace_id": w1["id"]},
                             headers=auth(tok)).json()
    preview_tree = client.get("/api/workspace/pages/tree", params={"workspace_id": w1["id"]},
                              headers=preview).json()
    client_tree = client.get("/api/workspace/pages/tree", headers=auth(ctok)).json()
    check("preview as client hides exactly what the client cannot see",
          [p["id"] for p in preview_tree["pages"]] == [p["id"] for p in client_tree["pages"]]
          and cs_page["id"] in [p["id"] for p in preview_tree["pages"]]
          and cs_folder["id"] not in [p["id"] for p in preview_tree["pages"]]
          and len(master_tree["pages"]) > len(preview_tree["pages"]),
          f"master={len(master_tree['pages'])} preview={len(preview_tree['pages'])} client={len(client_tree['pages'])}")

    r = client.get(f"/api/workspace/pages/{cs_page['id']}", headers=preview)
    check("a shared page is still readable in preview", r.status_code == 200, r.text)
    r = client.get(f"/api/workspace/pages/{cs_folder['id']}", headers=preview)
    check("an internal page 404s in preview, as it does for the client", r.status_code == 404, r.text)

    pov = client.get("/api/client-space/overview", params={"workspace_id": w1["id"]}, headers=preview).json()
    check("the marker keeps counting hidden items while previewing",
          (pov["hidden_from_client"] or {}).get("total", 0) >= 1 and pov["can_edit"] is False,
          str(pov["hidden_from_client"]))
    r = client.post("/api/client-space/plan/tasks",
                    json={"workspace_id": w1["id"], "title": "Written from preview"}, headers=preview)
    check("preview is read-only — no writing through the costume", r.status_code == 403, r.text)

    # A client's preview header is a no-op: they are already seeing the least.
    r = client.get("/api/client-space/overview", headers={**auth(ctok), "X-Client-Preview": "1"})
    check("preview header changes nothing for a real client",
          r.status_code == 200 and r.json()["workspace"]["id"] == w1["id"], r.text)

    # ---------------- client invite: workspace → email → temp password → forced change
    iw = client.post("/api/admin/workspaces", json={"name": "Invited Co"}, headers=auth(tok)).json()
    check("workspace created for the invite flow", bool(iw.get("id")), str(iw)[:160])

    r = client.post(f"/api/admin/workspaces/{iw['id']}/invite-client",
                    json={"email": "not-an-email", "name": "Dana"}, headers=auth(tok))
    check("invite rejects a malformed address", r.status_code == 422, r.text)

    r = client.post(f"/api/admin/workspaces/{iw['id']}/invite-client",
                    json={"email": "Dana@Invited.test", "name": "Dana Ruiz"}, headers=auth(tok))
    check("invite creates the client login", r.status_code == 200, r.text)
    inv = r.json()
    # The link names its workspace by SLUG, so it reads as the client's address
    # rather than a row id, and an operator following it lands in THIS client's
    # space rather than whichever one is first in their own list.
    check("invite returns the workspace link and credentials once",
          inv["email"] == "dana@invited.test"
          and inv["login_url"].endswith("/w/invited-co")
          and str(iw["id"]) not in inv["login_url"]
          and len(inv["temp_password"]) >= 12 and inv["workspace"]["name"] == "Invited Co",
          str({k: v for k, v in inv.items() if k != "temp_password"})[:220])
    # With no client host configured the link still has to work: it falls back to
    # the operator host's hash route, which reaches the same screen. A blank or
    # broken link in a credentials email is unrecoverable.
    check("invite link falls back to the operator host when no client host is set",
          inv["login_url"] == "http://testserver/#/w/invited-co", inv["login_url"])
    # No mailbox is connected in this suite and no SMTP_* is set, so delivery must
    # report failure honestly rather than claim a send that never happened.
    check("invite reports delivery truthfully when no mail is configured",
          inv["emailed"] is False and "SMTP_HOST" in inv["delivery"], str(inv["delivery"])[:200])

    # ---------------- the client host: app.revcadence.com/w/<slug>
    #
    # Two hosts, one deploy. These checks are the contract between them: the link
    # we email is built from the client host, and that host answers a real path
    # with the app rather than a 404. The second half is the one that bites — the
    # link works when clicked and breaks on the first refresh without it.
    was_client_base = config.CLIENT_BASE_URL
    try:
        config.CLIENT_BASE_URL = "https://app.revcadence.com"
        check("a configured client host builds the workspace link",
              config.client_workspace_url("invited-co") == "https://app.revcadence.com/w/invited-co",
              config.client_workspace_url("invited-co"))
        check("the client host never leaks a hash route into an emailed link",
              "#" not in config.client_workspace_url("invited-co"))
        check("no slug still resolves to the client host root",
              config.client_workspace_url("") == "https://app.revcadence.com")
        # A form is answered before the account exists, so its link is often the
        # first address a client sees from us. It belongs on the same host.
        check("form invites are issued against the client host too",
              config.client_form_url("tok123") == "https://app.revcadence.com/f/tok123",
              config.client_form_url("tok123"))
        r = client.get("/f/tok123", headers={"host": "app.revcadence.com"})
        check("the client host serves the form page at a real path",
              r.status_code == 200 and "text/html" in r.headers.get("content-type", ""),
              f"{r.status_code} {r.headers.get('content-type')}")
        r = client.post(f"/api/admin/workspaces/{iw['id']}/invite-client",
                        json={"email": "dana@invited.test"}, headers=auth(tok))
        check("re-invite is issued against the client host",
              r.status_code == 200
              and r.json()["login_url"] == "https://app.revcadence.com/w/invited-co", r.text[:200])
        # A re-invite rotates the temporary password, so the sign-in checks below
        # must carry the one this call issued, not the one it just invalidated.
        inv = r.json()
    finally:
        config.CLIENT_BASE_URL = was_client_base

    host = {"host": "app.revcadence.com"}
    r = client.get("/w/invited-co", headers=host)
    check("a real client path on the client host returns the app, not a 404",
          r.status_code == 200 and "text/html" in r.headers.get("content-type", ""),
          f"{r.status_code} {r.headers.get('content-type')}")
    r = client.get("/w/invited-co/docs/999", headers=host)
    check("a deep client path on the client host returns the app too",
          r.status_code == 200 and "text/html" in r.headers.get("content-type", ""),
          f"{r.status_code} {r.headers.get('content-type')}")
    # The fallback must not swallow the API, or every call from that host would
    # come back as an HTML page and the client app would fail to load its data.
    r = client.get("/api/auth/me", headers={**host, **auth(tok)})
    check("the client host still reaches the API, not the SPA fallback",
          r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"),
          f"{r.status_code} {r.headers.get('content-type')}")
    r = client.get("/healthz", headers=host)
    check("the client host still reaches healthz", r.status_code == 200, r.text[:120])
    # index.html links its bundle absolutely (/assets/…), so a page opened at a
    # nested path still asks for the same URL. If the fallback captured /assets
    # the browser would be handed HTML where it expected JavaScript and the app
    # would not boot — a 404 here proves the static mount still owns that prefix.
    r = client.get("/assets/not-a-real-bundle.js", headers=host)
    check("the client host does not swallow /assets", r.status_code == 404, str(r.status_code))
    # The operator host is untouched: it serves the hash router, so an unknown
    # real path there is still a 404 rather than a silent SPA page.
    r = client.get("/w/invited-co", headers={"host": "engine.revcadence.com"})
    check("the operator host does not gain an SPA fallback", r.status_code == 404, str(r.status_code))

    # client@webaholics.com is w1's client, not this workspace's. An invite must
    # not quietly repoint an existing account at a different client's data.
    r = client.post(f"/api/admin/workspaces/{iw['id']}/invite-client",
                    json={"email": "client@webaholics.com"}, headers=auth(tok))
    check("invite refuses an address owned by another account", r.status_code == 409, r.text)
    still = client.post("/api/auth/login", json={
        "email": "client@webaholics.com", "password": "client-pw"})
    check("the refused invite left that account untouched",
          still.status_code == 200 and still.json()["must_change_password"] is False, still.text)

    # The client signs in with the temporary password and is told to replace it.
    invite_device = TestClient(app)
    li = invite_device.post("/api/auth/login",
                            json={"email": "dana@invited.test", "password": inv["temp_password"]})
    check("client signs in with the temporary password", li.status_code == 200, li.text)
    itok = li.json()["token"]
    check("login flags the pending password change", li.json()["must_change_password"] is True, li.text)

    me_pending = invite_device.get("/api/auth/me", headers=auth(itok))
    check("/me still answers so the app knows to ask",
          me_pending.status_code == 200 and me_pending.json()["must_change_password"] is True,
          me_pending.text)

    # THE gate: the session is real, and it can reach nothing until the change.
    for path in ("/api/deals", "/api/client-space/overview", "/api/workspace/pages/tree"):
        r = invite_device.get(path, headers=auth(itok))
        check(f"temporary password cannot reach {path}",
              r.status_code == 403 and r.json()["detail"] == "Password change required", r.text[:160])

    r = invite_device.post("/api/auth/change-password", headers=auth(itok),
                           json={"current_password": "wrong-password", "new_password": "a-brand-new-password-1"})
    check("change-password requires the current password", r.status_code == 400, r.text)
    r = invite_device.post("/api/auth/change-password", headers=auth(itok),
                           json={"current_password": inv["temp_password"], "new_password": "short"})
    check("change-password enforces a minimum length", r.status_code == 422, r.text)
    r = invite_device.post("/api/auth/change-password", headers=auth(itok),
                           json={"current_password": inv["temp_password"], "new_password": inv["temp_password"]})
    check("change-password refuses reusing the temporary one", r.status_code == 422, r.text)

    r = invite_device.post("/api/auth/change-password", headers=auth(itok),
                           json={"current_password": inv["temp_password"], "new_password": "dana-picks-this-one-9"})
    check("client sets their own password", r.status_code == 200, r.text)

    me_done = invite_device.get("/api/auth/me", headers=auth(itok)).json()
    check("the flag clears without a new sign-in", me_done["must_change_password"] is False, str(me_done)[:160])
    r = invite_device.get("/api/client-space/overview", headers=auth(itok))
    check("the same token now reaches the workspace",
          r.status_code == 200 and r.json()["workspace"]["id"] == iw["id"], r.text[:160])

    stale = invite_device.post("/api/auth/login",
                               json={"email": "dana@invited.test", "password": inv["temp_password"]})
    check("the temporary password stops working", stale.status_code == 401, stale.text)
    fresh = invite_device.post("/api/auth/login",
                               json={"email": "dana@invited.test", "password": "dana-picks-this-one-9"})
    check("the chosen password works", fresh.status_code == 200
          and fresh.json()["must_change_password"] is False, fresh.text)

    # Re-inviting the same client rotates the temporary password and re-locks them.
    again = client.post(f"/api/admin/workspaces/{iw['id']}/invite-client",
                        json={"email": "dana@invited.test"}, headers=auth(tok)).json()
    check("re-invite is a resend, not a conflict", again["reissued"] is True
          and again["temp_password"] != inv["temp_password"], str(again.get("reissued")))
    old = invite_device.post("/api/auth/login",
                             json={"email": "dana@invited.test", "password": "dana-picks-this-one-9"})
    check("re-invite invalidates the password it replaced", old.status_code == 401, old.text)
    re_login = invite_device.post("/api/auth/login",
                                  json={"email": "dana@invited.test", "password": again["temp_password"]})
    check("re-invite's password works and asks for a change again",
          re_login.status_code == 200 and re_login.json()["must_change_password"] is True, re_login.text)

    # ---- password reset (forgot + owner reset-link + reset) ----
    ru = client.post("/api/admin/users", json={"email": "reset@webaholics.com", "password": "old-password-1234",
                     "role": "client", "workspace_ids": [w1["id"]]}, headers=auth(tok)).json()
    check("reset test user created", bool(ru.get("id")), str(ru)[:120])
    fg = client.post("/api/auth/forgot", json={"email": "reset@webaholics.com"})
    check("forgot returns generic ok", fg.status_code == 200 and fg.json()["ok"])
    fg2 = client.post("/api/auth/forgot", json={"email": "nobody@nowhere.test"})
    check("forgot does not reveal unknown accounts", fg2.status_code == 200 and fg2.json()["ok"])
    rl = client.post(f"/api/admin/users/{ru['id']}/reset-link", headers=auth(tok)).json()
    token = rl["reset_path"].split("/reset/")[-1]
    check("owner gets a reset link", "/reset/" in rl["reset_path"] and token)
    bad = client.post("/api/auth/reset", json={"token": "not-a-real-token", "password": "brand-new-password-1"})
    check("invalid reset token rejected", bad.status_code == 400)
    short = client.post("/api/auth/reset", json={"token": token, "password": "short"})
    check("short new password rejected", short.status_code == 422)
    ok = client.post("/api/auth/reset", json={"token": token, "password": "brand-new-password-1"})
    check("reset with valid token succeeds", ok.status_code == 200)
    li = client.post("/api/auth/login", json={"email": "reset@webaholics.com", "password": "brand-new-password-1"})
    check("can log in with the new password", li.status_code == 200 and li.json().get("token"))
    reuse = client.post("/api/auth/reset", json={"token": token, "password": "another-new-password-9"})
    check("reset token is one-time (reuse fails)", reuse.status_code == 400)

    print(f"\n{sum(1 for _, ok in PASS if ok)}/{len(PASS)} checks passed")


if __name__ == "__main__":
    main()
