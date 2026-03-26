"""Journey CSV parser — validates, decodes, and builds hierarchy from uploaded CSV files.

Supports two CSV formats:
1. Simple format — explicit columns: journey_name, chapter_name, chapter_number, etc.
2. SpeakX format — admin-code-based columns: journeyID, chapterID, adminCode, etc.
   with embedded tasks (lesson/tasks/0/task, lesson/tasks/1/task, lesson/tasks/2/task).
"""

import csv
import io
import re

import structlog
from pydantic import ValidationError

from app.ingestion.schemas import (
    ActivityStructure,
    ChapterStructure,
    CSVRow,
    JourneyStructure,
    LessonStructure,
    QuestStructure,
    TaskStructure,
)

logger = structlog.get_logger()


MAX_CSV_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_ROW_COUNT = 100_000
MAX_CELL_LENGTH = 10_000

_ADMIN_CODE_NUM_RE = re.compile(r"[A-Za-z]+(\d+)$")


def parse_journey_csv(
    file_content: bytes,
) -> tuple[list[CSVRow], list[str]]:
    """Parse raw CSV bytes into validated CSVRow objects.

    Enforces size limits (50 MB), row limits (100K), and cell
    truncation (10K chars). Automatically detects SpeakX nested
    format vs simple flat format. Returns parsed rows and any errors.
    """
    errors: list[str] = []
    rows: list[CSVRow] = []

    if len(file_content) > MAX_CSV_SIZE_BYTES:
        errors.append(
            f"CSV exceeds size limit of "
            f"{MAX_CSV_SIZE_BYTES // (1024 * 1024)}MB"
        )
        return rows, errors

    text = _decode_content(file_content)
    if text is None:
        errors.append(
            "File encoding not supported. Use UTF-8."
        )
        return rows, errors

    try:
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        speakx = _is_speakx_format(headers)

        if speakx:
            logger.info(
                "Detected SpeakX CSV format",
                columns=len(headers),
            )

        for i, raw_row in enumerate(reader, start=2):
            if i - 1 > MAX_ROW_COUNT:
                errors.append(
                    f"CSV exceeds max {MAX_ROW_COUNT} rows"
                )
                break
            try:
                if speakx:
                    task_dicts = _transform_speakx_row(raw_row)
                    for td in task_dicts:
                        rows.append(CSVRow(**td))
                else:
                    cleaned = {
                        k.strip().lower().replace(" ", "_"): (
                            v.strip()[:MAX_CELL_LENGTH]
                            if v
                            else v
                        )
                        for k, v in raw_row.items()
                    }
                    int_fields = [
                        "chapter_number",
                        "quest_number",
                        "activity_number",
                        "lesson_number",
                        "task_number",
                    ]
                    for field in int_fields:
                        if field in cleaned and cleaned[field]:
                            cleaned[field] = int(
                                cleaned[field],
                            )
                    rows.append(CSVRow(**cleaned))
            except (
                ValidationError,
                ValueError,
                TypeError,
            ) as exc:
                errors.append(f"Row {i}: {exc}")
    except csv.Error as exc:
        errors.append(f"CSV parsing error: {exc}")

    if not rows and not errors:
        errors.append(
            "CSV file is empty or has no data rows"
        )

    return rows, errors


def _is_speakx_format(headers: list[str]) -> bool:
    """Detect SpeakX nested CSV format by checking for admin-code columns."""
    normalized = {h.strip().lower() for h in headers}
    return "journeyid" in normalized and "admincode" in normalized


def _extract_number_from_code(code: str) -> int:
    """Extract trailing number from an admin code segment.

    Examples: 'J1_C01' → 1, 'J1_C01_Q03' → 3, 'J1_C01_Q01_A12' → 12
    """
    parts = code.strip().split("_")
    if not parts:
        return 1
    last = parts[-1]
    match = _ADMIN_CODE_NUM_RE.match(last)
    if match:
        return int(match.group(1))
    return 1


def _safe_get(row: dict[str, str], key: str) -> str:
    """Get a trimmed, truncated value from a CSV row."""
    val = row.get(key, "")
    if val is None:
        return ""
    return val.strip()[:MAX_CELL_LENGTH]


