"""Demo data seeder — creates sample users and notifications after journey ingestion.

Seeds UserJourneyState records across all 12 learning states with realistic field
values, then generates fallback-template notifications so the admin portal's
Dashboard, Segmentation, and Notifications pages are immediately populated.
"""

import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import ConfigManager
from app.ingestion.schemas import ChapterStructure, JourneyStructure
from app.llm.provider import LLMProvider, LLMProviderError
from app.llm.schemas import (
    ChapterAnalysis,
    JourneyAnalysis,
    NotificationCopy,
    NotificationPrompt,
)
from app.models.journey import Chapter, Journey
from app.models.notification import Notification
from app.models.user import UserJourneyState
from app.notifications.generator import NotificationGenerator
from app.notifications.image_generator import generate_notification_image, save_notification_image
from app.notifications.prompt_builder import NotificationPromptBuilder, StoryContext
from app.notifications.strategy import NotificationStrategyEngine

logger = structlog.get_logger()

# Distribution: (state, count, config_overrides)
STATE_DISTRIBUTION: list[tuple[str, int, dict]] = [
    ("new_unstarted", 3, {
        "activities_completed": 0,
        "avg_score_window": 0.0,
        "avg_completion_speed": 0.0,
        "retry_count_window": 0,
        "chapter_index": None,
        "days_inactive": 0,
    }),
    ("onboarding", 3, {
        "activities_completed_range": (1, 3),
        "avg_score_window_range": (60.0, 80.0),
        "avg_completion_speed_range": (1.0, 3.0),
        "retry_count_window": 0,
        "chapter_index": 0,
        "days_inactive": 0,
    }),
    ("progressing_active", 5, {
        "activities_completed_range": (20, 80),
        "avg_score_window_range": (70.0, 95.0),
        "avg_completion_speed_range": (1.5, 4.0),
        "retry_count_window": 1,
        "chapter_index_range": (1, 3),
        "days_inactive": 0,
    }),
    ("progressing_slow", 3, {
        "activities_completed_range": (10, 30),
        "avg_score_window_range": (55.0, 75.0),
        "avg_completion_speed_range": (0.5, 1.5),
        "retry_count_window": 2,
        "chapter_index_range": (1, 2),
        "days_inactive": 1,
    }),
    ("struggling", 3, {
        "activities_completed_range": (5, 20),
        "avg_score_window_range": (40.0, 55.0),
        "avg_completion_speed_range": (0.3, 1.0),
        "retry_count_window_range": (3, 8),
        "chapter_index_range": (0, 1),
        "days_inactive": 0,
    }),
    ("bored_skimming", 2, {
        "activities_completed_range": (40, 100),
        "avg_score_window_range": (85.0, 98.0),
        "avg_completion_speed_range": (5.0, 10.0),
        "retry_count_window": 0,
        "chapter_index_range": (2, 4),
        "days_inactive": 0,
    }),
    ("chapter_transition", 2, {
        "activities_completed_range": (30, 60),
        "avg_score_window_range": (70.0, 85.0),
        "avg_completion_speed_range": (2.0, 4.0),
        "retry_count_window": 0,
        "chapter_index_range": (1, 3),
        "days_inactive": 0,
    }),
    ("dormant_short", 2, {
        "activities_completed_range": (15, 50),
        "avg_score_window_range": (60.0, 80.0),
        "avg_completion_speed_range": (1.5, 3.0),
        "retry_count_window": 1,
        "chapter_index_range": (1, 3),
        "days_inactive": 3,
    }),
    ("dormant_long", 2, {
        "activities_completed_range": (20, 60),
        "avg_score_window_range": (55.0, 75.0),
        "avg_completion_speed_range": (1.0, 2.5),
        "retry_count_window": 2,
        "chapter_index_range": (1, 4),
        "days_inactive": 10,
    }),
    ("churned", 2, {
        "activities_completed_range": (10, 40),
        "avg_score_window_range": (50.0, 70.0),
        "avg_completion_speed_range": (0.8, 2.0),
        "retry_count_window": 3,
        "chapter_index_range": (0, 3),
        "days_inactive": 35,
    }),
    ("completing", 2, {
        "activities_completed_range": (180, 220),
        "avg_score_window_range": (75.0, 90.0),
        "avg_completion_speed_range": (2.0, 4.0),
        "retry_count_window": 1,
        "chapter_index": -1,
        "days_inactive": 0,
    }),
    ("completed", 1, {
        "activities_completed_range": (220, 230),
        "avg_score_window_range": (80.0, 95.0),
        "avg_completion_speed_range": (2.5, 4.5),
        "retry_count_window": 0,
        "chapter_index": -1,
        "days_inactive": 1,
    }),
]


