"""Celery tasks for scheduled notification slots, event-triggered, and pending delivery."""

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


@celery_app.task(name="workers.notification_worker.process_pending_notifications", queue="notifications")
def process_pending_notifications() -> dict:
    """Celery task: process pending live notifications whose send time has passed.

    Runs every minute via beat schedule.  Picks up notifications with
    mode='live', delivery_status='pending', and scheduled_for <= now.
    Checks DND, sends via CleverTap, and updates delivery status.
    """
    return asyncio.run(_process_pending())


@celery_app.task(name="workers.notification_worker.handle_payment_trigger", queue="notifications")
def handle_payment_trigger(user_id: str, journey_id: str, payment_time_iso: str) -> dict:
    """Celery task: schedule Day 0 notifications for a payment event.

    Calculates the Day 0 schedule, generates LLM notification content for each
    slot, and stores them with scheduled_for times.  Slot 1 is sent immediately.
    """
    return asyncio.run(_handle_payment(user_id, journey_id, payment_time_iso))


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


async def _process_pending() -> dict:
    """Process up to 10 pending live notifications whose send time has passed."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.config.settings import settings
    from app.models.base import AsyncSessionLocal
    from app.models.notification import Notification
    from app.notifications.delivery import CleverTapDeliveryService
    from app.notifications.dnd import is_dnd_active

    sent_count = 0
    failed_count = 0
    skipped_dnd_count = 0

    async with AsyncSessionLocal() as db_session:
        now = datetime.now(timezone.utc)
        query = (
            select(Notification)
            .where(
                Notification.mode == "live",
                Notification.delivery_status == "pending",
                Notification.scheduled_for <= now,
            )
            .order_by(Notification.scheduled_for.asc())
            .limit(10)
        )
        result = await db_session.execute(query)
        pending = list(result.scalars().all())

        if not pending:
            return {"processed": 0, "sent": 0, "failed": 0, "skipped_dnd": 0}

        delivery = CleverTapDeliveryService(
            account_id=settings.clevertap_account_id,
            passcode=settings.clevertap_passcode,
            region=settings.clevertap_region,
            base_url=settings.base_url,
        )

        try:
            for notification in pending:
                if notification.scheduled_for and is_dnd_active(
                    notification.scheduled_for,
                ):
                    notification.delivery_status = "skipped_dnd"
                    skipped_dnd_count += 1
                    logger.info(
                        "Notification skipped (DND active)",
                        notification_id=str(notification.id),
                    )
                    continue

                image_url = None
                if notification.image_path:
                    image_url = f"{settings.base_url}/static/generated/{notification.image_path}"

                response = await delivery.send(
                    notification=notification,
                    user_id=notification.user_id,
                    image_url=image_url,
                    notification_name=notification.theme,
                )

                if notification.delivery_status == "sent":
                    sent_count += 1
                else:
                    failed_count += 1

            await db_session.commit()
        finally:
            await delivery.close()

    total = sent_count + failed_count + skipped_dnd_count
    logger.info(
        "Pending notifications processed",
        total=total,
        sent=sent_count,
        failed=failed_count,
        skipped_dnd=skipped_dnd_count,
    )
    return {
        "processed": total,
        "sent": sent_count,
        "failed": failed_count,
        "skipped_dnd": skipped_dnd_count,
    }


async def _handle_payment(
    user_id: str, journey_id: str, payment_time_iso: str,
) -> dict:
    """Schedule Day 0 notifications for a user who just paid."""
    import uuid as uuid_mod
    from datetime import datetime

    from app.config.manager import ConfigManager
    from app.config.settings import settings
    from app.llm.claude_provider import ClaudeProvider
    from app.models.base import AsyncSessionLocal
    from app.models.notification import Notification
    from app.notifications.day0_scheduler import calculate_day0_schedule
    from app.notifications.scheduler import NotificationScheduler

    payment_time = datetime.fromisoformat(payment_time_iso)
    schedule = calculate_day0_schedule(payment_time)

    if not schedule:
        return {"scheduled": 0, "slots": []}

    async with AsyncSessionLocal() as db_session:
        config = ConfigManager(db_session)
        llm = ClaudeProvider(api_key=settings.anthropic_api_key)
        scheduler = NotificationScheduler(db_session, config, llm)

        slot_results = []
        for slot_info in schedule:
            try:
                notif = Notification(
                    user_id=user_id,
                    journey_id=uuid_mod.UUID(journey_id),
                    state_at_generation="new_unstarted",
                    theme=slot_info.theme.value,
                    title=f"[Day0 Slot {slot_info.slot}] {slot_info.name}",
                    body=f"Notification for {slot_info.name} — content pending LLM generation",
                    cta="Open App",
                    generation_method="day0_scheduled",
                    mode="live",
                    delivery_status="pending",
                    scheduled_for=slot_info.send_at,
                )
                db_session.add(notif)
                slot_results.append({
                    "slot": slot_info.slot,
                    "name": slot_info.name,
                    "send_at": slot_info.send_at.isoformat(),
                    "theme": slot_info.theme.value,
                })
            except Exception as exc:
                logger.error(
                    "Failed to schedule Day0 slot",
                    slot=slot_info.slot,
                    error=str(exc),
                )

        await db_session.commit()

    logger.info(
        "Day0 schedule created",
        user_id=user_id,
        total_slots=len(slot_results),
    )
    return {"scheduled": len(slot_results), "slots": slot_results}
