"""Prompt construction for bulk notification template generation.

Builds quest-aware prompts for the LLM using the NotifCraft agent system prompt.
Each prompt generates 8 notification templates for a specific quest × segment × theme
combination.
"""

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from app.llm.schemas import NotificationPrompt
from app.models.journey import Chapter, Journey
from app.models.user import UserJourneyState, UserProfile
from app.notifications.schemas import (
    EngagementSegment,
    NotificationTheme,
    QuestContext,
    SEGMENT_DESCRIPTIONS,
    SEGMENT_LABELS,
)

EXAMPLES_PATH = Path(__file__).resolve().parent.parent.parent / "templates" / "notification_examples.json"

# ── Legacy: kept for existing code that imports STATE_DESCRIPTIONS ──
STATE_DESCRIPTIONS: dict[str, str] = {
    "new_unstarted": "This is a brand new user who hasn't started yet. They need excitement and curiosity.",
    "onboarding": "This learner just started. They need gentle encouragement and quick wins.",
    "progressing_active": "This learner is actively engaged and making progress. Keep momentum going.",
    "progressing_slow": "This learner has slowed down. They need a gentle nudge without pressure.",
    "struggling": "This learner is finding content difficult. They need encouragement, not pressure.",
    "bored_skimming": "This learner is breezing through too fast. They need a challenge or curiosity hook.",
    "chapter_transition": "This learner finished a chapter but hasn't started the next. Tease what's coming.",
    "dormant_short": "This learner has been inactive for 2+ days. Remind them what they're missing.",
    "dormant_long": "This learner has been away for 7+ days. Reconnect emotionally with the story.",
    "churned": "This learner has been gone 30+ days. Use the strongest hook to bring them back.",
    "completing": "This learner is almost done! Celebrate progress and push for the finish line.",
    "completed": "This learner finished the journey. Appreciate and encourage sharing.",
}


THEME_MODIFIERS: dict[str, str] = {
    "epic_meaning": (
        "Make the learner feel part of something bigger. Connect learning to career transformation, "
        "community impact, joining a movement. Use words: mission, movement, transform, belong, together. "
        "Tone: inspirational, grand, purposeful."
    ),
    "accomplishment": (
        "Celebrate progress and achievements. Reference specific milestones, streaks, scores, completions. "
        "Use achievement language: unlocked, earned, mastered, crushed, nailed. "
        "Tone: celebratory, proud, specific."
    ),
    "empowerment": (
        "Give the learner choices and agency. Offer forks, customization, difficulty control. "
        "Frame learning as CHOICE not obligation. Use words: choose, decide, your way, explore, unlock. "
        "Tone: empowering, respectful of autonomy."
    ),
    "ownership": (
        "Reference what the learner has accumulated — streaks, badges, vocabulary, chapters completed. "
        "Use possession language: your collection, your progress, your streak, earned, built, saved. "
        "Tone: protective, asset-focused, collector's pride."
    ),
    "social_influence": (
        "Leverage community, peers, and competition. Show what others are doing, use social proof numbers. "
        "Reference trending content, community favorites, peer counts. "
        "Tone: social, competitive, community-driven. Never shame."
    ),
    "scarcity": (
        "Create genuine urgency with time-limited content, expiring offers, exclusive access. "
        "Use countdown language: expiring, last chance, closing soon, limited spots. "
        "Tone: urgent, exclusive. NEVER fabricate fake scarcity."
    ),
    "unpredictability": (
        "Spark curiosity with surprise rewards, mystery content, story cliffhangers, open loops. "
        "Use ellipsis and questions to create information gaps. "
        "Tone: mysterious, playful. Promise must be delivered on tap."
    ),
    "loss_avoidance": (
        "Highlight what they'll lose if they don't act — streaks at risk, progress fading, "
        "falling behind. Frame action as PROTECTION not obligation. "
        "Tone: protective, warning, urgent-but-caring. Never threaten."
    ),
}

