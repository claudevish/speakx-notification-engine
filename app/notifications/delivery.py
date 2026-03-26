"""CleverTap push notification delivery with retry logic.

Handles the HTTP transport layer for sending push notifications through the
CleverTap API, including exponential-backoff retries on transient failures and
timeouts.
"""

import asyncio
from datetime import datetime, timezone

import httpx
import structlog

from app.models.notification import Notification

logger = structlog.get_logger()

CLEVERTAP_API_URL = "https://api.clevertap.com/1/send/push.json"


class CleverTapDeliveryService:
    """Delivers push notifications via the CleverTap REST API.

    Manages an async HTTP client with authentication headers and implements
    up to 3 retry attempts with exponential backoff for server errors (5xx),
    rate limiting (429), and timeouts.
    """

    def __init__(self, account_id: str, passcode: str) -> None:
        """Initialise the delivery service with CleverTap credentials.

        Args:
            account_id: The CleverTap account ID for API authentication.
            passcode: The CleverTap passcode for API authentication.
        """
        self.account_id = account_id
        self.passcode = passcode
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

    async def send(self, notification: Notification, user_id: str) -> dict:
        """Send a push notification to a user via the CleverTap API.

        Retries up to 3 times with exponential backoff on 5xx errors, 429
        rate limits, and network timeouts. Updates the notification's
        ``delivery_status`` and ``sent_at`` fields in place.

        Args:
            notification: The ``Notification`` ORM instance to deliver. Its
                ``delivery_status`` is mutated to ``"sent"`` or ``"failed"``.
            user_id: The CleverTap identity string for the target user.

        Returns:
            A dict with the CleverTap API response on success, or an error
            dict (``{"error": ...}``) on failure.
        """
        payload = {
            "to": {"identity": [user_id]},
            "tag_group": notification.theme,
            "content": {
                "title": notification.title,
                "body": notification.body,
                "action": notification.cta,
            },
        }

        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(1, 4):
            try:
                response = await client.post(CLEVERTAP_API_URL, json=payload)

                if response.status_code == 200:
                    notification.delivery_status = "sent"
                    notification.sent_at = datetime.now(
                        timezone.utc,
                    )
                    logger.info(
                        "Notification sent via CleverTap",
                        notification_id=str(notification.id),
                        user_id=user_id,
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
