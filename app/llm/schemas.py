from pydantic import BaseModel


class JourneyAnalysis(BaseModel):
    summary: str
    emotional_arc: list[str]
    narrative_themes: list[str]
    character_relationships: list[dict]
    segment_signals: dict
    difficulty_progression: str


class ChapterAnalysis(BaseModel):
    emotional_context: str
    difficulty_curve: str
    key_vocabulary: list[str]
    narrative_moment: str
    segment_content: dict
    engagement_hooks: list[str]


class NotificationPrompt(BaseModel):
    user_state: str
    user_profile: dict
    chapter_analysis: dict
    journey_summary: str
    notification_theme: str
    constraints: dict


class NotificationCopy(BaseModel):
    title: str
    body: str
    cta: str
    theme_used: str
    confidence: float
