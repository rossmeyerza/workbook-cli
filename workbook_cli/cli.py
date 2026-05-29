from __future__ import annotations

import argparse
import json
import sys

from . import config
from .auth import clear_auth_state
from .client import WorkbookClient
from .dates import week_dates, week_start
from .jobs import fetch_jobs_with_tasks, load_jobs_cache, save_jobs_cache, search_jobs
from .jsonio import print_json, read_json_arg
from .timesheet import submit_entries, summarize_week


def _client(*, headless: bool = True, force: bool = False) -> WorkbookClient:
    client = WorkbookClient()
    if not client.login(headless=headless, force=force):
        raise RuntimeError("Workbook authentication failed")
    return client


def cmd_auth(args: argparse.Namespace) -> None:
    command = args.auth_command or "login"
    if command == "clear":
        clear_auth_state()
        print_json({"ok": True, "cleared": True}, pretty=args.pretty)
        return

    if command == "status":
        client = WorkbookClient()
        ok = client.login(headless=True, force=False)
        print_json({
            "ok": ok,
            "user": client.me() if ok else None,
            "cookies_file": str(config.COOKIES_FILE),
            "browser_state_file": str(config.BROWSER_STATE_FILE),
        }, pretty=args.pretty)
        return

    client = _client(headless=not args.headed, force=args.force)
    print_json({"ok": True, "user": client.me()}, pretty=args.pretty)


def cmd_me(args: argparse.Namespace) -> None:
    print_json(_client().me(), pretty=args.pretty)


def _jobs_for_args(args: argparse.Namespace, client: WorkbookClient) -> list[dict]:
    if args.refresh:
        jobs = fetch_jobs_with_tasks(client, week_dates(args.week_offset)["Mon"])
        save_jobs_cache(jobs)
        return jobs
    cache = load_jobs_cache()
    if cache and isinstance(cache.get("jobs"), list):
        return cache["jobs"]
    jobs = fetch_jobs_with_tasks(client, week_dates(args.week_offset)["Mon"])
    save_jobs_cache(jobs)
    return jobs


def cmd_jobs(args: argparse.Namespace) -> None:
    client = _client()
    if args.jobs_command == "tasks":
        tasks = client.get_tasks_for_job(args.job_id)
        print_json({
            "job_id": args.job_id,
            "tasks": [
                {"task_id": task.get("Id"), "task_name": task.get("TaskName", "")}
                for task in tasks
            ],
        }, pretty=args.pretty)
        return

    if args.jobs_command == "refresh":
        jobs = fetch_jobs_with_tasks(client, week_dates(args.week_offset)["Mon"])
        save_jobs_cache(jobs)
        print_json({"ok": True, "count": len(jobs), "cache_file": str(config.JOBS_CACHE_FILE)}, pretty=args.pretty)
        return

    jobs = _jobs_for_args(args, client)
    if args.jobs_command == "search":
        jobs = search_jobs(jobs, args.query)
    print_json({"count": len(jobs), "jobs": jobs}, pretty=args.pretty)


def cmd_timesheet(args: argparse.Namespace) -> None:
    client = _client()
    if args.timesheet_command == "show":
        print_json(summarize_week(client, args.week_offset), pretty=args.pretty)
        return

    payload = read_json_arg(args.json, args.json_file)
    result = submit_entries(
        client,
        payload,
        week_offset=args.week_offset,
        dry_run=args.dry_run,
        separate_rows=args.separate_rows,
    )
    print_json(result, pretty=args.pretty)
    if not result["ok"]:
        raise SystemExit(1)


