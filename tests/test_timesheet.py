import json

import pytest

from workbook_cli.timesheet import resume_submission, submit_entries, validate_entries


DATES = {
    "Mon": "2026-09-07",
    "Tue": "2026-09-08",
    "Wed": "2026-09-09",
    "Thu": "2026-09-10",
    "Fri": "2026-09-11",
}


class FakeClient:
    def __init__(self, entries=None) -> None:
        self.resource_id = 8092
        self.entries = list(entries or [])
        self.reads = 0
        self.inserts = 0
        self.updates = 0

    def get_daily_entries(self, _date):
        self.reads += 1
        return [dict(entry) for entry in self.entries]

    def quick_insert(self, *, job_id, task_id, date, check_week=True):
        self.inserts += 1
        entry_id = max([entry["Id"] for entry in self.entries] or [100]) + 1
        self.entries.append({
            "Id": entry_id,
            "JobId": job_id,
            "TaskId": task_id,
            "RegistrationDate": date,
            "Hours": None,
            "Description": "",
        })
        return {"Id": entry_id}

    def update_time_entry(self, *, entry_id, hours, task_id, description, activity_id, billable):
        self.updates += 1
        entry = next(row for row in self.entries if row["Id"] == entry_id)
        entry.update(Hours=hours, TaskId=task_id, Description=description)
        return {"Id": entry_id}


def payload(job_id=1, task_id=None, description="Work", hours=None):
    return [{
        "job_id": job_id,
        "task_id": task_id,
        "description": description,
        "hours": hours or {"Mon": 1},
    }]


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


@pytest.mark.parametrize("hours", [float("nan"), float("inf"), -1, True])
def test_validate_entries_rejects_invalid_hours(hours) -> None:
    with pytest.raises(ValueError):
        validate_entries(payload(hours={"Mon": hours}))


def test_validate_entries_rejects_unknown_day_and_bad_description() -> None:
    with pytest.raises(ValueError, match="unknown day"):
        validate_entries(payload(hours={"Sunday": 1}))
    with pytest.raises(ValueError, match="description must be text"):
        validate_entries([{"job_id": 1, "hours": 1, "description": 12}])


def test_validation_happens_before_any_client_read(tmp_path) -> None:
    client = FakeClient()
    with pytest.raises(ValueError):
        submit_entries(client, payload(hours={"Mon": float("nan")}), journal_path=tmp_path / "journal.json")
    assert client.reads == client.inserts == client.updates == 0


def test_known_tasked_job_requires_a_task_before_reads(tmp_path, monkeypatch) -> None:
    from workbook_cli import config

    cache = tmp_path / "jobs.json"
    cache.write_text(json.dumps({
        "jobs": [{"job_id": 101, "tasks": [{"task_id": 7, "task_name": "Delivery"}]}],
    }))
    monkeypatch.setattr(config, "JOBS_CACHE_FILE", cache)
    client = FakeClient()
    with pytest.raises(ValueError, match="requires a task_id"):
        submit_entries(
            client,
            payload(job_id=101),
            dates_override=DATES,
            journal_path=tmp_path / "journal.json",
        )
    assert client.reads == client.inserts == client.updates == 0


def test_taskless_jobs_are_matched_by_job_and_task(tmp_path) -> None:
    client = FakeClient([
        {"Id": 11, "JobId": 101, "TaskId": None, "RegistrationDate": DATES["Mon"], "Hours": 2, "Description": "A"},
        {"Id": 12, "JobId": 202, "TaskId": None, "RegistrationDate": DATES["Mon"], "Hours": 2, "Description": "B"},
    ])

    result = submit_entries(
        client,
        payload(job_id=202, description="Changed", hours={"Mon": 2}),
        dates_override=DATES,
        journal_path=tmp_path / "journal.json",
    )

    assert result["ok"] is True
    assert next(row for row in client.entries if row["Id"] == 11)["Description"] == "A"
    assert next(row for row in client.entries if row["Id"] == 12)["Description"] == "Changed"


def test_description_only_change_is_updated_and_verified(tmp_path) -> None:
    client = FakeClient([
        {"Id": 11, "JobId": 101, "TaskId": 7, "RegistrationDate": DATES["Mon"], "Hours": 1, "Description": "Old"},
    ])
    result = submit_entries(
        client,
        payload(job_id=101, task_id=7, description="New"),
        dates_override=DATES,
        journal_path=tmp_path / "journal.json",
    )
    assert result["ok"] is True
    assert result["updated"] == 1
    assert client.updates == 1


