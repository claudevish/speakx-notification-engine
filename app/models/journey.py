import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Journey(Base):
    __tablename__ = "journeys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_chapters: Mapped[int] = mapped_column(default=0)
    llm_journey_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="journey",
        order_by="Chapter.chapter_number",
        cascade="all, delete-orphan",
    )


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        Index("ix_chapters_journey_chapter", "journey_id", "chapter_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    journey_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journeys.id"), index=True)
    chapter_number: Mapped[int] = mapped_column()
    name: Mapped[str] = mapped_column(String(255))
    theme: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    llm_analysis: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

    journey: Mapped["Journey"] = relationship(back_populates="chapters")
    quests: Mapped[list["Quest"]] = relationship(
        back_populates="chapter",
        order_by="Quest.quest_number",
        cascade="all, delete-orphan",
    )


class Quest(Base):
    __tablename__ = "quests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    journey_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journeys.id"), index=True)
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapters.id"), index=True)
    quest_number: Mapped[int] = mapped_column()
    name: Mapped[str] = mapped_column(String(255))
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

    chapter: Mapped["Chapter"] = relationship(back_populates="quests")
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="quest",
        order_by="Activity.activity_number",
        cascade="all, delete-orphan",
    )


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    journey_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journeys.id"), index=True)
    quest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quests.id"), index=True)
    activity_number: Mapped[int] = mapped_column()
    name: Mapped[str] = mapped_column(String(255))
    activity_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

    quest: Mapped["Quest"] = relationship(back_populates="activities")
    lessons: Mapped[list["Lesson"]] = relationship(
        back_populates="activity",
        order_by="Lesson.lesson_number",
        cascade="all, delete-orphan",
    )


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    journey_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journeys.id"), index=True)
    activity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("activities.id"), index=True)
    lesson_number: Mapped[int] = mapped_column()
    name: Mapped[str] = mapped_column(String(255))
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

    activity: Mapped["Activity"] = relationship(back_populates="lessons")
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="lesson",
        order_by="Task.task_number",
        cascade="all, delete-orphan",
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    journey_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journeys.id"), index=True)
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lessons.id"), index=True)
    task_number: Mapped[int] = mapped_column()
    name: Mapped[str] = mapped_column(String(255))
    task_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

    lesson: Mapped["Lesson"] = relationship(back_populates="tasks")
