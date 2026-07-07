"""User accounts. One table, a `role` column separates patients from chemists.
Chemists additionally own inventory + a pharmacy name."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")  # 'user' | 'chemist'
    pharmacy_name: Mapped[str] = mapped_column(String(160), default="")  # chemists only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    prescriptions = relationship("Prescription", back_populates="owner",
                                 cascade="all, delete-orphan")
    inventory = relationship("InventoryItem", back_populates="owner",
                             cascade="all, delete-orphan")
