"""Celery task for asynchronous journey CSV ingestion via the admin API."""

import asyncio
import base64
import json
import uuid

import structlog

from workers.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(name="workers.ingestion_worker.ingest_journey_task", queue="ingestion")
def ingest_journey_task(file_content_b64: str, filename: str) -> dict:
    """Celery task: decode base64 CSV content and run the full ingestion pipeline."""
    return asyncio.run(_run_ingestion(file_content_b64, filename))


async def _run_ingestion(file_content_b64: str, filename: str) -> dict:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.config.settings import settings
    from app.ingestion.service import IngestionService
    from app.llm.claude_provider import ClaudeProvider

    file_content = base64.b64decode(file_content_b64)

    # Create a fresh engine per task to avoid event-loop conflicts
    # (each asyncio.run() creates a new loop, but module-level engines
    # bind to the loop that was active at import time).
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    try:
        async with session_factory() as db_session:
            llm_provider = ClaudeProvider(api_key=settings.anthropic_api_key)
            service = IngestionService(db_session=db_session, llm_provider=llm_provider)

            status = await service.ingest_journey(file_content, filename)
            status_dict = status.model_dump(mode="json")

            # Auto-seed demo users and generate fallback notifications
            if status.journey_id:
                try:
                    from app.seeding.demo_seeder import DemoSeeder

                    journey_uuid = (
                        uuid.UUID(status.journey_id)
                        if isinstance(status.journey_id, str)
                        else status.journey_id
                    )
                    seeder = DemoSeeder(db_session)
                    seed_result = await seeder.seed_and_generate(journey_uuid)
                    status_dict["seeding"] = seed_result
                    logger.info("Demo seeding complete", **seed_result)
                except Exception:
                    logger.exception("Demo seeding failed (non-fatal)")

            if status.journey_id:
                redis = Redis.from_url(settings.redis_url)
                try:
                    await redis.set(
                        f"ingestion:{status.journey_id}:status",
                        json.dumps(status_dict),
                        ex=3600,
                    )
                finally:
                    await redis.aclose()

            return status_dict
    finally:
        await engine.dispose()
