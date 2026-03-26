"""Prompt construction for LLM-powered notification generation.

Builds the user-context prompt and the system prompt sent to the LLM, including
state-specific descriptions, theme modifiers, story context extracted from chapter
analysis, and few-shot examples loaded from a JSON template file.
"""

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from app.llm.schemas import NotificationPrompt
from app.models.journey import Chapter, Journey
from app.models.user import UserJourneyState, UserProfile
from app.notifications.schemas import NotificationTheme

EXAMPLES_PATH = Path(__file__).resolve().parent.parent.parent / "templates" / "notification_examples.json"

STATE_DESCRIPTIONS: dict[str, str] = {
    "new_unstarted": "This is a brand new user who hasn't started yet. They need excitement and curiosity.",
    "onboarding": "This learner just started. They need gentle encouragement and quick wins.",
    "progressing_active": "This learner is actively engaged and making progress. Keep momentum going.",
    "progressing_slow": "This learner has slowed down. They need a gentle nudge without pressure.",
    "struggling": (
        "This learner is finding content difficult -- retrying tasks and scoring below average. "
        "They need encouragement, not pressure."
    ),
    "bored_skimming": "This learner is breezing through too fast. They need a challenge or curiosity hook.",
    "chapter_transition": "This learner finished a chapter but hasn't started the next. Tease what's coming.",
    "dormant_short": "This learner has been inactive for 2+ days. Remind them what they're missing.",
    "dormant_long": "This learner has been away for 7+ days. Reconnect emotionally with the story.",
    "churned": "This learner has been gone 30+ days. Use the strongest hook to bring them back.",
    "completing": "This learner is almost done! Celebrate progress and push for the finish line.",
    "completed": "This learner finished the journey. Appreciate and encourage sharing.",
}


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

THEME_MODIFIERS: dict[str, str] = {
    "epic_meaning": "Make the learner feel part of something bigger. Connect learning to a larger mission — career transformation, community impact, joining a movement of learners.",
    "accomplishment": "Celebrate progress and achievements. Highlight milestones, streaks, completions, and scores. Make them feel proud of how far they've come.",
    "empowerment": "Give the learner choices and creative control. Highlight paths, options, and strategies they can pick. Make them feel in charge of their learning.",
    "ownership": "Reference what the learner has earned — coins, badges, progress, streaks. Remind them of their accumulated assets and investments in learning.",
    "social_influence": "Leverage community, friends, and peers. Show what others are doing, invite competition, encourage sharing and group learning.",
    "scarcity": "Create urgency and time pressure. Limited-time content, expiring offers, trial countdowns, or content that's available only now.",
    "unpredictability": "Spark curiosity with surprise rewards, mystery content, random challenges, or unexpected story twists. Make them NEED to tap to find out.",
    "loss_avoidance": "Highlight what they'll lose if they don't act — streaks at risk, progress fading, falling behind peers, or missed opportunities.",
}


class NotificationPromptBuilder:
    """Builds structured prompts for the notification LLM.

    Assembles user state context, profile data, chapter analysis, and theme
    instructions into a ``NotificationPrompt`` object. Also constructs the
    system prompt with theme modifiers and few-shot examples.
    """

    def __init__(self) -> None:
        """Initialise the builder with an empty examples cache."""
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
        """Build the user-context prompt for the LLM.

        Extracts rich story context from the chapter analysis and journey
        summary, and structures it alongside user state and profile data.

        Args:
            user_state: The user's current journey state record.
            user_profile: Optional user profile with demographic/learning info.
            chapter: Optional current chapter with LLM analysis data.
            journey: The journey the user is enrolled in.
            theme: The chosen notification theme.
            slot: The time-slot index (1-6) for the notification.

        Returns:
            A fully populated ``NotificationPrompt`` ready for LLM consumption.
        """
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
        """Build the system-level prompt with theme instructions, story context, and examples.

        Combines base copywriting instructions, theme-specific modifiers, rich
        story context (chapter name, narrative moment, characters, emotional tone),
        and up to three few-shot examples loaded from the templates file.

        Args:
            theme: The notification theme to tailor the system prompt for.

        Returns:
            The complete system prompt string.
        """
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
            base += "STORY CONTEXT — use this to make the notification specific to where the learner is:\n"
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
            base += "\nIMPORTANT: Reference the specific story, characters, or chapter content above. "
            base += "Do NOT write generic notifications. Make it feel personal to THIS learner's story position.\n\n"

        examples = self._load_examples().get(theme.value, [])
        if examples:
            base += "Examples:\n"
            for ex in examples[:3]:
                base += f'- Title: "{ex["title"]}" | Body: "{ex["body"]}" | CTA: "{ex["cta"]}"\n'

        return base

    def compute_prompt_hash(self, prompt: NotificationPrompt) -> str:
        """Compute a SHA-256 hash of the serialised prompt for deduplication.

        Args:
            prompt: The notification prompt to hash.

        Returns:
            A hex-encoded SHA-256 digest string.
        """
        serialized = prompt.model_dump_json(exclude_none=True)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def _load_examples(self) -> dict[str, list[dict]]:
        """Load and cache few-shot examples from the templates JSON file.

        Returns:
            A dict mapping theme names to lists of example dicts. Returns an
            empty dict if the file is missing or contains invalid JSON.
        """
        if self._examples is not None:
            return self._examples
        try:
            self._examples = json.loads(EXAMPLES_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self._examples = {}
        return self._examples
