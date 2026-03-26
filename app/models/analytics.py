import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class JourneyProgressSnapshot(Base):
    __tablename__ = "journey_progress_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4,
    )
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    journey_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("journeys.id"),
    )
    snapshot_date: Mapped[date]
    state: Mapped[str] = mapped_column(String(50))
    chapter_progress: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
    )
    total_activities_completed: Mapped[int] = mapped_column(
        Integer, default=0,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "journey_id", "snapshot_date",
            name="uq_snapshot_user_journey_date",
        ),
    )


class AttributionEvent(Base):
    __tablename__ = "attribution_events"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4,
    )
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notifications.id"),
    )
    app_open_timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
    )
    attribution_window_hours: Mapped[int] = mapped_column(
        Integer, default=4,
    )
    activities_completed_after: Mapped[int] = mapped_column(
        Integer, default=0,
    )

    __table_args__ = (
        Index("ix_attribution_user_notif", "user_id", "notification_id"),
    )
