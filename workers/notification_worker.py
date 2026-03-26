"""Celery tasks for scheduled notification slots and event-triggered notifications."""

import asyncio

import structlog

from workers.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(name="workers.notification_worker.run_notification_slot", queue="notifications")
def run_notification_slot(slot: int) -> dict:
    """Celery task: generate and send notifications for a scheduled time slot."""
    return asyncio.run(_run_slot(slot))


@celery_app.task(name="workers.notification_worker.generate_event_notification", queue="notifications")
def generate_event_notification(user_id: str, journey_id: str, new_state: str) -> dict:
    """Celery task: generate a notification triggered by a state transition event."""
    return asyncio.run(_run_event_notification(user_id, journey_id, new_state))


async def _run_slot(slot: int) -> dict:

    from app.config.manager import ConfigManager
    from app.config.settings import settings
    from app.llm.claude_provider import ClaudeProvider
    from app.models.base import AsyncSessionLocal
    from app.notifications.scheduler import NotificationScheduler

    async with AsyncSessionLocal() as db_session:
        config = ConfigManager(db_session)
        llm = ClaudeProvider(api_key=settings.anthropic_api_key)
        scheduler = NotificationScheduler(db_session, config, llm)
        result = await scheduler.schedule_slot(slot)

    logger.info("Notification slot task complete", slot=slot, result=result)
    return result


async def _run_event_notification(user_id: str, journey_id: str, new_state: str) -> dict:
    import uuid

    from app.config.manager import ConfigManager
    from app.config.settings import settings
    from app.llm.claude_provider import ClaudeProvider
    from app.models.base import AsyncSessionLocal
    from app.notifications.scheduler import process_event_notification

    async with AsyncSessionLocal() as db_session:
        config = ConfigManager(db_session)
        llm = ClaudeProvider(api_key=settings.anthropic_api_key)
        notif_id = await process_event_notification(
            user_id, uuid.UUID(journey_id), new_state, db_session, config, llm,
        )
        await db_session.commit()

    result = {"notification_id": str(notif_id) if notif_id else None}
    logger.info("Event notification task complete", user_id=user_id, result=result)
    return result
