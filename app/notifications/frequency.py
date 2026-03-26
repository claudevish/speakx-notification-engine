"""Frequency capping and activity-based suppression for notifications.

Provides checks that prevent over-notifying a single user: a daily send cap
and a suppression window that skips notifications when the user has been
recently active in the app.
"""

import uuid
from datetime import datetime, time, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import ConfigManager
from app.models.notification import Notification
from app.models.user import UserJourneyState

logger = structlog.get_logger()


class FrequencyCapService:
    """Enforces per-user notification frequency caps and suppression rules.

    Uses the database to count today's sent notifications and check the user's
    last activity timestamp against configurable thresholds.
    """

    def __init__(self, db_session: AsyncSession, config_manager: ConfigManager) -> None:
        """Initialise the service with a database session and config manager.

        Args:
            db_session: An async SQLAlchemy session for querying notification
                and user state records.
            config_manager: Application configuration accessor for reading
                cap and suppression thresholds.
        """
        self.db = db_session
        self.config = config_manager

    async def can_send(self, user_id: str, journey_id: uuid.UUID) -> bool:
        """Check whether the user is within their daily notification cap.

        Counts non-failed notifications sent to the user today (UTC) and
        compares against the ``max_per_day`` config value.

        Args:
            user_id: The unique identifier of the user.
            journey_id: The journey UUID (reserved for future per-journey caps).

        Returns:
            ``True`` if the user has not yet reached the daily cap.
        """
        max_per_day = await self.config.get("max_per_day", 6)

        today_start = datetime.combine(
            datetime.now(timezone.utc).date(), time.min,
        ).replace(tzinfo=timezone.utc)

        result = await self.db.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id,
                Notification.created_at >= today_start,
                Notification.delivery_status != "failed",
            )
        )
        count = result.scalar() or 0
        return count < max_per_day

    async def should_suppress(self, user_id: str, journey_id: uuid.UUID) -> bool:
        """Determine whether to suppress a notification for a recently active user.

        Looks up the user's ``last_activity_at`` timestamp for the given journey
        and suppresses the notification if the user was active within the
        ``suppress_if_active_minutes`` config window (default 120 minutes).

        Args:
            user_id: The unique identifier of the user.
            journey_id: The journey UUID to check activity against.

        Returns:
            ``True`` if the notification should be suppressed because the user
            was recently active.
        """
        suppress_minutes = await self.config.get("suppress_if_active_minutes", 120)

        result = await self.db.execute(
            select(UserJourneyState.last_activity_at).where(
                UserJourneyState.user_id == user_id,
                UserJourneyState.journey_id == journey_id,
            )
        )
        last_activity = result.scalar_one_or_none()

        if last_activity is None:
            return False

        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        minutes_since = (now - last_activity).total_seconds() / 60

        return minutes_since < suppress_minutes
