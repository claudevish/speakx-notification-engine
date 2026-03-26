"""Notification scheduling orchestrator.

Coordinates the full notification pipeline for both scheduled time-slot runs
and event-triggered notifications: strategy resolution, frequency capping,
prompt building, LLM generation, and database persistence.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import ConfigManager
from app.llm.provider import LLMProvider
from app.models.journey import Chapter, Journey
from app.models.notification import Notification
from app.models.user import UserJourneyState, UserProfile
from app.notifications.frequency import FrequencyCapService
from app.notifications.generator import NotificationGenerator
from app.notifications.prompt_builder import NotificationPromptBuilder, StoryContext
from app.notifications.strategy import NotificationStrategyEngine

logger = structlog.get_logger()


class NotificationScheduler:
    """Orchestrates scheduled notification generation for all eligible users.

    For each time slot, iterates over active user journey states, applies
    frequency caps and suppression rules, selects themes, generates copy via
    the LLM pipeline, and persists the resulting notifications.
    """

    def __init__(
        self,
        db_session: AsyncSession,
        config_manager: ConfigManager,
        llm_provider: LLMProvider,
    ) -> None:
        """Initialise the scheduler with its dependencies.

        Args:
            db_session: An async SQLAlchemy session for database operations.
            config_manager: Application configuration accessor.
            llm_provider: The LLM backend for generating notification copy.
        """
        self.db = db_session
        self.config = config_manager
        self.strategy_engine = NotificationStrategyEngine()
        self.prompt_builder = NotificationPromptBuilder()
        self.generator = NotificationGenerator(llm_provider, config_manager)
        self.frequency_cap = FrequencyCapService(db_session, config_manager)

    async def schedule_slot(self, slot: int) -> dict:
        """Run the notification pipeline for a given time slot.

        Queries all eligible user journey states (excluding ``completed`` and
        ``churned``), generates a notification for each, and commits the
        results to the database.

        Args:
            slot: The time-slot index (1-6) within the day.

        Returns:
            A summary dict with keys ``slot``, ``users_processed``,
            ``notifications_generated``, ``suppressed``, and ``capped``.
        """
        summary = {
            "slot": slot,
            "users_processed": 0,
            "notifications_generated": 0,
            "suppressed": 0,
            "capped": 0,
        }

        excluded = ("completed", "churned")
        result = await self.db.execute(
            select(UserJourneyState).where(
                UserJourneyState.current_state.notin_(excluded),
            )
        )
        users = result.scalars().all()
        summary["users_processed"] = len(users)

        mode = await self.config.get("enabled", True)
        notification_mode = "shadow" if mode else "live"

        for user_state in users:
            try:
                notif = await self._generate_for_user(user_state, slot, notification_mode)
                if notif == "suppressed":
                    summary["suppressed"] += 1
                elif notif == "capped":
                    summary["capped"] += 1
                elif notif is not None:
                    summary["notifications_generated"] += 1
            except Exception:
                logger.exception(
                    "Failed to generate notification",
                    user_id=user_state.user_id,
                    slot=slot,
                )

        await self.db.commit()
        logger.info("Notification slot complete", **summary)
        return summary

    async def _generate_for_user(
        self,
        user_state: UserJourneyState,
        slot: int,
        mode: str,
    ) -> Optional[str]:
        """Generate and persist a single notification for one user.

        Applies suppression and frequency cap checks, selects a theme,
        builds the prompt, generates copy, and writes the notification row.

        Args:
            user_state: The user's current journey state record.
            slot: The time-slot index (1-6).
            mode: Delivery mode -- ``"live"`` or ``"shadow"``.

        Returns:
            The string UUID of the created notification, or the literal
            strings ``"suppressed"`` / ``"capped"`` if the notification was
            skipped, or ``None`` if the journey could not be found.
        """
        strategy = self.strategy_engine.get_strategy(user_state.current_state)

        if strategy.suppress_if_active:
            if await self.frequency_cap.should_suppress(user_state.user_id, user_state.journey_id):
                return "suppressed"

        if not await self.frequency_cap.can_send(user_state.user_id, user_state.journey_id):
            return "capped"

        theme = self.strategy_engine.select_theme(strategy, slot, [])

        profile = await self._get_profile(user_state.user_id)
        chapter = await self._get_chapter(user_state.current_chapter_id)
        journey = await self._get_journey(user_state.journey_id)
        if journey is None:
            return None

        story_context = StoryContext.extract(chapter, journey)

        prompt = self.prompt_builder.build_prompt(
            user_state, profile, chapter, journey, theme, slot,
        )
        system_prompt = self.prompt_builder.build_system_prompt(theme)
        prompt_hash = self.prompt_builder.compute_prompt_hash(prompt)

        generated = await self.generator.generate(prompt, system_prompt, theme, prompt_hash, story_context)

        notification = Notification(
            user_id=user_state.user_id,
            journey_id=user_state.journey_id,
            state_at_generation=user_state.current_state,
            theme=generated.theme.value,
            title=generated.title,
            body=generated.body,
            cta=generated.cta,
            generation_method=generated.generation_method,
            llm_prompt_hash=generated.prompt_hash,
            mode=mode,
            scheduled_for=datetime.now(timezone.utc),
        )
        self.db.add(notification)
        await self.db.flush()

        return str(notification.id)

    async def _get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Fetch a user's profile by user ID.

        Args:
            user_id: The unique identifier of the user.

        Returns:
            The ``UserProfile`` instance, or ``None`` if not found.
        """
        result = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def _get_chapter(self, chapter_id: Optional[uuid.UUID]) -> Optional[Chapter]:
        """Fetch a chapter by its UUID.

        Args:
            chapter_id: The chapter's UUID, or ``None`` to short-circuit.

        Returns:
            The ``Chapter`` instance, or ``None`` if the ID is ``None`` or
            no matching record exists.
        """
        if chapter_id is None:
            return None
        result = await self.db.execute(
            select(Chapter).where(Chapter.id == chapter_id)
        )
        return result.scalar_one_or_none()

    async def _get_journey(self, journey_id: uuid.UUID) -> Optional[Journey]:
        """Fetch a journey by its UUID.

        Args:
            journey_id: The journey's UUID.

        Returns:
            The ``Journey`` instance, or ``None`` if not found.
        """
        result = await self.db.execute(
            select(Journey).where(Journey.id == journey_id)
        )
        return result.scalar_one_or_none()


