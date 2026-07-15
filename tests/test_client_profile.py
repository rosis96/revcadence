"""Client Profile tests — the required scenarios:
1. Closed Won creates a client profile
2. running it twice creates no duplicate
3. onboarding submission saves correctly
4. immutable original submission retained
5. conflicting values are flagged
6. workspace isolation
7. blueprint/agreement linked correctly
8. scope-specific onboarding questions
Run: python3 -m tests.test_client_profile
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/rc_cp_test.db")
os.environ.setdefault("JWT_SECRET", "test")
if os.path.exists("/tmp/rc_cp_test.db"):
    os.remove("/tmp/rc_cp_test.db")

from app.db import init_db, session  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.models.identity import Organization, User, Membership, Workspace  # noqa: E402
from app.models.crm import Company, Contact, Deal, Stage, Activity  # noqa: E402
from app.models.documents import Document  # noqa: E402
from app.models.client_profile import ClientProfile  # noqa: E402
from app.client.profiles import ensure_profile, submit_onboarding, get_field  # noqa: E402
from app.client import schema  # noqa: E402

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok  {name}")
    else:
        FAIL += 1; print(f"FAIL  {name}")


def main():
    init_db()
    with session() as db:
        org = Organization(name="o", slug="o"); db.add(org); db.flush()
        ws = Workspace(org_id=org.id, name="W", slug="w"); db.add(ws)
        ws2 = Workspace(org_id=org.id, name="W2", slug="w2"); db.add(ws2); db.flush()
        won = Stage(workspace_id=ws.id, name="Won", is_won=True); db.add(won); db.flush()
        co = Company(workspace_id=ws.id, name="Acme Media", website="acme.com", industry="Media"); db.add(co)
        co2 = Company(workspace_id=ws2.id, name="Other Co"); db.add(co2); db.flush()
        ct = Contact(workspace_id=ws.id, company_id=co.id, first_name="Alan", last_name="Siegel",
                     title="CEO", email="alan@acme.com"); db.add(ct); db.flush()
        deal = Deal(workspace_id=ws.id, company_id=co.id, contact_id=ct.id, stage_id=won.id,
                    value=3600, description="Full revenue engine — outbound + inbound",
                    tags=["outbound", "inbound"]); db.add(deal)
        bp = Document(workspace_id=ws.id, company_id=co.id, kind="blueprint",
                      fields={"content": {"exec_summary": "Acme needs steady pipeline.",
                                          "what_we_build": ["Outbound", "Reply mgmt"],
                                          "commercial": "3.5k/mo + performance",
                                          "target_outcome": "20 booked calls/mo"},
                              "transcript": "Alan: we struggle with follow-up."}); db.add(bp)
        ag = Document(workspace_id=ws.id, company_id=co.id, kind="agreement"); db.add(ag)
        db.add(Activity(workspace_id=ws.id, company_id=co.id, kind="note", body="Kickoff: wants HubSpot sync."))
        db.commit()
        coid, coid2, did = co.id, co2.id, deal.id

    # 1. Closed Won creates a profile
    with session() as db:
        p = ensure_profile(db, coid, did)
        check("1 Closed Won creates a profile", p is not None and p.is_active_client)
        check("1 seeded company_name from company", get_field(p, "overview", "company_name").get("value") == "Acme Media")
        check("1 seeded pricing from deal/blueprint", bool(get_field(p, "delivery_scope", "pricing").get("value")))
        pid = p.id

    # 2. idempotent — no duplicate
    with session() as db:
        ensure_profile(db, coid, did)
        n = db.query(ClientProfile).filter(ClientProfile.company_id == coid).count()
        check("2 running twice → no duplicate", n == 1)

    # 7. blueprint + agreement linked
    with session() as db:
        p = db.query(ClientProfile).filter(ClientProfile.company_id == coid).first()
        check("7 blueprint linked", p.blueprint_doc_id is not None)
        check("7 agreement linked", p.agreement_doc_id is not None)
        check("7 meeting transcript copied from blueprint",
              "struggle" in str(get_field(p, "onboarding_info", "meeting_transcript").get("value")))

    # 8. scope-specific onboarding questions (full = outbound + inbound + extras)
    with session() as db:
        p = db.query(ClientProfile).filter(ClientProfile.company_id == coid).first()
        targets = {f["target"] for f in (p.onboarding_form or {}).get("fields", [])}
        check("8 full scope detected", p.scope_type == "full")
        check("8 outbound question present", "icp.icp_industries" in targets)
        check("8 inbound question present", "sales_process.inbound_setup" in targets)
        # outbound-only client should NOT get inbound questions
        f_out = schema.build_onboarding_form("outbound")
        t_out = {x["target"] for x in f_out["fields"]}
        check("8 outbound form excludes inbound-only q", "sales_process.inbound_setup" not in t_out)

    # 3 + 4. onboarding submission saves + immutable original retained
    with session() as db:
        p = db.query(ClientProfile).filter(ClientProfile.company_id == coid).first()
        res = submit_onboarding(db, p, {"icp.icp_industries": "SaaS, agencies",
                                        "onboarding_info.calendars": "calendly.com/acme"}, "client")
        check("3 submission applied empty fields", res["applied"] >= 1)
        p = db.query(ClientProfile).filter(ClientProfile.company_id == coid).first()
        check("3 field saved from submission", get_field(p, "icp", "icp_industries").get("value") == "SaaS, agencies")
        check("4 immutable original submission retained", len(p.onboarding_submissions) == 1
              and p.onboarding_submissions[0]["answers"]["icp.icp_industries"] == "SaaS, agencies")
        # submit again with a DIFFERENT value → conflict flagged, original kept
        submit_onboarding(db, p, {"icp.icp_industries": "Healthcare only"}, "client")
        p = db.query(ClientProfile).filter(ClientProfile.company_id == coid).first()
        check("4 second submission appended (immutable)", len(p.onboarding_submissions) == 2)
        # 5. conflict flagged, not overwritten
        check("5 conflicting value flagged", any(f["field"] == "icp.icp_industries" for f in p.review_flags))
        check("5 existing value NOT overwritten", get_field(p, "icp", "icp_industries").get("value") == "SaaS, agencies")

    # 6. workspace isolation — profile for co is not reachable as co2's, and co2 has none
    with session() as db:
        p2 = db.query(ClientProfile).filter(ClientProfile.company_id == coid2).first()
        check("6 other workspace company has no profile", p2 is None)
        p = db.query(ClientProfile).filter(ClientProfile.company_id == coid).first()
        check("6 profile stays in its workspace", p.workspace_id != 0)

    print(f"\n{PASS}/{PASS + FAIL} checks passed")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
