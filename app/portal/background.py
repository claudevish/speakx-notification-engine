"""In-process background task runner for environments without Celery workers (e.g. Railway).

Provides asyncio-based task execution with an in-memory status tracker,
replacing the Celery dependency for CSV ingestion.
"""

import asyncio
import base64
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings

logger = structlog.get_logger()

# In-memory task status store: task_id -> {status, result, error}
_task_store: dict[str, dict[str, Any]] = {}


def get_task_status(task_id: str) -> dict[str, Any]:
    """Get the current status of a background task."""
    entry = _task_store.get(task_id)
    if not entry:
        return {"task_id": task_id, "status": "UNKNOWN"}
    return {"task_id": task_id, **entry}


def launch_ingestion_task(file_content: bytes, filename: str) -> str:
    """Launch an ingestion task in the background, return the task ID."""
    task_id = str(uuid.uuid4())
    _task_store[task_id] = {"status": "PENDING"}

    content_b64 = base64.b64encode(file_content).decode("utf-8")
    asyncio.get_event_loop().create_task(
        _run_ingestion_bg(task_id, content_b64, filename),
    )
    return task_id


async def _run_ingestion_bg(task_id: str, file_content_b64: str, filename: str) -> None:
    """Run the full ingestion pipeline as a background coroutine."""
    _task_store[task_id] = {"status": "STARTED"}

    try:
        file_content = base64.b64decode(file_content_b64)

        engine = create_async_engine(settings.database_url, echo=False)
        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False,
        )

        try:
            async with session_factory() as db_session:
                from app.llm.claude_provider import ClaudeProvider

                llm_provider = ClaudeProvider(api_key=settings.anthropic_api_key)

                from app.ingestion.service import IngestionService

                service = IngestionService(db_session=db_session, llm_provider=llm_provider)
                status = await service.ingest_journey(file_content, filename)
                status_dict = status.model_dump(mode="json")

                # Auto-seed demo users
                if status.journey_id:
                    try:
                        from app.seeding.demo_seeder import DemoSeeder

                        journey_uuid = (
                            uuid.UUID(str(status.journey_id))
                            if isinstance(status.journey_id, str)
                            else status.journey_id
                        )
                        seeder = DemoSeeder(db_session)
                        seed_result = await seeder.seed_and_generate(journey_uuid)
                        status_dict["seeding"] = seed_result
                        logger.info("Demo seeding complete", **seed_result)
                    except Exception:
                        logger.exception("Demo seeding failed (non-fatal)")

                _task_store[task_id] = {"status": "SUCCESS", "result": status_dict}
        finally:
            await engine.dispose()

    except Exception as exc:
        logger.exception("Background ingestion failed", task_id=task_id)
        _task_store[task_id] = {"status": "FAILURE", "error": str(exc)}
