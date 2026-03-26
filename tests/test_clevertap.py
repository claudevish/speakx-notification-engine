"""CleverTap delivery tests — push notification dispatch and error handling."""

import uuid
from unittest.mock import AsyncMock, patch

import httpx

from app.models.notification import Notification
from app.notifications.delivery import CleverTapDeliveryService


def _make_notification() -> Notification:
    return Notification(
        id=uuid.uuid4(),
        user_id="test-user",
        journey_id=uuid.uuid4(),
        state_at_generation="progressing_active",
        theme="motivational",
        title="Test Title",
        body="Test Body",
        cta="Open App",
        generation_method="fallback_template",
        mode="live",
        delivery_status="pending",
    )


async def test_successful_delivery() -> None:
    service = CleverTapDeliveryService("test-account", "test-passcode")

    mock_response = httpx.Response(200, json={"status": "success"}, request=httpx.Request("POST", "https://test"))

    with patch.object(service, "_get_client") as mock_client_fn:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_fn.return_value = mock_client

        notification = _make_notification()
        result = await service.send(notification, "test-user")

        assert result["status"] == "success"
        assert notification.delivery_status == "sent"
        assert notification.sent_at is not None


async def test_auth_failure() -> None:
    service = CleverTapDeliveryService("test-account", "test-passcode")

    mock_response = httpx.Response(401, text="Unauthorized", request=httpx.Request("POST", "https://test"))

    with patch.object(service, "_get_client") as mock_client_fn:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_fn.return_value = mock_client

        notification = _make_notification()
        result = await service.send(notification, "test-user")

        assert notification.delivery_status == "failed"
        assert "error" in result


async def test_rate_limit_retry() -> None:
    service = CleverTapDeliveryService("test-account", "test-passcode")

    response_429 = httpx.Response(429, text="Rate limited", request=httpx.Request("POST", "https://test"))
    response_200 = httpx.Response(200, json={"status": "success"}, request=httpx.Request("POST", "https://test"))

    with patch.object(service, "_get_client") as mock_client_fn:
        mock_client = AsyncMock()
        mock_client.post.side_effect = [response_429, response_200]
        mock_client_fn.return_value = mock_client

        notification = _make_notification()
        await service.send(notification, "test-user")

        assert notification.delivery_status == "sent"
        assert mock_client.post.call_count == 2


async def test_timeout_retry() -> None:
    service = CleverTapDeliveryService("test-account", "test-passcode")

    response_200 = httpx.Response(200, json={"status": "success"}, request=httpx.Request("POST", "https://test"))

    with patch.object(service, "_get_client") as mock_client_fn:
        mock_client = AsyncMock()
        mock_client.post.side_effect = [httpx.TimeoutException("timeout"), response_200]
        mock_client_fn.return_value = mock_client

        notification = _make_notification()
        await service.send(notification, "test-user")

        assert notification.delivery_status == "sent"
        assert mock_client.post.call_count == 2
