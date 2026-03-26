"""Health check endpoint — reports status of PostgreSQL, Redis, and Celery workers."""

import time
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config.settings import settings

logger = structlog.get_logger()

router = APIRouter(tags=["health"])


@router.get("/admin/health")
async def health_check(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    services: dict[str, dict[str, Any]] = {}

    # Check PostgreSQL
    pg_start = time.monotonic()
    try:
        await db.execute(text("SELECT 1"))
        pg_ms = round((time.monotonic() - pg_start) * 1000, 1)
        services["postgres"] = {
            "status": "up",
            "latency_ms": pg_ms,
        }
    except Exception as exc:
        pg_ms = round((time.monotonic() - pg_start) * 1000, 1)
        services["postgres"] = {
            "status": "down",
            "latency_ms": pg_ms,
            "error": str(exc)[:100],
        }
        logger.warning(
            "Postgres health check failed", error=str(exc),
        )

    # Check Redis
    redis_start = time.monotonic()
    try:
        from redis.asyncio import Redis

        redis_client = Redis.from_url(
            settings.redis_url, socket_timeout=3,
        )
        try:
            await redis_client.ping()
            redis_ms = round(
                (time.monotonic() - redis_start) * 1000, 1,
            )
            services["redis"] = {
                "status": "up",
                "latency_ms": redis_ms,
            }
        finally:
            await redis_client.aclose()
    except Exception as exc:
        redis_ms = round(
            (time.monotonic() - redis_start) * 1000, 1,
        )
        services["redis"] = {
            "status": "down",
            "latency_ms": redis_ms,
            "error": str(exc)[:100],
        }
        logger.warning(
            "Redis health check failed", error=str(exc),
        )

    # Check Celery workers
    try:
        from workers.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=2)
        active = inspector.active()
        worker_count = len(active) if active else 0
        services["celery_workers"] = {
            "status": "up" if worker_count > 0 else "down",
            "active_workers": worker_count,
        }
    except Exception as exc:
        services["celery_workers"] = {
            "status": "down",
            "active_workers": 0,
            "error": str(exc)[:100],
        }
        logger.warning(
            "Celery health check failed", error=str(exc),
        )

    # Determine overall status
    statuses = [s["status"] for s in services.values()]
    if all(s == "up" for s in statuses):
        overall = "healthy"
    elif services.get("postgres", {}).get("status") == "down":
        overall = "unhealthy"
    else:
        overall = "degraded"

    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.environment,
        "services": services,
    }
