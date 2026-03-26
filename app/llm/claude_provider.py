import asyncio
import json

import anthropic
import structlog

from app.ingestion.schemas import ChapterStructure, JourneyStructure
from app.llm.provider import LLMProvider, LLMProviderError, LLMValidationError
from app.llm.schemas import (
    ChapterAnalysis,
    JourneyAnalysis,
    NotificationCopy,
    NotificationPrompt,
)

logger = structlog.get_logger()

JOURNEY_SYSTEM_PROMPT = """You are analyzing an English learning journey for an EdTech app (SpeakX).
Extract the emotional arc, narrative themes, character relationships, segment signals, and difficulty progression.

Respond ONLY with valid JSON matching this exact schema:
{
  "summary": "string - 2-3 sentence journey overview",
  "emotional_arc": ["string per chapter - emotional beat"],
  "narrative_themes": ["string - recurring themes"],
  "character_relationships": [{"character": "string", "role": "string", "appears_in": ["chapter names"]}],
  "segment_signals": {"learning_reason_key": "relevant content description"},
  "difficulty_progression": "string - overall difficulty trend"
}"""

CHAPTER_SYSTEM_PROMPT = """You are analyzing a single chapter of an English learning journey for an EdTech app (SpeakX).
Given the journey context and chapter details, extract chapter-level insights for personalized notifications.

Respond ONLY with valid JSON matching this exact schema:
{
  "emotional_context": "string - emotional tone of this chapter",
  "difficulty_curve": "string - easy/medium/hard + trend",
  "key_vocabulary": ["string - important words/phrases"],
  "narrative_moment": "string - 1-2 sentence story moment",
  "segment_content": {"learning_reason_key": "chapter-specific hook"},
  "engagement_hooks": ["string - compelling aspects for notifications"]
}"""


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6-20250514") -> None:
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def analyze_journey(self, journey_structure: JourneyStructure) -> JourneyAnalysis:
        chapter_summaries = []
        for ch in journey_structure.chapters:
            quest_names = [q.name for q in ch.quests]
            chapter_summaries.append(
                f"Chapter {ch.chapter_number}: {ch.name}"
                f" (Theme: {ch.theme or 'N/A'})"
                f" — Quests: {', '.join(quest_names)}"
            )

        user_prompt = (
            f"Journey: {journey_structure.name}\n"
            f"Total chapters: {len(journey_structure.chapters)}\n\n"
            + "\n".join(chapter_summaries)
        )

        raw = await self._call_with_retry(JOURNEY_SYSTEM_PROMPT, user_prompt, max_tokens=2000)
        return self._parse_response(raw, JourneyAnalysis)

    async def analyze_chapter(
        self, chapter_data: ChapterStructure, journey_context: JourneyAnalysis,
    ) -> ChapterAnalysis:
        quest_details = []
        for quest in chapter_data.quests:
            activities = [
                f"{a.name} ({a.activity_type or 'general'})" for a in quest.activities
            ]
            quest_details.append(f"  Quest {quest.quest_number}: {quest.name} — Activities: {', '.join(activities)}")

        user_prompt = (
            f"Journey summary: {journey_context.summary}\n"
            f"Journey themes: {', '.join(journey_context.narrative_themes)}\n\n"
            f"Chapter {chapter_data.chapter_number}: {chapter_data.name}\n"
            f"Theme: {chapter_data.theme or 'N/A'}\n"
            f"Quests:\n" + "\n".join(quest_details)
        )

        raw = await self._call_with_retry(CHAPTER_SYSTEM_PROMPT, user_prompt, max_tokens=1500)
        return self._parse_response(raw, ChapterAnalysis)

    async def generate_notification(self, prompt: NotificationPrompt) -> NotificationCopy:
        system_prompt = (
            "You are a notification copywriter for SpeakX, an English learning app popular in India. "
            "Write push notifications in Hinglish -- natural Hindi-English code-switching as spoken "
            "in urban India. Max 2 lines for body. Always include a call-to-action.\n\n"
            "Respond ONLY with valid JSON: {\"title\": \"...\", \"body\": \"...\", \"cta\": \"...\"}\n\n"
            f"Theme: {prompt.notification_theme}\n"
        )

        user_prompt = (
            f"User state: {prompt.user_state}\n"
            f"User profile: {prompt.user_profile}\n"
            f"Chapter context: {prompt.chapter_analysis}\n"
            f"Journey summary: {prompt.journey_summary}\n"
            f"Constraints: {prompt.constraints}\n"
        )

        raw = await self._call_with_retry(system_prompt, user_prompt, max_tokens=500)
        data = self._parse_response(raw, NotificationCopy)
        return data

    async def _call_with_retry(self, system: str, user: str, max_tokens: int) -> str:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=0.3,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return response.content[0].text
            except (anthropic.APIError, anthropic.APITimeoutError) as exc:
                last_error = exc
                wait_time = 2 ** (attempt - 1)
                await logger.awarning(
                    "LLM API call failed, retrying",
                    attempt=attempt,
                    model=self.model,
                    error=str(exc),
                    wait_seconds=wait_time,
                )
                await asyncio.sleep(wait_time)

        raise LLMProviderError(f"LLM call failed after 3 attempts: {last_error}")

    @staticmethod
    def _parse_response(raw: str, schema: type) -> JourneyAnalysis | ChapterAnalysis:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMValidationError(f"LLM returned invalid JSON: {exc}") from exc

        try:
            return schema(**data)
        except Exception as exc:
            raise LLMValidationError(f"LLM response doesn't match schema {schema.__name__}: {exc}") from exc
