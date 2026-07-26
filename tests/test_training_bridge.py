"""Regression checks for the safe, versioned Workspace Training Bridge.

Run: python -m tests.test_training_bridge
No network or OpenAI calls are made.
"""
import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/training.db"
os.environ["JWT_SECRET"] = "training-test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)
PASS = []


def check(name, condition, detail=""):
    PASS.append(bool(condition))
    print(("✓" if condition else "✗ FAIL"), name, detail if not condition else "")
    assert condition, f"{name}: {detail}"


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    init_db()
    r = client.post("/api/auth/bootstrap", json={
        "org": "Training Org",
        "email": "owner@example.com",
        "password": "owner-password-123",
    })
    check("owner bootstrapped", r.status_code == 200, r.text)
    owner = client.post("/api/auth/login", json={
        "email": "owner@example.com", "password": "owner-password-123",
    }).json()["token"]
    ws = client.post("/api/admin/workspaces", json={"name": "RevCadence"},
                     headers=headers(owner)).json()
    ws_id = ws["id"]

    formats = [{
        "name": "personalized_first_line",
        "label": "Personalized First Line",
        "guidance": "Use one verified achievement.",
        "template": "{{company}} achieved {{result}}.",
        "placeholders": [{"token": "company"}, {"token": "result"}],
        "examples": [],
    }]
    r = client.put(f"/api/enrich-lists/config/{ws_id}", headers=headers(owner), json={
        "profile": {"client_name": "RevCadence", "main_offer": "Managed outbound"},
        "formats": formats,
        "rules": "Use specific facts.",
        "reading_level": "b2 business",
    })
    check("workspace config seeded", r.status_code == 200, r.text)

    export = client.get(
        f"/api/enrich-lists/config/{ws_id}/training/export", headers=headers(owner),
    )
    check("safe package exports", export.status_code == 200, export.text)
    package = export.json()
    check("B2 is the exported writing standard", package["config"]["reading_level"] == "b2 business")
    check("export declares no leads or credentials",
          package["safety"]["contains_leads"] is False
          and package["safety"]["contains_credentials"] is False)
    check("workspace secret is not exportable",
          "reoon_api_key" not in str(package).lower() and "email" not in package["config"])

    r = client.post("/api/admin/users", headers=headers(owner), json={
        "email": "client@example.com", "password": "client-password-123",
        "role": "client", "workspace_ids": [ws_id],
    })
    check("client login created", r.status_code == 200, r.text)
    client_token = client.post("/api/auth/login", json={
        "email": "client@example.com", "password": "client-password-123",
    }).json()["token"]
    r = client.get(f"/api/enrich-lists/config/{ws_id}/training/export",
                   headers=headers(client_token))
    check("client cannot export training package", r.status_code == 403, r.text)

    proposed = {
        "schema": "revcadence.workspace-training",
        "schema_version": 1,
        "config": {
            "rules": "Use specific facts.\nNever use corporate jargon.",
            # `token` is a legitimate format-placeholder field, not a credential.
            "formats": formats,
        },
        "evaluation_cases": [{
            "name": "Approved Unbox benchmark",
            "company": "Unbox",
            "website": "https://unboxpd.com/",
            "facts": {"evidence": [{
                "id": "ev_1",
                "type": "measurable_result",
                "claim": "Monstatek M1 reached $2.8 million in crowdfunding",
                "source_url": "https://unboxpd.com/work/monstatek",
                "supporting_quote": "Monstatek M1 reached $2.8 million in crowdfunding.",
                "source_kind": "html",
                "confidence": 1,
            }]},
            "expected_outputs": {
                "personalized_first_line": {
                    "example": "Bringing Monstatek's M1 to market before its $2.8 million validation stands out.",
                    "required_terms": ["Monstatek", "$2.8 million"],
                },
            },
            "notes": "Approved comparison output.",
            "active": True,
        }],
    }
    preview = client.post(
        f"/api/enrich-lists/config/{ws_id}/training/preview",
        headers=headers(owner), json={"package": proposed},
    )
    check("training package previews", preview.status_code == 200, preview.text)
    preview_data = preview.json()
    check("preview reports rules and golden cases",
          {x["section"] for x in preview_data["changes"]} == {"rules", "evaluation_cases"})

    r = client.post(
        f"/api/enrich-lists/config/{ws_id}/training/apply",
        headers=headers(owner), json={"package": proposed},
    )
    check("apply requires reviewed revision", r.status_code == 409, r.text)
    applied = client.post(
        f"/api/enrich-lists/config/{ws_id}/training/apply",
        headers=headers(owner), json={
            "package": preview_data["normalized_package"],
            "expected_revision": preview_data["current_revision"],
            "note": "Add B2 benchmark",
        },
    )
    check("reviewed package applies", applied.status_code == 200, applied.text)
    check("apply creates a rollback point", bool(applied.json()["rollback_revision_id"]))

    updated = client.get(
        f"/api/enrich-lists/config/{ws_id}/training/export", headers=headers(owner),
    ).json()
    check("golden case persists", len(updated["evaluation_cases"]) == 1)
    check("training rule persists", "corporate jargon" in updated["config"]["rules"])

    no_confirm = client.post(
        f"/api/enrich-lists/config/{ws_id}/training/evaluate",
        headers=headers(owner), json={"confirm_spend": False},
    )
    check("live evaluation requires explicit cost confirmation", no_confirm.status_code == 422)
    from app.enrichment import ai
    original_call = ai._call_openai
    original_key = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "training-test-key"
    ai._call_openai = lambda *_args, **_kwargs: {"candidates": {
        "personalized_first_line": [
            "Monstatek's M1 reached $2.8 million in crowdfunding.",
            "Monstatek validated the M1 with $2.8 million in crowdfunding.",
        ],
    }}
    try:
        evaluated = client.post(
            f"/api/enrich-lists/config/{ws_id}/training/evaluate",
            headers=headers(owner), json={"confirm_spend": True},
        )
    finally:
        ai._call_openai = original_call
        if original_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = original_key
    check("golden evaluation runs through the live writer path",
          evaluated.status_code == 200, evaluated.text)
    check("required-term scorer passes the grounded result",
          evaluated.json()["passed"] == 1 and evaluated.json()["average_score"] == 100,
          evaluated.text)

    bad = client.post(
        f"/api/enrich-lists/config/{ws_id}/training/preview",
        headers=headers(owner), json={
            "package": {"config": {"profile": {"api_key": "must-not-import"}}},
        },
    )
    check("credential-shaped content is rejected", bad.status_code == 422, bad.text)

    approved = client.post(
        f"/api/enrich-lists/config/{ws_id}/formats/personalized_first_line/feedback",
        headers=headers(owner), json={
            "text": "Bringing the M1 to market before its crowdfunding result stands out.",
            "verdict": "approved", "reason": "",
        },
    )
    rejected = client.post(
        f"/api/enrich-lists/config/{ws_id}/formats/personalized_first_line/feedback",
        headers=headers(owner), json={
            "text": "Leveraging this differentiated capability can accelerate opportunity progression.",
            "verdict": "rejected", "reason": "Too corporate and abstract.",
        },
    )
    check("approved feedback persists", approved.status_code == 200, approved.text)
    check("rejected feedback persists with a reason", rejected.status_code == 200, rejected.text)
    cfg = client.get(f"/api/enrich-lists/config/{ws_id}", headers=headers(owner)).json()
    fmt = cfg["formats"][0]
    check("format stores both feedback lanes",
          len(fmt["examples"]) == 1 and fmt["rejected_examples"][0]["reason"] == "Too corporate and abstract.")

    revisions = client.get(
        f"/api/enrich-lists/config/{ws_id}/training/revisions", headers=headers(owner),
    ).json()
    check("revision history is visible", len(revisions) == 1)
    restored = client.post(
        f"/api/enrich-lists/config/{ws_id}/training/rollback/{revisions[0]['id']}",
        headers=headers(owner),
    )
    check("rollback succeeds", restored.status_code == 200, restored.text)
    rolled_back = client.get(
        f"/api/enrich-lists/config/{ws_id}/training/export", headers=headers(owner),
    ).json()
    check("rollback restores the pre-import package",
          rolled_back["config"]["rules"] == "Use specific facts."
          and rolled_back["evaluation_cases"] == [])

    print(f"\n{sum(PASS)}/{len(PASS)} checks passed")


if __name__ == "__main__":
    main()
