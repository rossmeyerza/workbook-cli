from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import config
from .jsonio import print_json

console = Console()


def write_output(data: Any, *, args, renderer=None) -> None:
    if getattr(args, "format", "json") == "json":
        print_json(data, pretty=getattr(args, "pretty", False))
        return
    if renderer:
        renderer(data)
        return
    render_generic(data)


def render_generic(data: Any) -> None:
    console.print(data)


def render_auth(data: dict) -> None:
    status = "[green]OK[/]" if data.get("ok") else "[red]Failed[/]"
    user = data.get("user") or {}
    lines = [f"[bold]Status:[/] {status}"]
    if user:
        lines.append(f"[bold]User:[/] {user.get('name') or '-'}")
        lines.append(f"[bold]Resource ID:[/] {user.get('resource_id') or '-'}")
    if data.get("cookies_file"):
        lines.append(f"[bold]Cookies:[/] {data['cookies_file']}")
    console.print(Panel("\n".join(lines), title="Workbook Auth", border_style="cyan"))


def render_me(data: dict) -> None:
    table = Table(title="Workbook User")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Name", str(data.get("name") or "-"))
    table.add_row("Resource ID", str(data.get("resource_id") or "-"))
    console.print(table)


def render_jobs(data: dict) -> None:
    jobs = data.get("jobs", [])
    table = Table(title=f"Workbook Jobs ({len(jobs)})")
    table.add_column("Job ID", justify="right", style="cyan")
    table.add_column("Customer")
    table.add_column("Project")
    table.add_column("Job")
    table.add_column("Tasks", justify="right")

    for job in jobs:
        table.add_row(
            str(job.get("job_id") or ""),
            job.get("customer") or "",
            job.get("project") or "",
            job.get("job_name") or "",
            str(len(job.get("tasks") or [])),
        )
    console.print(table)


def render_tasks(data: dict) -> None:
    tasks = data.get("tasks", [])
    table = Table(title=f"Tasks for Job {data.get('job_id')} ({len(tasks)})")
    table.add_column("Task ID", justify="right", style="cyan")
    table.add_column("Task")
    for task in tasks:
        table.add_row(str(task.get("task_id") or ""), task.get("task_name") or "")
    console.print(table)


def render_refresh(data: dict) -> None:
    console.print(Panel(
        f"[bold]Jobs cached:[/] {data.get('count', 0)}\n"
        f"[bold]Cache file:[/] {data.get('cache_file', '-')}",
        title="Workbook Cache",
        border_style="green" if data.get("ok") else "red",
    ))


def render_timesheet(data: dict) -> None:
    totals = data.get("totals", {})
    summary = Table(title=f"Timesheet Week {data.get('week_start')}")
    for day in config.DAY_NAMES:
        summary.add_column(day, justify="right")
    summary.add_column("Total", justify="right", style="bold")
    summary.add_row(
        *(f"{float(totals.get(day, 0)):.2g}" for day in config.DAY_NAMES),
        f"{float(data.get('week_total', 0)):.2g}",
    )
    console.print(summary)

    entries = [entry for entry in data.get("entries", []) if entry.get("hours")]
    if not entries:
        console.print("[dim]No submitted entries.[/]")
        return

    detail = Table(title="Entries")
    detail.add_column("Day", width=5)
    detail.add_column("Hours", justify="right")
    detail.add_column("Job")
    detail.add_column("Task")
    detail.add_column("Description")
    for entry in entries:
        detail.add_row(
            str(entry.get("day") or ""),
            f"{float(entry.get('hours') or 0):.2g}",
            entry.get("job_name") or str(entry.get("job_id") or ""),
            entry.get("task_name") or str(entry.get("task_id") or ""),
            entry.get("description") or "",
        )
    console.print(detail)


def render_submit(data: dict) -> None:
    status = "[green]OK[/]" if data.get("ok") else "[red]Errors[/]"
    console.print(Panel(
        f"[bold]Status:[/] {status}\n"
        f"[bold]Week:[/] {data.get('week_start')}\n"
        f"[bold]Created:[/] {data.get('created', 0)}\n"
        f"[bold]Updated:[/] {data.get('updated', 0)}\n"
        f"[bold]Dry run:[/] {data.get('dry_run', False)}",
        title="Timesheet Submit",
        border_style="green" if data.get("ok") else "red",
    ))

    operations = data.get("operations", [])
    if operations:
        table = Table(title="Operations")
        table.add_column("Action")
        table.add_column("Day")
        table.add_column("Job ID", justify="right")
        table.add_column("Task ID", justify="right")
        table.add_column("Hours", justify="right")
        table.add_column("Entry ID", justify="right")
        for op in operations:
            table.add_row(
                op.get("action") or "",
                op.get("day") or "",
                str(op.get("job_id") or ""),
                str(op.get("task_id") or ""),
                f"{float(op.get('hours') or 0):.2g}",
                str(op.get("entry_id") or op.get("existing_entry_id") or ""),
            )
        console.print(table)

    errors = data.get("errors", [])
    if errors:
        table = Table(title="Errors")
        table.add_column("Day")
        table.add_column("Job ID", justify="right")
        table.add_column("Task ID", justify="right")
        table.add_column("Error")
        for error in errors:
            table.add_row(
                error.get("day") or "",
                str(error.get("job_id") or ""),
                str(error.get("task_id") or ""),
                error.get("error") or "",
            )
        console.print(table)


def render_paths(data: dict) -> None:
    table = Table(title="workbook-cli Paths")
    table.add_column("Name", style="bold")
    table.add_column("Path")
    for key, value in data.items():
        table.add_row(key, str(value))
    console.print(table)