def _transform_speakx_row(raw_row: dict[str, str]) -> list[dict]:
    """Transform a SpeakX CSV row (one lesson, embedded tasks) into CSVRow dicts.

    Each SpeakX row represents one lesson with up to 3 embedded tasks.
    This function expands it into one CSVRow-compatible dict per task.
    """
    chapter_id = _safe_get(raw_row, "chapterID") or "C01"
    quest_id = _safe_get(raw_row, "questId") or "Q01"
    admin_code = _safe_get(raw_row, "adminCode") or "A01"
    lesson_code = _safe_get(raw_row, "lesson/adminCode") or "L01"
    activity_title = (
        _safe_get(raw_row, "activityTitle/En")
        or _safe_get(raw_row, "activityTitle/Hi")
    )

    base: dict = {
        "journey_name": _safe_get(raw_row, "journeyTitle"),
        "chapter_name": _safe_get(raw_row, "chapterTitle"),
        "chapter_number": _extract_number_from_code(chapter_id),
        "quest_name": (
            _safe_get(raw_row, "questTitle/En")
            or _safe_get(raw_row, "questTitle/Hi")
        ),
        "quest_number": _extract_number_from_code(quest_id),
        "activity_name": activity_title,
        "activity_number": _extract_number_from_code(admin_code),
        "activity_type": _safe_get(raw_row, "questType") or None,
        "lesson_name": activity_title,
        "lesson_number": _extract_number_from_code(lesson_code),
    }

    results: list[dict] = []
    for i in range(3):
        task_key = f"lesson/tasks/{i}/task"
        task_name = _safe_get(raw_row, task_key)
        if task_name and task_name.upper() != "NA":
            mandatory_key = f"lesson/tasks/{i}/isMandatory"
            is_mandatory = (
                _safe_get(raw_row, mandatory_key).upper() == "TRUE"
            )
            results.append({
                **base,
                "task_name": task_name,
                "task_number": i + 1,
                "task_type": (
                    "mandatory" if is_mandatory else "optional"
                ),
            })

    if not results:
        results.append({
            **base,
            "task_name": activity_title or "Untitled Task",
            "task_number": 1,
            "task_type": None,
        })

    return results


def _decode_content(content: bytes) -> str | None:
    """Attempt to decode bytes using a fallback encoding chain."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    return None


def build_journey_hierarchy(rows: list[CSVRow]) -> JourneyStructure:
    """Build a nested JourneyStructure tree from flat CSV rows."""
    if not rows:
        return JourneyStructure(name="Unknown")

    journey_name = rows[0].journey_name
    chapters: dict[int, ChapterStructure] = {}
    seen_keys: set[tuple[int, int, int, int, int]] = set()

    for row in rows:
        key = (
            row.chapter_number, row.quest_number, row.activity_number,
            row.lesson_number, row.task_number,
        )
        if key in seen_keys:
            logger.warning(
                "Duplicate row detected, skipping",
                journey_name=journey_name,
                key=key,
            )
            continue
        seen_keys.add(key)

        if row.chapter_number not in chapters:
            chapters[row.chapter_number] = ChapterStructure(
                name=row.chapter_name,
                chapter_number=row.chapter_number,
            )
        chapter = chapters[row.chapter_number]

        quest = _get_or_create_quest(chapter, row.quest_number, row.quest_name)
        activity = _get_or_create_activity(quest, row.activity_number, row.activity_name, row.activity_type)
        lesson = _get_or_create_lesson(activity, row.lesson_number, row.lesson_name)

        lesson.tasks.append(TaskStructure(
            name=row.task_name,
            task_number=row.task_number,
            task_type=row.task_type,
        ))

    sorted_chapters = [chapters[k] for k in sorted(chapters.keys())]
    return JourneyStructure(name=journey_name, chapters=sorted_chapters)


def _get_or_create_quest(chapter: ChapterStructure, number: int, name: str) -> QuestStructure:
    for quest in chapter.quests:
        if quest.quest_number == number:
            return quest
    quest = QuestStructure(name=name, quest_number=number)
    chapter.quests.append(quest)
    return quest


def _get_or_create_activity(
    quest: QuestStructure, number: int, name: str, activity_type: str | None,
) -> ActivityStructure:
    for activity in quest.activities:
        if activity.activity_number == number:
            return activity
    activity = ActivityStructure(name=name, activity_number=number, activity_type=activity_type)
    quest.activities.append(activity)
    return activity


def _get_or_create_lesson(activity: ActivityStructure, number: int, name: str) -> LessonStructure:
    for lesson in activity.lessons:
        if lesson.lesson_number == number:
            return lesson
    lesson = LessonStructure(name=name, lesson_number=number)
    activity.lessons.append(lesson)
    return lesson
