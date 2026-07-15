"""Agreements & Invoices — the contract + billing layer of RevCadence.

An Agreement is a versioned, signable contract linked to the CRM graph
(workspace/company/contact/deal/blueprint/client_profile). Once both signatures
are captured it is EXECUTED: the HTML is frozen, a checksum is stored, and the
version is locked — future changes require a new version/amendment.

An Invoice is a professional bill linked to the same graph (and usually to the
executed Agreement). Neither model stores secrets; public pages read from the
frozen/rendered fields, never the internal notes.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text

from ..db import Base

# Enforced server-side (service.validate_transition).
AGREEMENT_STATUSES = ("draft", "ready", "sent", "viewed", "client_signed",
                      "countersigned", "executed", "voided", "archived")
# A signed/executed agreement is immutable; these may still be edited freely.
EDITABLE_STATUSES = ("draft", "ready")

INVOICE_STATUSES = ("draft", "issued", "viewed", "partially_paid", "paid", "overdue", "void")


class Agreement(Base):
    __tablename__ = "agreements"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), index=True)
    blueprint_doc_id = Column(Integer, ForeignKey("documents.id"), index=True)
    client_profile_id = Column(Integer, ForeignKey("client_profiles.id"), index=True)

    # identity / public routing
    number = Column(String(40), default="", index=True)      # AGR-000123
    title = Column(String(512), default="")
    slug = Column(String(255), default="", index=True)       # agreement.<domain>/<slug>
    public_token = Column(String(64), default="", index=True)  # hard-to-guess; required to sign

    status = Column(String(30), nullable=False, default="draft", index=True)

    # versioning: a chain of Agreement rows. root_id groups a version family;
    # version increments; is_current marks the live one. Amendments are new rows.
    version = Column(Integer, default=1)
    root_id = Column(Integer, index=True)      # id of v1 (self for v1)
    supersedes_id = Column(Integer, index=True)  # the version this replaced
    is_current = Column(Boolean, default=True)

    # content
    sections = Column(JSON, default=list)   # [{key,label,body}] structured contract body
    fields = Column(JSON, default=dict)     # effective_date, fees{setup,recurring,...}, term, etc.
    missing_flags = Column(JSON, default=list)  # ["fees.recurring", ...] required-but-empty
    html = Column(Text, default="")         # rendered public HTML (draft/live)

    # client signature
    client_signer_name = Column(String(255), default="")
    client_signer_email = Column(String(255), default="")
    client_signer_title = Column(String(255), default="")
    client_signature_repr = Column(Text, default="")     # styled name rendering (NOT biometric)
    client_consent_text = Column(Text, default="")
    client_consent_version = Column(String(40), default="")
    client_signed_at = Column(DateTime)
    client_ip = Column(String(64), default="")
    client_user_agent = Column(String(512), default="")
    client_sig_doc_version = Column(Integer)             # agreement.version at signing

    # internal countersignature
    counter_signer_name = Column(String(255), default="")
    counter_signer_email = Column(String(255), default="")
    counter_signer_title = Column(String(255), default="")
    counter_signature_repr = Column(Text, default="")
    counter_user_id = Column(Integer, ForeignKey("users.id"))
    countersigned_at = Column(DateTime)
    counter_ip = Column(String(64), default="")
    counter_user_agent = Column(String(512), default="")

    # execution / locking
    executed_at = Column(DateTime)
    executed_html = Column(Text, default="")   # frozen snapshot the executed PDF renders from
    checksum = Column(String(80), default="")  # sha256 of the executed content
    locked = Column(Boolean, default=False)

    # view tracking
    first_viewed_at = Column(DateTime)
    last_viewed_at = Column(DateTime)
    view_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)   # billing contact
    deal_id = Column(Integer, ForeignKey("deals.id"), index=True)
    agreement_id = Column(Integer, ForeignKey("agreements.id"), index=True)
    client_profile_id = Column(Integer, ForeignKey("client_profiles.id"), index=True)

    number = Column(String(40), default="", index=True)    # INV-000123
    slug = Column(String(255), default="", index=True)
    public_token = Column(String(64), default="", index=True)
    status = Column(String(30), nullable=False, default="draft", index=True)

    issue_date = Column(String(20), default="")   # ISO date strings (no tz ambiguity)
    due_date = Column(String(20), default="")
    currency = Column(String(8), default="USD")

    bill_to_name = Column(String(255), default="")
    bill_to_company = Column(String(255), default="")
    bill_to_address = Column(Text, default="")
    bill_to_email = Column(String(255), default="")

    line_items = Column(JSON, default=list)   # [{description, quantity, rate, amount}]
    tax_rate = Column(Float, default=0.0)     # percent
    tax_amount = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    subtotal = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    amount_paid = Column(Float, default=0.0)
    balance_due = Column(Float, default=0.0)

    notes = Column(Text, default="")
    payment_instructions = Column(Text, default="")

    first_viewed_at = Column(DateTime)
    last_viewed_at = Column(DateTime)
    view_count = Column(Integer, default=0)
    paid_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
