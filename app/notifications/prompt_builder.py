"""Prompt construction for LLM-powered notification generation.

Builds the user-context prompt and the system prompt sent to the LLM, including
state-specific descriptions, theme modifiers, and few-shot examples loaded from
a JSON template file.
"""

import hashlib
import json
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

THEME_MODIFIERS: dict[str, str] = {
    "click_bait": "Use curiosity gaps. Tease content without revealing. Make them NEED to tap.",
    "fomo": "Create urgency. What are they missing? What are others doing?",
    "motivational": "Inspire and uplift. Remind them why they started and how far they've come.",
    "relationship": "Reference the story characters. Build emotional connection.",
    "appreciation": "Thank and celebrate. Make them feel valued and accomplished.",
    "wotd": "Feature an interesting English word/phrase. Make it fun and practical.",
    "challenge": "Pose a fun challenge or question. Gamify the learning.",
    "story_teaser": "Tease the next story moment. What happens next? Build anticipation.",
    "milestone": "Celebrate a milestone. Numbers, streaks, completions.",
    "tip": "Share a practical English tip. Quick, useful, actionable.",
    "streak": "Reference their streak or consistency. Motivate continuation.",
    "quiz": "Pose a quick question. Make them curious about the answer.",
    "recap": "Recap their journey so far. Remind them of progress made.",
    "social_proof": "Others are learning too. Community and shared progress.",
    "humor": "Light humor. Make them smile. Hinglish wordplay welcome.",
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
        user_profile: UserProfile | None,
        chapter: Chapter | None,
        journey: Journey,
        theme: NotificationTheme,
        slot: int,
    ) -> NotificationPrompt:
        """Build the user-context prompt for the LLM.

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
        """Build the system-level prompt with theme instructions and examples.

        Combines base copywriting instructions, theme-specific modifiers, and
        up to three few-shot examples loaded from the templates file.

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
            base += f"Theme instruction: {modifier}\n\n"

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
