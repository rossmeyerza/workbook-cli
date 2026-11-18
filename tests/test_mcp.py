import argparse
import json
import os
import sys

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from workbook_cli.cli import build_parser
from workbook_cli.mcp import COMMANDS, build_argv


def _cli_commands(parser, path=()):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from _cli_commands(sub, (*path, name))
            return
        if action.dest == "auth_command":
            yield from ((*path, name) for name in action.choices)
            return
    yield path


def test_all_cli_commands_have_one_tool():
    assert sorted(command.path for command in COMMANDS.values()) == sorted(_cli_commands(build_parser()))


@pytest.mark.parametrize("name, arguments", [
    ("auth_login", {"headed": True, "force": True, "debug_auth": True}),
    ("auth_status", {}),
    ("auth_clear", {"confirm": True}),
    ("me", {"format": "table"}),
    ("jobs_list", {"refresh": True, "week_offset": -1}),
    ("jobs_search", {"query": "--refresh", "pretty": True}),
    ("jobs_tasks", {"job_id": 123}),
    ("jobs_refresh", {"week_offset": -2}),
    ("timesheet_show", {"week_offset": 1}),
    ("timesheet_delete", {"entry_id": 123, "week_offset": -1}),
    ("timesheet_delete", {"entry_id": 123, "confirm": True}),
    ("timesheet_submit", {"input_json": [{"job_id": 123}], "dry_run": True, "separate_rows": True}),
    ("timesheet_submit", {"json_file": "/tmp/batch.json", "journal": "my journal.json", "confirm": True}),
    ("timesheet_submit", {"resume": "my journal.json", "confirm": True}),
    ("config_paths", {}),
    ("config_init", {"email": "test@example.test", "url": "https://example.test", "force": True, "confirm": True}),
])
def test_arguments_match_cli(name, arguments, monkeypatch):
    monkeypatch.setenv("WORKBOOK_MCP_PASSWORD", "test-placeholder")
    parsed = vars(build_parser().parse_args(build_argv(name, arguments)))
    command = COMMANDS[name].path
    if name == "timesheet_delete":
        assert parsed["confirm"] is arguments.get("confirm", False)
    assert parsed["domain"] == command[0]
    if len(command) == 2:
        assert parsed[f"{command[0]}_command"] == command[1]
    for key, expected in arguments.items():
        if key != "confirm" or name == "timesheet_delete":
            actual = parsed[key]
            assert (json.loads(actual) if isinstance(expected, list) else actual) == expected


@pytest.mark.parametrize("name, arguments", [
    ("auth_clear", {}),
    ("config_init", {"email": "test@example.test"}),
    ("timesheet_submit", {"input_json": []}),
    ("timesheet_submit", {"resume": "my journal.json"}),
])
def test_sensitive_calls_require_confirmation(name, arguments):
    with pytest.raises(ValueError, match="approval"):
        build_argv(name, arguments)


def test_stdio_parity_and_error_results(tmp_path):
    cache = tmp_path / "data" / "workbook-cli" / "cache" / "jobs.json"
    cache.parent.mkdir(parents=True)
    job = {"job_id": 123, "job_name": "Sample job", "customer": "", "project": "", "tasks": []}
    cache.write_text(json.dumps({"jobs": [job]}))
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_DATA_HOME": str(tmp_path / "data"),
           "WORKBOOK_MCP_PASSWORD": "test-placeholder"}

    async def check():
        params = StdioServerParameters(command=sys.executable, args=["-m", "workbook_cli.mcp"], env=env)
        async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
            await session.initialize()
            assert {tool.name for tool in (await session.list_tools()).tools} == set(COMMANDS)
            search = await session.call_tool("jobs_search", {"query": "123"})
            assert not search.isError
            assert search.structuredContent == {"count": 1, "jobs": [job]}
            assert json.loads(search.content[0].text) == search.structuredContent
            table = await session.call_tool("jobs_list", {"format": "table"})
            assert not table.isError and "Sample job" in table.content[0].text
            assert table.structuredContent is None
            denied = await session.call_tool("timesheet_submit", {"input_json": [job]})
            assert denied.isError and "approval" in denied.content[0].text
            invalid = await session.call_tool("jobs_list", {"unrecognised": True})
            assert invalid.isError
            args = {"email": "test@example.test", "confirm": True}
            config = await session.call_tool("config_init", args)
            assert not config.isError and config.structuredContent["ok"]
            assert "test-placeholder" not in config.content[0].text
            existing = await session.call_tool("config_init", args)
            assert existing.isError and not existing.structuredContent["ok"]

    anyio.run(check)
