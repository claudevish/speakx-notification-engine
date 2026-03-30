"""Portal JSON API routes — serves data for Alpine.js fetch calls."""

import base64
import uuid as uuid_mod
from datetime import datetime, timedelta
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.config.manager import ConfigManager
from app.models.config import AppConfig
from app.models.journey import (
    Activity,
    Chapter,
    Journey,
    Lesson,
    Quest,
)
from app.models.notification import Notification
from app.models.user import UserJourneyState
from app.notifications.schemas import (
    BulkGenerationRequest,
    EngagementSegment,
    NotificationTheme,
    QuestContext,
    SEGMENT_DESCRIPTIONS,
    SEGMENT_LABELS,
)

logger = structlog.get_logger()

portal_api_router = APIRouter(prefix="/portal/api", tags=["portal-api"])


@portal_api_router.get("/stats")
async def dashboard_stats(
    journey_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    state_query = select(
        UserJourneyState.current_state,
        func.count(UserJourneyState.id),
    ).group_by(UserJourneyState.current_state)
    if journey_id:
        state_query = state_query.where(UserJourneyState.journey_id == journey_id)

    state_result = await db.execute(state_query)
    state_counts = dict(state_result.all())

    notif_base = select(func.count(Notification.id))
    if journey_id:
        notif_base = notif_base.where(Notification.journey_id == journey_id)

    total_notifs = (await db.execute(notif_base)).scalar() or 0

    llm_q = select(func.count(Notification.id)).where(
        Notification.generation_method == "llm_generated"
    )
    if journey_id:
        llm_q = llm_q.where(Notification.journey_id == journey_id)
    llm_count = (await db.execute(llm_q)).scalar() or 0

    recent_q = select(func.count(Notification.id)).where(
        Notification.created_at >= datetime.utcnow() - timedelta(hours=24)
    )
    if journey_id:
        recent_q = recent_q.where(Notification.journey_id == journey_id)
    recent_24h = (await db.execute(recent_q)).scalar() or 0

    shadow_q = select(func.count(Notification.id)).where(Notification.mode == "shadow")
    if journey_id:
        shadow_q = shadow_q.where(Notification.journey_id == journey_id)
    shadow_count = (await db.execute(shadow_q)).scalar() or 0

    return {
        "state_counts": state_counts,
        "total_users": sum(state_counts.values()),
        "total_notifications": total_notifs,
        "llm_generated": llm_count,
        "fallback_count": total_notifs - llm_count,
        "recent_24h": recent_24h,
        "shadow_count": shadow_count,
    }


@portal_api_router.get("/recent-notifications")
async def recent_notifications(
    journey_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    query = select(Notification)
    if journey_id:
        query = query.where(Notification.journey_id == journey_id)
    query = query.order_by(Notification.created_at.desc()).limit(15)

    result = await db.execute(query)
    notifications = result.scalars().all()
    return [_serialize_notification(n) for n in notifications]


@portal_api_router.post("/upload")
async def upload_csv(file: UploadFile) -> dict[str, Any]:
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files accepted")

    content = await file.read()
    content_b64 = base64.b64encode(content).decode("utf-8")

    from workers.ingestion_worker import ingest_journey_task
    task = ingest_journey_task.delay(content_b64, file.filename)

    return {"task_id": task.id, "status": "queued", "filename": file.filename}


@portal_api_router.get("/upload/status/{task_id}")
async def upload_status(task_id: str) -> dict[str, Any]:
    from workers.celery_app import celery_app
    result = celery_app.AsyncResult(task_id)

    response: dict[str, Any] = {"task_id": task_id, "status": result.status}
    if result.ready():
        if result.successful():
            response["result"] = result.result
        else:
            response["error"] = str(result.result)
    return response


@portal_api_router.get("/journeys")
async def list_journeys(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Journey).order_by(Journey.created_at.desc())
    )
    journeys = result.scalars().all()
    items = []
    for j in journeys:
        items.append({
            "id": str(j.id),
            "name": j.name,
            "status": j.status,
            "total_chapters": j.total_chapters,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        })
    return items


@portal_api_router.get("/journey/{journey_id}/tree")
async def journey_tree(
    journey_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(Journey)
        .options(
            selectinload(Journey.chapters)
            .selectinload(Chapter.quests)
            .selectinload(Quest.activities)
            .selectinload(Activity.lessons)
            .selectinload(Lesson.tasks)
        )
        .where(Journey.id == journey_id)
    )
    j = result.scalar_one_or_none()
    if not j:
        raise HTTPException(status_code=404, detail="Journey not found")

    return {
        "id": str(j.id),
        "name": j.name,
        "status": j.status,
        "llm_summary": j.llm_journey_summary,
        "chapters": [
            {
                "id": str(ch.id),
                "name": ch.name,
                "chapter_number": ch.chapter_number,
                "theme": ch.theme,
                "llm_analysis": ch.llm_analysis,
                "quests": [
                    {
                        "id": str(q.id),
                        "name": q.name,
                        "quest_number": q.quest_number,
                        "activities": [
                            {
                                "id": str(a.id),
                                "name": a.name,
                                "activity_number": a.activity_number,
                                "activity_type": a.activity_type,
                                "lessons": [
                                    {
                                        "id": str(ls.id),
                                        "name": ls.name,
                                        "lesson_number": ls.lesson_number,
                                        "tasks": [
                                            {
                                                "id": str(t.id),
                                                "name": t.name,
                                                "task_number": t.task_number,
                                                "task_type": t.task_type,
                                            }
                                            for t in ls.tasks
                                        ],
                                    }
                                    for ls in a.lessons
                                ],
                            }
                            for a in q.activities
                        ],
                    }
                    for q in ch.quests
                ],
            }
            for ch in j.chapters
        ],
    }


@portal_api_router.get("/segmentation/matrix")
async def segmentation_matrix(
    journey_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.notifications.prompt_builder import THEME_MODIFIERS
    from app.notifications.strategy import NotificationStrategyEngine, THEME_PSYCHOLOGY

    engine = NotificationStrategyEngine()
    default_config = engine.get_default_config()

    # Build segment matrix
    segment_matrix = []
    for cfg in default_config:
        segment_matrix.append({
            "segment": cfg.segment.value,
            "label": SEGMENT_LABELS.get(cfg.segment.value, cfg.segment.value),
            "description": SEGMENT_DESCRIPTIONS.get(cfg.segment.value, ""),
            "themes": [t.value for t in cfg.themes],
        })

    return {
        "segment_matrix": segment_matrix,
        "theme_modifiers": THEME_MODIFIERS,
        "theme_psychology": THEME_PSYCHOLOGY,
    }


@portal_api_router.get("/notifications")
async def list_notifications(
    journey_id: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    theme: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    method: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    query = select(Notification)
    if journey_id:
        query = query.where(Notification.journey_id == journey_id)
    if state:
        query = query.where(Notification.state_at_generation == state)
    if theme:
        query = query.where(Notification.theme == theme)
    if mode:
        query = query.where(Notification.mode == mode)
    if method:
        query = query.where(Notification.generation_method == method)
    if search:
        query = query.where(
            Notification.title.ilike(f"%{search}%")
            | Notification.body.ilike(f"%{search}%")
        )

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = (
        query.order_by(Notification.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(query)
    notifications = result.scalars().all()

    return {
        "items": [_serialize_notification(n) for n in notifications],
        "total": total,
        "page": page,
        "pages": max(1, (total + limit - 1) // limit),
    }


@portal_api_router.get("/notifications/stats")
async def notification_stats(
    journey_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    method_q = select(Notification.generation_method, func.count(Notification.id)).group_by(
        Notification.generation_method
    )
    mode_q = select(Notification.mode, func.count(Notification.id)).group_by(Notification.mode)
    state_q = select(Notification.state_at_generation, func.count(Notification.id)).group_by(
        Notification.state_at_generation
    )
    theme_q = select(Notification.theme, func.count(Notification.id)).group_by(Notification.theme)

    if journey_id:
        method_q = method_q.where(Notification.journey_id == journey_id)
        mode_q = mode_q.where(Notification.journey_id == journey_id)
        state_q = state_q.where(Notification.journey_id == journey_id)
        theme_q = theme_q.where(Notification.journey_id == journey_id)

    by_method = dict((await db.execute(method_q)).all())
    by_mode = dict((await db.execute(mode_q)).all())
    by_state = dict((await db.execute(state_q)).all())
    by_theme = dict((await db.execute(theme_q)).all())

    return {
        "by_method": by_method,
        "by_mode": by_mode,
        "by_state": by_state,
        "by_theme": by_theme,
        "total": sum(by_method.values()),
    }


@portal_api_router.get("/config")
async def get_config(
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(AppConfig).order_by(AppConfig.category, AppConfig.key)
    )
    entries = result.scalars().all()
    return [
        {
            "key": e.key,
            "value": e.value,
            "description": e.description or "",
            "category": e.category or "",
            "updated_at": str(e.updated_at) if e.updated_at else "",
        }
        for e in entries
    ]


class ConfigUpdateBody(BaseModel):
    value: Any


@portal_api_router.put("/config/{key}")
async def update_config(
    key: str,
    body: ConfigUpdateBody,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    config = ConfigManager(db)
    await config.set(key, body.value, updated_by="portal")
    await db.commit()
    return {"key": key, "value": body.value, "status": "updated"}


@portal_api_router.post("/journey/{journey_id}/seed")
async def seed_journey(
    journey_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Manually trigger demo user seeding and notification generation."""
    from app.seeding.demo_seeder import DemoSeeder

    seeder = DemoSeeder(db)
    result = await seeder.seed_and_generate(uuid_mod.UUID(journey_id))
    await db.commit()
    return result


@portal_api_router.get("/segmentation/segments")
async def segment_config() -> dict[str, Any]:
    """Return the 4 segments with labels, descriptions, and default themes."""
    from app.notifications.strategy import NotificationStrategyEngine, THEME_PSYCHOLOGY

    engine = NotificationStrategyEngine()
    default_config = engine.get_default_config()

    segments = []
    for cfg in default_config:
        segments.append({
            "segment": cfg.segment.value,
            "label": SEGMENT_LABELS.get(cfg.segment.value, cfg.segment.value),
            "description": SEGMENT_DESCRIPTIONS.get(cfg.segment.value, ""),
            "default_themes": [t.value for t in cfg.themes],
        })

    all_themes = [
        {"value": t.value, "psychology": THEME_PSYCHOLOGY.get(t.value, "")}
        for t in NotificationTheme
    ]

    return {
        "segments": segments,
        "themes": all_themes,
    }


@portal_api_router.post("/generate-bulk")
async def generate_bulk_notifications(
    body: BulkGenerationRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate bulk notification templates for a journey.

    Process: For each segment × quest × theme → generate 8 templates.
    """
    from app.config.manager import ConfigManager
    from app.llm.claude_provider import ClaudeProvider
    from app.config.settings import settings
    from app.notifications.generator import BulkNotificationGenerator

    # Load journey with chapters and quests
    result = await db.execute(
        select(Journey)
        .options(
            selectinload(Journey.chapters)
            .selectinload(Chapter.quests)
        )
        .where(Journey.id == body.journey_id)
    )
    journey = result.scalar_one_or_none()
    if not journey:
        raise HTTPException(status_code=404, detail="Journey not found")

    # Extract quest contexts from journey hierarchy
    quest_contexts: list[QuestContext] = []
    for chapter in sorted(journey.chapters, key=lambda c: c.chapter_number or 0):
        analysis = chapter.llm_analysis or {}
        for quest in sorted(chapter.quests, key=lambda q: q.quest_number or 0):
            quest_contexts.append(QuestContext(
                quest_id=f"{journey.name[:2].upper()}_C{chapter.chapter_number}_Q{quest.quest_number}",
                quest_title=quest.name or f"Quest {quest.quest_number}",
                quest_number=quest.quest_number or 0,
                chapter_name=chapter.name or f"Chapter {chapter.chapter_number}",
                chapter_number=chapter.chapter_number or 0,
                total_chapters=journey.total_chapters or 0,
                narrative_moment=analysis.get("narrative_moment", ""),
                emotional_context=analysis.get("emotional_context", ""),
                engagement_hooks=analysis.get("engagement_hooks", []),
                character_name="",
                key_vocabulary=analysis.get("key_vocabulary", []),
            ))

    # Extract character name from journey summary
    summary = journey.llm_journey_summary or {}
    characters = summary.get("character_relationships", [])
    char_name = characters[0].get("character", "") if characters else ""
    for qctx in quest_contexts:
        qctx.character_name = char_name

    # Build segments list
    segments = [EngagementSegment(s) for s in body.segments]

    # Initialize generator
    config_manager = ConfigManager(db)
    llm = ClaudeProvider(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model,
    )
    generator = BulkNotificationGenerator(llm, config_manager)

    # Generate all templates
    gen_result = await generator.generate_bulk(
        journey_id=str(journey.id),
        segments=segments,
        theme_config=body.theme_config,
        quest_contexts=quest_contexts,
    )

    return {
        "journey_id": gen_result.journey_id,
        "journey_name": journey.name,
        "total_rows": gen_result.total_rows,
        "segments_processed": gen_result.segments_processed,
        "quests_processed": gen_result.quests_processed,
        "rows": [row.model_dump() for row in gen_result.rows],
    }


@portal_api_router.post("/generate-bulk/csv")
async def generate_bulk_csv(
    body: BulkGenerationRequest,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate bulk notifications and return as downloadable CSV."""
    # Reuse the bulk generation logic
    result = await generate_bulk_notifications(body, db)

    from app.notifications.generator import rows_to_csv
    from app.notifications.schemas import BulkNotificationRow

    rows = [BulkNotificationRow(**r) for r in result["rows"]]
    csv_content = rows_to_csv(rows)

    journey_name = result.get("journey_name", "journey")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in journey_name)

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_notifications.csv"',
        },
    )


def _serialize_notification(n: Notification) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "user_id": n.user_id,
        "journey_id": str(n.journey_id) if n.journey_id else None,
        "state": n.state_at_generation,
        "theme": n.theme,
        "title": n.title,
        "body": n.body,
        "cta": n.cta,
        "method": n.generation_method,
        "mode": n.mode,
        "delivery_status": n.delivery_status,
        "image_url": f"/static/generated/{n.image_path}" if n.image_path else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }
