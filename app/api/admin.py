"""Admin API endpoints — ingestion trigger, config management, shadow notification review."""

import base64
import json
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, rate_limiter, verify_api_key
from app.config.manager import ConfigManager
from app.config.settings import settings
from app.models.config import AppConfig
from app.models.journey import Journey
from app.models.notification import Notification
from app.models.user import UserProfile

logger = structlog.get_logger()

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(verify_api_key), Depends(rate_limiter)],
)


@router.post("/ingest")
async def trigger_ingestion(file: UploadFile) -> dict[str, Any]:
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = await file.read()
    content_b64 = base64.b64encode(content).decode("utf-8")

    from workers.ingestion_worker import ingest_journey_task
    task = ingest_journey_task.delay(content_b64, file.filename)

    await logger.ainfo("Ingestion task queued", task_id=task.id, filename=file.filename)

    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Ingestion started",
    }


@router.get("/ingest/{journey_id}/status")
async def get_ingestion_status(
    journey_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    redis = Redis.from_url(settings.redis_url)
    try:
        cached = await redis.get(f"ingestion:{journey_id}:status")
        if cached:
            return json.loads(cached)
    finally:
        await redis.aclose()

    result = await db.execute(select(Journey).where(Journey.id == journey_id))
    journey = result.scalar_one_or_none()
    if not journey:
        raise HTTPException(status_code=404, detail="Journey not found")

    return {
        "journey_id": str(journey.id),
        "status": journey.status,
        "total_chapters": journey.total_chapters,
    }


@router.get("/config")
async def get_config(
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    config = ConfigManager(db)
    if category:
        entries = await config.get_by_category(category)
    else:
        result = await db.execute(select(AppConfig))
        entries = result.scalars().all()

    return [
        {
            "key": e.key if hasattr(e, "key") else e["key"],
            "value": e.value if hasattr(e, "value") else e["value"],
            "description": (
                e.description
                if hasattr(e, "description")
                else e.get("description", "")
            ),
            "category": (
                e.category
                if hasattr(e, "category")
                else e.get("category", "")
            ),
            "updated_at": (
                str(e.updated_at)
                if hasattr(e, "updated_at") and e.updated_at
                else ""
            ),
        }
        for e in entries
    ]


class ConfigUpdateRequest(BaseModel):
    value: Any


@router.put("/config/{key}")
async def update_config(
    key: str,
    body: ConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    config = ConfigManager(db)
    old_value = await config.get(key)
    await config.set(key, body.value, updated_by="admin")
    await db.commit()

    logger.info(
        "config_updated",
        key=key,
        old_value=old_value,
        new_value=body.value,
    )

    return {
        "key": key,
        "value": body.value,
        "updated_by": "admin",
        "status": "updated",
    }


@router.get("/notifications/shadow-review")
async def shadow_review(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    state: Optional[str] = Query(None),
    theme: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    query = (
        select(Notification)
        .where(Notification.mode == "shadow")
    )

    if state:
        query = query.where(
            Notification.state_at_generation == state,
        )
    if theme:
        query = query.where(Notification.theme == theme)

    query = (
        query.order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    notifications = result.scalars().all()

    items = []
    for n in notifications:
        profile_result = await db.execute(
            select(UserProfile).where(
                UserProfile.user_id == n.user_id,
            ),
        )
        profile = profile_result.scalar_one_or_none()

        journey_result = await db.execute(
            select(Journey).where(
                Journey.id == n.journey_id,
            ),
        )
        journey = journey_result.scalar_one_or_none()

        items.append({
            "notification_id": str(n.id),
            "user_id": n.user_id,
            "state_at_generation": n.state_at_generation,
            "theme": n.theme,
            "title": n.title,
            "body": n.body,
            "cta": n.cta,
            "generation_method": n.generation_method,
            "created_at": (
                n.created_at.isoformat()
                if n.created_at
                else None
            ),
            "learning_reason": (
                profile.learning_reason if profile else None
            ),
            "journey_name": (
                journey.name if journey else None
            ),
        })

    return items
