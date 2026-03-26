"""LLM output tests — notification generation, fallback, prompt building, and copy validation."""

from unittest.mock import AsyncMock

from app.config.manager import ConfigManager
from app.llm.provider import LLMProvider, LLMProviderError
from app.llm.schemas import NotificationCopy, NotificationPrompt
from app.notifications.generator import NotificationGenerator
from app.notifications.schemas import NotificationTheme


def _make_prompt() -> NotificationPrompt:
    return NotificationPrompt(
        user_state="This learner is actively progressing.",
        user_profile={"learning_reason": "job_interview", "profession": "engineer"},
        chapter_analysis={"narrative_moment": "Raj prepares for his presentation"},
        journey_summary="English learning journey for professionals",
        notification_theme="motivational",
        constraints={"max_body_lines": 2, "language": "hinglish"},
    )


def _mock_config() -> ConfigManager:
    mock = AsyncMock(spec=ConfigManager)
    mock.get.return_value = 0.7
    return mock


async def test_valid_notification_copy() -> None:
    mock_llm = AsyncMock(spec=LLMProvider)
    mock_llm.generate_notification.return_value = NotificationCopy(
        title="Keep going!",
        body="Aaj bhi practice karo. Raj aapka wait kar raha hai!",
        cta="Continue",
        theme_used="motivational",
        confidence=0.95,
    )

    config = _mock_config()
    generator = NotificationGenerator(mock_llm, config)
    result = await generator.generate(
        _make_prompt(), "system prompt", NotificationTheme.motivational, "hash123",
    )

    assert result.title == "Keep going!"
    assert result.generation_method == "llm_generated"


async def test_missing_title_triggers_fallback() -> None:
    mock_llm = AsyncMock(spec=LLMProvider)
    mock_llm.generate_notification.return_value = NotificationCopy(
        title="",
        body="Test body",
        cta="Open",
        theme_used="motivational",
        confidence=0.5,
    )

    config = _mock_config()
    generator = NotificationGenerator(mock_llm, config)
    result = await generator.generate(
        _make_prompt(), "system prompt", NotificationTheme.motivational, "hash123",
    )

    assert result.generation_method == "fallback_template"


async def test_body_too_long_triggers_fallback() -> None:
    mock_llm = AsyncMock(spec=LLMProvider)
    mock_llm.generate_notification.return_value = NotificationCopy(
        title="Title",
        body="Line 1\nLine 2\nLine 3\nLine 4",
        cta="Open",
        theme_used="motivational",
        confidence=0.5,
    )

    config = _mock_config()
    generator = NotificationGenerator(mock_llm, config)
    result = await generator.generate(
        _make_prompt(), "system prompt", NotificationTheme.motivational, "hash123",
    )

    assert result.generation_method == "fallback_template"


async def test_persistent_failure_triggers_fallback() -> None:
    mock_llm = AsyncMock(spec=LLMProvider)
    mock_llm.generate_notification.side_effect = LLMProviderError("API down")

    config = _mock_config()
    generator = NotificationGenerator(mock_llm, config)
    result = await generator.generate(
        _make_prompt(), "system prompt", NotificationTheme.motivational, "hash123",
    )

    assert result.generation_method == "fallback_template"
    assert result.title != ""


async def test_fallback_template_selection() -> None:
    mock_llm = AsyncMock(spec=LLMProvider)
    mock_llm.generate_notification.side_effect = LLMProviderError("fail")

    config = _mock_config()
    generator = NotificationGenerator(mock_llm, config)

    prompt = _make_prompt()
    prompt.user_state = "struggling"

    result = await generator.generate(
        prompt, "system prompt", NotificationTheme.motivational, "hash123",
    )

    assert result.generation_method == "fallback_template"
    assert result.theme == NotificationTheme.motivational
