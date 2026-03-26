"""Ingestion pipeline tests — CSV parsing, validation, hierarchy building, and LLM analysis."""

from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.parser import build_journey_hierarchy, parse_journey_csv
from app.ingestion.schemas import ChapterStructure, JourneyStructure
from app.ingestion.service import IngestionService
from app.ingestion.validator import validate_journey_structure
from app.llm.provider import LLMProvider, LLMProviderError
from app.llm.schemas import ChapterAnalysis, JourneyAnalysis
from app.models.journey import Activity, Chapter, Journey, Lesson, Quest, Task

VALID_CSV_HEADER = (
    "journey_name,chapter_name,chapter_number,quest_name,quest_number,"
    "activity_name,activity_number,activity_type,lesson_name,lesson_number,"
    "task_name,task_number,task_type"
)

VALID_CSV_ROWS = [
    "Dil se English,Intro,1,Quest1,1,Act1,1,reading,Lesson1,1,Task1,1,quiz",
    "Dil se English,Intro,1,Quest1,1,Act1,1,reading,Lesson1,1,Task2,2,practice",
    "Dil se English,Intro,1,Quest1,1,Act2,2,writing,Lesson1,1,Task1,1,exercise",
    "Dil se English,Intro,1,Quest2,2,Act1,1,speaking,Lesson1,1,Task1,1,dialogue",
    "Dil se English,Chapter 2,2,Quest1,1,Act1,1,listening,Lesson1,1,Task1,1,audio",
    "Dil se English,Chapter 2,2,Quest1,1,Act1,1,listening,Lesson1,1,Task2,2,quiz",
    "Dil se English,Chapter 2,2,Quest1,1,Act1,1,listening,Lesson2,2,Task1,1,fill",
    "Dil se English,Chapter 2,2,Quest1,1,Act2,2,grammar,Lesson1,1,Task1,1,match",
    "Dil se English,Chapter 2,2,Quest2,2,Act1,1,vocab,Lesson1,1,Task1,1,flashcard",
    "Dil se English,Chapter 2,2,Quest2,2,Act1,1,vocab,Lesson1,1,Task2,2,spell",
]


def _make_csv(rows: list[str] | None = None) -> bytes:
    lines = [VALID_CSV_HEADER] + (rows if rows is not None else VALID_CSV_ROWS)
    return "\n".join(lines).encode("utf-8")


def _mock_journey_analysis() -> JourneyAnalysis:
    return JourneyAnalysis(
        summary="Test journey about English learning",
        emotional_arc=["excitement", "challenge"],
        narrative_themes=["friendship", "discovery"],
        character_relationships=[],
        segment_signals={"career": "professional English"},
        difficulty_progression="easy to medium",
    )


def _mock_chapter_analysis() -> ChapterAnalysis:
    return ChapterAnalysis(
        emotional_context="warm and welcoming",
        difficulty_curve="easy, rising",
        key_vocabulary=["hello", "thank you"],
        narrative_moment="The journey begins with a new friend",
        segment_content={"career": "meeting colleagues"},
        engagement_hooks=["exciting story twist"],
    )


def _create_mock_llm() -> LLMProvider:
    mock = AsyncMock(spec=LLMProvider)
    mock.analyze_journey.return_value = _mock_journey_analysis()
    mock.analyze_chapter.return_value = _mock_chapter_analysis()
    return mock


async def test_parse_valid_csv() -> None:
    rows, errors = parse_journey_csv(_make_csv())
    assert len(errors) == 0
    assert len(rows) == 10
    assert rows[0].journey_name == "Dil se English"
    assert rows[0].chapter_number == 1


async def test_parse_invalid_encoding() -> None:
    bad_bytes = b"\xff\xfe" + b"\x00" * 10
    rows, errors = parse_journey_csv(bad_bytes)
    assert len(errors) > 0
    assert len(rows) == 0


async def test_parse_empty_csv() -> None:
    empty = VALID_CSV_HEADER.encode("utf-8")
    rows, errors = parse_journey_csv(empty)
    assert len(errors) > 0
    assert "empty" in errors[0].lower()


async def test_validate_sequential_chapters() -> None:
    structure = JourneyStructure(
        name="Test",
        chapters=[
            ChapterStructure(name="Ch1", chapter_number=1, quests=[]),
            ChapterStructure(name="Ch3", chapter_number=3, quests=[]),
        ],
    )
    errors = validate_journey_structure(structure)
    assert any("sequential" in e.lower() or "not sequential" in e.lower() for e in errors)


async def test_validate_missing_quests() -> None:
    structure = JourneyStructure(
        name="Test",
        chapters=[
            ChapterStructure(name="Ch1", chapter_number=1, quests=[]),
        ],
    )
    errors = validate_journey_structure(structure)
    assert any("no quests" in e.lower() for e in errors)


async def test_build_hierarchy_deduplication() -> None:
    rows_no_dup, _ = parse_journey_csv(_make_csv(VALID_CSV_ROWS))
    hierarchy_clean = build_journey_hierarchy(rows_no_dup)

    duplicate_rows = VALID_CSV_ROWS + [VALID_CSV_ROWS[0]]
    rows_with_dup, _ = parse_journey_csv(_make_csv(duplicate_rows))
    hierarchy_dup = build_journey_hierarchy(rows_with_dup)

    def _count_tasks(h: JourneyStructure) -> int:
        total = 0
        for ch in h.chapters:
            for q in ch.quests:
                for a in q.activities:
                    for ls in a.lessons:
                        total += len(ls.tasks)
        return total

    assert _count_tasks(hierarchy_clean) == 10
    assert _count_tasks(hierarchy_dup) == 10


async def test_ingestion_service_stores_hierarchy(test_db: AsyncSession) -> None:
    mock_llm = _create_mock_llm()
    service = IngestionService(db_session=test_db, llm_provider=mock_llm)

    status = await service.ingest_journey(_make_csv(), "test.csv")

    assert status.status == "complete"
    assert status.journey_id is not None
    assert status.total_chapters == 2
    assert status.chapters_analyzed == 2

    journeys = (await test_db.execute(select(Journey))).scalars().all()
    assert len(journeys) == 1
    assert journeys[0].status == "active"

    chapters = (await test_db.execute(select(Chapter))).scalars().all()
    assert len(chapters) == 2

    quests = (await test_db.execute(select(Quest))).scalars().all()
    assert len(quests) == 4

    activities = (await test_db.execute(select(Activity))).scalars().all()
    assert len(activities) == 6

    lessons = (await test_db.execute(select(Lesson))).scalars().all()
    assert len(lessons) >= 4

    tasks = (await test_db.execute(select(Task))).scalars().all()
    assert len(tasks) == 10

    mock_llm.analyze_journey.assert_called_once()
    assert mock_llm.analyze_chapter.call_count == 2


async def test_ingestion_service_llm_failure(test_db: AsyncSession) -> None:
    mock_llm = _create_mock_llm()
    mock_llm.analyze_journey.side_effect = LLMProviderError("API timeout")

    service = IngestionService(db_session=test_db, llm_provider=mock_llm)
    status = await service.ingest_journey(_make_csv(), "test.csv")

    assert status.status == "failed"
    assert any("API timeout" in e for e in status.errors)

    journeys = (await test_db.execute(select(Journey))).scalars().all()
    assert len(journeys) == 1
    assert journeys[0].status == "failed"
