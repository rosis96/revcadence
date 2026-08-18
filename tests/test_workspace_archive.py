"""Archive, restore, and replace a workspace.

Deleting a workspace is a soft delete: it disappears from every list, switcher
and query — the client's included — and nothing is destroyed until somebody
comes back for it. This suite covers the whole round trip, including the one
that only exists because of it: creating a workspace whose name or client email
an ARCHIVED workspace already holds.

Run:  python -m tests.test_workspace_archive   (uses a throwaway SQLite DB)
"""
import os
import tempfile

TEST_ROOT = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT}/test.db"
os.environ["JWT_SECRET"] = "test-secret"
# System mail stays OFF. Set to "" rather than deleted: app.config loads a local
# .env with override=False, so an ABSENT key would be filled in from the
# developer's real SMTP credentials and this suite would email its own fixtures.
for _smtp in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"):
    os.environ[_smtp] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import init_db, session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.crm import Company  # noqa: E402
from app.models.identity import Membership, Organization, User, Workspace  # noqa: E402

client = TestClient(app)
PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond)))
    print(("✓" if cond else "✗ FAIL"), name, detail if not cond else "")
    assert cond, f"{name}: {detail}"


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def user_list(tok):
    return client.get("/api/admin/users", headers=auth(tok)).json()


def ws_list(tok, archived=0):
    return client.get("/api/admin/workspaces", params={"archived": archived}, headers=auth(tok)).json()


def delete_ws(tok, w, *, confirm_name=None, password="master-pw"):
    """Delete a workspace the way the screen does: name typed, password given."""
    return client.post(f"/api/admin/workspaces/{w['id']}/archive", headers=auth(tok),
                       json={"confirm_name": w["name"] if confirm_name is None else confirm_name,
                             "password": password})


