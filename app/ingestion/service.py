"""Journey ingestion orchestrator — coordinates CSV parsing, LLM analysis, and DB persistence."""

from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.parser import build_journey_hierarchy, parse_journey_csv
from app.ingestion.schemas import IngestionStatus, JourneyStructure
from app.ingestion.validator import validate_journey_structure
from app.llm.provider import LLMProvider
from app.models.journey import (
    Activity,
    Chapter,
    Journey,
    Lesson,
    Quest,
    Task,
)

logger = structlog.get_logger()


class IngestionService:
    """Orchestrates end-to-end journey ingestion: parse → validate → store → analyze."""

    def __init__(self, db_session: AsyncSession, llm_provider: LLMProvider) -> None:
        self.db = db_session
        self.llm = llm_provider

    async def ingest_journey(self, file_content: bytes, filename: str) -> IngestionStatus:
        """Ingest a CSV file: parse, validate, persist hierarchy, run LLM analysis."""
        started_at = datetime.now(timezone.utc)
        log = logger.bind(filename=filename)

        rows, parse_errors = parse_journey_csv(file_content)
        if parse_errors:
            await log.aerror("CSV parsing failed", errors=parse_errors)
            return IngestionStatus(
                status="failed", errors=parse_errors, started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

        hierarchy = build_journey_hierarchy(rows)
        validation_errors = validate_journey_structure(hierarchy)
        if validation_errors:
            await log.aerror("Validation failed", errors=validation_errors)
            return IngestionStatus(
                status="failed", errors=validation_errors, started_at=started_at,
                total_rows=len(rows), completed_at=datetime.now(timezone.utc),
            )

        journey = Journey(name=hierarchy.name, status="analyzing")
        self.db.add(journey)
        await self.db.flush()
        await log.ainfo("Journey record created", journey_id=str(journey.id), journey_name=journey.name)

        try:
            await self._store_hierarchy(journey, hierarchy)
            await self.db.flush()
            await log.ainfo("Hierarchy stored", chapters=len(hierarchy.chapters))

            journey_analysis = await self.llm.analyze_journey(hierarchy)
            journey.llm_journey_summary = journey_analysis.model_dump()
            await log.ainfo("Journey-level LLM analysis complete")

            chapters = await self._get_chapters(journey)
            analyzed_count = 0
            failed_chapters: list[str] = []
            for i, chapter_struct in enumerate(
                hierarchy.chapters,
            ):
                try:
                    db_chapter = chapters[i]
                    chapter_analysis = (
                        await self.llm.analyze_chapter(
                            chapter_struct, journey_analysis,
                        )
                    )
                    db_chapter.llm_analysis = (
                        chapter_analysis.model_dump()
                    )
                    analyzed_count += 1
                    await log.ainfo(
                        "Chapter analysis complete",
                        chapter=chapter_struct.name,
                        progress=(
                            f"{analyzed_count}"
                            f"/{len(hierarchy.chapters)}"
                        ),
                    )
                except Exception as ch_exc:
                    failed_chapters.append(
                        chapter_struct.name,
                    )
                    await log.awarning(
                        "Chapter analysis failed, skipping",
                        chapter=chapter_struct.name,
                        error=str(ch_exc),
                    )

            journey.status = "active"
            journey.total_chapters = len(hierarchy.chapters)
            await self.db.commit()

            return IngestionStatus(
                journey_id=journey.id, status="complete",
                total_rows=len(rows), processed_rows=len(rows),
                chapters_analyzed=analyzed_count, total_chapters=len(hierarchy.chapters),
                started_at=started_at, completed_at=datetime.now(timezone.utc),
            )

        except Exception as exc:
            journey.status = "failed"
            await self.db.commit()
            await log.aerror("Ingestion failed", error=str(exc))
            return IngestionStatus(
                journey_id=journey.id, status="failed",
                errors=[str(exc)], total_rows=len(rows),
                started_at=started_at, completed_at=datetime.now(timezone.utc),
            )

    async def _store_hierarchy(self, journey: Journey, hierarchy: JourneyStructure) -> None:
        for ch_struct in hierarchy.chapters:
            chapter = Chapter(
                journey_id=journey.id, chapter_number=ch_struct.chapter_number,
                name=ch_struct.name, theme=ch_struct.theme,
            )
            self.db.add(chapter)
            await self.db.flush()

            for q_struct in ch_struct.quests:
                quest = Quest(
                    journey_id=journey.id, chapter_id=chapter.id,
                    quest_number=q_struct.quest_number, name=q_struct.name,
                )
                self.db.add(quest)
                await self.db.flush()

                for a_struct in q_struct.activities:
                    activity = Activity(
                        journey_id=journey.id, quest_id=quest.id,
                        activity_number=a_struct.activity_number, name=a_struct.name,
                        activity_type=a_struct.activity_type,
                    )
                    self.db.add(activity)
                    await self.db.flush()

                    for l_struct in a_struct.lessons:
                        lesson = Lesson(
                            journey_id=journey.id, activity_id=activity.id,
                            lesson_number=l_struct.lesson_number, name=l_struct.name,
                        )
                        self.db.add(lesson)
                        await self.db.flush()

                        for t_struct in l_struct.tasks:
                            task = Task(
                                journey_id=journey.id, lesson_id=lesson.id,
                                task_number=t_struct.task_number, name=t_struct.name,
                                task_type=t_struct.task_type,
                            )
                            self.db.add(task)

    async def _get_chapters(self, journey: Journey) -> list[Chapter]:
        from sqlalchemy import select
        result = await self.db.execute(
            select(Chapter)
            .where(Chapter.journey_id == journey.id)
            .order_by(Chapter.chapter_number)
        )
        return list(result.scalars().all())
