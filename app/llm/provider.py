from abc import ABC, abstractmethod

from app.ingestion.schemas import ChapterStructure, JourneyStructure
from app.llm.schemas import (
    ChapterAnalysis,
    JourneyAnalysis,
    NotificationCopy,
    NotificationPrompt,
)


class LLMProvider(ABC):
    @abstractmethod
    async def analyze_journey(self, journey_structure: JourneyStructure) -> JourneyAnalysis:
        ...

    @abstractmethod
    async def analyze_chapter(
        self, chapter_data: ChapterStructure, journey_context: JourneyAnalysis,
    ) -> ChapterAnalysis:
        ...

    @abstractmethod
    async def generate_notification(self, prompt: NotificationPrompt) -> NotificationCopy:
        ...

    @abstractmethod
    async def generate_raw(self, system_prompt: str, user_prompt: str) -> str:
        """Send a raw system+user prompt and return the raw text response."""
        ...


class LLMProviderError(Exception):
    pass


class LLMValidationError(LLMProviderError):
    pass
