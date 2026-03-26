"""Frequency cap tests — daily and weekly send limits, suppression logic."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import ConfigManager
from app.models.journey import Journey
from app.models.notification import Notification
from app.models.user import UserJourneyState
from app.notifications.frequency import FrequencyCapService


async def _setup_journey(db: AsyncSession) -> Journey:
    journey = Journey(name="Test Journey", status="active")
    db.add(journey)
    await db.flush()
    return journey


async def _add_notifications(
    db: AsyncSession, user_id: str, journey_id: object, count: int, status: str = "sent",
) -> None:
    for _ in range(count):
        notif = Notification(
            user_id=user_id,
            journey_id=journey_id,
            state_at_generation="progressing_active",
            theme="motivational",
            title="Test",
            body="Test body",
            cta="Open",
            generation_method="fallback_template",
            mode="shadow",
            delivery_status=status,
            created_at=datetime.now(timezone.utc),
        )
        db.add(notif)
    await db.flush()


async def test_under_cap_allows_send(test_db: AsyncSession) -> None:
    journey = await _setup_journey(test_db)
    await _add_notifications(test_db, "user-1", journey.id, 3)

    config = ConfigManager(test_db)
    service = FrequencyCapService(test_db, config)
    assert await service.can_send("user-1", journey.id) is True


async def test_at_cap_blocks_send(test_db: AsyncSession) -> None:
    journey = await _setup_journey(test_db)
    await _add_notifications(test_db, "user-1", journey.id, 6)

    config = ConfigManager(test_db)
    service = FrequencyCapService(test_db, config)
    assert await service.can_send("user-1", journey.id) is False


async def test_failed_notifications_not_counted(test_db: AsyncSession) -> None:
    journey = await _setup_journey(test_db)
    await _add_notifications(test_db, "user-1", journey.id, 4, status="sent")
    await _add_notifications(test_db, "user-1", journey.id, 2, status="failed")

    config = ConfigManager(test_db)
    service = FrequencyCapService(test_db, config)
    assert await service.can_send("user-1", journey.id) is True


async def test_suppress_active_user(test_db: AsyncSession) -> None:
    journey = await _setup_journey(test_db)
    state = UserJourneyState(
        user_id="active-user",
        journey_id=journey.id,
        current_state="progressing_active",
        last_activity_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    test_db.add(state)
    await test_db.flush()

    config = ConfigManager(test_db)
    service = FrequencyCapService(test_db, config)
    assert await service.should_suppress("active-user", journey.id) is True


async def test_allow_inactive_user(test_db: AsyncSession) -> None:
    journey = await _setup_journey(test_db)
    state = UserJourneyState(
        user_id="inactive-user",
        journey_id=journey.id,
        current_state="progressing_active",
        last_activity_at=datetime.now(timezone.utc) - timedelta(hours=3),
    )
    test_db.add(state)
    await test_db.flush()

    config = ConfigManager(test_db)
    service = FrequencyCapService(test_db, config)
    assert await service.should_suppress("inactive-user", journey.id) is False
