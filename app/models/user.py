import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UserJourneyState(Base):
    __tablename__ = "user_journey_state"
    __table_args__ = (
        UniqueConstraint("user_id", "journey_id", name="uq_user_journey"),
        Index("ix_user_journey_state_state", "current_state"),
        Index("ix_user_journey_state_last_activity", "last_activity_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    journey_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journeys.id"), index=True)
    current_state: Mapped[str] = mapped_column(String(50), default="new_unstarted")
    state_entered_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    current_chapter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("chapters.id"), nullable=True,
    )
    current_quest_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("quests.id"), nullable=True,
    )
    activities_completed: Mapped[int] = mapped_column(default=0)
    chapter_progress: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    retry_count_window: Mapped[int] = mapped_column(default=0)
    avg_score_window: Mapped[float] = mapped_column(default=0.0)
    avg_completion_speed: Mapped[float] = mapped_column(default=0.0)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    journey: Mapped["Journey"] = relationship()
    current_chapter: Mapped[Optional["Chapter"]] = relationship()
    current_quest: Mapped[Optional["Quest"]] = relationship()


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    learning_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    profession: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    proficiency_level: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    language_comfort: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(server_default=func.now())
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)


# Forward references for relationships
from app.models.journey import Chapter, Journey, Quest  # noqa: E402, F401
