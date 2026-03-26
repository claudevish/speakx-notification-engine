"""Portal page routes — serves Jinja2 templates for the admin web interface."""

from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.config.settings import settings
from app.models.journey import (
    Activity,
    Chapter,
    Journey,
    Lesson,
    Quest,
    Task,
)
from app.models.notification import Notification
from app.models.user import UserJourneyState

logger = structlog.get_logger()

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

portal_router = APIRouter(prefix="/portal", tags=["portal"])


def _check_portal() -> None:
    if not settings.portal_enabled:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)


async def _get_all_journeys(db: AsyncSession) -> list:
    """Fetch all journeys ordered by creation date (newest first)."""
    result = await db.execute(
        select(Journey).order_by(Journey.created_at.desc())
    )
    return list(result.scalars().all())


@portal_router.get("/", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    journey_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    _check_portal()

    all_journeys = await _get_all_journeys(db)

    # Determine selected journey
    selected_journey = None
    if journey_id:
        for j in all_journeys:
            if str(j.id) == journey_id:
                selected_journey = j
                break
    elif all_journeys:
        selected_journey = all_journeys[0]

    # State counts — filtered by journey if selected
    state_query = select(
        UserJourneyState.current_state,
        func.count(UserJourneyState.id),
    ).group_by(UserJourneyState.current_state)
    if selected_journey:
        state_query = state_query.where(UserJourneyState.journey_id == selected_journey.id)
    state_result = await db.execute(state_query)
    state_counts: dict[str, int] = dict(state_result.all())
    total_users = sum(state_counts.values())

    # Notification counts — filtered by journey if selected
    notif_base = select(func.count(Notification.id))
    if selected_journey:
        notif_base = notif_base.where(Notification.journey_id == selected_journey.id)
    total_notifications = (await db.execute(notif_base)).scalar() or 0

    llm_q = select(func.count(Notification.id)).where(
        Notification.generation_method == "llm_generated"
    )
    if selected_journey:
        llm_q = llm_q.where(Notification.journey_id == selected_journey.id)
    llm_count = (await db.execute(llm_q)).scalar() or 0

    # Recent notifications — filtered by journey if selected
    recent_q = select(Notification)
    if selected_journey:
        recent_q = recent_q.where(Notification.journey_id == selected_journey.id)
    recent_q = recent_q.order_by(Notification.created_at.desc()).limit(15)
    recent_result = await db.execute(recent_q)
    recent_notifications = recent_result.scalars().all()

    # Hierarchy counts for selected journey
    hierarchy_counts: dict[str, int] = {}
    if selected_journey:
        for model, label in [
            (Chapter, "chapters"), (Quest, "quests"),
            (Activity, "activities"), (Lesson, "lessons"), (Task, "tasks"),
        ]:
            count_result = await db.execute(
                select(func.count(model.id)).where(model.journey_id == selected_journey.id)
            )
            hierarchy_counts[label] = count_result.scalar() or 0

    active_states = {
        "onboarding", "progressing_active", "progressing_slow",
        "struggling", "bored_skimming", "chapter_transition",
        "completing",
    }
    active_users = sum(v for k, v in state_counts.items() if k in active_states)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "page": "dashboard",
        "journey": selected_journey,
        "journeys": all_journeys,
        "selected_journey_id": str(selected_journey.id) if selected_journey else None,
        "state_counts": state_counts,
        "total_users": total_users,
        "active_users": active_users,
        "total_notifications": total_notifications,
        "llm_count": llm_count,
        "recent_notifications": recent_notifications,
        "hierarchy_counts": hierarchy_counts,
    })


@portal_router.get("/upload", response_class=HTMLResponse)
async def upload_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    _check_portal()
    journeys = await _get_all_journeys(db)
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "page": "upload",
        "journeys": journeys,
    })


