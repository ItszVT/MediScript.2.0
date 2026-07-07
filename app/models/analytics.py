"""Persistent analytics — stored in the database, aggregated across ALL time
and sessions (not per-session). Three event tables feed both the user's
personal analytics and the chemist's business analytics."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class VoteEvent(Base):
    """Yes/No verdict on a prediction (was the matched medicine correct?)."""
    __tablename__ = "vote_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True)
    context: Mapped[str] = mapped_column(String(16))       # upload|search
    query: Mapped[str] = mapped_column(String(300), default="")
    predicted: Mapped[str] = mapped_column(String(200), default="")
    verdict: Mapped[str] = mapped_column(String(4))        # yes|no
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)


class SearchEvent(Base):
    """A medicine search performed by a user (drives 'most searched')."""
    __tablename__ = "search_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True)
    query: Mapped[str] = mapped_column(String(200), index=True)
    top_result: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)


class StockEvent(Base):
    """Outcome of a stock check when a medicine was confirmed."""
    __tablename__ = "stock_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True)
    medicine: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(16))   # in_stock|out_of_stock|not_stocked
    role: Mapped[str] = mapped_column(String(16), default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True)
