"""Read and submit Workbook timesheets."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from . import config
from .client import WorkbookClient
from .dates import day_name_from_registration_date, week_dates, week_start

try:
    import fcntl
except ImportError:  # pragma: no cover - Linux is the supported install target.
    fcntl = None


JOURNAL_VERSION = 1


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


def _normalise_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a finite non-negative number")
    return number


def _normalise_hours(value: object) -> dict[str, float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        hours = _normalise_number(value, "hours")
        return {day: hours for day in config.DAY_NAMES}
    if isinstance(value, dict):
        unknown = sorted(set(value) - set(config.DAY_NAMES))
        if unknown:
            raise ValueError(f"hours has unknown day {unknown[0]!r}")
        return {
            day: _normalise_number(value.get(day, 0), f"hours.{day}")
            for day in config.DAY_NAMES
        }
    raise ValueError("hours must be a number or day-name object")


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive integer") from exc
    if number <= 0 or str(value).strip() != str(number):
        raise ValueError(f"{label} must be a positive integer")
    return number


def validate_entries(data: object) -> list[dict]:
    """Validate the complete payload before any Workbook write."""
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

        description = item.get("description", "")
        if not isinstance(description, str):
            raise ValueError(f"entry {index} description must be text")
        descriptions = item.get("descriptions", {})
        if descriptions is None:
            descriptions = {}
        if not isinstance(descriptions, dict):
            raise ValueError(f"entry {index} descriptions must be a day-name object")
        unknown = sorted(set(descriptions) - set(config.DAY_NAMES))
        if unknown:
            raise ValueError(f"entry {index} descriptions has unknown day {unknown[0]!r}")
        if any(not isinstance(value, str) for value in descriptions.values()):
            raise ValueError(f"entry {index} descriptions must contain text values")

        task_value = item.get("task_id")
        task_id = None if task_value in (None, 0, "0", "") else _positive_int(task_value, f"entry {index} task_id")
        activity_id = _positive_int(item.get("activity_id", 530), f"entry {index} activity_id")
        billable = item.get("billable", True)
        if not isinstance(billable, bool):
            raise ValueError(f"entry {index} billable must be true or false")

        result.append({
            "job_id": _positive_int(item["job_id"], f"entry {index} job_id"),
            "task_id": task_id,
            "description": description,
            "descriptions": descriptions,
            "hours": _normalise_hours(item["hours"]),
            "activity_id": activity_id,
            "billable": billable,
        })
    return result


def _canonical_payload(entries: list[dict]) -> list[dict]:
    return [{
        "job_id": entry["job_id"],
        "task_id": entry["task_id"],
        "description": entry["description"],
        "descriptions": entry["descriptions"],
        "hours": entry["hours"],
        "activity_id": entry["activity_id"],
        "billable": entry["billable"],
    } for entry in entries]


def _validate_cached_tasks(entries: list[dict]) -> None:
    """Reject known invalid job and task combinations from the local cache."""
    from .jobs import load_jobs_cache

    cache = load_jobs_cache()
    if not isinstance(cache, dict) or not isinstance(cache.get("jobs"), list):
        return
    jobs = {job.get("job_id"): job for job in cache["jobs"] if isinstance(job, dict)}
    for index, entry in enumerate(entries):
        job = jobs.get(entry["job_id"])
        if not job:
            continue
        tasks = job.get("tasks") or []
        if tasks and entry["task_id"] is None:
            raise ValueError(f"entry {index} job {entry['job_id']} requires a task_id")
        if entry["task_id"] is not None and tasks:
            allowed = {task.get("task_id") for task in tasks if isinstance(task, dict)}
            if entry["task_id"] not in allowed:
                raise ValueError(
                    f"entry {index} task {entry['task_id']} does not belong to job {entry['job_id']}"
                )


def _payload_hash(entries: list[dict]) -> str:
    raw = json.dumps(_canonical_payload(entries), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _same_date(value: object, expected: str) -> bool:
    return isinstance(value, str) and value[:10] == expected[:10]


def _same_identity(row: dict, *, job_id: int, task_id: int, date: str) -> bool:
    return (
        row.get("Id") is not None
        and row.get("JobId") == job_id
        and (row.get("TaskId") or 0) == task_id
        and _same_date(row.get("RegistrationDate"), date)
    )


def _matches(entries: list[dict], operation: dict, *, excluded: set[int] | None = None) -> list[dict]:
    excluded = excluded or set()
    return [
        row for row in entries
        if row.get("Id") not in excluded
        and _same_identity(
            row,
            job_id=operation["job_id"],
            task_id=operation["task_id"],
            date=operation["date"],
        )
    ]


def _is_desired(row: dict, operation: dict) -> bool:
    if not _same_identity(
        row,
        job_id=operation["job_id"],
        task_id=operation["task_id"],
        date=operation["date"],
    ):
        return False
    try:
        same_hours = math.isclose(float(row.get("Hours")), operation["hours"], abs_tol=1e-9)
    except (TypeError, ValueError):
        same_hours = False
    return same_hours and (row.get("Description") or "") == operation["description"]


def _build_operations(entries: list[dict], dates: dict[str, str]) -> list[dict]:
    operations = []
    for entry_index, entry in enumerate(entries):
        for day in config.DAY_NAMES:
            hours = entry["hours"][day]
            if hours == 0:
                continue
            operations.append({
                "operation_id": f"{entry_index}:{day}",
                "entry_index": entry_index,
                "day": day,
                "date": dates[day],
                "job_id": entry["job_id"],
                "task_id": entry["task_id"] or 0,
                "hours": hours,
                "description": entry["descriptions"].get(day, entry["description"]),
                "activity_id": entry["activity_id"],
                "billable": entry["billable"],
                "status": "pending",
                "action": None,
                "entry_id": None,
            })
    return operations


def _context(client: WorkbookClient, entries: list[dict], dates: dict[str, str], separate_rows: bool) -> dict:
    return {
        "workbook_url": config.WORKBOOK_URL,
        "resource_id": client.resource_id,
        "week_dates": {day: dates[day] for day in config.DAY_NAMES},
        "payload_sha256": _payload_hash(entries),
        "separate_rows": separate_rows,
    }


def _default_journal_path(context: dict) -> Path:
    week = context["week_dates"]["Mon"][:10]
    resource = context["resource_id"] or "unknown"
    digest = context["payload_sha256"][:16]
    return config.SUBMISSION_DIR / f"submission_{resource}_{week}_{digest}.json"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        path.chmod(0o600)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def load_submission_journal(path: str | Path) -> dict:
    journal_path = Path(path)
    try:
        data = json.loads(journal_path.read_text())
    except Exception as exc:
        raise ValueError(f"Cannot read submission journal {journal_path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != JOURNAL_VERSION:
        raise ValueError(f"Unsupported or invalid submission journal: {journal_path}")
    if not isinstance(data.get("context"), dict) or not isinstance(data.get("payload"), list):
        raise ValueError(f"Incomplete submission journal: {journal_path}")
    if not isinstance(data.get("operations"), list):
        raise ValueError(f"Incomplete submission journal: {journal_path}")
    validated = validate_entries(data["payload"])
    if data["context"].get("payload_sha256") != _payload_hash(validated):
        raise ValueError(f"Submission journal payload hash does not match: {journal_path}")
    dates = data["context"].get("week_dates")
    if not isinstance(dates, dict) or any(not isinstance(dates.get(day), str) for day in config.DAY_NAMES):
        raise ValueError(f"Submission journal has invalid week dates: {journal_path}")
    context = data["context"]
    if (
        not isinstance(context.get("workbook_url"), str)
        or context.get("resource_id") is not None
        and (not isinstance(context["resource_id"], int) or isinstance(context["resource_id"], bool))
        or not isinstance(context.get("separate_rows"), bool)
    ):
        raise ValueError(f"Submission journal has invalid context: {journal_path}")
    expected = _build_operations(validated, dates)
    operations = data["operations"]
    immutable = (
        "operation_id", "entry_index", "day", "date", "job_id", "task_id",
        "hours", "description", "activity_id", "billable",
    )
    if len(operations) != len(expected):
        raise ValueError(f"Submission journal operation count does not match: {journal_path}")
    allowed_statuses = {
        "pending", "insert_in_flight", "insert_uncertain", "insert_failed",
        "update_pending", "update_in_flight", "update_uncertain", "update_failed",
        "success", "uncertain", "ambiguous",
    }
    for saved, planned in zip(operations, expected):
        if not isinstance(saved, dict) or any(saved.get(key) != planned.get(key) for key in immutable):
            raise ValueError(f"Submission journal operation data does not match: {journal_path}")
        if saved.get("status") not in allowed_statuses:
            raise ValueError(f"Submission journal has an invalid operation status: {journal_path}")
        if saved.get("action") not in {None, "create", "update", "unchanged"}:
            raise ValueError(f"Submission journal has an invalid operation action: {journal_path}")
        entry_id = saved.get("entry_id")
        if entry_id is not None and (not isinstance(entry_id, int) or isinstance(entry_id, bool) or entry_id <= 0):
            raise ValueError(f"Submission journal has an invalid entry ID: {journal_path}")
        before = saved.get("pre_insert_ids", [])
        if not isinstance(before, list) or any(not isinstance(value, int) or isinstance(value, bool) for value in before):
            raise ValueError(f"Submission journal has an invalid insert snapshot: {journal_path}")
    return data


@contextmanager
def _journal_lock(path: Path):
    if fcntl is None:  # pragma: no cover
        raise RuntimeError("Submission journal locking is not available")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    stream = lock_path.open("a+")
    try:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f"Submission journal is already in use: {path}") from exc
        yield
    finally:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _read_entries(client: WorkbookClient, anchor: str) -> list[dict]:
    entries = client.get_daily_entries(anchor)
    if not isinstance(entries, list):
        raise RuntimeError("Workbook returned unexpected daily entry data")
    return entries


def _zero_hours(row: dict) -> bool:
    if "Hours" not in row:
        raise ValueError("Workbook did not return the hours for this entry.")
    return row["Hours"] is None or float(row["Hours"]) == 0


def clear_entry(client: WorkbookClient, entry_id: int, *, week_offset: int = 0, confirm: bool = False) -> dict:
    """Set the hours of one existing entry to zero."""
    entry_id = _positive_int(entry_id, "entry_id")
    anchor = week_dates(week_offset)["Mon"]
    matches = [row for row in _read_entries(client, anchor) if row.get("Id") == entry_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one entry with ID {entry_id} in the week of {anchor[:10]}. Found {len(matches)}.")
    row = matches[0]
    result = {
        "ok": True, "dry_run": not confirm, "entry_id": entry_id, "date": row.get("RegistrationDate"),
        "job_id": row.get("JobId"), "task_id": row.get("TaskId"), "previous_hours": row.get("Hours"), "hours": 0,
    }
    if _zero_hours(row):
        return {**result, "status": "already_zero"}
    if not confirm:
        return {**result, "status": "preview"}

    if any(key not in row for key in ("ActivityId", "Billable", "TaskId", "Description")):
        raise ValueError("Workbook did not return the metadata needed to preserve this entry. No update was made.")
    try:
        client.update_time_entry(
            entry_id=entry_id, hours=0, task_id=row["TaskId"], description=row["Description"],
            activity_id=row["ActivityId"], billable=row["Billable"],
        )
    except Exception as exc:
        raise RuntimeError(f"Workbook update failed or is uncertain. Check the entry before you retry: {exc}") from exc
    try:
        remaining = [row for row in _read_entries(client, anchor) if row.get("Id") == entry_id]
        if not remaining:
            return {**result, "status": "not_returned"}
        if len(remaining) == 1 and _zero_hours(remaining[0]):
            return {**result, "status": "zeroed"}
    except Exception as exc:
        raise RuntimeError(f"Could not verify the update. Check the entry before you retry: {exc}") from exc
    raise RuntimeError("Workbook did not confirm zero hours. Check the entry before you retry.")


def _set_error(operation: dict, status: str, message: str) -> None:
    operation["status"] = status
    operation["error"] = message


def _resolve_uncertain_insert(operation: dict, entries: list[dict]) -> bool:
    if "pre_insert_ids" not in operation:
        _set_error(operation, "insert_uncertain", "Insert has no pre-insert snapshot. No retry was made.")
        return False
    candidates = _matches(entries, operation, excluded=set(operation["pre_insert_ids"]))
    if len(candidates) == 1:
        operation["entry_id"] = candidates[0]["Id"]
        operation["status"] = "update_pending"
        operation.pop("error", None)
        return True
    if len(candidates) > 1:
        _set_error(operation, "insert_uncertain", "Insert recovery found multiple new cells. Review Workbook before retrying.")
    else:
        _set_error(operation, "insert_uncertain", "Insert is not confirmed. No retry was made.")
    return False


def _result(journal: dict, path: Path, *, dry_run: bool = False, resumed: bool = False) -> dict:
    operations = []
    errors = []
    created = 0
    updated = 0
    hours_written = 0.0
    hours_lost = 0.0
    for saved in journal["operations"]:
        success = saved.get("status") == "success"
        action = saved.get("action") or "pending"
        output = {
            "action": action,
            "day": saved["day"],
            "date": saved["date"],
            "job_id": saved["job_id"],
            "task_id": saved["task_id"] or None,
            "hours": saved["hours"],
            "entry_id": saved.get("entry_id"),
            "status": saved.get("status"),
        }
        operations.append(output)
        if success and not dry_run:
            hours_written += saved["hours"]
            if action == "create":
                created += 1
                updated += 1
            elif action == "update":
                updated += 1
        elif not success:
            hours_lost += saved["hours"]
            errors.append({
                "day": saved["day"],
                "job_id": saved["job_id"],
                "task_id": saved["task_id"] or None,
                "error": saved.get("error") or "Operation is pending. Resume the submission journal.",
            })
    return {
        "ok": not errors,
        "dry_run": dry_run,
        "resumed": resumed,
        "week_start": journal["context"]["week_dates"]["Mon"][:10],
        "created": created,
        "updated": updated,
        "planned_hours": sum(saved["hours"] for saved in journal["operations"]),
        "hours_written": hours_written,
        "hours_lost": hours_lost,
        "journal_path": None if dry_run else str(path),
        "operations": operations,
        "errors": errors,
    }


def submit_entries(
    client: WorkbookClient,
    payload: object,
    *,
    week_offset: int = 0,
    dry_run: bool = False,
    separate_rows: bool = False,
    journal_path: str | Path | None = None,
    resume: bool = False,
    dates_override: dict[str, str] | None = None,
) -> dict:
    """Submit entries and verify each write with a Workbook readback."""
    entries = validate_entries(payload)
    if not resume:
        _validate_cached_tasks(entries)
    dates = dates_override or week_dates(week_offset)
    if any(not isinstance(dates.get(day), str) for day in config.DAY_NAMES):
        raise ValueError("week date mapping is incomplete")
    planned = _build_operations(entries, dates)
    if not separate_rows:
        identities = [(op["job_id"], op["task_id"], op["date"]) for op in planned]
        if len(identities) != len(set(identities)):
            raise ValueError("payload contains duplicate job, task, and day cells; use --separate-rows if required")

    context = _context(client, entries, dates, separate_rows)
    path = Path(journal_path) if journal_path else _default_journal_path(context)
    anchor = dates["Mon"]

    if dry_run:
        current = _read_entries(client, anchor)
        used: set[int] = set()
        for operation in planned:
            matches = _matches(current, operation, excluded=used)
            if separate_rows or not matches:
                operation["action"] = "create"
            elif len(matches) == 1:
                operation["action"] = "unchanged" if _is_desired(matches[0], operation) else "update"
                operation["entry_id"] = matches[0]["Id"]
                used.add(matches[0]["Id"])
            else:
                _set_error(operation, "ambiguous", "Multiple existing Workbook cells match this job, task, and date.")
                continue
            operation["status"] = "success"
        journal = {"version": JOURNAL_VERSION, "context": context, "payload": _canonical_payload(entries), "operations": planned}
        return _result(journal, path, dry_run=True)

    with _journal_lock(path):
        if path.exists():
            journal = load_submission_journal(path)
            if journal["context"] != context:
                raise ValueError(f"Submission journal context does not match: {path}")
            resumed_run = True
        else:
            if resume:
                raise ValueError(f"Submission journal does not exist: {path}")
            journal = {
                "version": JOURNAL_VERSION,
                "context": context,
                "payload": _canonical_payload(entries),
                "operations": planned,
            }
            _atomic_write(path, journal)
            resumed_run = False

        def persist() -> None:
            _atomic_write(path, journal)

        used: set[int] = set()
        for operation in journal["operations"]:
            status = operation.get("status", "pending")
            try:
                current = _read_entries(client, anchor)
            except Exception as exc:
                _set_error(operation, "pending", f"Workbook read failed before a write: {exc}")
                persist()
                break

            entry_id = operation.get("entry_id")
            exact = next((row for row in current if row.get("Id") == entry_id), None) if entry_id is not None else None

            if status == "success":
                if exact is not None and _is_desired(exact, operation):
                    used.add(entry_id)
                    continue
                _set_error(operation, "uncertain", "The verified Workbook cell changed. No retry was made.")
                persist()
                continue

            if status in {"insert_in_flight", "insert_uncertain"}:
                if not _resolve_uncertain_insert(operation, current):
                    persist()
                    continue
                persist()
                entry_id = operation["entry_id"]
                exact = next((row for row in current if row.get("Id") == entry_id), None)

            elif status == "insert_failed":
                if not _resolve_uncertain_insert(operation, current):
                    if operation.get("status") == "insert_uncertain" and "not confirmed" in operation.get("error", ""):
                        operation["status"] = "pending"
                        operation.pop("error", None)
                    else:
                        persist()
                        continue
                persist()

            elif status in {"update_in_flight", "update_uncertain", "uncertain"}:
                if exact is not None and _is_desired(exact, operation):
                    operation["status"] = "success"
                    operation.pop("error", None)
                    used.add(entry_id)
                    persist()
                else:
                    _set_error(operation, "update_uncertain", "Update is not confirmed. No retry was made.")
                    persist()
                continue

            elif status == "update_failed":
                if exact is not None and _is_desired(exact, operation):
                    operation["status"] = "success"
                    operation.pop("error", None)
                    used.add(entry_id)
                    persist()
                    continue
                operation["status"] = "update_pending"
                operation.pop("error", None)
                persist()

            if operation.get("status") == "pending":
                candidates = _matches(current, operation, excluded=used)
                if not separate_rows and len(candidates) > 1:
                    _set_error(operation, "ambiguous", "Multiple existing Workbook cells match this job, task, and date.")
                    persist()
                    continue
                if not separate_rows and len(candidates) == 1:
                    candidate = candidates[0]
                    operation["entry_id"] = candidate["Id"]
                    if _is_desired(candidate, operation):
                        operation["action"] = "unchanged"
                        operation["status"] = "success"
                        used.add(candidate["Id"])
                        persist()
                        continue
                    operation["action"] = "update"
                    operation["status"] = "update_pending"
                    persist()
                else:
                    operation["action"] = "create"
                    operation["pre_insert_ids"] = sorted(
                        row["Id"] for row in current if row.get("Id") is not None
                    )
                    operation["status"] = "insert_in_flight"
                    operation.pop("error", None)
                    persist()
                    try:
                        client.quick_insert(
                            job_id=operation["job_id"],
                            task_id=operation["task_id"] or None,
                            date=operation["date"],
                            check_week=not separate_rows,
                        )
                    except Exception as exc:
                        uncertain = bool(getattr(exc, "may_have_succeeded", True))
                        _set_error(
                            operation,
                            "insert_uncertain" if uncertain else "insert_failed",
                            ("Insert may have reached Workbook. No retry was made: " if uncertain else "Insert failed: ") + str(exc),
                        )
                        persist()
                        continue
                    try:
                        current = _read_entries(client, anchor)
                    except Exception as exc:
                        _set_error(operation, "insert_uncertain", f"Insert readback failed. No retry was made: {exc}")
                        persist()
                        continue
                    if not _resolve_uncertain_insert(operation, current):
                        persist()
                        continue
                    persist()

            if operation.get("status") != "update_pending":
                continue
            entry_id = operation.get("entry_id")
            if entry_id is None:
                _set_error(operation, "update_uncertain", "No Workbook entry ID is available. No update was made.")
                persist()
                continue
            current_entry = next((row for row in current if row.get("Id") == entry_id), None)
            if current_entry is None or not _same_identity(
                current_entry,
                job_id=operation["job_id"],
                task_id=operation["task_id"],
                date=operation["date"],
            ):
                _set_error(operation, "update_uncertain", "The saved Workbook entry ID no longer matches this cell. No update was made.")
                persist()
                continue
            operation["status"] = "update_in_flight"
            operation.pop("error", None)
            persist()
            try:
                client.update_time_entry(
                    entry_id=entry_id,
                    hours=operation["hours"],
                    task_id=operation["task_id"] or None,
                    description=operation["description"],
                    activity_id=operation["activity_id"],
                    billable=operation["billable"],
                )
            except Exception as exc:
                uncertain = bool(getattr(exc, "may_have_succeeded", True))
                _set_error(
                    operation,
                    "update_uncertain" if uncertain else "update_failed",
                    ("Update may have reached Workbook. No retry was made: " if uncertain else "Update failed: ") + str(exc),
                )
                persist()
                continue
            try:
                verified = _read_entries(client, anchor)
            except Exception as exc:
                _set_error(operation, "update_uncertain", f"Update readback failed. No retry was made: {exc}")
                persist()
                continue
            exact = next((row for row in verified if row.get("Id") == entry_id), None)
            if exact is None or not _is_desired(exact, operation):
                _set_error(operation, "update_uncertain", "Workbook readback did not confirm the update. No retry was made.")
                persist()
                continue
            operation["status"] = "success"
            operation.pop("error", None)
            used.add(entry_id)
            persist()

        return _result(journal, path, resumed=resumed_run)


def resume_submission(client: WorkbookClient, journal_path: str | Path) -> dict:
    """Resume the exact payload and week stored in a journal."""
    journal = load_submission_journal(journal_path)
    context = journal["context"]
    if context.get("workbook_url") != config.WORKBOOK_URL:
        raise ValueError("Submission journal Workbook URL does not match this configuration")
    if context.get("resource_id") != client.resource_id:
        raise ValueError("Submission journal user does not match the authenticated Workbook user")
    return submit_entries(
        client,
        journal["payload"],
        separate_rows=bool(context.get("separate_rows", False)),
        journal_path=journal_path,
        resume=True,
        dates_override=context["week_dates"],
    )
