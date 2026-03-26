"""Pydantic schemas for Redis Stream event payloads."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class ProgressEvent(BaseModel):
    event_id: str
    user_id: str
    event_type: Literal[
        "activity_completed",
        "chapter_completed",
        "quest_completed",
        "app_opened",
        "session_ended",
    ]
    journey_id: str
    chapter_id: Optional[str] = None
    quest_id: Optional[str] = None
    activity_id: Optional[str] = None
    score: Optional[float] = None
    retry_count: Optional[int] = None
    time_spent_seconds: Optional[float] = None
    timestamp: datetime
    metadata: Optional[dict] = None


class ProfileEvent(BaseModel):
    event_id: str
    user_id: str
    event_type: Literal["profile_created", "profile_updated"]
    learning_reason: Optional[str] = None
    profession: Optional[str] = None
    region: Optional[str] = None
    proficiency_level: Optional[str] = None
    language_comfort: Optional[str] = None
    timestamp: datetime
