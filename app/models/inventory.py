"""Chemist inventory. Fields with no free public source (rack, expiry,
supplier, purchase history) live here and are populated ONLY from a chemist's
own connected data. The `is_demo` flag marks seeded demo rows so they can be
filtered out / cleared, keeping demo data separate from production."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    name: Mapped[str] = mapped_column(String(160), index=True)
    brand: Mapped[str] = mapped_column(String(160), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # chemist-owned fields (no public source; supplied by the chemist)
    rack_location: Mapped[str] = mapped_column(String(60), default="")
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier: Mapped[str] = mapped_column(String(160), default="")
    reorder_level: Mapped[int] = mapped_column(Integer, default=10)

    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now)

    owner = relationship("User", back_populates="inventory")
