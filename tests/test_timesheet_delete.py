from unittest.mock import Mock

import pytest

from workbook_cli.client import WorkbookClient
from workbook_cli.timesheet import clear_entry


ENTRY = {
    "Id": 123, "JobId": 345, "TaskId": 678, "Hours": 2, "Description": "Work",
    "ActivityId": 777, "Billable": False,
}


def test_delete_previews_without_writing():
    client = Mock()
    client.get_daily_entries.return_value = [ENTRY]
    result = clear_entry(client, 123)
    assert result["status"] == "preview" and result["dry_run"]
    assert result["previous_hours"] == 2 and result["hours"] == 0
    client.update_time_entry.assert_not_called()


@pytest.mark.parametrize("readback, status", [([{**ENTRY, "Hours": 0}], "zeroed"), ([], "not_returned")])
def test_delete_updates_only_the_exact_id_and_verifies(readback, status):
    client = Mock()
    client.get_daily_entries.side_effect = [[{**ENTRY, "Id": 124}, ENTRY], readback]
    assert clear_entry(client, 123, confirm=True)["status"] == status
    client.update_time_entry.assert_called_once_with(
        entry_id=123, hours=0, task_id=678, description="Work", activity_id=777, billable=False,
    )
    assert client.get_daily_entries.call_count == 2


@pytest.mark.parametrize("rows", [[], [ENTRY, ENTRY], [{"Id": 123, "Hours": 2}]])
def test_delete_refuses_missing_duplicate_or_incomplete_entry(rows):
    client = Mock()
    client.get_daily_entries.return_value = rows
    with pytest.raises(ValueError):
        clear_entry(client, 123, confirm=True)
    client.update_time_entry.assert_not_called()


def test_delete_does_not_retry_when_workbook_keeps_the_hours():
    client = Mock()
    client.get_daily_entries.return_value = [ENTRY]
    with pytest.raises(RuntimeError, match="did not confirm zero hours"):
        clear_entry(client, 123, confirm=True)
    assert client.update_time_entry.call_count == 1


def test_client_sends_numeric_zero_not_null(monkeypatch):
    client = WorkbookClient()
    post = Mock()
    monkeypatch.setattr(client, "_mutating_post", post)
    client.update_time_entry(entry_id=123, hours=0, task_id=678, description="Work")
    payload = post.call_args.args[1]
    assert payload["Hours"] == 0
