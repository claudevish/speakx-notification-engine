import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CSVRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    journey_name: str
    chapter_name: str
    chapter_number: int
    quest_name: str
    quest_number: int
    activity_name: str
    activity_number: int
    activity_type: Optional[str] = None
    lesson_name: str
    lesson_number: int
    task_name: str
    task_number: int
    task_type: Optional[str] = None


class TaskStructure(BaseModel):
    name: str
    task_number: int
    task_type: Optional[str] = None


class LessonStructure(BaseModel):
    name: str
    lesson_number: int
    tasks: list[TaskStructure] = []


class ActivityStructure(BaseModel):
    name: str
    activity_number: int
    activity_type: Optional[str] = None
    lessons: list[LessonStructure] = []


class QuestStructure(BaseModel):
    name: str
    quest_number: int
    activities: list[ActivityStructure] = []


class ChapterStructure(BaseModel):
    name: str
    chapter_number: int
    theme: Optional[str] = None
    quests: list[QuestStructure] = []


class JourneyStructure(BaseModel):
    name: str
    chapters: list[ChapterStructure] = []


class IngestionStatus(BaseModel):
    journey_id: Optional[uuid.UUID] = None
    status: str
    total_rows: int = 0
    processed_rows: int = 0
    chapters_analyzed: int = 0
    total_chapters: int = 0
    errors: list[str] = []
    started_at: datetime
    completed_at: Optional[datetime] = None