def test_ambiguous_existing_cells_are_not_changed(tmp_path) -> None:
    rows = [
        {"Id": entry_id, "JobId": 101, "TaskId": 7, "RegistrationDate": DATES["Mon"], "Hours": 1, "Description": "Old"}
        for entry_id in (11, 12)
    ]
    client = FakeClient(rows)
    result = submit_entries(
        client,
        payload(job_id=101, task_id=7),
        dates_override=DATES,
        journal_path=tmp_path / "journal.json",
    )
    assert result["ok"] is False
    assert "Multiple existing" in result["errors"][0]["error"]
    assert client.inserts == client.updates == 0


def test_resume_adopts_an_insert_after_response_is_lost(tmp_path) -> None:
    class LostInsertClient(FakeClient):
        def quick_insert(self, **kwargs):
            result = super().quick_insert(**kwargs)
            if self.inserts == 1:
                raise RuntimeError("connection ended")
            return result

    client = LostInsertClient()
    journal = tmp_path / "journal.json"
    first = submit_entries(client, payload(), dates_override=DATES, journal_path=journal)
    assert first["ok"] is False
    assert client.inserts == 1

    resumed = resume_submission(client, journal)
    assert resumed["ok"] is True
    assert resumed["resumed"] is True
    assert client.inserts == 1
    assert client.updates == 1


def test_resume_does_not_retry_an_unconfirmed_insert(tmp_path) -> None:
    class LostInsertClient(FakeClient):
        def quick_insert(self, **kwargs):
            self.inserts += 1
            raise RuntimeError("connection ended")

    client = LostInsertClient()
    journal = tmp_path / "journal.json"
    submit_entries(client, payload(), dates_override=DATES, journal_path=journal)
    resumed = resume_submission(client, journal)
    assert resumed["ok"] is False
    assert "not confirmed" in resumed["errors"][0]["error"]
    assert client.inserts == 1


def test_resume_confirms_update_after_response_is_lost(tmp_path) -> None:
    class LostUpdateClient(FakeClient):
        def update_time_entry(self, **kwargs):
            result = super().update_time_entry(**kwargs)
            if self.updates == 1:
                raise RuntimeError("connection ended")
            return result

    client = LostUpdateClient([
        {"Id": 11, "JobId": 101, "TaskId": 7, "RegistrationDate": DATES["Mon"], "Hours": 1, "Description": "Old"},
    ])
    journal = tmp_path / "journal.json"
    first = submit_entries(
        client,
        payload(job_id=101, task_id=7, description="New"),
        dates_override=DATES,
        journal_path=journal,
    )
    assert first["ok"] is False
    resumed = resume_submission(client, journal)
    assert resumed["ok"] is True
    assert client.updates == 1


def test_tampered_journal_is_rejected_before_reads(tmp_path) -> None:
    client = FakeClient()
    journal = tmp_path / "journal.json"
    first = submit_entries(client, payload(), dates_override=DATES, journal_path=journal)
    assert first["ok"] is True
    data = json.loads(journal.read_text())
    data["payload"][0]["job_id"] = 999
    journal.write_text(json.dumps(data))
    reads_before = client.reads
    with pytest.raises(ValueError, match="hash"):
        resume_submission(client, journal)
    assert client.reads == reads_before


def test_saved_entry_id_is_rechecked_before_update(tmp_path) -> None:
    client = FakeClient([
        {"Id": 11, "JobId": 101, "TaskId": 7, "RegistrationDate": DATES["Mon"], "Hours": 1, "Description": "Old"},
    ])
    journal = tmp_path / "journal.json"
    first = submit_entries(
        client,
        payload(job_id=101, task_id=7, description="New"),
        dates_override=DATES,
        journal_path=journal,
    )
    assert first["ok"] is True
    data = json.loads(journal.read_text())
    data["operations"][0].update(status="update_pending", entry_id=999)
    journal.write_text(json.dumps(data))
    updates_before = client.updates
    resumed = resume_submission(client, journal)
    assert resumed["ok"] is False
    assert "no longer matches" in resumed["errors"][0]["error"]
    assert client.updates == updates_before