async def process_event_notification(
    user_id: str,
    journey_id: uuid.UUID,
    new_state: str,
    db_session: AsyncSession,
    config_manager: ConfigManager,
    llm_provider: LLMProvider,
) -> Optional[uuid.UUID]:
    """Generate and persist a notification triggered by a state-change event.

    This standalone function is called when a user transitions to a new
    learning state. It runs the full notification pipeline (frequency cap,
    strategy, prompt, LLM generation, persistence) for a single user
    outside of the regular time-slot scheduling.

    Args:
        user_id: The unique identifier of the user.
        journey_id: The UUID of the journey the user is enrolled in.
        new_state: The user's new learning state after the transition.
        db_session: An async SQLAlchemy session for database operations.
        config_manager: Application configuration accessor.
        llm_provider: The LLM backend for generating notification copy.

    Returns:
        The UUID of the created ``Notification`` row, or ``None`` if the
        notification was skipped (frequency cap, missing journey, etc.).
    """
    frequency_cap = FrequencyCapService(db_session, config_manager)

    if not await frequency_cap.can_send(user_id, journey_id):
        return None

    strategy_engine = NotificationStrategyEngine()
    strategy = strategy_engine.get_strategy(new_state)
    theme = strategy_engine.select_theme(strategy, 6, [])

    prompt_builder = NotificationPromptBuilder()

    result = await db_session.execute(
        select(UserJourneyState).where(
            UserJourneyState.user_id == user_id,
            UserJourneyState.journey_id == journey_id,
        )
    )
    user_state = result.scalar_one_or_none()
    if user_state is None:
        return None

    profile_result = await db_session.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()

    journey_result = await db_session.execute(
        select(Journey).where(Journey.id == journey_id)
    )
    journey = journey_result.scalar_one_or_none()
    if journey is None:
        return None

    chapter = None
    if user_state.current_chapter_id:
        ch_result = await db_session.execute(
            select(Chapter).where(Chapter.id == user_state.current_chapter_id)
        )
        chapter = ch_result.scalar_one_or_none()

    story_context = StoryContext.extract(chapter, journey)

    prompt = prompt_builder.build_prompt(user_state, profile, chapter, journey, theme, 6)
    system_prompt = prompt_builder.build_system_prompt(theme)
    prompt_hash = prompt_builder.compute_prompt_hash(prompt)

    generator = NotificationGenerator(llm_provider, config_manager)
    generated = await generator.generate(prompt, system_prompt, theme, prompt_hash, story_context)

    mode_enabled = await config_manager.get("enabled", True)
    mode = "shadow" if mode_enabled else "live"

    notification = Notification(
        user_id=user_id,
        journey_id=journey_id,
        state_at_generation=new_state,
        theme=generated.theme.value,
        title=generated.title,
        body=generated.body,
        cta=generated.cta,
        generation_method=generated.generation_method,
        llm_prompt_hash=generated.prompt_hash,
        mode=mode,
        scheduled_for=datetime.now(timezone.utc),
    )
    db_session.add(notification)
    await db_session.flush()

    return notification.id