def cmd_config(args: argparse.Namespace) -> None:
    if args.config_command == "paths":
        print_json({
            "config_file": str(config.CONFIG_FILE),
            "data_dir": str(config.DATA_DIR),
            "cookies_file": str(config.COOKIES_FILE),
            "browser_state_file": str(config.BROWSER_STATE_FILE),
            "jobs_cache_file": str(config.JOBS_CACHE_FILE),
        }, pretty=args.pretty)
        return

    config.ensure_dirs()
    if config.CONFIG_FILE.exists() and not args.force:
        print_json({"ok": False, "error": f"{config.CONFIG_FILE} already exists; use --force"}, pretty=args.pretty)
        raise SystemExit(1)
    content = (
        f"WORKBOOK_URL={args.url}\n"
        f"WORKBOOK_EMAIL={args.email}\n"
        f"WORKBOOK_PASSWORD={args.password}\n"
    )
    config.CONFIG_FILE.write_text(content)
    config.CONFIG_FILE.chmod(0o600)
    print_json({"ok": True, "config_file": str(config.CONFIG_FILE)}, pretty=args.pretty)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workbook-cli", description="Agent-friendly Workbook timesheet CLI")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    sub = parser.add_subparsers(dest="domain", required=True)

    p_auth = sub.add_parser("auth", help="Manage Workbook authentication")
    p_auth.add_argument("auth_command", nargs="?", choices=["login", "status", "clear"], default="login")
    p_auth.add_argument("--headed", action="store_true", help="Use a visible browser")
    p_auth.add_argument("--force", action="store_true", help="Force browser login")
    p_auth.set_defaults(func=cmd_auth)

    p_me = sub.add_parser("me", help="Show current Workbook user")
    p_me.set_defaults(func=cmd_me)

    p_jobs = sub.add_parser("jobs", help="Search Workbook jobs and tasks")
    p_jobs.add_argument("--week-offset", type=int, default=0)
    p_jobs.add_argument("--refresh", action="store_true", help="Refresh job cache first")
    jobs_sub = p_jobs.add_subparsers(dest="jobs_command", required=True)
    p_jobs_list = jobs_sub.add_parser("list", help="List cached jobs")
    p_jobs_list.set_defaults(func=cmd_jobs)
    p_jobs_search = jobs_sub.add_parser("search", help="Search jobs/tasks")
    p_jobs_search.add_argument("query")
    p_jobs_search.set_defaults(func=cmd_jobs)
    p_jobs_tasks = jobs_sub.add_parser("tasks", help="List tasks for a job")
    p_jobs_tasks.add_argument("job_id", type=int)
    p_jobs_tasks.set_defaults(func=cmd_jobs)
    p_jobs_refresh = jobs_sub.add_parser("refresh", help="Refresh job/task cache")
    p_jobs_refresh.set_defaults(func=cmd_jobs)

    p_ts = sub.add_parser("timesheet", help="Show or submit timesheets")
    p_ts.add_argument("--week-offset", type=int, default=0)
    ts_sub = p_ts.add_subparsers(dest="timesheet_command", required=True)
    p_ts_show = ts_sub.add_parser("show", help="Show a week")
    p_ts_show.set_defaults(func=cmd_timesheet)
    p_ts_submit = ts_sub.add_parser("submit", help="Submit JSON timesheet entries")
    p_ts_submit.add_argument("--json", help="JSON array payload, or '-' for stdin")
    p_ts_submit.add_argument("--json-file", help="Read JSON array payload from a file")
    p_ts_submit.add_argument("--dry-run", action="store_true", help="Plan changes without writing")
    p_ts_submit.add_argument("--separate-rows", action="store_true", help="Always create new Workbook rows")
    p_ts_submit.set_defaults(func=cmd_timesheet)

    p_config = sub.add_parser("config", help="Manage local configuration")
    cfg_sub = p_config.add_subparsers(dest="config_command", required=True)
    p_cfg_paths = cfg_sub.add_parser("paths", help="Show state/config paths")
    p_cfg_paths.set_defaults(func=cmd_config)
    p_cfg_init = cfg_sub.add_parser("init", help="Write ~/.config/workbook-cli/.env")
    p_cfg_init.add_argument("--url", default=config.WORKBOOK_URL)
    p_cfg_init.add_argument("--email", required=True)
    p_cfg_init.add_argument("--password", required=True)
    p_cfg_init.add_argument("--force", action="store_true")
    p_cfg_init.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except json.JSONDecodeError as exc:
        print_json({"ok": False, "error": f"invalid JSON: {exc}"})
        return 2
    except Exception as exc:
        print_json({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
