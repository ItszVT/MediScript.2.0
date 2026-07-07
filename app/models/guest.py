"""Anonymous guest usage — powers the 'try once without signing in' demo.
Keyed by a random guest cookie; counts how many free actions were used."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GuestUsage(Base):
    __tablename__ = "guest_usage"

    guest_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    uploads: Mapped[int] = mapped_column(Integer, default=0)
    searches: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
