import pytest

from workbook_cli.timesheet import validate_entries


def test_validate_entries_accepts_day_hours() -> None:
    entries = validate_entries([{
        "job_id": 1,
        "task_id": 2,
        "description": "Work",
        "hours": {"Mon": 1, "Wed": 2.5},
    }])

    assert entries[0]["job_id"] == 1
    assert entries[0]["task_id"] == 2
    assert entries[0]["hours"]["Mon"] == 1
    assert entries[0]["hours"]["Tue"] == 0


def test_validate_entries_expands_numeric_hours() -> None:
    entries = validate_entries([{"job_id": 1, "task_id": 2, "hours": 1.5}])

    assert entries[0]["hours"] == {
        "Mon": 1.5,
        "Tue": 1.5,
        "Wed": 1.5,
        "Thu": 1.5,
        "Fri": 1.5,
    }


def test_validate_entries_requires_array() -> None:
    with pytest.raises(ValueError, match="JSON array"):
        validate_entries({"job_id": 1})
