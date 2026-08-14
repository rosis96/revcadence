"""Seed a complete, safe local demo workspace.

This creates a realistic dashboard without configuring any live integration.
All contact addresses use example.com, which is reserved for documentation and
cannot receive email. Re-running is safe: an existing workspace with the same
slug is left unchanged.

Usage:
    python -m scripts.seed_demo --owner-email admin@ascendly.com
"""
import argparse
from datetime import datetime, timedelta

from app.db import init_db, session
from app.models.agreements import Agreement, Invoice
from app.models.billing import Subscription
from app.models.client_profile import ClientProfile
from app.models.crm import Activity, Company, Contact, Deal, Note, Stage, Task
from app.models.documents import Document
from app.models.enrich import EnrichConfig, EnrichLead, EnrichList
from app.models.identity import Membership, User, Workspace
from app.models.reply import ReplyLead
from app.provision import provision_workspace


WORKSPACE_NAME = "Acme Growth Partners"
WORKSPACE_SLUG = "acme-growth-partners"


def main():
    parser = argparse.ArgumentParser(description="Seed a safe local demo workspace")
    parser.add_argument("--owner-email", default="admin@ascendly.com")
    args = parser.parse_args()

    init_db()
    now = datetime.utcnow()
    with session() as db:
        owner = db.query(User).filter(User.email == args.owner_email.lower().strip()).first()
        if not owner:
            raise SystemExit(f"No local user found for {args.owner_email}. Create the admin account first.")
        membership = db.query(Membership).filter(Membership.user_id == owner.id).first()
        if not membership:
            raise SystemExit(f"{args.owner_email} has no organization membership.")
        existing = db.query(Workspace).filter(
            Workspace.org_id == membership.org_id, Workspace.slug == WORKSPACE_SLUG
        ).first()
        if existing:
            print(f"Demo workspace already exists: {existing.name} (id={existing.id})")
            return

        workspace = Workspace(
            org_id=membership.org_id,
            name=WORKSPACE_NAME,
            slug=WORKSPACE_SLUG,
            domain="acmegrowth.example.com",
            settings={"acv_default": 24000, "digest_client_name": WORKSPACE_NAME},
        )
        db.add(workspace)
        db.flush()
        provision_workspace(db, workspace)
        db.flush()

        config = db.query(EnrichConfig).filter(EnrichConfig.workspace_id == workspace.id).one()
        config.profile = {
            "company": "Acme Growth Partners",
            "offer": "Outbound pipeline generation for B2B service firms",
            "proof": "Qualified meetings with transparent pipeline reporting",
        }
        config.icp_definition = "B2B agencies and consultancies with 10–200 employees."
        config.rules = "Keep copy concise, specific, and grounded in public evidence."

        stage = {row.name: row for row in db.query(Stage).filter_by(workspace_id=workspace.id).all()}
        companies = [
            ("Northstar Studio", "northstar.example.com", "Creative services", "Maya", "Chen", "Founder"),
            ("Harbor Analytics", "harbor.example.com", "Analytics", "Owen", "Patel", "VP Growth"),
            ("Cedar & Co.", "cedar.example.com", "Professional services", "Priya", "Singh", "Managing Director"),
            ("Summit Software", "summit.example.com", "SaaS", "Leo", "Martinez", "CEO"),
            ("Brightline Ops", "brightline.example.com", "Operations consulting", "Nora", "Taylor", "COO"),
            ("Apex Commerce", "apex.example.com", "Ecommerce", "Jon", "Williams", "Head of Revenue"),
        ]
        crm = []
        for index, (name, domain, industry, first, last, title) in enumerate(companies):
            company = Company(workspace_id=workspace.id, name=name, domain=domain,
                              website=f"https://{domain}", industry=industry,
                              location="United States", employee_count=20 + index * 15,
                              revenue_range="$2M–$10M", icp_fit="strict")
            db.add(company)
            db.flush()
            contact = Contact(workspace_id=workspace.id, company_id=company.id,
                              first_name=first, last_name=last,
                              email=f"{first.lower()}.{last.lower()}@example.com",
                              title=title, location="United States", buying_role="decision maker",
                              email_status="valid", revenue_score=82 - index * 4, source="demo")
            db.add(contact)
            db.flush()
            crm.append((company, contact))

        deal_specs = [
            (0, "Opportunity", 18000, "Discovery call requested", 2),
            (1, "Meeting Booked", 24000, "Strategy call scheduled", 1),
            (2, "Meeting Completed", 32000, "Proposal requested", 3),
            (3, "Follow-up", 28000, "Waiting on leadership review", 9),
            (4, "Won", 36000, "Client onboarding in progress", 18),
            (5, "Lost", 15000, "Budget deferred to next quarter", 12),
        ]
        deals = []
        for company_index, stage_name, value, next_step, age in deal_specs:
            company, contact = crm[company_index]
            deal = Deal(workspace_id=workspace.id, company_id=company.id, contact_id=contact.id,
                        stage_id=stage[stage_name].id, name=f"{company.name} — Growth Program",
                        value=value, owner_user_id=owner.id, status_label=stage_name,
                        source="demo outbound", lead_intent="positive", next_step=next_step,
                        next_action_date=(now + timedelta(days=max(1, 5 - company_index))).date().isoformat(),
                        close_date=(now + timedelta(days=30)).date().isoformat(),
                        tags=["demo", "outbound"], stage_changed_at=now - timedelta(days=age))
            db.add(deal)
            db.flush()
            deals.append(deal)

        for deal in deals:
            db.add(Activity(workspace_id=workspace.id, company_id=deal.company_id, contact_id=deal.contact_id,
                            deal_id=deal.id, kind="deal_created", title=f"Deal created: {deal.name}",
                            actor_user_id=owner.id, occurred_at=now - timedelta(days=20)))
            db.add(Activity(workspace_id=workspace.id, company_id=deal.company_id, contact_id=deal.contact_id,
                            deal_id=deal.id, kind="email_out", title="Outbound introduction sent",
                            body="A concise, personalized outreach email.", actor_user_id=owner.id,
                            occurred_at=now - timedelta(days=12)))
            db.add(Activity(workspace_id=workspace.id, company_id=deal.company_id, contact_id=deal.contact_id,
                            deal_id=deal.id, kind="email_in", title="Interested — let’s discuss next steps",
                            body="This looks relevant. Can we book time next week?",
                            data={"intent": "positive"}, occurred_at=now - timedelta(days=8)))
            db.add(Activity(workspace_id=workspace.id, company_id=deal.company_id, contact_id=deal.contact_id,
                            deal_id=deal.id, kind="stage_change", title=f"Moved to {deal.status_label}",
                            actor_user_id=owner.id, occurred_at=deal.stage_changed_at))

        meeting = deals[1]
        db.add(Activity(workspace_id=workspace.id, company_id=meeting.company_id, contact_id=meeting.contact_id,
                        deal_id=meeting.id, kind="meeting_booked", title="Harbor Analytics strategy call",
                        data={"duration_minutes": 30}, occurred_at=now.replace(hour=14, minute=0, second=0, microsecond=0)))
        db.add_all([
            Task(workspace_id=workspace.id, deal_id=deals[0].id, contact_id=deals[0].contact_id,
                 title="Prepare discovery-call brief", due_at=now + timedelta(days=1), assignee_user_id=owner.id),
            Task(workspace_id=workspace.id, deal_id=deals[2].id, contact_id=deals[2].contact_id,
                 title="Send tailored proposal", due_at=now + timedelta(days=2), assignee_user_id=owner.id),
            Task(workspace_id=workspace.id, deal_id=deals[3].id, contact_id=deals[3].contact_id,
                 title="Follow up on leadership review", due_at=now + timedelta(days=3), assignee_user_id=owner.id),
        ])
        db.add(Note(workspace_id=workspace.id, company_id=deals[2].company_id, contact_id=deals[2].contact_id,
                    deal_id=deals[2].id, author_user_id=owner.id,
                    body="Strong fit: they need a repeatable qualified-meeting engine before Q4."))

        replies = [
            ("Maya Chen", "maya.chen@example.com", "positive", "would_send", False, "booked"),
            ("Owen Patel", "owen.patel@example.com", "pricing_question", "would_send", False, "new"),
            ("Priya Singh", "priya.singh@example.com", "positive", "send", True, "replied"),
            ("Jon Williams", "jon.williams@example.com", "not_interested", "stop", True, "stopped"),
        ]
        for name, email, intent, action, reviewed, status in replies:
            db.add(ReplyLead(workspace_id=workspace.id, reply_workspace=workspace.name, platform="demo",
                             dedupe_key=f"demo:{email}", name=name, email=email,
                             company=name.split()[0] + " Demo", campaign="Q3 Growth Campaign",
                             subject="Quick question about pipeline", intent=intent, intent_bucket=intent,
                             confidence="high", conf_num=0.91, action=action, reviewed=reviewed,
                             replied=action == "send", reply_added=action == "send", stage=status,
                             reply_text="This looks interesting — could you share more detail?",
                             main_reply="Thanks for the reply. Here are a few relevant ideas.",
                             thread=[{"direction": "in", "text": "Interested in learning more."}]))

        lead_list = EnrichList(workspace_id=workspace.id, name="August agency prospects",
                               icp_definition=config.icp_definition)
        db.add(lead_list)
        db.flush()
        for first, last, company in [("Avery", "Brooks", "Evergreen Creative"), ("Sam", "Kim", "Vector Partners"),
                                     ("Jordan", "Reed", "Orbit Studio"), ("Casey", "Morgan", "Fieldwork"),
                                     ("Riley", "Adams", "Juniper Labs")]:
            db.add(EnrichLead(workspace_id=workspace.id, list_id=lead_list.id, first_name=first, last_name=last,
                              title="Founder", company=company, website=f"https://{company.lower().replace(' ', '')}.example.com",
                              email=f"{first.lower()}.{last.lower()}@example.com", industry="Professional services",
                              free_status="ok", email_status="safe", verify_source="free", title_status="pass",
                              icp_decision="ICP", icp_score=86, icp_reason="Matches the demo ICP.",
                              status="done", result={"opener": f"Noticed {company}'s focus on growth."}))

        blueprint = Document(workspace_id=workspace.id, company_id=deals[2].company_id,
                             contact_id=deals[2].contact_id, deal_id=deals[2].id, kind="blueprint",
                             status="published", title="Cedar & Co. Growth Blueprint", slug="cedar-growth-blueprint",
                             published=True, html="<h1>Growth Blueprint</h1><p>Demo content only.</p>",
                             view_count=2, first_viewed_at=now - timedelta(days=2))
        db.add(blueprint)
        db.flush()
        agreement = Agreement(workspace_id=workspace.id, company_id=deals[2].company_id,
                              contact_id=deals[2].contact_id, deal_id=deals[2].id,
                              blueprint_doc_id=blueprint.id, number="AGR-DEMO-001",
                              title="Cedar & Co. Growth Program Agreement", slug="cedar-growth-agreement",
                              public_token="demo-agreement-token", status="sent",
                              fields={"fees": {"setup": 4000, "recurring": 2500}, "term": "3 months"},
                              sections=[{"key": "scope", "label": "Scope", "body": "Demo agreement scope."}])
        db.add(agreement)
        db.flush()
        db.add(Invoice(workspace_id=workspace.id, company_id=deals[2].company_id, contact_id=deals[2].contact_id,
                       deal_id=deals[2].id, agreement_id=agreement.id, number="INV-DEMO-001",
                       slug="cedar-growth-invoice", public_token="demo-invoice-token", status="issued",
                       issue_date=now.date().isoformat(), due_date=(now + timedelta(days=14)).date().isoformat(),
                       bill_to_name="Priya Singh", bill_to_company="Cedar & Co.", bill_to_email="priya.singh@example.com",
                       line_items=[{"description": "Growth program — month one", "quantity": 1, "rate": 2500, "amount": 2500}],
                       subtotal=2500, total=2500, balance_due=2500, notes="Demo invoice — no payment is requested."))

        won_company, won_contact = crm[4]
        db.add(ClientProfile(workspace_id=workspace.id, company_id=won_company.id, contact_id=won_contact.id,
                             deal_id=deals[4].id, is_active_client=True, scope_type="full",
                             onboarding_status="approved", completeness=85,
                             data={"overview": {"company_name": {"value": won_company.name, "source": "demo"}},
                                   "delivery_scope": {"offer": {"value": "Outbound pipeline", "source": "demo"}}}))
        db.add(Subscription(workspace_id=workspace.id, plan_name="Growth", price_monthly=2500,
                            status="active", started_at=now - timedelta(days=18),
                            current_period_end=now + timedelta(days=12), notes="Local demo subscription."))

        print(f"Created demo workspace '{workspace.name}' (id={workspace.id})")
        print("Seeded: 6 companies, 6 contacts, 6 deals, activities, tasks, replies, enrichment leads, documents, agreement, invoice, client profile, and subscription.")


if __name__ == "__main__":
    main()
