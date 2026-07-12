"""Global key/value settings (org-wide) — port of the legacy app_settings.
Used by Reply Settings: OpenAI/Gemini keys, models, review webhook, reply
delay, trigger tags. Secret values are encrypted at rest."""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from ..db import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(120), primary_key=True)
    value = Column(Text, default="")
    is_secret = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
