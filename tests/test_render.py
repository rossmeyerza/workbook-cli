from workbook_cli.render import render_jobs, render_submit, render_timesheet


def test_render_jobs_smoke() -> None:
    render_jobs({
        "count": 1,
        "jobs": [{
            "job_id": 123,
            "job_name": "Example Job",
            "customer": "Client",
            "project": "Project",
            "tasks": [{"task_id": 456, "task_name": "Delivery"}],
        }],
    })


def test_render_timesheet_smoke() -> None:
    render_timesheet({
        "week_start": "2026-05-25",
        "totals": {"Mon": 1, "Tue": 0, "Wed": 2, "Thu": 0, "Fri": 1.5},
        "week_total": 4.5,
        "entries": [{
            "day": "Mon",
            "hours": 1,
            "job_name": "Example Job",
            "task_name": "Delivery",
            "description": "Reviewed work.",
        }],
    })


def test_render_submit_smoke() -> None:
    render_submit({
        "ok": True,
        "dry_run": True,
        "week_start": "2026-05-25",
        "created": 0,
        "updated": 0,
        "operations": [{
            "action": "create",
            "day": "Mon",
            "job_id": 123,
            "task_id": 456,
            "hours": 1,
        }],
        "errors": [],
    })
