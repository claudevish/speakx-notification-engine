"""CleverTap Reporting API engagement sync — polls every 30 minutes."""

from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationEvent

logger = structlog.get_logger()

CLEVERTAP_API_URL = "https://api.clevertap.com/1/events/query.json"


class CleverTapSyncService:
    def __init__(
        self,
        account_id: str,
        passcode: str,
        db_session: AsyncSession,
    ) -> None:
        self.account_id = account_id
        self.passcode = passcode
        self.db = db_session

    def _get_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={
                "X-CleverTap-Account-Id": self.account_id,
                "X-CleverTap-Passcode": self.passcode,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def sync_engagement_events(
        self, since_minutes: int = 35,
    ) -> dict:
        since = datetime.now(timezone.utc) - timedelta(
            minutes=since_minutes,
        )
        summary = {
            "events_synced": 0,
            "events_skipped_duplicate": 0,
            "events_unmatched": 0,
        }

        try:
            events = await self._fetch_events(since)
        except (httpx.HTTPError, Exception) as exc:
            logger.error(
                "CleverTap sync failed", error=str(exc),
            )
            return summary

        for event in events:
            await self._process_event(event, summary)

        logger.info(
            "CleverTap engagement sync complete",
            **summary,
        )
        return summary

    async def _fetch_events(
        self, since: datetime,
    ) -> list[dict]:
        from_ts = int(since.timestamp())
        to_ts = int(datetime.now(timezone.utc).timestamp())

        payload = {
            "event_name": "Notification Sent",
            "from": from_ts,
            "to": to_ts,
        }

        async with self._get_client() as client:
            resp = await client.post(
                CLEVERTAP_API_URL, json=payload,
            )
            if resp.status_code != 200:
                logger.warning(
                    "CleverTap API error",
                    status=resp.status_code,
                    body=resp.text[:200],
                )
                return []
            data = resp.json()
            return data.get("records", [])

    async def _process_event(
        self, event: dict, summary: dict,
    ) -> None:
        campaign_id = event.get("campaign_id", "")
        event_type = event.get("event_type", "delivered")

        if not campaign_id:
            summary["events_unmatched"] += 1
            return

        result = await self.db.execute(
            select(Notification).where(
                Notification.clevertap_campaign_id == campaign_id,
            ),
        )
        notification = result.scalar_one_or_none()

        if not notification:
            summary["events_unmatched"] += 1
            return

        existing = await self.db.execute(
            select(NotificationEvent).where(
                NotificationEvent.notification_id == notification.id,
                NotificationEvent.event_type == event_type,
            ),
        )
        if existing.scalar_one_or_none():
            summary["events_skipped_duplicate"] += 1
            return

        notif_event = NotificationEvent(
            notification_id=notification.id,
            user_id=notification.user_id,
            event_type=event_type,
            metadata={"source": "clevertap_sync", "raw": event},
        )
        self.db.add(notif_event)

        if event_type == "delivered":
            notification.delivery_status = "delivered"

        await self.db.flush()
        summary["events_synced"] += 1

    async def close(self) -> None:
        pass
