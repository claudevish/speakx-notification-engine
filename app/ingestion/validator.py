from app.ingestion.schemas import JourneyStructure

REQUIRED_COLUMNS = [
    "journey_name", "chapter_name", "chapter_number",
    "quest_name", "quest_number", "activity_name",
    "activity_number", "lesson_name", "lesson_number",
    "task_name", "task_number",
]


def validate_csv_columns(headers: list[str]) -> list[str]:
    normalized = [h.strip().lower().replace(" ", "_") for h in headers]
    return [col for col in REQUIRED_COLUMNS if col not in normalized]


def validate_journey_structure(structure: JourneyStructure) -> list[str]:
    errors: list[str] = []

    if not structure.chapters:
        errors.append("Journey has no chapters")
        return errors

    chapter_numbers = [ch.chapter_number for ch in structure.chapters]
    expected = list(range(1, len(chapter_numbers) + 1))
    if sorted(chapter_numbers) != expected:
        errors.append(
            f"Chapter numbers not sequential: got {sorted(chapter_numbers)}, expected {expected}"
        )

    chapter_names: set[str] = set()
    for chapter in structure.chapters:
        if chapter.name in chapter_names:
            errors.append(f"Duplicate chapter name: '{chapter.name}'")
        chapter_names.add(chapter.name)

        if not chapter.quests:
            errors.append(f"Chapter '{chapter.name}' has no quests")
            continue

        quest_numbers = [q.quest_number for q in chapter.quests]
        expected_quests = list(range(1, len(quest_numbers) + 1))
        if sorted(quest_numbers) != expected_quests:
            errors.append(
                f"Quest numbers in chapter '{chapter.name}' not sequential: "
                f"got {sorted(quest_numbers)}, expected {expected_quests}"
            )

        quest_names: set[str] = set()
        for quest in chapter.quests:
            if quest.name in quest_names:
                errors.append(f"Duplicate quest name in chapter '{chapter.name}': '{quest.name}'")
            quest_names.add(quest.name)

            if not quest.activities:
                errors.append(f"Quest '{quest.name}' in chapter '{chapter.name}' has no activities")

    return errors
