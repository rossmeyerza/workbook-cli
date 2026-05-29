from __future__ import annotations

import json
from datetime import datetime

from . import config
from .client import WorkbookClient


def load_jobs_cache() -> dict | None:
    if not config.JOBS_CACHE_FILE.exists():
        return None
    try:
        return json.loads(config.JOBS_CACHE_FILE.read_text())
    except Exception:
        return None


def save_jobs_cache(jobs: list[dict]) -> None:
    config.ensure_dirs()
    config.JOBS_CACHE_FILE.write_text(json.dumps({
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "jobs": jobs,
    }, indent=2))


def fetch_jobs_with_tasks(client: WorkbookClient, date: str) -> list[dict]:
    jobs = []
    for job in client.get_allowed_jobs(date):
        job_id = job["Id"]
        tasks = client.get_tasks_for_job(job_id)
        jobs.append({
            "job_id": job_id,
            "job_name": job.get("JobName", ""),
            "customer": job.get("CustomerName", ""),
            "project": job.get("ProjectName", ""),
            "tasks": [
                {"task_id": task["Id"], "task_name": task.get("TaskName", "")}
                for task in tasks
            ],
        })
    return jobs


def search_jobs(jobs: list[dict], query: str) -> list[dict]:
    terms = [part.lower() for part in query.split() if part.strip()]
    if not terms:
        return jobs

    results = []
    for job in jobs:
        haystack = " ".join([
            str(job.get("job_id", "")),
            job.get("job_name", ""),
            job.get("customer", ""),
            job.get("project", ""),
            " ".join(task.get("task_name", "") for task in job.get("tasks", [])),
            " ".join(str(task.get("task_id", "")) for task in job.get("tasks", [])),
        ]).lower()
        if all(term in haystack for term in terms):
            results.append(job)
    return results
