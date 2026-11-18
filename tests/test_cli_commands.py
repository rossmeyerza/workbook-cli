import json
from argparse import Namespace

from workbook_cli import cli


def test_auth_status_does_not_start_browser(monkeypatch, capsys) -> None:
    class FakeClient:
        last_error = "Session expired"

        def login_saved(self):
            return False

        def login(self, **_kwargs):
            raise AssertionError("status must not start login")

        def browser_status(self):
            return {"installed": True, "executable": "/browser"}

    monkeypatch.setattr(cli, "WorkbookClient", FakeClient)
    args = Namespace(auth_command="status", format="json", pretty=False)
    cli.cmd_auth(args)
    assert json.loads(capsys.readouterr().out)["authenticated"] is False


def test_cached_job_search_does_not_authenticate(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_jobs_cache", lambda: {
        "jobs": [{"job_id": 497719, "job_name": "Example", "customer": "", "project": "", "tasks": []}],
    })
    monkeypatch.setattr(cli, "_client", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not authenticate")))
    args = Namespace(
        jobs_command="search",
        query="497719",
        refresh=False,
        week_offset=0,
        format="json",
        pretty=False,
    )
    cli.cmd_jobs(args)
    assert json.loads(capsys.readouterr().out)["jobs"][0]["job_id"] == 497719
