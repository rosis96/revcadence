"""Platform billing — one subscription per client workspace. Works manually
today (you record the plan/price/status); Stripe-ready fields let it be
automated later without a schema change."""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from ..db import Base

# canonical statuses (mirror Stripe's so automation is a drop-in later)
SUB_STATUSES = ("trialing", "active", "past_due", "canceled", "none")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), unique=True, nullable=False, index=True)
    plan_name = Column(String(120), default="Pilot")
    price_monthly = Column(Float, default=0.0)     # what this client pays / month
    status = Column(String(20), default="none")    # trialing | active | past_due | canceled | none
    started_at = Column(DateTime)
    current_period_end = Column(DateTime)          # next renewal / when access lapses
    notes = Column(Text, default="")
    # Stripe linkage (optional — for future automation)
    stripe_customer_id = Column(String(120), default="")
    stripe_subscription_id = Column(String(120), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