# ── 10 World-Class Notification Patterns ──
NOTIFICATION_PATTERNS: list[str] = [
    "Cliffhanger — Leave an open loop the user MUST close. End with '...' or a question.",
    "Milestone — Celebrate a specific, earned achievement with numbers.",
    "Social Proof — Show that peers are doing what you want the user to do. Use real-feeling numbers.",
    "Streak Protector — Trigger loss aversion around a built-up investment.",
    "Personal Coach — Speak like a friend, not a brand. Warm, direct, empathetic.",
    "Mystery Box — Promise a surprise reward for action. Use gift/mystery language.",
    "Countdown — Create genuine time pressure with specific deadlines.",
    "Progress Nudge — Show how close they are to a goal with percentages or counts.",
    "Emotional Mirror — Reflect their journey back to them. Growth stats, monthly recap.",
    "Character Hook — Use narrative characters as emotional anchors. Name the character.",
]


@dataclass
class StoryContext:
    """Extracted story context from chapter analysis and journey summary."""

    chapter_name: str = ""
    chapter_number: int = 0
    total_chapters: int = 0
    narrative_moment: str = ""
    emotional_context: str = ""
    engagement_hook: str = ""
    character_name: str = ""
    key_vocabulary: list[str] = field(default_factory=list)
    narrative_themes: list[str] = field(default_factory=list)
    chapter_progress: str = ""

    @classmethod
    def extract(
        cls,
        chapter: "Chapter | None",
        journey: "Journey",
    ) -> "StoryContext":
        """Build a StoryContext from chapter and journey model objects."""
        ctx = cls()
        ctx.total_chapters = journey.total_chapters or 0

        if chapter:
            ctx.chapter_name = chapter.name or ""
            ctx.chapter_number = chapter.chapter_number or 0
            if ctx.total_chapters > 0:
                ctx.chapter_progress = f"Chapter {ctx.chapter_number} of {ctx.total_chapters}"

            analysis = chapter.llm_analysis or {}
            ctx.narrative_moment = analysis.get("narrative_moment", "")
            ctx.emotional_context = analysis.get("emotional_context", "")
            hooks = analysis.get("engagement_hooks", [])
            if hooks:
                ctx.engagement_hook = random.choice(hooks)
            ctx.key_vocabulary = analysis.get("key_vocabulary", [])

        summary = journey.llm_journey_summary or {}
        ctx.narrative_themes = summary.get("narrative_themes", [])
        characters = summary.get("character_relationships", [])
        if characters:
            ctx.character_name = characters[0].get("character", "")

        return ctx

    @classmethod
    def from_quest_context(cls, qctx: QuestContext) -> "StoryContext":
        """Build a StoryContext from a QuestContext (for bulk generation)."""
        hook = random.choice(qctx.engagement_hooks) if qctx.engagement_hooks else ""
        return cls(
            chapter_name=qctx.chapter_name,
            chapter_number=qctx.chapter_number,
            total_chapters=qctx.total_chapters,
            narrative_moment=qctx.narrative_moment,
            emotional_context=qctx.emotional_context,
            engagement_hook=hook,
            character_name=qctx.character_name,
            key_vocabulary=qctx.key_vocabulary,
            chapter_progress=f"Chapter {qctx.chapter_number} of {qctx.total_chapters}",
        )

    def to_placeholders(self) -> dict[str, str]:
        """Convert to a dict of placeholder keys for fallback template interpolation."""
        return {
            "chapter_name": self.chapter_name or "your current chapter",
            "chapter_number": str(self.chapter_number) if self.chapter_number else "1",
            "total_chapters": str(self.total_chapters) if self.total_chapters else "?",
            "chapter_progress": self.chapter_progress or "your learning journey",
            "narrative_moment": self.narrative_moment[:80] if self.narrative_moment else "aapki story continue ho rahi hai",
            "emotional_context": self.emotional_context[:60] if self.emotional_context else "an exciting moment",
            "engagement_hook": self.engagement_hook[:80] if self.engagement_hook else "something interesting awaits",
            "character_name": self.character_name or "your guide",
            "story_placeholder": self.narrative_moment[:50] if self.narrative_moment else "aapki story continue ho rahi hai",
        }


