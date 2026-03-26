"""Manages state transitions for user learning journeys.

Processes incoming progress and profile events, evaluates behavioral
signals via :class:`BehavioralEvaluator`, and drives the
:class:`JourneyStateMachine` to produce state changes that are persisted
back to the database.
"""

import time
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from statemachine.exceptions import TransitionNotAllowed

from app.config.manager import ConfigManager
from app.events.schemas import ProfileEvent, ProgressEvent
from app.models.user import UserJourneyState, UserProfile
from app.state_engine.evaluator import BehavioralEvaluator
from app.state_engine.machine import JourneyStateMachine

logger = structlog.get_logger()


class StateTransitionManager:
    """Orchestrates event processing and state transitions for user journeys.

    Receives raw progress/profile events, resolves (or creates) the
    corresponding persisted user state, evaluates behavioral signals, and
    applies the appropriate state-machine transition.

    Attributes:
        db: The async SQLAlchemy session used for persistence.
        config: The runtime configuration manager.
        evaluator: The behavioral signal evaluator instance.
    """

    def __init__(self, db_session: AsyncSession, config_manager: ConfigManager) -> None:
        """Initialise the manager with a database session and configuration.

        Args:
            db_session: An async SQLAlchemy session for reading/writing user
                journey state.
            config_manager: Provides runtime-configurable thresholds and
                feature flags.
        """
        self.db = db_session
        self.config = config_manager
        self.evaluator = BehavioralEvaluator(config_manager)

    async def process_event(self, event: ProgressEvent) -> Optional[str]:
        """Process a progress event and return the new state if changed.

        Loads the user's current journey state, updates activity metadata,
        evaluates behavioral signals, and applies any valid state machine
        transition.

        Args:
            event: The incoming progress event containing user activity data.

        Returns:
            The new state identifier string if a transition occurred, or
            ``None`` if the state remained unchanged.
        """
        start_time = time.monotonic()

        user_state = await self._get_or_create_state(event.user_id, event.journey_id)
        old_state = user_state.current_state

        user_state.last_activity_at = datetime.now(timezone.utc)
        if event.activity_id:
            user_state.activities_completed += 1
        if event.chapter_id:
            try:
                user_state.current_chapter_id = uuid_mod.UUID(event.chapter_id)
            except (ValueError, AttributeError):
                pass
        if event.quest_id:
            try:
                user_state.current_quest_id = uuid_mod.UUID(event.quest_id)
            except (ValueError, AttributeError):
                pass

        self._update_chapter_progress(user_state, event)

        signals = await self.evaluator.evaluate_signals(user_state, event)

        machine = JourneyStateMachine(initial_state=old_state)
        machine.set_context(event.user_id, event.journey_id)

        new_state = self._apply_transitions(machine, old_state, event, signals)

        if new_state and new_state != old_state:
            user_state.current_state = new_state
            user_state.state_entered_at = datetime.now(timezone.utc)
            await self.db.flush()

            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "User state changed",
                user_id=event.user_id,
                journey_id=event.journey_id,
                event_type=event.event_type,
                old_state=old_state,
                new_state=new_state,
                signals=signals,
                processing_time_ms=round(elapsed_ms, 2),
            )
            return new_state

        await self.db.flush()
        return None

    async def process_profile_event(self, event: ProfileEvent) -> None:
        """Upsert a user profile record from a profile-sync event.

        Creates or updates the ``UserProfile`` row with any non-``None``
        fields present on the event.

        Args:
            event: The profile event containing user demographic and
                preference data.
        """
        result = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == event.user_id)
        )
        profile = result.scalar_one_or_none()

        if profile is None:
            profile = UserProfile(user_id=event.user_id)
            self.db.add(profile)

        if event.learning_reason is not None:
            profile.learning_reason = event.learning_reason
        if event.profession is not None:
            profile.profession = event.profession
        if event.region is not None:
            profile.region = event.region
        if event.proficiency_level is not None:
            profile.proficiency_level = event.proficiency_level
        if event.language_comfort is not None:
            profile.language_comfort = event.language_comfort

        profile.synced_at = event.timestamp
        await self.db.flush()

        logger.info(
            "User profile synced",
            user_id=event.user_id,
            event_type=event.event_type,
        )

    async def _get_or_create_state(
        self, user_id: str, journey_id: str,
    ) -> UserJourneyState:
        """Retrieve an existing journey state or create a new one.

        Args:
            user_id: The unique identifier of the learner.
            journey_id: The unique identifier of the journey (as a UUID string).

        Returns:
            The persisted ``UserJourneyState`` instance.
        """
        journey_uuid = uuid_mod.UUID(journey_id)
        result = await self.db.execute(
            select(UserJourneyState).where(
                UserJourneyState.user_id == user_id,
                UserJourneyState.journey_id == journey_uuid,
            )
        )
        state = result.scalar_one_or_none()
        if state is None:
            state = UserJourneyState(
                user_id=user_id,
                journey_id=journey_uuid,
                current_state="new_unstarted",
            )
            self.db.add(state)
            await self.db.flush()
        return state

    def _apply_transitions(
        self,
        machine: JourneyStateMachine,
        current_state: str,
        event: ProgressEvent,
        signals: list[str],
    ) -> Optional[str]:
        """Determine and attempt the correct state transition.

        Evaluates the current state, event type, and behavioral signals to
        select the appropriate transition to send to the state machine.

        Args:
            machine: The state machine instance positioned at the user's
                current state.
            current_state: The string identifier of the current state.
            event: The progress event being processed.
            signals: Behavioral signal labels produced by the evaluator
                (e.g. ``"struggling"``, ``"bored"``, ``"near_completion"``).

        Returns:
            The new state identifier if a transition succeeded, or ``None``
            if no transition was applicable or allowed.
        """
        if current_state in ("dormant_short", "dormant_long", "churned"):
            return self._try_send(machine, "reactivate")

        if current_state == "new_unstarted" and event.event_type == "activity_completed":
            return self._try_send(machine, "start_journey")

        if current_state == "chapter_transition":
            if event.event_type in ("activity_completed", "app_opened"):
                return self._try_send(machine, "resume_from_transition")

        if current_state == "onboarding" and event.event_type == "activity_completed":
            onboarding_threshold = 3
            meta = getattr(event, "metadata", None) or {}
            total = meta.get("activities_completed", 0)
            if total >= onboarding_threshold:
                return self._try_send(machine, "complete_onboarding")

        if "struggling" in signals and current_state in ("progressing_active", "progressing_slow"):
            return self._try_send(machine, "start_struggling")

        if current_state == "struggling" and "struggling" not in signals:
            return self._try_send(machine, "stop_struggling")

        if "bored" in signals and current_state in ("progressing_active", "progressing_slow"):
            return self._try_send(machine, "start_skimming")

        if current_state == "bored_skimming" and "bored" not in signals:
            return self._try_send(machine, "stop_skimming")

        if "near_completion" in signals and current_state == "progressing_active":
            return self._try_send(machine, "near_completion")

        if current_state == "completing":
            meta = getattr(event, "metadata", None) or {}
            if meta.get("journey_complete", False):
                return self._try_send(machine, "finish")

        return None

    @staticmethod
    def _try_send(machine: JourneyStateMachine, event_name: str) -> Optional[str]:
        """Attempt to send a named event to the state machine.

        Catches ``TransitionNotAllowed`` so callers do not need to handle
        invalid transitions explicitly.

        Args:
            machine: The state machine to send the event to.
            event_name: The transition event name (e.g. ``"reactivate"``).

        Returns:
            The machine's new state value if the transition succeeded, or
            ``None`` if the transition was not allowed from the current state.
        """
        try:
            machine.send(event_name)
            return machine.current_state_value
        except TransitionNotAllowed:
            return None

    @staticmethod
    def _update_chapter_progress(
        user_state: UserJourneyState, event: ProgressEvent,
    ) -> None:
        """Increment chapter-level completion counters on the user state.

        Only applies when the event represents a completed activity within a
        known chapter.

        Args:
            user_state: The persisted journey state to update.
            event: The progress event; must have ``event_type`` of
                ``"activity_completed"`` and a non-empty ``chapter_id``.
        """
        if event.event_type != "activity_completed" or not event.chapter_id:
            return

        progress = user_state.chapter_progress or {}
        chapter_key = f"chapter_{event.chapter_id}"

        if chapter_key not in progress:
            progress[chapter_key] = {"completed": 0, "total": 0}

        ch_data = progress[chapter_key]
        ch_data["completed"] = ch_data.get("completed", 0) + 1

        user_state.chapter_progress = progress
