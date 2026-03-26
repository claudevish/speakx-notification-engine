"""Click tracking endpoints for push notification interactions.

Ported from NotifyGen's webhook tracking system. When a user taps a push
notification, the deep link (wzrk_dl) points here. We log the click event
and redirect the user to the app's lesson page.
"""

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.notification import NotificationEvent

logger = structlog.get_logger()

tracking_router = APIRouter(prefix="/api", tags=["tracking"])

REDIRECT_URL = "https://www.speakx.in/lesson"


@tracking_router.get("/track")
async def track_click(
    type: str = Query("click"),
    identity: str = Query(""),
    slot: int = Query(0),
    name: str = Query(""),
    day: int = Query(0),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Record a notification click and redirect to the lesson page.

    Called when a user taps a push notification. The wzrk_dl deep link
    in the notification payload points to this endpoint with tracking params.

    Args:
        type: Event type (always "click" for notification taps).
        identity: User identifier (phone number or CleverTap identity).
        slot: Notification slot number (1-6).
        name: Human-readable notification name.
        day: Journey day when the notification was sent.
        db: Database session.

    Returns:
        HTTP 302 redirect to the lesson page.
    """
    if identity:
        event = NotificationEvent(
            user_id=identity,
            event_type=type,
            metadata_={
                "slot": slot,
                "notification_name": name,
                "journey_day": day,
                "source": "push_click",
            },
        )
        db.add(event)
        await db.commit()

        logger.info(
            "Notification click tracked",
            identity=identity,
            slot=slot,
            name=name,
            day=day,
        )

    return RedirectResponse(url=REDIRECT_URL, status_code=302)


@tracking_router.post("/track-open")
async def track_app_open(
    identity: str = Query(""),
    source: str = Query("notification"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Record an app open event triggered by a notification.

    Args:
        identity: User identifier.
        source: Source of the open event (default: notification).
        db: Database session.

    Returns:
        Confirmation dict with tracking status.
    """
    if not identity:
        return {"success": False, "error": "identity required"}

    event = NotificationEvent(
        user_id=identity,
        event_type="app_open",
        metadata_={"source": source},
    )
    db.add(event)
    await db.commit()

    logger.info("App open tracked", identity=identity, source=source)
    return {"success": True, "identity": identity, "event": "app_open"}


@tracking_router.get("/tracking/{identity}")
async def get_tracking_data(
    identity: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get click and app-open analytics for a specific user.

    Args:
        identity: User identifier to look up.
        db: Database session.

    Returns:
        Dict with clicks, opens, and summary statistics.
    """
    clicks_q = (
        select(NotificationEvent)
        .where(
            NotificationEvent.user_id == identity,
            NotificationEvent.event_type == "click",
        )
        .order_by(NotificationEvent.timestamp.desc())
        .limit(50)
    )
    clicks_result = await db.execute(clicks_q)
    clicks = clicks_result.scalars().all()

    opens_q = (
        select(NotificationEvent)
        .where(
            NotificationEvent.user_id == identity,
            NotificationEvent.event_type == "app_open",
        )
        .order_by(NotificationEvent.timestamp.desc())
        .limit(50)
    )
    opens_result = await db.execute(opens_q)
    opens = opens_result.scalars().all()

    click_count_q = select(func.count(NotificationEvent.id)).where(
        NotificationEvent.user_id == identity,
        NotificationEvent.event_type == "click",
    )
    total_clicks = (await db.execute(click_count_q)).scalar() or 0

    open_count_q = select(func.count(NotificationEvent.id)).where(
        NotificationEvent.user_id == identity,
        NotificationEvent.event_type == "app_open",
    )
    total_opens = (await db.execute(open_count_q)).scalar() or 0

    return {
        "identity": identity,
        "clicks": [
            {
                "id": str(c.id),
                "event_type": c.event_type,
                "metadata": c.metadata_,
                "timestamp": c.timestamp.isoformat() if c.timestamp else None,
            }
            for c in clicks
        ],
        "opens": [
            {
                "id": str(o.id),
                "event_type": o.event_type,
                "metadata": o.metadata_,
                "timestamp": o.timestamp.isoformat() if o.timestamp else None,
            }
            for o in opens
        ],
        "summary": {
            "total_clicks": total_clicks,
            "total_opens": total_opens,
        },
    }
