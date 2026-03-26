"""Notification copy generation via LLM with fallback templates.

Sends assembled prompts to the LLM provider, validates the output, and falls
back to pre-written templates when the LLM is unavailable or returns invalid
copy.
"""

import json
import random
from pathlib import Path

import structlog

from app.config.manager import ConfigManager
from app.llm.provider import LLMProvider, LLMProviderError
from app.llm.schemas import NotificationCopy, NotificationPrompt
from app.notifications.prompt_builder import StoryContext
from app.notifications.schemas import GeneratedNotification, NotificationTheme

logger = structlog.get_logger()

FALLBACK_PATH = Path(__file__).resolve().parent.parent.parent / "templates" / "fallback_notifications.json"


class NotificationGenerator:
    """Generates notification copy using an LLM with template-based fallback.

    Attempts LLM generation first, validates the output, and falls back to
    pre-written JSON templates when the LLM fails or produces invalid copy.
    """

    def __init__(self, llm_provider: LLMProvider, config_manager: ConfigManager) -> None:
        """Initialise the generator with an LLM provider and config manager.

        Args:
            llm_provider: The LLM backend used to generate notification text.
            config_manager: Application configuration accessor.
        """
        self.llm = llm_provider
        self.config = config_manager
        self._fallback_templates: dict[str, list[dict]] | None = None

    async def generate(
        self,
        prompt: NotificationPrompt,
        system_prompt: str,
        theme: NotificationTheme,
        prompt_hash: str,
        story_context: "StoryContext | None" = None,
    ) -> GeneratedNotification:
        """Generate notification copy, falling back to templates on failure.

        Calls the LLM provider, validates the returned copy, and wraps the
        result in a ``GeneratedNotification``. If the LLM call fails or
        validation rejects the output, a fallback template is used instead.

        Args:
            prompt: The assembled user-context prompt.
            system_prompt: The system-level instructions for the LLM.
            theme: The notification theme being generated.
            prompt_hash: SHA-256 hash of the prompt for deduplication.
            story_context: Optional rich story context for fallback interpolation.

        Returns:
            A ``GeneratedNotification`` with the final title, body, and CTA.
        """
        try:
            copy = await self.llm.generate_notification(prompt)
            if self._validate_copy(copy):
                return GeneratedNotification(
                    title=self._truncate(copy.title, 100),
                    body=self._truncate(copy.body, 300),
                    cta=self._truncate(copy.cta, 50),
                    theme=theme,
                    generation_method="llm_generated",
                    prompt_hash=prompt_hash,
                )
            logger.warning(
                "LLM output validation failed, using fallback",
            )
        except (LLMProviderError, Exception) as exc:
            logger.warning(
                "LLM generation failed, using fallback",
                error=str(exc),
            )

        return self._fallback_generate(prompt, theme, prompt_hash, story_context)

    def _fallback_generate(
        self,
        prompt: NotificationPrompt,
        theme: NotificationTheme,
        prompt_hash: str,
        story_context: "StoryContext | None" = None,
    ) -> GeneratedNotification:
        """Generate a story-aware notification from pre-written fallback templates.

        Looks up templates by a composite key of user state and theme, then
        interpolates rich story placeholders (chapter name, characters,
        engagement hooks, narrative moments, chapter progress).

        Args:
            prompt: The assembled user-context prompt (used for template key).
            theme: The notification theme to match templates against.
            prompt_hash: SHA-256 hash of the prompt for traceability.
            story_context: Optional rich story context for placeholder interpolation.

        Returns:
            A ``GeneratedNotification`` with ``generation_method`` set to
            ``"fallback_template"``.
        """
        templates = self._load_fallback_templates()
        key = f"{prompt.user_state.split('.')[0].split(' ')[0].lower()}|{theme.value}"

        candidates = templates.get(key, [])
        if not candidates:
            for k, v in templates.items():
                if theme.value in k:
                    candidates = v
                    break

        if not candidates:
            candidates = [{"title": "Keep learning!", "body": "Aaj bhi kuch naya seekho.", "cta": "Open app"}]

        template = random.choice(candidates)

        placeholders: dict[str, str] = {}
        if story_context:
            placeholders = story_context.to_placeholders()
        else:
            story = ""
            if prompt.chapter_analysis:
                story = str(prompt.chapter_analysis.get("narrative_moment", ""))[:50]
            placeholders = {
                "story_placeholder": story or "aapki story continue ho rahi hai",
                "chapter_name": str(prompt.chapter_analysis.get("_chapter_name", "your current chapter")) if prompt.chapter_analysis else "your current chapter",
                "chapter_number": str(prompt.chapter_analysis.get("_chapter_number", "1")) if prompt.chapter_analysis else "1",
                "total_chapters": str(prompt.chapter_analysis.get("_total_chapters", "?")) if prompt.chapter_analysis else "?",
                "chapter_progress": "your learning journey",
                "narrative_moment": story or "aapki story continue ho rahi hai",
                "emotional_context": "an exciting moment",
                "engagement_hook": "something interesting awaits",
                "character_name": "your guide",
            }

        title = template["title"]
        body = template["body"]
        cta = template["cta"]

        for placeholder_key, value in placeholders.items():
            token = "{" + placeholder_key + "}"
            title = title.replace(token, value)
            body = body.replace(token, value)
            cta = cta.replace(token, value)

        logger.info("Fallback template used", theme=theme.value, key=key)

        return GeneratedNotification(
            title=title,
            body=body,
            cta=cta,
            theme=theme,
            generation_method="fallback_template",
            prompt_hash=prompt_hash,
        )

    @staticmethod
    def _validate_copy(copy: NotificationCopy) -> bool:
        """Validate that LLM-generated copy meets quality constraints.

        Checks that title, body, and CTA are non-empty and that the body
        does not exceed three lines.

        Args:
            copy: The raw notification copy returned by the LLM.

        Returns:
            ``True`` if the copy passes all validation checks.
        """
        if not copy.title or not copy.body or not copy.cta:
            return False
        if len(copy.body.strip().split("\n")) > 3:
            return False
        return True

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        """Truncate text to a maximum length, appending ellipsis if needed.

        Args:
            text: The input string to truncate.
            max_len: Maximum allowed character count.

        Returns:
            The original text if within the limit, otherwise the first
            ``max_len - 3`` characters followed by ``"..."``.
        """
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    def _load_fallback_templates(self) -> dict[str, list[dict]]:
        """Load and cache fallback notification templates from JSON.

        Returns:
            A dict mapping composite keys (``"state|theme"``) to lists of
            template dicts. Returns an empty dict if the file is missing or
            contains invalid JSON.
        """
        if self._fallback_templates is not None:
            return self._fallback_templates
        try:
            self._fallback_templates = json.loads(FALLBACK_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self._fallback_templates = {}
        return self._fallback_templates
