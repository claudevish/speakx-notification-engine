"""CleverTap push notification delivery with retry logic.

Handles the HTTP transport layer for sending push notifications through the
CleverTap API, including exponential-backoff retries on transient failures and
timeouts.  Supports platform-specific payloads for Android (big picture, channel,
deep link) and iOS (rich media, deep link).
"""

import asyncio
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

import httpx
import structlog

from app.models.notification import Notification

logger = structlog.get_logger()


def _build_api_url(region: str) -> str:
    """Build the CleverTap push API URL for the given region.

    Args:
        region: CleverTap data region code (in1, us1, eu1, sg1, aps3, mec1).

    Returns:
        The full API endpoint URL.
    """
    return f"https://{region}.api.clevertap.com/1/send/push.json"


def build_tracking_url(
    base_url: str,
    identity: str,
    slot: int,
    notification_name: str,
    journey_day: int,
) -> str:
    """Build a click-tracking deep link URL.

    When the user taps a notification, the device opens this URL which logs the
    click and redirects to the app's lesson page.

    Args:
        base_url: The public server URL (e.g. https://example.up.railway.app).
        identity: The user identifier (phone number or CleverTap identity).
        slot: The notification slot number (1-6).
        notification_name: Human-readable notification name.
        journey_day: The user's current journey day.

    Returns:
        A fully-formed tracking URL with query parameters.
    """
    params = urlencode({
        "type": "click",
        "identity": identity,
        "slot": slot,
        "name": notification_name,
        "day": journey_day,
    })
    return f"{base_url}/api/track?{params}"


class CleverTapDeliveryService:
    """Delivers push notifications via the CleverTap REST API.

    Manages an async HTTP client with authentication headers and implements
    up to 3 retry attempts with exponential backoff for server errors (5xx),
    rate limiting (429), and timeouts.

    Supports platform-specific payloads:
    - Android: notification channel (wzrk_cid), big picture (wzrk_bp),
      high priority, deep link (wzrk_dl)
    - iOS: mutable-content for rich media, media_url, deep link (wzrk_dl)
    """

    def __init__(
        self,
        account_id: str,
        passcode: str,
        region: str = "in1",
        base_url: str = "",
    ) -> None:
        """Initialise the delivery service with CleverTap credentials.

        Args:
            account_id: The CleverTap account ID for API authentication.
            passcode: The CleverTap passcode for API authentication.
            region: CleverTap data region (default: in1 for India).
            base_url: Public server URL for building tracking links.
        """
        self.account_id = account_id
        self.passcode = passcode
        self.region = region
        self.base_url = base_url
        self.api_url = _build_api_url(region)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the shared async HTTP client, creating it on first use.

        Returns:
            A configured ``httpx.AsyncClient`` with CleverTap auth headers
            and a 30-second timeout.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "X-CleverTap-Account-Id": self.account_id,
                    "X-CleverTap-Passcode": self.passcode,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    def _build_payload(
        self,
        notification: Notification,
        user_id: str,
        image_url: str | None = None,
        slot: int = 0,
        notification_name: str = "",
        journey_day: int = 0,
    ) -> dict:
        """Build the CleverTap push payload with platform-specific fields.

        Args:
            notification: The Notification ORM instance.
            user_id: The CleverTap identity string for the target user.
            image_url: Optional image URL for rich notifications.
            slot: Notification slot number (1-6) for tracking.
            notification_name: Human-readable name for tracking.
            journey_day: Current journey day for tracking.

        Returns:
            The complete payload dict for the CleverTap API.
        """
        tracking_url = ""
        if self.base_url:
            tracking_url = build_tracking_url(
                base_url=self.base_url,
                identity=user_id,
                slot=slot,
                notification_name=notification_name or notification.theme,
                journey_day=journey_day,
            )

        content: dict = {
            "title": notification.title,
            "body": notification.body,
        }

        platform_specific: dict = {}

        android: dict = {
            "wzrk_cid": "general_updates",
            "priority": "high",
        }
        if image_url:
            android["wzrk_bp"] = image_url
        if tracking_url:
            android["wzrk_dl"] = tracking_url
        platform_specific["android"] = android

        ios: dict = {}
        if image_url:
            ios["mutable-content"] = "true"
            ios["media_url"] = image_url
            ios["media_dl"] = "true"
        if tracking_url:
            ios["wzrk_dl"] = tracking_url
        if ios:
            platform_specific["ios"] = ios

        if platform_specific:
            content["platform_specific"] = platform_specific

        return {
            "to": {"Identity": [str(user_id)]},
            "tag_group": "NotifyGen Automation",
            "content": content,
        }

    async def send(
        self,
        notification: Notification,
        user_id: str,
        image_url: str | None = None,
        slot: int = 0,
        notification_name: str = "",
        journey_day: int = 0,
    ) -> dict:
        """Send a push notification to a user via the CleverTap API.

        Retries up to 3 times with exponential backoff on 5xx errors, 429
        rate limits, and network timeouts. Updates the notification's
        ``delivery_status`` and ``sent_at`` fields in place.

        Args:
            notification: The ``Notification`` ORM instance to deliver. Its
                ``delivery_status`` is mutated to ``"sent"`` or ``"failed"``.
            user_id: The CleverTap identity string for the target user.
            image_url: Optional image URL for rich push notifications.
            slot: Notification slot number for click tracking.
            notification_name: Human-readable name for click tracking.
            journey_day: Journey day for click tracking.

        Returns:
            A dict with the CleverTap API response on success, or an error
            dict (``{"error": ...}``) on failure.
        """
        payload = self._build_payload(
            notification=notification,
            user_id=user_id,
            image_url=image_url,
            slot=slot,
            notification_name=notification_name,
            journey_day=journey_day,
        )

        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(1, 4):
            try:
                response = await client.post(self.api_url, json=payload)

                if response.status_code == 200:
                    notification.delivery_status = "sent"
                    notification.sent_at = datetime.now(timezone.utc)
                    logger.info(
                        "Notification sent via CleverTap",
                        notification_id=str(notification.id),
                        user_id=user_id,
                        slot=slot,
                    )
                    try:
                        return response.json()
                    except Exception:
                        return {
                            "status": "sent",
                            "raw": response.text[:200],
                        }

                if response.status_code >= 500 or response.status_code == 429:
                    last_error = httpx.HTTPStatusError(
                        f"CleverTap API {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    wait_time = 2 ** (attempt - 1)
                    logger.warning(
                        "CleverTap API error, retrying",
                        status=response.status_code,
                        attempt=attempt,
                    )
                    await asyncio.sleep(wait_time)
                    continue

                notification.delivery_status = "failed"
                logger.error(
                    "CleverTap delivery failed",
                    notification_id=str(notification.id),
                    status=response.status_code,
                    body=response.text[:200],
                )
                return {"error": response.text, "status": response.status_code}

            except httpx.TimeoutException as exc:
                last_error = exc
                wait_time = 2 ** (attempt - 1)
                logger.warning(
                    "CleverTap timeout, retrying",
                    attempt=attempt,
                    wait_seconds=wait_time,
                )
                await asyncio.sleep(wait_time)

        notification.delivery_status = "failed"
        logger.error(
            "CleverTap delivery failed after retries",
            notification_id=str(notification.id),
            error=str(last_error),
        )
        return {"error": str(last_error)}

    async def close(self) -> None:
        """Close the underlying HTTP client and release resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
