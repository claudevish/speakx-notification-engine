"""Edge case tests — covers critical boundary conditions."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.manager import ConfigManager
from app.ingestion.parser import parse_journey_csv
from app.llm.provider import LLMProvider, LLMProviderError
from app.llm.schemas import NotificationCopy, NotificationPrompt
from app.models.journey import Journey
from app.models.notification import Notification
from app.notifications.delivery import CleverTapDeliveryService
from app.notifications.frequency import FrequencyCapService
from app.notifications.generator import NotificationGenerator
from app.notifications.schemas import NotificationTheme
from app.state_engine.temporal import scan_dormancy


def _mock_config() -> ConfigManager:
    mock = AsyncMock(spec=ConfigManager)
    mock.get.return_value = 0.7
    return mock


async def test_malformed_csv_upload() -> None:
    garbage = b"\x00\x01\x02\xff\xfe\xfd" * 100
    rows, errors = parse_journey_csv(garbage)
    assert len(rows) == 0
    assert len(errors) > 0


async def test_oversized_csv_rejected() -> None:
    big = b"a" * (51 * 1024 * 1024)
    rows, errors = parse_journey_csv(big)
    assert len(rows) == 0
    assert any("size limit" in e for e in errors)


async def test_llm_returns_non_json() -> None:
    mock_llm = AsyncMock(spec=LLMProvider)
    mock_llm.generate_notification.side_effect = (
        LLMProviderError("Invalid JSON response")
    )

    config = _mock_config()
    generator = NotificationGenerator(mock_llm, config)
    prompt = NotificationPrompt(
        user_state="Active learner.",
        user_profile={"learning_reason": "general"},
        chapter_analysis={},
        journey_summary="Test journey",
        notification_theme="motivational",
        constraints={"max_body_lines": 2},
    )
    result = await generator.generate(
        prompt,
        "system",
        NotificationTheme.motivational,
        "hash",
    )
    assert result.generation_method == "fallback_template"
    assert result.title != ""


async def test_llm_timeout() -> None:
    mock_llm = AsyncMock(spec=LLMProvider)
    mock_llm.generate_notification.side_effect = (
        TimeoutError("LLM request timed out")
    )

    config = _mock_config()
    generator = NotificationGenerator(mock_llm, config)
    prompt = NotificationPrompt(
        user_state="Active learner.",
        user_profile={},
        chapter_analysis={},
        journey_summary="",
        notification_theme="motivational",
        constraints={},
    )
    result = await generator.generate(
        prompt,
        "system",
        NotificationTheme.motivational,
        "hash",
    )
    assert result.generation_method == "fallback_template"


async def test_notification_field_truncation() -> None:
    mock_llm = AsyncMock(spec=LLMProvider)
    mock_llm.generate_notification.return_value = (
        NotificationCopy(
            title="X" * 500,
            body="Short body",
            cta="Open",
            theme_used="motivational",
            confidence=0.9,
        )
    )

    config = _mock_config()
    generator = NotificationGenerator(mock_llm, config)
    prompt = NotificationPrompt(
        user_state="Active learner.",
        user_profile={},
        chapter_analysis={},
        journey_summary="",
        notification_theme="motivational",
        constraints={},
    )
    result = await generator.generate(
        prompt,
        "system",
        NotificationTheme.motivational,
        "hash",
    )
    assert result.generation_method == "llm_generated"
    assert len(result.title) <= 100
    assert result.title.endswith("...")


async def test_dormancy_scan_empty_db(
    test_db: AsyncSession,
) -> None:
    config = ConfigManager(test_db)
    result = await scan_dormancy(test_db, config)
    assert result["users_scanned"] == 0


async def test_attribution_no_matching_notification(
    test_db: AsyncSession,
) -> None:
    from app.analytics.attribution import AttributionService

    config = ConfigManager(test_db)
    service = AttributionService(test_db, config)
    result = await service.check_attribution(
        "nonexistent-user",
        datetime.now(timezone.utc),
    )
    assert result is None


async def test_config_missing_key_returns_default(
    test_db: AsyncSession,
) -> None:
    config = ConfigManager(test_db)
    result = await config.get(
        "totally_nonexistent_key", "default_val",
    )
    assert result == "default_val"


async def test_frequency_cap_empty_db(
    test_db: AsyncSession,
) -> None:
    journey = Journey(name="Test", status="active")
    test_db.add(journey)
    await test_db.flush()

    config = ConfigManager(test_db)
    service = FrequencyCapService(test_db, config)
    result = await service.can_send("new-user", journey.id)
    assert result is True


async def test_clevertap_unexpected_format() -> None:
    from unittest.mock import patch

    import httpx

    service = CleverTapDeliveryService(
        "test-account", "test-passcode",
    )

    mock_response = httpx.Response(
        200,
        text="Not JSON",
        request=httpx.Request("POST", "https://test"),
    )

    with patch.object(
        service, "_get_client",
    ) as mock_client_fn:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_fn.return_value = mock_client

        notification = Notification(
            user_id="test",
            journey_id=journey_id_placeholder(),
            state_at_generation="progressing_active",
            theme="motivational",
            title="Test",
            body="Test",
            cta="Open",
            generation_method="fallback_template",
            mode="live",
            delivery_status="pending",
        )
        await service.send(notification, "test")
        assert notification.delivery_status in (
            "sent", "failed",
        )


async def test_empty_csv_file() -> None:
    rows, errors = parse_journey_csv(b"")
    assert len(rows) == 0
    assert len(errors) > 0


def journey_id_placeholder():  # noqa: ANN201
    import uuid
    return uuid.uuid4()