def main():
    init_db()
    with session() as db:
        org = Organization(name="Ascendly", slug="ascendly")
        db.add(org)
        db.flush()
        u = User(email="master@ascendly.one", password_hash=hash_password("master-pw"))
        db.add(u)
        db.flush()
        db.add(Membership(user_id=u.id, org_id=org.id, role="owner", workspace_ids=[]))
    tok = client.post("/api/auth/login",
                      json={"email": "master@ascendly.one", "password": "master-pw"}).json()["token"]

    # ---------------------------------------------------------------- archive
    acme = client.post("/api/admin/workspaces", json={"name": "Acme Inc"}, headers=auth(tok)).json()
    other = client.post("/api/admin/workspaces", json={"name": "Bravo Ltd"}, headers=auth(tok)).json()
    r = client.post(f"/api/admin/workspaces/{acme['id']}/invite-client",
                    json={"email": "ops@acme.com", "name": "Dana"}, headers=auth(tok))
    check("client invited", r.status_code == 200, r.text)

    # The delete this replaces refused any workspace holding data. That is the
    # whole point of the change, so the workspace under test holds some.
    with session() as db:
        db.add(Company(workspace_id=acme["id"], name="A Customer"))

    r = delete_ws(tok, acme, confirm_name="Acme")
    check("a mistyped name is refused", r.status_code == 422, r.text)
    r = delete_ws(tok, acme, password="not-the-password")
    check("a wrong password is refused", r.status_code == 403, r.text)
    check("and the refusal changed nothing", len(ws_list(tok)) == 2, str(ws_list(tok)))

    r = delete_ws(tok, acme)
    check("a workspace holding data still deletes", r.status_code == 200, r.text)
    check("its client login was suspended with it", r.json()["suspended_users"] == 1, r.text)

    live = ws_list(tok)
    check("archived workspace leaves the live list",
          [w["id"] for w in live] == [other["id"]], str(live))
    arch = ws_list(tok, archived=1)
    check("archived workspace is in the archive",
          len(arch) == 1 and arch[0]["id"] == acme["id"] and arch[0]["archived_at"], str(arch))
    check("the archive still reports what it holds", arch[0]["counts"]["companies"] == 1, str(arch))

    me = client.get("/api/auth/me", headers=auth(tok)).json()
    check("archived workspace leaves the master's switcher",
          [w["id"] for w in me["workspaces"]] == [other["id"]], str(me["workspaces"]))
    r = client.get("/api/deals", params={"workspace_id": acme["id"]}, headers=auth(tok))
    check("archived workspace is unreachable even by id", r.status_code == 403, r.text)
    r = client.post(f"/api/admin/workspaces/{acme['id']}/invite-client",
                    json={"email": "ops@acme.com"}, headers=auth(tok))
    check("an archived workspace cannot be invited to", r.status_code == 409, r.text)

    # Its client has nothing to manage while the workspace is gone, and listing
    # them would mean listing a workspace id with no workspace behind it.
    emails = [u["email"] for u in user_list(tok)]
    check("its client leaves the users list", "ops@acme.com" not in emails, str(emails))
    check("the operator accounts are untouched", "master@ascendly.one" in emails, str(emails))

    # A member spanning both workspaces keeps their account and loses only the
    # archived id — one deleted workspace must not blank out an operator.
    r = client.post("/api/admin/users", headers=auth(tok), json={
        "email": "ops@ascendly.one", "password": "member-password", "role": "member",
        "workspace_ids": [other["id"]]})
    check("member created", r.status_code == 200, r.text)
    with session() as db:
        mem = db.query(Membership).filter(Membership.user_id == r.json()["id"]).first()
        mem.workspace_ids = [acme["id"], other["id"]]
    row = next(u for u in user_list(tok) if u["email"] == "ops@ascendly.one")
    check("a member spanning both keeps only the live workspace",
          row["workspace_ids"] == [other["id"]], str(row))

    # ---------------------------------------------------------------- restore
    r = client.post("/api/admin/workspaces/check-conflicts",
                    json={"name": "acme inc", "email": ""}, headers=auth(tok))
    hits = r.json()["conflicts"]
    check("same name finds the archived workspace",
          len(hits) == 1 and hits[0]["id"] == acme["id"] and hits[0]["matched"] == ["name"], r.text)
    r = client.post("/api/admin/workspaces/check-conflicts",
                    json={"name": "Totally Different", "email": "OPS@acme.com"}, headers=auth(tok))
    hits = r.json()["conflicts"]
    check("same client email finds it too",
          len(hits) == 1 and hits[0]["matched"] == ["email"], r.text)
    r = client.post("/api/admin/workspaces/check-conflicts",
                    json={"name": "Bravo Ltd", "email": ""}, headers=auth(tok))
    check("a LIVE duplicate is not an archive conflict", r.json()["conflicts"] == [], r.text)

    r = client.post(f"/api/admin/workspaces/{acme['id']}/restore", headers=auth(tok))
    check("restore succeeds", r.status_code == 200 and r.json()["restored_users"] == 1, r.text)
    check("its client is back in the users list",
          "ops@acme.com" in [u["email"] for u in user_list(tok)], str(user_list(tok)))
    check("restored workspace is back in the live list",
          {w["id"] for w in ws_list(tok)} == {acme["id"], other["id"]})
    check("restored workspace holds everything it did",
          ws_list(tok)[0]["counts"]["companies"] == 1, str(ws_list(tok)))
    r = client.post("/api/auth/login", json={"email": "ops@acme.com", "password": "nope"})
    check("the client account exists again (wrong password, not unknown user)",
          r.status_code == 401, r.text)
    with session() as db:
        check("the client login was re-enabled",
              db.query(User).filter(User.email == "ops@acme.com").first().active is True)

    # ------------------------------------------------------- create over it
    delete_ws(tok, acme)
    r = client.post("/api/admin/workspaces", json={"name": "Acme Inc"}, headers=auth(tok))
    check("creating over an archived address is refused, with a way out",
          r.status_code == 409 and "Restore it" in r.json()["detail"], r.text)

    r = client.post("/api/admin/workspaces",
                    json={"name": "Acme Inc", "replace_ids": [acme["id"]]}, headers=auth(tok))
    check("replacing the archived one succeeds", r.status_code == 200, r.text)
    fresh = r.json()
    check("the replacement took the address", fresh["slug"] == "acme-inc", r.text)
    check("the archive is empty", ws_list(tok, archived=1) == [], str(ws_list(tok, archived=1)))
    with session() as db:
        check("the replaced workspace is gone",
              db.query(Workspace).filter(Workspace.id == acme["id"]).first() is None)
        check("its records went with it",
              db.query(Company).filter(Company.workspace_id == acme["id"]).count() == 0)
        check("its orphaned client login went with it",
              db.query(User).filter(User.email == "ops@acme.com").first() is None)

    # The reason erasing that login matters: the same client is being set up
    # again, and a leftover account would make their address unusable forever.
    r = client.post(f"/api/admin/workspaces/{fresh['id']}/invite-client",
                    json={"email": "ops@acme.com", "name": "Dana"}, headers=auth(tok))
    check("the freed email can be invited to the new workspace", r.status_code == 200, r.text)

    # ---------------------------------------------------------------- purge
    r = client.post(f"/api/admin/workspaces/{other['id']}/purge", headers=auth(tok))
    check("a live workspace cannot be purged", r.status_code == 409, r.text)
    delete_ws(tok, other)
    r = client.post(f"/api/admin/workspaces/{other['id']}/purge", headers=auth(tok))
    check("an archived workspace can be purged", r.status_code == 200, r.text)
    check("and it leaves the archive", ws_list(tok, archived=1) == [])

    failed = [n for n, ok in PASS if not ok]
    print(f"\n{len(PASS) - len(failed)}/{len(PASS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
