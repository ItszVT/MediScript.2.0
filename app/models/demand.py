"""Anonymous medicine demand + restock requests.

Every time a medicine is confirmed (from OCR) or searched, a DemandEvent is
recorded (no patient identity stored). When a demanded medicine isn't in a
chemist's stock, a RestockRequest is opened/incremented — de-duplicated so a
popular missing medicine shows as one row with a rising count.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DemandEvent(Base):
    __tablename__ = "demand_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    medicine: Mapped[str] = mapped_column(String(160), index=True)
    source: Mapped[str] = mapped_column(String(16), default="upload")  # upload|search
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)


class RestockRequest(Base):
    __tablename__ = "restock_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    medicine: Mapped[str] = mapped_column(String(160), index=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    reason: Mapped[str] = mapped_column(String(24), default="not_stocked")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now)
