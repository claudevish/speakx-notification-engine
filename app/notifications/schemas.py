from enum import Enum

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
