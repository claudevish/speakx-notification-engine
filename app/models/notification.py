import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_scheduled", "user_id", "scheduled_for"),
        Index("ix_notifications_mode_created", "mode", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    journey_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journeys.id"))
    state_at_generation: Mapped[str] = mapped_column(String(50))
    theme: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    cta: Mapped[str] = mapped_column(String(255))
    generation_method: Mapped[str] = mapped_column(String(30))
    llm_prompt_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mode: Mapped[str] = mapped_column(String(10), default="shadow")
    delivery_status: Mapped[str] = mapped_column(String(20), default="pending")
    clevertap_campaign_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    image_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    __table_args__ = (
        Index("ix_notif_events_notif_type", "notification_id", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("notifications.id"), index=True, nullable=True,
    )
    user_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(20))
    timestamp: Mapped[datetime] = mapped_column(server_default=func.now())
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
