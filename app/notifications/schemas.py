from enum import Enum

from pydantic import BaseModel


class NotificationTheme(str, Enum):
    click_bait = "click_bait"
    fomo = "fomo"
    motivational = "motivational"
    relationship = "relationship"
    appreciation = "appreciation"
    wotd = "wotd"
    challenge = "challenge"
    story_teaser = "story_teaser"
    milestone = "milestone"
    tip = "tip"
    streak = "streak"
    quiz = "quiz"
    recap = "recap"
    social_proof = "social_proof"
    humor = "humor"


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