class BulkPromptBuilder:
    """Builds system prompts for bulk notification template generation.

    Constructs the NotifCraft system prompt tailored to a specific
    segment × theme × quest combination, requesting 8 template variations.
    """

    def __init__(self) -> None:
        self._examples: dict[str, list[dict]] | None = None

    def build_bulk_system_prompt(
        self,
        segment: EngagementSegment,
        theme: NotificationTheme,
        quest_context: QuestContext,
    ) -> str:
        """Build the full system prompt for generating 8 templates.

        Args:
            segment: The engagement segment to target.
            theme: The Octolysis theme to use.
            quest_context: Rich quest/chapter context from the journey.

        Returns:
            Complete system prompt string for the LLM.
        """
        parts: list[str] = []

        # Identity
        parts.append(
            "You are NotifCraft — an elite push notification copywriter for SpeakX, "
            "an English learning app popular in India. You write in Hinglish — natural "
            "Hindi-English code-switching as spoken in urban India.\n"
        )

        # Segment context
        seg_label = SEGMENT_LABELS.get(segment.value, segment.value)
        seg_desc = SEGMENT_DESCRIPTIONS.get(segment.value, "")
        parts.append(f"TARGET SEGMENT: {seg_label}\n{seg_desc}\n")

        # Theme instruction
        modifier = THEME_MODIFIERS.get(theme.value, "")
        parts.append(f"OCTOLYSIS THEME — {theme.value}:\n{modifier}\n")

        # Quest/Story context
        story = StoryContext.from_quest_context(quest_context)
        parts.append("QUEST CONTEXT — make every notification specific to this quest:")
        parts.append(f"- Quest: \"{quest_context.quest_title}\" (Quest {quest_context.quest_number})")
        if story.chapter_progress:
            parts.append(f"- Chapter: \"{story.chapter_name}\" ({story.chapter_progress})")
        if story.narrative_moment:
            parts.append(f"- Story moment: {story.narrative_moment}")
        if story.emotional_context:
            parts.append(f"- Emotional tone: {story.emotional_context}")
        if story.engagement_hook:
            parts.append(f"- Engagement hook: {story.engagement_hook}")
        if story.character_name:
            parts.append(f"- Key character: {story.character_name}")
        if story.key_vocabulary:
            parts.append(f"- Key vocabulary: {', '.join(story.key_vocabulary[:5])}")
        parts.append("")

        # Copy constraints
        parts.append(
            "COPY RULES:\n"
            "- Title: Max 60 chars. Punchy. One idea. Max 1 emoji.\n"
            "- Body: Max 120 chars. 1-2 lines. Hinglish. Specific to quest/chapter/character.\n"
            "- CTA: Max 25 chars. Action verb. Describes what happens on tap.\n"
            "- Image: Suggest an image keyword (e.g. quest_start, streak_fire, mystery_box, "
            "social_proof, countdown, milestone, character_moment, progress_bar).\n"
            "- NEVER write generic copy. Reference the quest, chapter, or character by name.\n"
            "- Each of the 8 templates must use a DIFFERENT angle/pattern.\n"
        )

        # Patterns reference
        parts.append("USE THESE 8+ PATTERNS (one per template, vary them):")
        for i, pattern in enumerate(NOTIFICATION_PATTERNS[:8], 1):
            parts.append(f"  {i}. {pattern}")
        parts.append("")

        # Few-shot examples
        examples = self._load_examples().get(theme.value, [])
        if examples:
            parts.append("REFERENCE EXAMPLES (for tone, not to copy):")
            for ex in examples[:3]:
                parts.append(f'  - Title: "{ex["title"]}" | Body: "{ex["body"]}" | CTA: "{ex["cta"]}"')
            parts.append("")

        # Output format
        parts.append(
            "OUTPUT: Respond with ONLY a JSON array of exactly 8 objects. No markdown, no explanation.\n"
            "Each object: {\"title\": \"...\", \"body\": \"...\", \"cta\": \"...\", \"image\": \"...\"}\n"
        )

        return "\n".join(parts)

    def build_bulk_user_prompt(
        self,
        segment: EngagementSegment,
        theme: NotificationTheme,
        quest_context: QuestContext,
    ) -> str:
        """Build the user-message prompt for a bulk generation request."""
        return (
            f"Generate 8 unique Hinglish push notification templates for:\n"
            f"- Segment: {SEGMENT_LABELS.get(segment.value, segment.value)}\n"
            f"- Theme: {theme.value}\n"
            f"- Quest: \"{quest_context.quest_title}\"\n"
            f"- Chapter: \"{quest_context.chapter_name}\" "
            f"(Chapter {quest_context.chapter_number} of {quest_context.total_chapters})\n\n"
            f"Each template must use a different notification pattern. "
            f"Return JSON array of 8 objects."
        )

    def _load_examples(self) -> dict[str, list[dict]]:
        """Load and cache few-shot examples from the templates JSON file."""
        if self._examples is not None:
            return self._examples
        try:
            self._examples = json.loads(EXAMPLES_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self._examples = {}
        return self._examples


# ── Legacy compatibility class ──

class NotificationPromptBuilder:
    """Legacy prompt builder for per-user notification generation."""

    def __init__(self) -> None:
        self._examples: dict[str, list[dict]] | None = None

    def build_prompt(
        self,
        user_state: UserJourneyState,
        user_profile: "UserProfile | None",
        chapter: "Chapter | None",
        journey: Journey,
        theme: NotificationTheme,
        slot: int,
    ) -> NotificationPrompt:
        state_desc = STATE_DESCRIPTIONS.get(user_state.current_state, "Active learner.")
        story_ctx = StoryContext.extract(chapter, journey)
        self._last_story_context = story_ctx

        profile_data: dict = {}
        if user_profile:
            profile_data = {
                "learning_reason": user_profile.learning_reason or "general",
                "profession": user_profile.profession or "unknown",
                "region": user_profile.region or "India",
                "proficiency_level": user_profile.proficiency_level or "A2",
                "language_comfort": user_profile.language_comfort or "Hindi-primary",
            }

        chapter_data: dict = {}
        if chapter and chapter.llm_analysis:
            chapter_data = chapter.llm_analysis
            chapter_data["_chapter_name"] = chapter.name or ""
            chapter_data["_chapter_number"] = chapter.chapter_number or 0
            chapter_data["_total_chapters"] = journey.total_chapters or 0

        return NotificationPrompt(
            user_state=state_desc,
            user_profile=profile_data,
            chapter_analysis=chapter_data,
            journey_summary=journey.llm_journey_summary.get("summary", "") if journey.llm_journey_summary else "",
            notification_theme=theme.value,
            constraints={
                "max_body_lines": 2,
                "language": "hinglish",
                "cta_required": True,
                "slot": slot,
            },
        )

    def build_system_prompt(self, theme: NotificationTheme) -> str:
        base = (
            "You are a notification copywriter for SpeakX, an English learning app popular in India. "
            "Write push notifications in Hinglish -- natural Hindi-English code-switching as spoken "
            "in urban India. Max 2 lines for body. Always include a call-to-action.\n\n"
            "Respond ONLY with valid JSON: {\"title\": \"...\", \"body\": \"...\", \"cta\": \"...\"}\n\n"
        )

        modifier = THEME_MODIFIERS.get(theme.value, "")
        if modifier:
            base += f"Theme instruction (Octolysis Core Drive): {modifier}\n\n"

        story_ctx = getattr(self, "_last_story_context", None)
        if story_ctx and (story_ctx.chapter_name or story_ctx.narrative_moment):
            base += "STORY CONTEXT:\n"
            if story_ctx.chapter_progress:
                base += f"- Progress: {story_ctx.chapter_progress}\n"
            if story_ctx.chapter_name:
                base += f"- Current chapter: \"{story_ctx.chapter_name}\"\n"
            if story_ctx.narrative_moment:
                base += f"- Story moment: {story_ctx.narrative_moment}\n"
            if story_ctx.emotional_context:
                base += f"- Emotional tone: {story_ctx.emotional_context}\n"
            if story_ctx.engagement_hook:
                base += f"- Engagement hook: {story_ctx.engagement_hook}\n"
            if story_ctx.character_name:
                base += f"- Key character: {story_ctx.character_name}\n"
            if story_ctx.key_vocabulary:
                base += f"- Key vocabulary: {', '.join(story_ctx.key_vocabulary[:5])}\n"
            base += "\nIMPORTANT: Reference the specific story content above.\n\n"

        examples = self._load_examples().get(theme.value, [])
        if examples:
            base += "Examples:\n"
            for ex in examples[:3]:
                base += f'- Title: "{ex["title"]}" | Body: "{ex["body"]}" | CTA: "{ex["cta"]}"\n'

        return base

    def compute_prompt_hash(self, prompt: NotificationPrompt) -> str:
        serialized = prompt.model_dump_json(exclude_none=True)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def _load_examples(self) -> dict[str, list[dict]]:
        if self._examples is not None:
            return self._examples
        try:
            self._examples = json.loads(EXAMPLES_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self._examples = {}
        return self._examples
