"""Celery tasks for temporal scans, CleverTap sync, and daily analytics snapshots."""

import asyncio

import structlog

from workers.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(name="workers.temporal_worker.run_dormancy_scan", queue="default")
def run_dormancy_scan() -> dict:
    """Celery task: trigger an async dormancy scan across all users."""
    return asyncio.run(_run_dormancy())


@celery_app.task(name="workers.temporal_worker.run_chapter_transition_scan", queue="default")
def run_chapter_transition_scan() -> dict:
    """Celery task: trigger an async chapter-transition scan."""
    return asyncio.run(_run_chapter_transitions())


async def _run_dormancy() -> dict:
    from app.config.manager import ConfigManager
    from app.models.base import AsyncSessionLocal
    from app.state_engine.temporal import scan_dormancy

    async with AsyncSessionLocal() as db_session:
        config = ConfigManager(db_session)
        result = await scan_dormancy(db_session, config)
        await db_session.commit()

    logger.info("Dormancy scan task complete", result=result)
    return result


async def _run_chapter_transitions() -> dict:
    from app.config.manager import ConfigManager
    from app.models.base import AsyncSessionLocal
    from app.state_engine.temporal import scan_chapter_transitions

    async with AsyncSessionLocal() as db_session:
        config = ConfigManager(db_session)
        result = await scan_chapter_transitions(db_session, config)
        await db_session.commit()

    logger.info("Chapter transition scan task complete", result=result)
    return result


@celery_app.task(
    name="workers.temporal_worker.sync_clevertap_events",
    queue="default",
)
def sync_clevertap_events() -> dict:
    """Celery task: poll CleverTap for recent engagement events."""
    return asyncio.run(_sync_clevertap())


@celery_app.task(
    name="workers.temporal_worker.run_daily_snapshots",
    queue="default",
)
def run_daily_snapshots() -> dict:
    """Celery task: create daily journey progress snapshots for funnel analysis."""
    return asyncio.run(_daily_snapshots())


async def _sync_clevertap() -> dict:
    import os

    from app.analytics.clevertap_sync import CleverTapSyncService
    from app.models.base import AsyncSessionLocal

    account_id = os.environ.get("CLEVERTAP_ACCOUNT_ID", "")
    passcode = os.environ.get("CLEVERTAP_PASSCODE", "")

    async with AsyncSessionLocal() as db_session:
        service = CleverTapSyncService(
            account_id, passcode, db_session,
        )
        result = await service.sync_engagement_events()
        await db_session.commit()

    logger.info("CleverTap sync task complete", result=result)
    return result


async def _daily_snapshots() -> dict:
    from app.analytics.snapshots import take_daily_snapshots
    from app.models.base import AsyncSessionLocal

    async with AsyncSessionLocal() as db_session:
        result = await take_daily_snapshots(db_session)
        await db_session.commit()

    logger.info("Daily snapshots task complete", result=result)
    return result
