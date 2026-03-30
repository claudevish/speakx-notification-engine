"""Notification copy generation — LLM-powered with fallback templates.

Supports two modes:
1. Bulk generation: 8 templates per quest × segment × theme (new)
2. Single generation: per-user notifications with LLM + fallback (legacy)
"""

import csv
import io
import json
import random
from pathlib import Path
from typing import Any

import structlog

from app.config.manager import ConfigManager
from app.llm.provider import LLMProvider, LLMProviderError
from app.llm.schemas import NotificationCopy, NotificationPrompt
from app.notifications.prompt_builder import BulkPromptBuilder, StoryContext
from app.notifications.schemas import (
    BulkGenerationResult,
    BulkNotificationRow,
    EngagementSegment,
    GeneratedNotification,
    NotificationTheme,
    QuestContext,
)

logger = structlog.get_logger()

FALLBACK_PATH = Path(__file__).resolve().parent.parent.parent / "templates" / "fallback_notifications.json"

# ── Image keyword suggestions per theme ──
THEME_IMAGE_KEYS: dict[str, list[str]] = {
    "epic_meaning": ["hero_journey", "community_wave", "mission_badge", "sunrise_start"],
    "accomplishment": ["milestone_star", "trophy_unlock", "streak_fire", "level_up"],
    "empowerment": ["choice_fork", "power_up", "compass_explore", "customize_gear"],
    "ownership": ["vault_collection", "badge_shelf", "progress_bar", "treasure_chest"],
    "social_influence": ["social_proof", "leaderboard", "community_count", "peer_wave"],
    "scarcity": ["countdown_timer", "hourglass", "lock_expiring", "flash_deal"],
    "unpredictability": ["mystery_box", "surprise_gift", "question_mark", "hidden_door"],
    "loss_avoidance": ["streak_danger", "fading_progress", "shield_protect", "warning_alert"],
}


