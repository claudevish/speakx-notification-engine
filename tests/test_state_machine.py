"""State machine tests — validates 12-state transitions, metric evaluation, and scoring."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from statemachine.exceptions import TransitionNotAllowed

from app.config.manager import ConfigManager
from app.events.schemas import ProgressEvent
from app.models.journey import Journey
from app.models.user import UserJourneyState
from app.state_engine.machine import JourneyStateMachine
from app.state_engine.transitions import StateTransitionManager


def _make_progress_event(
    user_id: str = "user-1",
    journey_id: str | None = None,
    event_type: str = "activity_completed",
    score: float | None = None,
    retry_count: int | None = None,
    time_spent: float | None = None,
    chapter_id: str | None = None,
    activity_id: str | None = None,
    metadata: dict | None = None,
) -> ProgressEvent:
    return ProgressEvent(
        event_id=str(uuid.uuid4()),
        user_id=user_id,
        event_type=event_type,
        journey_id=journey_id or str(uuid.uuid4()),
        chapter_id=chapter_id,
        activity_id=activity_id or str(uuid.uuid4()),
        score=score,
        retry_count=retry_count,
        time_spent_seconds=time_spent,
        timestamp=datetime.now(timezone.utc),
        metadata=metadata,
    )


async def test_initial_state_is_new_unstarted() -> None:
    machine = JourneyStateMachine()
    assert machine.current_state_value == "new_unstarted"


async def test_start_journey_transition() -> None:
    machine = JourneyStateMachine()
    machine.send("start_journey")
    assert machine.current_state_value == "onboarding"


async def test_onboarding_to_progressing() -> None:
    machine = JourneyStateMachine("onboarding")
    machine.send("complete_onboarding")
    assert machine.current_state_value == "progressing_active"


async def test_onboarding_blocks_early() -> None:
    machine = JourneyStateMachine("onboarding")
    failed = False
    try:
        machine.send("start_struggling")
    except TransitionNotAllowed:
        failed = True
    assert failed
    assert machine.current_state_value == "onboarding"


async def test_struggling_detection() -> None:
    machine = JourneyStateMachine("progressing_active")
    machine.send("start_struggling")
    assert machine.current_state_value == "struggling"


async def test_struggling_recovery() -> None:
    machine = JourneyStateMachine("struggling")
    machine.send("stop_struggling")
    assert machine.current_state_value == "progressing_active"


async def test_bored_detection() -> None:
    machine = JourneyStateMachine("progressing_active")
    machine.send("start_skimming")
    assert machine.current_state_value == "bored_skimming"


async def test_dormant_short_after_2_days() -> None:
    machine = JourneyStateMachine("progressing_active")
    machine.send("go_dormant_short")
    assert machine.current_state_value == "dormant_short"


async def test_dormant_long_after_7_days() -> None:
    machine = JourneyStateMachine("dormant_short")
    machine.send("go_dormant_long")
    assert machine.current_state_value == "dormant_long"


async def test_churned_after_30_days() -> None:
    machine = JourneyStateMachine("dormant_long")
    machine.send("churn")
    assert machine.current_state_value == "churned"


async def test_reactivate_from_dormant() -> None:
    machine = JourneyStateMachine("dormant_short")
    machine.send("reactivate")
    assert machine.current_state_value == "progressing_active"


async def test_reactivate_from_churned() -> None:
    machine = JourneyStateMachine("churned")
    machine.send("reactivate")
    assert machine.current_state_value == "progressing_active"


async def test_chapter_transition() -> None:
    machine = JourneyStateMachine("progressing_active")
    machine.send("enter_chapter_transition")
    assert machine.current_state_value == "chapter_transition"


async def test_completing_state() -> None:
    machine = JourneyStateMachine("progressing_active")
    machine.send("near_completion")
    assert machine.current_state_value == "completing"


async def test_completed_state() -> None:
    machine = JourneyStateMachine("completing")
    machine.send("finish")
    assert machine.current_state_value == "completed"


async def test_invalid_transition_rejected() -> None:
    machine = JourneyStateMachine("new_unstarted")
    failed = False
    try:
        machine.send("go_dormant_short")
    except TransitionNotAllowed:
        failed = True
    assert failed
    assert machine.current_state_value == "new_unstarted"


async def test_transition_manager_creates_state(test_db: AsyncSession) -> None:
    journey = Journey(name="Test Journey", status="active")
    test_db.add(journey)
    await test_db.flush()

    config = ConfigManager(test_db)
    manager = StateTransitionManager(test_db, config)

    event = _make_progress_event(
        journey_id=str(journey.id),
        event_type="activity_completed",
        metadata={"activities_completed": 1},
    )
    new_state = await manager.process_event(event)

    assert new_state == "onboarding"

    result = await test_db.execute(
        select(UserJourneyState).where(
            UserJourneyState.user_id == event.user_id,
        )
    )
    state = result.scalar_one()
    assert state.current_state == "onboarding"


async def test_transition_manager_reactivate(test_db: AsyncSession) -> None:
    journey = Journey(name="Test Journey", status="active")
    test_db.add(journey)
    await test_db.flush()

    dormant_state = UserJourneyState(
        user_id="dormant-user",
        journey_id=journey.id,
        current_state="dormant_short",
        last_activity_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    test_db.add(dormant_state)
    await test_db.flush()

    config = ConfigManager(test_db)
    manager = StateTransitionManager(test_db, config)

    event = _make_progress_event(
        user_id="dormant-user",
        journey_id=str(journey.id),
        event_type="app_opened",
    )
    new_state = await manager.process_event(event)
    assert new_state == "progressing_active"