class DemoLLMProvider(LLMProvider):
    """No-op LLM provider that forces fallback template usage.

    Every method raises ``LLMProviderError`` immediately so the notification
    generator falls back to pre-written templates without making API calls.
    """

    async def analyze_journey(
        self, journey_structure: JourneyStructure,
    ) -> JourneyAnalysis:
        raise LLMProviderError("Demo mode — LLM disabled")

    async def analyze_chapter(
        self,
        chapter_data: ChapterStructure,
        journey_context: JourneyAnalysis,
    ) -> ChapterAnalysis:
        raise LLMProviderError("Demo mode — LLM disabled")

    async def generate_notification(
        self, prompt: NotificationPrompt,
    ) -> NotificationCopy:
        raise LLMProviderError("Demo mode — LLM disabled")

    async def generate_raw(self, system_prompt: str, user_prompt: str) -> str:
        raise LLMProviderError("Demo mode — LLM disabled")


DEMO_CHAPTER_ANALYSES: list[dict] = [
    {
        "emotional_context": "Excitement and nervous energy as the learner enters a new workplace",
        "difficulty_curve": "gradual",
        "key_vocabulary": ["introduce", "colleague", "meeting", "schedule", "deadline"],
        "narrative_moment": "Raj starts his first day at the new office, nervous but excited",
        "segment_content": {"career_growth": "First impressions matter -- learn to introduce yourself confidently"},
        "engagement_hooks": [
            "Raj ko boss ke saamne introduce karna hai -- help karo!",
            "Office mein pehla din -- kya impression padega?",
            "Meeting mein English bolne ka dar? Raj ke saath seekho!",
        ],
    },
    {
        "emotional_context": "Growing confidence through daily workplace interactions",
        "difficulty_curve": "moderate",
        "key_vocabulary": ["presentation", "feedback", "collaborate", "stakeholder", "deliverable"],
        "narrative_moment": "Raj has to give his first big presentation to the team",
        "segment_content": {"career_growth": "Master workplace conversations that get you noticed"},
        "engagement_hooks": [
            "Raj ki presentation mein twist aaya -- kya hoga?",
            "Boss ne feedback diya -- positive ya negative?",
            "Team meeting mein Raj ne kuch aisa bola ki sab impressed!",
        ],
    },
    {
        "emotional_context": "Tension and high stakes as interview preparation intensifies",
        "difficulty_curve": "challenging",
        "key_vocabulary": ["negotiate", "salary", "strengths", "experience", "opportunity"],
        "narrative_moment": "Priya calls Raj about a dream job opportunity but the interview is tomorrow",
        "segment_content": {"career_growth": "Crack any interview with confident English"},
        "engagement_hooks": [
            "Dream job ka interview kal hai -- Raj ready hoga?",
            "Priya ne secret interview tip share kiya!",
            "Salary negotiation mein kya bolna hai? Raj seekh raha hai!",
        ],
    },
    {
        "emotional_context": "Warmth and connection through social English skills",
        "difficulty_curve": "moderate",
        "key_vocabulary": ["casual", "weekend", "hobby", "recommendation", "celebrate"],
        "narrative_moment": "Raj is invited to his colleague's birthday party and needs to make small talk",
        "segment_content": {"career_growth": "Build relationships that open career doors"},
        "engagement_hooks": [
            "Party mein small talk kaise karo? Raj seekh raha hai!",
            "Colleague ne Raj ko weekend plan ke baare mein pucha!",
            "Birthday party mein Raj ne ek joke sunaya -- reaction kaisa tha?",
        ],
    },
    {
        "emotional_context": "Pride and achievement as the journey reaches its climax",
        "difficulty_curve": "advanced",
        "key_vocabulary": ["leadership", "vision", "inspire", "strategy", "milestone"],
        "narrative_moment": "Raj leads his first team meeting entirely in English and earns a promotion",
        "segment_content": {"career_growth": "From learner to leader -- your transformation story"},
        "engagement_hooks": [
            "Raj ko promotion mil gayi! Kaise kiya usne?",
            "Team meeting mein Raj ne sab ko inspire kiya!",
            "Final chapter -- Raj ka transformation complete!",
        ],
    },
]