class BulkNotificationGenerator:
    """Generates bulk notification templates for segment × quest × theme combos.

    For each combination, generates 8 unique templates using the LLM,
    falling back to pre-written templates if the LLM fails.
    """

    def __init__(self, llm_provider: LLMProvider, config_manager: ConfigManager) -> None:
        self.llm = llm_provider
        self.config = config_manager
        self.prompt_builder = BulkPromptBuilder()
        self._fallback_templates: dict[str, list[dict]] | None = None

    async def generate_bulk(
        self,
        journey_id: str,
        segments: list[EngagementSegment],
        theme_config: dict[str, list[str]],
        quest_contexts: list[QuestContext],
    ) -> BulkGenerationResult:
        """Generate all notification templates for a journey.

        Args:
            journey_id: The journey identifier.
            segments: Which segments to generate for.
            theme_config: Mapping of segment value -> list of theme values.
            quest_contexts: List of quest contexts extracted from the journey.

        Returns:
            BulkGenerationResult with all generated rows.
        """
        all_rows: list[BulkNotificationRow] = []

        for segment in segments:
            theme_values = theme_config.get(segment.value, [])
            themes = [NotificationTheme(v) for v in theme_values[:3]]

            for quest_ctx in quest_contexts:
                for theme in themes:
                    rows = await self._generate_for_combo(
                        journey_id, segment, theme, quest_ctx,
                    )
                    all_rows.extend(rows)

        return BulkGenerationResult(
            journey_id=journey_id,
            total_rows=len(all_rows),
            segments_processed=len(segments),
            quests_processed=len(quest_contexts),
            rows=all_rows,
        )

    async def _generate_for_combo(
        self,
        journey_id: str,
        segment: EngagementSegment,
        theme: NotificationTheme,
        quest_ctx: QuestContext,
    ) -> list[BulkNotificationRow]:
        """Generate 8 templates for one segment × theme × quest combo.

        Tries LLM first, falls back to template expansion if LLM fails.
        """
        try:
            system_prompt = self.prompt_builder.build_bulk_system_prompt(
                segment, theme, quest_ctx,
            )
            user_prompt = self.prompt_builder.build_bulk_user_prompt(
                segment, theme, quest_ctx,
            )
            templates = await self._llm_generate_8(system_prompt, user_prompt)
            if templates and len(templates) >= 4:
                return self._templates_to_rows(
                    journey_id, segment, theme, quest_ctx, templates[:8],
                )
            logger.warning(
                "LLM returned insufficient templates, using fallback",
                segment=segment.value, theme=theme.value, quest=quest_ctx.quest_id,
                count=len(templates) if templates else 0,
            )
        except (LLMProviderError, Exception) as exc:
            logger.warning(
                "LLM bulk generation failed, using fallback",
                error=str(exc),
                segment=segment.value, theme=theme.value, quest=quest_ctx.quest_id,
            )

        return self._fallback_generate_8(journey_id, segment, theme, quest_ctx)

    async def _llm_generate_8(
        self, system_prompt: str, user_prompt: str,
    ) -> list[dict[str, str]]:
        """Call LLM to generate 8 notification templates.

        Returns parsed list of dicts with title/body/cta/image keys.
        """
        raw = await self.llm.generate_raw(system_prompt, user_prompt)

        # Try to extract JSON array from response
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

        templates = json.loads(text)
        if not isinstance(templates, list):
            return []

        valid: list[dict[str, str]] = []
        for t in templates:
            if isinstance(t, dict) and t.get("title") and t.get("body") and t.get("cta"):
                valid.append({
                    "title": self._truncate(str(t["title"]), 60),
                    "body": self._truncate(str(t["body"]), 120),
                    "cta": self._truncate(str(t["cta"]), 25),
                    "image": str(t.get("image", "")),
                })
        return valid

    def _fallback_generate_8(
        self,
        journey_id: str,
        segment: EngagementSegment,
        theme: NotificationTheme,
        quest_ctx: QuestContext,
    ) -> list[BulkNotificationRow]:
        """Generate 8 fallback templates using pre-written templates + interpolation."""
        templates = self._load_fallback_templates()
        story = StoryContext.from_quest_context(quest_ctx)
        placeholders = story.to_placeholders()
        placeholders["quest_title"] = quest_ctx.quest_title

        # Try segment|theme key first, then theme-only
        key = f"{segment.value}|{theme.value}"
        candidates = templates.get(key, [])
        if not candidates:
            for k, v in templates.items():
                if theme.value in k:
                    candidates = v
                    break

        if not candidates:
            candidates = [
                {"title": "Naya quest ready hai!", "body": "Aaj {quest_title} try kar — kuch naya seekhne ka chance.", "cta": "Start quest"},
            ]

        # Expand to 8 by cycling + varying
        rows: list[BulkNotificationRow] = []
        image_keys = THEME_IMAGE_KEYS.get(theme.value, ["notification"])

        for i in range(8):
            template = candidates[i % len(candidates)]
            title = self._interpolate(template["title"], placeholders)
            body = self._interpolate(template["body"], placeholders)
            cta = self._interpolate(template["cta"], placeholders)
            image = image_keys[i % len(image_keys)]

            rows.append(BulkNotificationRow(
                journey_id=journey_id,
                segment=segment.value,
                quest_id=quest_ctx.quest_id,
                quest_title=quest_ctx.quest_title,
                theme=theme.value,
                template_number=i + 1,
                title=self._truncate(title, 60),
                body=self._truncate(body, 120),
                cta=self._truncate(cta, 25),
                image=image,
            ))

        return rows

    def _templates_to_rows(
        self,
        journey_id: str,
        segment: EngagementSegment,
        theme: NotificationTheme,
        quest_ctx: QuestContext,
        templates: list[dict[str, str]],
    ) -> list[BulkNotificationRow]:
        """Convert LLM-generated templates to BulkNotificationRow objects."""
        image_keys = THEME_IMAGE_KEYS.get(theme.value, ["notification"])
        rows: list[BulkNotificationRow] = []

        for i, t in enumerate(templates):
            rows.append(BulkNotificationRow(
                journey_id=journey_id,
                segment=segment.value,
                quest_id=quest_ctx.quest_id,
                quest_title=quest_ctx.quest_title,
                theme=theme.value,
                template_number=i + 1,
                title=t["title"],
                body=t["body"],
                cta=t["cta"],
                image=t.get("image") or image_keys[i % len(image_keys)],
            ))

        return rows

    @staticmethod
    def _interpolate(text: str, placeholders: dict[str, str]) -> str:
        """Replace {placeholder} tokens in text."""
        for key, value in placeholders.items():
            text = text.replace("{" + key + "}", value)
        return text

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    def _load_fallback_templates(self) -> dict[str, list[dict]]:
        if self._fallback_templates is not None:
            return self._fallback_templates
        try:
            self._fallback_templates = json.loads(FALLBACK_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self._fallback_templates = {}
        return self._fallback_templates


def rows_to_csv(rows: list[BulkNotificationRow]) -> str:
    """Convert a list of BulkNotificationRow objects to a CSV string."""
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "journeyId", "segment", "questId", "questTitle",
            "theme", "templateNumber", "title", "body", "cta", "image",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "journeyId": row.journey_id,
            "segment": row.segment,
            "questId": row.quest_id,
            "questTitle": row.quest_title,
            "theme": row.theme,
            "templateNumber": row.template_number,
            "title": row.title,
            "body": row.body,
            "cta": row.cta,
            "image": row.image,
        })
    return output.getvalue()


# ── Legacy single-notification generator ──

class NotificationGenerator:
    """Legacy: Generates single notification copy using LLM with fallback."""

    def __init__(self, llm_provider: LLMProvider, config_manager: ConfigManager) -> None:
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
            logger.warning("LLM output validation failed, using fallback")
        except (LLMProviderError, Exception) as exc:
            logger.warning("LLM generation failed, using fallback", error=str(exc))

        return self._fallback_generate(prompt, theme, prompt_hash, story_context)

    def _fallback_generate(
        self,
        prompt: NotificationPrompt,
        theme: NotificationTheme,
        prompt_hash: str,
        story_context: "StoryContext | None" = None,
    ) -> GeneratedNotification:
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

        return GeneratedNotification(
            title=title, body=body, cta=cta,
            theme=theme, generation_method="fallback_template", prompt_hash=prompt_hash,
        )

    @staticmethod
    def _validate_copy(copy: NotificationCopy) -> bool:
        if not copy.title or not copy.body or not copy.cta:
            return False
        if len(copy.body.strip().split("\n")) > 3:
            return False
        return True

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    def _load_fallback_templates(self) -> dict[str, list[dict]]:
        if self._fallback_templates is not None:
            return self._fallback_templates
        try:
            self._fallback_templates = json.loads(FALLBACK_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self._fallback_templates = {}
        return self._fallback_templates
