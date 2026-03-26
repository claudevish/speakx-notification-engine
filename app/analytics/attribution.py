"""Notification-to-app-return attribution within configurable time window."""

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import ConfigManager
from app.models.analytics import AttributionEvent
from app.models.notification import Notification

logger = structlog.get_logger()


class AttributionService:
    def __init__(
        self,
        db_session: AsyncSession,
        config_manager: ConfigManager,
    ) -> None:
        self.db = db_session
        self.config = config_manager

    async def check_attribution(
        self,
        user_id: str,
        app_open_timestamp: datetime,
    ) -> Optional[UUID]:
        window_hours = await self.config.get(
            "attribution.window_hours", 4,
        )

        window_start = app_open_timestamp - timedelta(
            hours=window_hours,
        )

        result = await self.db.execute(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.sent_at >= window_start,
                Notification.sent_at <= app_open_timestamp,
                Notification.delivery_status.in_(
                    ["sent", "delivered"],
                ),
            )
            .order_by(Notification.sent_at.desc())
            .limit(1),
        )
        notification = result.scalar_one_or_none()

        if not notification:
            logger.debug(
                "No notification to attribute",
                user_id=user_id,
            )
            return None

        attribution = AttributionEvent(
            user_id=user_id,
            notification_id=notification.id,
            app_open_timestamp=app_open_timestamp,
            attribution_window_hours=window_hours,
        )
        self.db.add(attribution)
        await self.db.flush()

        logger.info(
            "App return attributed to notification",
            user_id=user_id,
            notification_id=str(notification.id),
            attribution_id=str(attribution.id),
        )
        return notification.id

    async def update_post_return_engagement(
        self,
        user_id: str,
        attribution_event_id: UUID,
    ) -> None:
        result = await self.db.execute(
            select(AttributionEvent).where(
                AttributionEvent.id == attribution_event_id,
            ),
        )
        attribution = result.scalar_one_or_none()
        if not attribution:
            return

        from app.models.user import UserJourneyState

        state_result = await self.db.execute(
            select(UserJourneyState).where(
                UserJourneyState.user_id == user_id,
            ),
        )
        state = state_result.scalar_one_or_none()

        activities = 0
        if state and state.sliding_window_scores:
            recent = [
                s for s in state.sliding_window_scores
                if isinstance(s, dict)
            ]
            activities = len(recent)

        attribution.activities_completed_after = activities
        await self.db.flush()

        logger.info(
            "Post-return engagement updated",
            attribution_id=str(attribution_event_id),
            activities=activities,
        )