class DemoSeeder:
    """Seeds demo UserJourneyState records and generates fallback notifications.

    Designed to run after journey CSV ingestion so the admin portal shows a
    fully populated segmentation matrix and notifications page immediately.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self.db = db_session

    async def seed_and_generate(self, journey_id: uuid.UUID) -> dict:
        """Run the full seed pipeline: users then notifications.

        Args:
            journey_id: UUID of the ingested journey.

        Returns:
            Combined summary dict with user and notification counts.
        """
        user_summary = await self.seed_users(journey_id)
        notif_summary = await self.generate_notifications(journey_id)
        await self.db.commit()
        return {**user_summary, **notif_summary}

    async def seed_users(self, journey_id: uuid.UUID) -> dict:
        """Create demo UserJourneyState records across all 12 states.

        Deletes any existing demo users for re-seed support, then creates
        ~30 records with realistic field values based on the state distribution.

        Args:
            journey_id: UUID of the journey to attach users to.

        Returns:
            Summary dict with ``users_created`` and ``states_seeded`` counts.
        """
        journey = await self._get_journey(journey_id)
        if journey is None:
            return {"users_created": 0, "states_seeded": 0, "error": "Journey not found"}

        chapters = await self._get_chapters(journey_id)

        # Delete existing demo users for this journey (re-seed support)
        await self.db.execute(
            delete(UserJourneyState).where(
                UserJourneyState.journey_id == journey_id,
                UserJourneyState.user_id.like("demo_user_%"),
            )
        )
        await self.db.flush()

        user_num = 1
        users_created = 0
        now = datetime.utcnow()

        for state, count, config in STATE_DISTRIBUTION:
            for _ in range(count):
                user_id = f"demo_user_{user_num:03d}"
                user_num += 1

                chapter_id = self._resolve_chapter_id(config, chapters)
                last_activity = self._resolve_last_activity(config, now)
                activities = self._resolve_range_or_value(config, "activities_completed")
                avg_score = self._resolve_float_range(config, "avg_score_window")
                avg_speed = self._resolve_float_range(config, "avg_completion_speed")
                retries = self._resolve_range_or_value(config, "retry_count_window")

                user_state = UserJourneyState(
                    user_id=user_id,
                    journey_id=journey_id,
                    current_state=state,
                    state_entered_at=now - timedelta(days=random.randint(1, 14)),
                    last_activity_at=last_activity,
                    current_chapter_id=chapter_id,
                    activities_completed=activities,
                    avg_score_window=avg_score,
                    avg_completion_speed=avg_speed,
                    retry_count_window=retries,
                )
                self.db.add(user_state)
                users_created += 1

        await self.db.flush()

        # Populate chapters with demo LLM analysis if missing
        await self._seed_chapter_analyses(journey_id, chapters)

        logger.info("Demo users seeded", users_created=users_created, journey_id=str(journey_id))
        return {"users_created": users_created, "states_seeded": len(STATE_DISTRIBUTION)}

    async def generate_notifications(self, journey_id: uuid.UUID) -> dict:
        """Generate fallback-template notifications with preview images for all seeded demo users.

        Uses DemoLLMProvider to force the fallback path, reusing the existing
        notification pipeline (strategy -> prompt -> generator -> persist).
        Also generates 984x360 phone mockup preview PNG for each notification.

        Args:
            journey_id: UUID of the journey to generate notifications for.

        Returns:
            Summary dict with ``notifications_generated`` and ``images_generated`` counts.
        """
        # Delete existing demo notifications for re-seed support
        await self.db.execute(
            delete(Notification).where(
                Notification.journey_id == journey_id,
                Notification.user_id.like("demo_user_%"),
            )
        )
        await self.db.flush()

        result = await self.db.execute(
            select(UserJourneyState).where(
                UserJourneyState.journey_id == journey_id,
                UserJourneyState.user_id.like("demo_user_%"),
            )
        )
        users = result.scalars().all()

        if not users:
            return {"notifications_generated": 0, "images_generated": 0}

        llm_provider = DemoLLMProvider()
        config_manager = ConfigManager(self.db)
        strategy_engine = NotificationStrategyEngine()
        prompt_builder = NotificationPromptBuilder()
        generator = NotificationGenerator(llm_provider, config_manager)

        journey = await self._get_journey(journey_id)
        if journey is None:
            return {"notifications_generated": 0, "images_generated": 0}

        # Ensure output directory for notification images
        output_dir = Path(__file__).resolve().parent.parent / "static" / "generated" / "notifications"
        output_dir.mkdir(parents=True, exist_ok=True)

        notifications_created = 0
        images_created = 0

        for user_state in users:
            strategy = strategy_engine.get_strategy(user_state.current_state)
            notifications_for_user = min(2, len(strategy.applicable_themes))

            used_themes: list = []
            for i in range(notifications_for_user):
                slot = random.randint(1, 6)
                theme = strategy_engine.select_theme(strategy, slot, used_themes)
                used_themes.append(theme)

                chapter = await self._get_chapter(user_state.current_chapter_id)
                story_context = StoryContext.extract(chapter, journey)

                prompt = prompt_builder.build_prompt(
                    user_state, None, chapter, journey, theme, slot,
                )
                system_prompt = prompt_builder.build_system_prompt(theme)
                prompt_hash = prompt_builder.compute_prompt_hash(prompt)

                generated = await generator.generate(
                    prompt, system_prompt, theme, prompt_hash, story_context,
                )

                notification = Notification(
                    user_id=user_state.user_id,
                    journey_id=journey_id,
                    state_at_generation=user_state.current_state,
                    theme=generated.theme.value,
                    title=generated.title,
                    body=generated.body,
                    cta=generated.cta,
                    generation_method=generated.generation_method,
                    llm_prompt_hash=generated.prompt_hash,
                    mode="shadow",
                    scheduled_for=datetime.utcnow(),
                )
                self.db.add(notification)
                await self.db.flush()  # Flush to get notification.id

                # Generate phone mockup preview image
                try:
                    img_bytes = generate_notification_image(
                        title=generated.title,
                        body=generated.body,
                        cta=generated.cta,
                        theme=generated.theme.value,
                        state=user_state.current_state,
                    )
                    rel_path = save_notification_image(img_bytes, str(notification.id), output_dir)
                    notification.image_path = rel_path
                    images_created += 1
                except Exception:
                    logger.exception("Image generation failed for notification", notification_id=str(notification.id))

                notifications_created += 1

        await self.db.flush()
        logger.info(
            "Demo notifications generated",
            notifications_created=notifications_created,
            images_created=images_created,
            journey_id=str(journey_id),
        )
        return {"notifications_generated": notifications_created, "images_generated": images_created}

    # -- Helper methods --

    async def _seed_chapter_analyses(
        self, journey_id: uuid.UUID, chapters: list[Chapter],
    ) -> None:
        """Populate chapters with demo llm_analysis and journey with demo summary."""
        journey = await self._get_journey(journey_id)
        if journey and not journey.llm_journey_summary:
            journey.llm_journey_summary = {
                "summary": "An English learning journey following Raj's career transformation from nervous new employee to confident team leader.",
                "emotional_arc": [
                    "nervous excitement", "growing confidence",
                    "high-stakes tension", "social warmth", "pride and achievement",
                ],
                "narrative_themes": ["career growth", "confidence building", "workplace communication", "friendship"],
                "character_relationships": [
                    {"character": "Raj", "role": "protagonist learner", "appears_in": ["all chapters"]},
                    {"character": "Priya", "role": "supportive friend and mentor", "appears_in": ["Chapter 3", "Chapter 4"]},
                    {"character": "Boss", "role": "authority figure", "appears_in": ["Chapter 1", "Chapter 2", "Chapter 5"]},
                ],
                "segment_signals": {"career_growth": "Career-focused professionals wanting workplace English"},
                "difficulty_progression": "gradual increase from basic introductions to leadership communication",
            }

        for i, chapter in enumerate(chapters):
            if not chapter.llm_analysis:
                analysis_idx = i % len(DEMO_CHAPTER_ANALYSES)
                chapter.llm_analysis = DEMO_CHAPTER_ANALYSES[analysis_idx]

        await self.db.flush()

    async def _get_journey(self, journey_id: uuid.UUID) -> Optional[Journey]:
        result = await self.db.execute(
            select(Journey).where(Journey.id == journey_id)
        )
        return result.scalar_one_or_none()

    async def _get_chapters(self, journey_id: uuid.UUID) -> list[Chapter]:
        result = await self.db.execute(
            select(Chapter)
            .where(Chapter.journey_id == journey_id)
            .order_by(Chapter.chapter_number)
        )
        return list(result.scalars().all())

    async def _get_chapter(
        self, chapter_id: Optional[uuid.UUID],
    ) -> Optional[Chapter]:
        if chapter_id is None:
            return None
        result = await self.db.execute(
            select(Chapter).where(Chapter.id == chapter_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _resolve_chapter_id(
        config: dict, chapters: list[Chapter],
    ) -> Optional[uuid.UUID]:
        """Pick a chapter ID based on the state configuration."""
        if not chapters:
            return None

        idx = config.get("chapter_index")
        if idx is None:
            return None
        if idx == -1:
            return chapters[-1].id

        idx_range = config.get("chapter_index_range")
        if idx_range:
            low, high = idx_range
            high = min(high, len(chapters) - 1)
            low = min(low, high)
            idx = random.randint(low, high)
        else:
            idx = min(idx, len(chapters) - 1)

        return chapters[idx].id

    @staticmethod
    def _resolve_last_activity(config: dict, now: datetime) -> Optional[datetime]:
        """Calculate last_activity_at from days_inactive."""
        days = config.get("days_inactive", 0)
        if days == 0:
            return now - timedelta(hours=random.randint(1, 12))
        return now - timedelta(days=days, hours=random.randint(0, 12))

    @staticmethod
    def _resolve_range_or_value(config: dict, field: str) -> int:
        """Resolve an integer value from a range or fixed value in config."""
        range_key = f"{field}_range"
        if range_key in config:
            low, high = config[range_key]
            return random.randint(low, high)
        return config.get(field, 0)

    @staticmethod
    def _resolve_float_range(config: dict, field: str) -> float:
        """Resolve a float value from a range or fixed value in config."""
        range_key = f"{field}_range"
        if range_key in config:
            low, high = config[range_key]
            return round(random.uniform(low, high), 1)
        return config.get(field, 0.0)
