"""Local stdio MCP adapter for the Workbook CLI."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from subprocess import PIPE

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server


@dataclass(frozen=True)
class Command:
    path: tuple[str, ...]
    description: str
    properties: dict = field(default_factory=dict)
    required: tuple[str, ...] = ()
    read_only: bool = False


def param(kind: str, description: str, **kwargs) -> dict:
    return {"type": kind, "description": description, **kwargs}


WEEK = {"week_offset": param("integer", "Weeks from the current week.", default=0)}
JOBS = {**WEEK, "refresh": param("boolean", "Refresh the job cache first.", default=False)}
CONFIRM = param("boolean", "Set to true only after explicit user approval.", default=False)
OUTPUT = {
    "format": param("string", "Output format (the CLI's --json or --table).",
                    enum=["json", "table"], default="json"),
    "pretty": param("boolean", "Indent the JSON text.", default=False),
}
COMMANDS = {
    "_".join(command.path): command for command in (
        Command(("auth", "login"), "Sign in to Workbook and save the session. Use a visible browser for MFA.", {
            "headed": param("boolean", "Use a visible browser.", default=False),
            "force": param("boolean", "Sign in again even if the saved session works.", default=False),
            "debug_auth": param("boolean", "Save local browser trace and snapshots.", default=False),
        }),
        Command(("auth", "status"), "Check the saved Workbook session without a browser.", read_only=True),
        Command(("auth", "clear"), "Delete the local Workbook session files. Requires confirmation.",
                {"confirm": CONFIRM}),
        Command(("me",), "Show the current Workbook user.", read_only=True),
        Command(("jobs", "list"), "List jobs and tasks from the cache. Fetch them if the cache is empty.", JOBS),
        Command(("jobs", "search"), "Search Workbook jobs and tasks by name or number.", {
            **JOBS, "query": param("string", "Job or task search text."),
        }, ("query",)),
        Command(("jobs", "tasks"), "List tasks for a Workbook job.", {
            "job_id": param("integer", "Workbook job ID."),
        }, ("job_id",), read_only=True),
        Command(("jobs", "refresh"), "Fetch jobs and tasks from Workbook and update the local cache.", WEEK),
        Command(("timesheet", "show"), "Show Workbook timesheet entries for a week.", WEEK, read_only=True),
        Command(("timesheet", "submit"),
                "Preview, submit or resume Workbook timesheet entries. Live submissions and resumes require confirmation.", {
            **WEEK,
            "input_json": {
                "description": "Batch of entries with job_id, task_id and hours. Use an array or JSON text.",
                "anyOf": [{"type": "array", "items": {"type": "object"}}, {"type": "string"}],
            },
            "json_file": param("string", "Read the batch from this local JSON file."),
            "dry_run": param("boolean", "Preview the changes without writing to Workbook.", default=False),
            "separate_rows": param("boolean", "Create new Workbook rows instead of reusing rows.", default=False),
            "journal": param("string", "Local path for the submission journal."),
            "resume": param("string", "Local journal for an incomplete submission."),
            "confirm": CONFIRM,
        }),
        Command(("timesheet", "delete"),
                "Set one existing timesheet entry to zero hours. Preview unless the user approves the update.", {
            **WEEK,
            "entry_id": param("integer", "Entry ID from timesheet_show.", minimum=1),
            "confirm": CONFIRM,
        }, ("entry_id",)),
        Command(("config", "paths"), "Show local Workbook config and state paths.", read_only=True),
        Command(("config", "init"),
                "Write local Workbook config. Requires confirmation and WORKBOOK_MCP_PASSWORD in the server environment.", {
            "email": param("string", "Workbook account email.", minLength=1),
            "url": param("string", "Workbook URL. Omit to use the current CLI default."),
            "force": param("boolean", "Replace the config file if it exists.", default=False),
            "confirm": CONFIRM,
        }, ("email",)),
    )
}

# A new CLI process reads the latest config on every call. Pass arguments through
# a pipe so that credentials and descriptions do not appear in the process list.
_CLI_WORKER = "import json,sys; from workbook_cli.cli import main; sys.exit(main(json.load(sys.stdin)))"


def build_argv(name: str, arguments: dict) -> list[str]:
    command = COMMANDS[name]
    args = dict(arguments)
    confirmation_needed = name in {"auth_clear", "config_init"} or (
        name == "timesheet_submit" and (not args.get("dry_run") or args.get("resume"))
    )
    if name != "timesheet_delete" and not args.pop("confirm", False) and confirmation_needed:
        raise ValueError("Explicit user approval is required. Set confirm=true after approval.")

    if name == "timesheet_submit":
        if args.get("input_json") == "-":
            raise ValueError("Pass an array or JSON text in input_json. MCP does not use '-' for batch input.")
        if isinstance(args.get("input_json"), list):
            args["input_json"] = json.dumps(args["input_json"])
        if args.get("resume") and any(args.get(key) for key in (
            "input_json", "json_file", "dry_run", "separate_rows",
        )):
            raise ValueError("Do not combine resume with input_json, json_file, dry_run or separate_rows.")
        if not any(args.get(key) for key in ("resume", "input_json", "json_file")):
            raise ValueError("Provide input_json, json_file or resume.")

    if name == "config_init":
        password = os.environ.get("WORKBOOK_MCP_PASSWORD")
        if not password:
            raise ValueError("Set WORKBOOK_MCP_PASSWORD in the server environment, or use the CLI to configure Workbook.")
        args["password"] = password
        if any("\r" in args.get(key, "") or "\n" in args.get(key, "") for key in ("email", "password", "url")):
            raise ValueError("Config values cannot contain line breaks.")

    argv = [command.path[0]]
    for key in ("week_offset", "refresh"):
        if key in args:
            argv.extend(_option(key, args.pop(key)))
    argv.extend(command.path[1:])
    positional = {"jobs_search": "query", "jobs_tasks": "job_id", "timesheet_delete": "entry_id"}.get(name)
    for key, value in args.items():
        if key != positional:
            argv.extend(_option(key, value))
    if positional:
        argv.extend(["--", str(args[positional])])
    return argv


def _option(key: str, value: str | int | bool) -> list[str]:
    flag = "--" + key.replace("_", "-")
    if isinstance(value, bool):
        return [flag] if value else []
    return [f"{flag}={value}"]


async def run_cli(argv: list[str]) -> types.CallToolResult:
    env = {key: value for key, value in os.environ.items() if key != "WORKBOOK_MCP_PASSWORD"}
    process = await anyio.run_process(
        [sys.executable, "-I", "-c", _CLI_WORKER], input=json.dumps(argv).encode(), stdout=PIPE, stderr=None,
        check=False, env=env,
    )
    output = process.stdout.decode().strip()
    try:
        data = json.loads(output)
    except ValueError:
        data = None
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=output or (
            f"Workbook CLI exited with status {process.returncode}. Check the server's stderr for diagnostics."
        ))],
        structuredContent=data if isinstance(data, dict) else None,
        isError=process.returncode != 0,
    )


def create_server() -> Server:
    server = Server("workbook", instructions=(
        "Use Workbook tools to inspect jobs and timesheets. Preview a submission with dry_run=true. "
        "Set confirm=true for live changes only after explicit user approval. Never guess job or task IDs."
    ))
    # Calls on one server share the CLI's local session, cache and journals.
    lock = anyio.Lock()

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(
            name=name, description=command.description,
            inputSchema={"type": "object", "properties": {**command.properties, **OUTPUT},
                         "required": list(command.required), "additionalProperties": False},
            annotations=types.ToolAnnotations(readOnlyHint=command.read_only,
                                              destructiveHint=True if name == "timesheet_delete" else None),
        ) for name, command in COMMANDS.items()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
        argv = build_argv(name, arguments)
        async with lock:
            return await run_cli(argv)

    return server


async def serve() -> None:
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    anyio.run(serve)


if __name__ == "__main__":
    main()
