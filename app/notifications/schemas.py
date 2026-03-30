"""Notification schemas for segment-based bulk template generation.

Defines the 4 engagement segments, 8 Octolysis themes, and data models
for bulk notification template generation (Segments × Quests × Themes × Templates).
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class NotificationTheme(str, Enum):
    epic_meaning = "epic_meaning"
    accomplishment = "accomplishment"
    empowerment = "empowerment"
    ownership = "ownership"
    social_influence = "social_influence"
    scarcity = "scarcity"
    unpredictability = "unpredictability"
    loss_avoidance = "loss_avoidance"


class EngagementSegment(str, Enum):
    """4 user engagement segments based on engagement score (0-100)."""
    E_eq_0 = "E_eq_0"        # Never engaged
    E_lt_40 = "E_lt_40"      # Low engagement (1-39)
    E_lt_70 = "E_lt_70"      # Medium engagement (40-69)
    E_gte_70 = "E_gte_70"    # High engagement (70+)


SEGMENT_LABELS: dict[str, str] = {
    "E_eq_0": "Never Engaged (E=0)",
    "E_lt_40": "Low Engagement (E<40)",
    "E_lt_70": "Medium Engagement (E<70)",
    "E_gte_70": "High Engagement (E>=70)",
}

SEGMENT_DESCRIPTIONS: dict[str, str] = {
    "E_eq_0": (
        "Users who downloaded the app but never started a lesson. "
        "They need a compelling reason to begin — spark curiosity and purpose."
    ),
    "E_lt_40": (
        "Users with low engagement — they've tried a few lessons but haven't built a habit. "
        "They need empowerment, quick wins, and surprise to keep exploring."
    ),
    "E_lt_70": (
        "Users with medium engagement — they're building a habit and making progress. "
        "They need accomplishment signals, ownership reinforcement, and social proof."
    ),
    "E_gte_70": (
        "Highly engaged power users — consistent, invested, building streaks. "
        "They need accomplishment celebration, ownership protection, and loss avoidance nudges."
    ),
}


class SegmentThemeConfig(BaseModel):
    """Theme assignment for a segment — top 3 themes ordered by CTR priority."""
    segment: EngagementSegment
    themes: list[NotificationTheme]


class QuestContext(BaseModel):
    """Quest-level context extracted from journey data for notification generation."""
    quest_id: str
    quest_title: str
    quest_number: int
    chapter_name: str
    chapter_number: int
    total_chapters: int
    narrative_moment: str = ""
    emotional_context: str = ""
    engagement_hooks: list[str] = []
    character_name: str = ""
    key_vocabulary: list[str] = []


class BulkNotificationRow(BaseModel):
    """Single row in the generated notification CSV."""
    journey_id: str
    segment: str
    quest_id: str
    quest_title: str
    theme: str
    template_number: int
    title: str
    body: str
    cta: str
    image: str = ""


class BulkGenerationRequest(BaseModel):
    """Request payload for bulk notification generation."""
    journey_id: str
    segments: list[EngagementSegment]
    theme_config: dict[str, list[str]]  # segment -> list of theme values


class BulkGenerationResult(BaseModel):
    """Result of bulk notification generation."""
    journey_id: str
    total_rows: int
    segments_processed: int
    quests_processed: int
    rows: list[BulkNotificationRow]


# ── Legacy compatibility aliases ──
# These keep existing imports working during the transition

class NotificationStrategy(BaseModel):
    user_state: str
    applicable_themes: list[NotificationTheme]
    priority: str
    max_daily_for_state: int
    suppress_if_active: bool = False


class SegmentedPrompt(BaseModel):
    user_state: str
    user_profile: dict
    chapter_analysis: dict
    journey_summary: str
    selected_theme: NotificationTheme
    slot: int
    constraints: dict


class GeneratedNotification(BaseModel):
    title: str
    body: str
    cta: str
    theme: NotificationTheme
    generation_method: str
    prompt_hash: str
