"""Temporal scan tests — dormancy detection and chapter transition logic."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import ConfigManager
from app.models.journey import Journey
from app.models.user import UserJourneyState
from app.state_engine.temporal import scan_chapter_transitions, scan_dormancy


async def _create_journey(db: AsyncSession) -> Journey:
    journey = Journey(name="Test Journey", status="active")
    db.add(journey)
    await db.flush()
    return journey


async def _create_user_state(
    db: AsyncSession,
    journey_id: uuid.UUID,
    user_id: str,
    state: str,
    last_activity_days_ago: int,
    chapter_progress: dict | None = None,
) -> UserJourneyState:
    user_state = UserJourneyState(
        user_id=user_id,
        journey_id=journey_id,
        current_state=state,
        last_activity_at=datetime.now(timezone.utc) - timedelta(days=last_activity_days_ago),
        chapter_progress=chapter_progress,
    )
    db.add(user_state)
    await db.flush()
    return user_state


async def test_dormancy_scan_finds_inactive_users(test_db: AsyncSession) -> None:
    journey = await _create_journey(test_db)

    await _create_user_state(test_db, journey.id, "user-1day", "progressing_active", 1)
    await _create_user_state(test_db, journey.id, "user-3days", "progressing_active", 3)
    await _create_user_state(test_db, journey.id, "user-10days", "dormant_short", 10)

    config = ConfigManager(test_db)
    result = await scan_dormancy(test_db, config)

    assert result["transitions"]["dormant_short"] == 1
    assert result["transitions"]["dormant_long"] == 1


async def test_dormancy_scan_skips_already_dormant(test_db: AsyncSession) -> None:
    journey = await _create_journey(test_db)

    await _create_user_state(test_db, journey.id, "user-dormant", "dormant_short", 3)

    config = ConfigManager(test_db)
    result = await scan_dormancy(test_db, config)

    assert result["transitions"]["dormant_short"] == 0


async def test_dormancy_scan_respects_config(test_db: AsyncSession) -> None:
    journey = await _create_journey(test_db)

    await _create_user_state(test_db, journey.id, "user-3days", "progressing_active", 3)

    config = ConfigManager(test_db)
    await config.set("short_threshold_days", 5)

    result = await scan_dormancy(test_db, config)
    assert result["transitions"]["dormant_short"] == 0


async def test_chapter_transition_scan(test_db: AsyncSession) -> None:
    journey = await _create_journey(test_db)

    completed_at = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    chapter_progress = {
        "chapter_3": {
            "completed": 10,
            "total": 10,
            "chapter_completed": True,
            "completed_at": completed_at,
        }
    }

    await _create_user_state(
        test_db, journey.id, "user-ch-done", "progressing_active", 0,
        chapter_progress=chapter_progress,
    )

    config = ConfigManager(test_db)
    result = await scan_chapter_transitions(test_db, config)
    assert result["transitions"] == 1


async def test_chapter_transition_skip_active(test_db: AsyncSession) -> None:
    journey = await _create_journey(test_db)

    completed_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    chapter_progress = {
        "chapter_3": {
            "completed": 10,
            "total": 10,
            "chapter_completed": True,
            "completed_at": completed_at,
        }
    }

    await _create_user_state(
        test_db, journey.id, "user-active", "progressing_active", 0,
        chapter_progress=chapter_progress,
    )

    config = ConfigManager(test_db)
    result = await scan_chapter_transitions(test_db, config)
    assert result["transitions"] == 0