@portal_router.get("/journey", response_class=HTMLResponse)
async def journey_redirect(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Redirect to the latest journey, or show upload page if none exist."""
    _check_portal()
    result = await db.execute(
        select(Journey).order_by(Journey.created_at.desc()).limit(1)
    )
    journey = result.scalar_one_or_none()
    if journey:
        return RedirectResponse(url=f"/portal/journey/{journey.id}", status_code=302)
    return RedirectResponse(url="/portal/upload", status_code=302)


@portal_router.get("/journey/{journey_id}", response_class=HTMLResponse)
async def journey_explorer_page(
    request: Request,
    journey_id: str,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    _check_portal()
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
    journey = result.scalar_one_or_none()
    if not journey:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Journey not found")

    counts: dict[str, int] = {}
    for model, label in [
        (Chapter, "chapters"), (Quest, "quests"),
        (Activity, "activities"), (Lesson, "lessons"), (Task, "tasks"),
    ]:
        count_result = await db.execute(
            select(func.count(model.id)).where(model.journey_id == journey.id)
        )
        counts[label] = count_result.scalar() or 0

    all_journeys = await _get_all_journeys(db)

    return templates.TemplateResponse("journey_explorer.html", {
        "request": request,
        "page": "journey",
        "journey": journey,
        "journeys": all_journeys,
        "selected_journey_id": str(journey.id),
        "counts": counts,
    })


@portal_router.get("/segmentation", response_class=HTMLResponse)
async def segmentation_page(
    request: Request,
    journey_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    _check_portal()
    from app.notifications.prompt_builder import STATE_DESCRIPTIONS, THEME_MODIFIERS
    from app.notifications.strategy import NotificationStrategyEngine

    engine = NotificationStrategyEngine()
    all_journeys = await _get_all_journeys(db)

    # Determine selected journey
    selected_journey = None
    if journey_id:
        for j in all_journeys:
            if str(j.id) == journey_id:
                selected_journey = j
                break
    elif all_journeys:
        selected_journey = all_journeys[0]

    state_query = select(
        UserJourneyState.current_state,
        func.count(UserJourneyState.id),
    ).group_by(UserJourneyState.current_state)
    if selected_journey:
        state_query = state_query.where(UserJourneyState.journey_id == selected_journey.id)
    state_result = await db.execute(state_query)
    state_counts = dict(state_result.all())

    notif_theme_q = select(Notification.theme, func.count(Notification.id)).group_by(Notification.theme)
    if selected_journey:
        notif_theme_q = notif_theme_q.where(Notification.journey_id == selected_journey.id)
    notif_theme_result = await db.execute(notif_theme_q)
    theme_counts = dict(notif_theme_result.all())

    matrix = []
    state_order = [
        "new_unstarted", "onboarding", "progressing_active", "progressing_slow",
        "struggling", "bored_skimming", "chapter_transition",
        "dormant_short", "dormant_long", "churned", "completing", "completed",
    ]
    for state in state_order:
        strategy = engine.get_strategy(state)
        matrix.append({
            "state": state,
            "description": STATE_DESCRIPTIONS.get(state, ""),
            "priority": strategy.priority,
            "max_daily": strategy.max_daily_for_state,
            "suppress_if_active": strategy.suppress_if_active,
            "themes": [t.value for t in strategy.applicable_themes],
            "user_count": state_counts.get(state, 0),
        })

    slot_prefs: dict[int, list[str]] = {}
    for slot_num, themes in engine.SLOT_THEME_PREFERENCES.items():
        slot_prefs[slot_num] = [t.value for t in themes]

    return templates.TemplateResponse("segmentation.html", {
        "request": request,
        "page": "segmentation",
        "journeys": all_journeys,
        "selected_journey_id": str(selected_journey.id) if selected_journey else None,
        "matrix": matrix,
        "slot_preferences": slot_prefs,
        "theme_modifiers": THEME_MODIFIERS,
        "theme_counts": theme_counts,
    })


@portal_router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    _check_portal()
    all_journeys = await _get_all_journeys(db)

    return templates.TemplateResponse("notifications.html", {
        "request": request,
        "page": "notifications",
        "journeys": all_journeys,
    })


@portal_router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request) -> HTMLResponse:
    _check_portal()
    return templates.TemplateResponse("config.html", {
        "request": request,
        "page": "config",
    })
