"""The Client Profile field catalog (structured sections, not one JSON blob) and
the scope-specific onboarding-form generator.

SECTIONS defines every editable section and its fields. Each field is
(key, label, visibility) where visibility is "internal" or "client" (client =
information the client can see / provides). The UI renders these as structured
inputs; values + provenance are stored per field in ClientProfile.data.
"""

# section_key -> (label, [ (field_key, label, visibility) ])
SECTIONS = {
    "overview": ("Company & Offer", [
        ("company_name", "Company name", "client"),
        ("website", "Website", "client"),
        ("industry", "Industry / category", "client"),
        ("business_overview", "Business overview", "client"),
        ("products_services", "Products / services", "client"),
        ("main_offer", "Main offer", "client"),
        ("avg_deal_value", "Average deal / project value", "internal"),
        ("target_markets", "Target markets & geography", "client"),
        ("differentiators", "Differentiators", "client"),
        ("competitors", "Competitors", "internal"),
        ("case_studies", "Case studies & proof", "client"),
        ("positioning", "Current positioning", "client"),
    ]),
    "icp": ("ICP & Targeting", [
        ("icp_industries", "Ideal customer industries", "internal"),
        ("company_sizes", "Company sizes", "internal"),
        ("revenue_ranges", "Revenue ranges", "internal"),
        ("locations", "Locations", "internal"),
        ("decision_titles", "Decision-maker titles", "internal"),
        ("buying_triggers", "Buying triggers", "internal"),
        ("qualification_rules", "Qualification rules", "internal"),
        ("non_icp_rules", "Non-ICP rules", "internal"),
        ("exclusions", "Exclusions", "internal"),
        ("min_deal_value", "Minimum deal value", "internal"),
    ]),
    "sales_process": ("Sales & Revenue Process", [
        ("lead_sources", "Current lead sources", "internal"),
        ("outbound_setup", "Outbound setup", "internal"),
        ("inbound_setup", "Inbound setup", "internal"),
        ("crm_tools", "CRM & tools", "internal"),
        ("sales_stages", "Sales stages", "internal"),
        ("avg_sales_cycle", "Average sales cycle", "internal"),
        ("meeting_qualification", "Meeting qualification definition", "internal"),
        ("followup_process", "Current follow-up process", "internal"),
        ("proposal_process", "Proposal process", "internal"),
        ("common_objections", "Common objections", "internal"),
        ("revenue_leaks", "Known revenue leaks", "internal"),
    ]),
    "delivery_scope": ("Delivery Scope", [
        ("services_purchased", "Services purchased", "client"),
        ("deliverables", "Agreed deliverables", "client"),
        ("channels", "Channels included", "client"),
        ("targets", "Meeting / pipeline targets", "client"),
        ("implementation_reqs", "Implementation requirements", "client"),
        ("dependencies", "Dependencies", "internal"),
        ("client_responsibilities", "Client responsibilities", "client"),
        ("revcadence_responsibilities", "RevCadence responsibilities", "client"),
        ("scope_exclusions", "Exclusions", "client"),
        ("start_date", "Start date", "client"),
        ("term", "Term", "client"),
        ("pricing", "Pricing", "client"),
        ("revenue_share", "Commission / revenue-share terms", "internal"),
        ("special_conditions", "Special conditions", "internal"),
    ]),
    "messaging": ("Messaging & Content", [
        ("value_prop", "Value proposition", "client"),
        ("approved_pitch", "Approved pitch", "internal"),
        ("approved_claims", "Approved claims", "internal"),
        ("tone_of_voice", "Tone of voice", "internal"),
        ("personalization_rules", "Personalization rules", "internal"),
        ("prohibited_claims", "Prohibited claims", "internal"),
        ("mentionable_proof", "Case studies we may mention", "internal"),
        ("reply_formats", "Response / reply formats", "internal"),
        ("scheduling_rules", "Scheduling rules", "internal"),
        ("sender_identities", "Sender identities", "internal"),
        ("brand_assets", "Brand assets & links", "client"),
    ]),
    "onboarding_info": ("Onboarding Information", [
        ("kickoff_notes", "Kickoff notes", "internal"),
        ("meeting_transcript", "Meeting transcript", "internal"),
        ("uploaded_files", "Uploaded files", "internal"),
        ("credentials_supplied", "Credentials supplied", "internal"),
        ("integrations_requested", "Integrations requested", "internal"),
        ("domains_accounts", "Domains / accounts", "internal"),
        ("calendars", "Calendars", "internal"),
        ("crm_access", "CRM access", "internal"),
        ("campaign_requirements", "Campaign requirements", "internal"),
        ("client_goals", "Client goals", "client"),
        ("client_concerns", "Client concerns", "internal"),
        ("client_expectations", "Client expectations", "client"),
        ("approval_notes", "Approval notes", "internal"),
    ]),
}

# Fields that feed the onboarding-completeness %, per scope.
_CORE_COMMON = ["overview.main_offer", "overview.business_overview", "delivery_scope.services_purchased",
                "delivery_scope.deliverables", "delivery_scope.start_date", "onboarding_info.client_goals"]
_CORE_OUTBOUND = ["icp_industries", "icp.decision_titles", "messaging.sender_identities",
                  "onboarding_info.domains_accounts", "onboarding_info.calendars", "icp.exclusions"]
_CORE_INBOUND = ["sales_process.inbound_setup", "sales_process.crm_tools",
                 "sales_process.meeting_qualification", "onboarding_info.crm_access"]


def completeness_fields(scope_type: str) -> list:
    fields = list(_CORE_COMMON)
    if scope_type in ("outbound", "full"):
        fields += ["icp.icp_industries", "icp.decision_titles", "messaging.sender_identities",
                   "onboarding_info.domains_accounts", "onboarding_info.calendars", "icp.exclusions"]
    if scope_type in ("inbound", "full"):
        fields += ["sales_process.inbound_setup", "sales_process.crm_tools",
                   "sales_process.meeting_qualification", "onboarding_info.crm_access"]
    if scope_type == "full":
        fields += ["sales_process.proposal_process", "delivery_scope.targets", "sales_process.revenue_leaks"]
    return sorted(set(fields))


# ------- onboarding form questions (only relevant ones show, per scope) -------
_Q_OUTBOUND = [
    ("icp.icp_industries", "Which industries are your ideal customers in?", "textarea"),
    ("icp.decision_titles", "What job titles do you sell to?", "textarea"),
    ("icp.exclusions", "Any industries/companies we should NEVER contact?", "textarea"),
    ("overview.main_offer", "What is the core offer we should pitch?", "textarea"),
    ("overview.case_studies", "Proof / case studies we can reference?", "textarea"),
    ("messaging.sender_identities", "Which sender name(s) and email(s) should we send from?", "textarea"),
    ("onboarding_info.domains_accounts", "Sending domains / accounts to use?", "textarea"),
    ("onboarding_info.calendars", "Calendar / booking link for meetings?", "text"),
]
_Q_INBOUND = [
    ("sales_process.inbound_setup", "Where do inbound leads come from (forms, website, chat)?", "textarea"),
    ("overview.website", "Website URL", "text"),
    ("sales_process.followup_process", "How are inbound leads routed & responded to today?", "textarea"),
    ("sales_process.meeting_qualification", "What makes an inbound lead 'qualified'?", "textarea"),
    ("sales_process.crm_tools", "What CRM / tools do you use?", "textarea"),
    ("delivery_scope.client_responsibilities", "Who owns responses on your side?", "textarea"),
]
_Q_FULL_EXTRA = [
    ("sales_process.sales_stages", "What are your sales stages / pipeline?", "textarea"),
    ("sales_process.proposal_process", "How do proposals work today?", "textarea"),
    ("sales_process.revenue_leaks", "Where do deals most often stall or leak?", "textarea"),
    ("delivery_scope.targets", "What meeting / pipeline targets are we aiming for?", "textarea"),
]
_Q_COMMON_TAIL = [
    ("onboarding_info.client_goals", "What does success look like in the first 90 days?", "textarea"),
    ("onboarding_info.client_concerns", "Any concerns or must-avoids?", "textarea"),
    ("onboarding_info.integrations_requested", "Integrations you want connected?", "textarea"),
]


def build_onboarding_form(scope_type: str) -> dict:
    """A scope-specific onboarding form so irrelevant questions aren't shown."""
    qs = []
    if scope_type in ("outbound", "full"):
        qs += _Q_OUTBOUND
    if scope_type in ("inbound", "full"):
        qs += _Q_INBOUND
    if scope_type == "full":
        qs += _Q_FULL_EXTRA
    qs += _Q_COMMON_TAIL
    # de-dup by target field, preserve order
    seen, fields = set(), []
    for target, label, ftype in qs:
        if target in seen:
            continue
        seen.add(target)
        fields.append({"target": target, "label": label, "type": ftype})
    return {"scope_type": scope_type, "fields": fields}


def field_meta(target: str):
    """(section_label, field_label, visibility) for a 'section.field' target."""
    if "." not in target:
        return None
    sec, fld = target.split(".", 1)
    s = SECTIONS.get(sec)
    if not s:
        return None
    for k, label, vis in s[1]:
        if k == fld:
            return s[0], label, vis
    return None
