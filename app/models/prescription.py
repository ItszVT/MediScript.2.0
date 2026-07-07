"""Prescription scans and the medicine detections extracted from them."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok|no_match|empty
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    owner = relationship("User", back_populates="prescriptions")
    detections = relationship("Detection", back_populates="prescription",
                              cascade="all, delete-orphan")


class Detection(Base):
    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(
        ForeignKey("prescriptions.id"), index=True)
    line_text: Mapped[str] = mapped_column(Text, default="")
    matched_name: Mapped[str] = mapped_column(String(160), default="")
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    confirmed: Mapped[int] = mapped_column(Integer, default=0)  # 0/1

    prescription = relationship("Prescription", back_populates="detections")
