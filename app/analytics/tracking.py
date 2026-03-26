"""Notification lifecycle tracking — records internal events (sent, failed)."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationEvent

logger = structlog.get_logger()


class NotificationTrackingService:
    def __init__(self, db_session: AsyncSession) -> None:
        self.db = db_session

    async def record_event(
        self,
        notification_id: UUID,
        user_id: str,
        event_type: str,
        metadata: Optional[dict] = None,
    ) -> None:
        event = NotificationEvent(
            notification_id=notification_id,
            user_id=user_id,
            event_type=event_type,
            metadata=metadata,
        )
        self.db.add(event)
        await self.db.flush()

        logger.info(
            "Notification event recorded",
            notification_id=str(notification_id),
            event_type=event_type,
        )

    async def get_notification_history(
        self, user_id: str, days: int = 30,
    ) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.created_at >= since,
            )
            .order_by(Notification.created_at.desc()),
        )
        notifications = result.scalars().all()

        history = []
        for notif in notifications:
            events_result = await self.db.execute(
                select(NotificationEvent)
                .where(
                    NotificationEvent.notification_id
                    == notif.id,
                )
                .order_by(NotificationEvent.timestamp),
            )
            events = events_result.scalars().all()

            history.append({
                "id": str(notif.id),
                "title": notif.title,
                "body": notif.body,
                "cta": notif.cta,
                "theme": notif.theme,
                "state_at_generation": notif.state_at_generation,
                "generation_method": notif.generation_method,
                "mode": notif.mode,
                "delivery_status": notif.delivery_status,
                "created_at": (
                    notif.created_at.isoformat()
                    if notif.created_at
                    else None
                ),
                "sent_at": (
                    notif.sent_at.isoformat()
                    if notif.sent_at
                    else None
                ),
                "events": [
                    {
                        "event_type": e.event_type,
                        "timestamp": e.timestamp.isoformat(),
                    }
                    for e in events
                ],
            })

        return history
