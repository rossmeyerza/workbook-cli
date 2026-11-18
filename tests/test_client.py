import pytest

from workbook_cli import config
from workbook_cli.client import WorkbookAPIError, WorkbookClient


class FakeResponse:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data
        self.ok = 200 <= status < 400

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, response):
        self.response = response

    def post(self, *_args, **_kwargs):
        return self.response


def test_mutation_decodes_workbook_error_and_logs_safely(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    client = WorkbookClient()
    client.resource_id = 8092
    client.session = FakeSession(FakeResponse(400, {
        "ResponseStatus": {"Message": "Task is required for Secret description"},
    }))

    with pytest.raises(WorkbookAPIError, match="Task is required") as caught:
        client.update_time_entry(
            entry_id=12,
            hours=1,
            task_id=None,
            description="Secret description",
        )

    assert caught.value.may_have_succeeded is False
    log = next(tmp_path.glob("mutation_*.json")).read_text()
    assert "Secret description" not in log
    assert '"description_length": 18' in log


def test_server_error_is_treated_as_uncertain(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    client = WorkbookClient()
    client.resource_id = 8092
    client.session = FakeSession(FakeResponse(500, {}))
    with pytest.raises(WorkbookAPIError) as caught:
        client.quick_insert(job_id=1, task_id=None, date="2026-09-07")
    assert caught.value.may_have_succeeded is True
