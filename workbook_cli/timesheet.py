from __future__ import annotations

from . import config
from .client import WorkbookClient
from .dates import day_name_from_registration_date, week_dates, week_start


def summarize_week(client: WorkbookClient, week_offset: int = 0) -> dict:
    dates = week_dates(week_offset)
    entries = client.get_daily_entries(dates["Mon"])
    totals = {day: 0.0 for day in config.DAY_NAMES}
    rows = []

    for entry in entries:
        day = day_name_from_registration_date(entry.get("RegistrationDate", ""))
        hours = entry.get("Hours") or 0
        if day and hours:
            totals[day] += float(hours)
        rows.append({
            "id": entry.get("Id"),
            "day": day,
            "date": entry.get("RegistrationDate"),
            "hours": hours,
            "job_id": entry.get("JobId"),
            "job_name": entry.get("JobName", ""),
            "task_id": entry.get("TaskId"),
            "task_name": entry.get("TaskName", ""),
            "description": entry.get("Description", ""),
        })

    monday = week_start(week_offset)
    return {
        "week_start": monday.strftime("%Y-%m-%d"),
        "week_offset": week_offset,
        "totals": totals,
        "week_total": sum(totals.values()),
        "entries": rows,
    }


def _normalise_hours(value) -> dict[str, float]:
    if isinstance(value, (int, float)):
        return {day: float(value) for day in config.DAY_NAMES}
    if isinstance(value, dict):
        return {
            day: float(value.get(day, 0) or 0)
            for day in config.DAY_NAMES
        }
    raise ValueError("hours must be a number or day-name object")


def validate_entries(data) -> list[dict]:
    if not isinstance(data, list):
        raise ValueError("timesheet payload must be a JSON array")
    result = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"entry {index} must be an object")
        if "job_id" not in item:
            raise ValueError(f"entry {index} is missing job_id")
        if "hours" not in item:
            raise ValueError(f"entry {index} is missing hours")
        result.append({
            "job_id": int(item["job_id"]),
            "task_id": int(item["task_id"]) if item.get("task_id") else None,
            "description": str(item.get("description", "")),
            "descriptions": item.get("descriptions") or {},
            "hours": _normalise_hours(item["hours"]),
            "activity_id": int(item.get("activity_id", 530)),
            "billable": bool(item.get("billable", True)),
        })
    return result


def submit_entries(
    client: WorkbookClient,
    payload,
    *,
    week_offset: int = 0,
    dry_run: bool = False,
    separate_rows: bool = False,
) -> dict:
    entries = validate_entries(payload)
    dates = week_dates(week_offset)
    monday_iso = dates["Mon"]
    existing = client.get_daily_entries(monday_iso)

    existing_by_task_date = {
        (entry.get("TaskId") or 0, entry.get("RegistrationDate")): entry
        for entry in existing
    }
    operations = []
    errors = []
    created = 0
    updated = 0

    for entry in entries:
        job_id = entry["job_id"]
        task_id = entry["task_id"] or 0

        for day, hours in entry["hours"].items():
            if hours <= 0:
                continue
            day_iso = dates[day]
            description = entry["descriptions"].get(day, entry["description"])
            key = (task_id, day_iso)
            existing_entry = existing_by_task_date.get(key)

            if dry_run:
                operations.append({
                    "action": "update" if existing_entry else "create",
                    "day": day,
                    "date": day_iso,
                    "job_id": job_id,
                    "task_id": task_id or None,
                    "hours": hours,
                    "description": description,
                    "existing_entry_id": existing_entry.get("Id") if existing_entry else None,
                })
                continue

            try:
                if separate_rows or not existing_entry:
                    inserted = client.quick_insert(
                        job_id=job_id,
                        task_id=task_id,
                        date=day_iso,
                        check_week=not separate_rows,
                    )
                    created += 1
                    entry_id = inserted.get("Id")
                    if not entry_id:
                        refreshed = client.get_daily_entries(monday_iso)
                        candidates = [
                            row for row in refreshed
                            if (row.get("TaskId") or 0) == task_id and row.get("RegistrationDate") == day_iso
                        ]
                        entry_id = max(candidates, key=lambda row: row["Id"])["Id"] if candidates else None
                    if not entry_id:
                        raise RuntimeError("could not resolve inserted entry id")
                else:
                    entry_id = existing_entry["Id"]

                client.update_time_entry(
                    entry_id=entry_id,
                    hours=hours,
                    task_id=task_id,
                    description=description,
                    activity_id=entry["activity_id"],
                    billable=entry["billable"],
                )
                updated += 1
                operations.append({
                    "action": "create" if not existing_entry or separate_rows else "update",
                    "day": day,
                    "entry_id": entry_id,
                    "job_id": job_id,
                    "task_id": task_id or None,
                    "hours": hours,
                })
            except Exception as exc:
                errors.append({
                    "day": day,
                    "job_id": job_id,
                    "task_id": task_id or None,
                    "error": str(exc),
                })

    return {
        "ok": not errors,
        "dry_run": dry_run,
        "week_start": week_start(week_offset).strftime("%Y-%m-%d"),
        "created": created,
        "updated": updated,
        "operations": operations,
        "errors": errors,
    }
