from __future__ import annotations

import requests

from . import config
from .auth import load_cookies, login_via_browser, save_cookies


class WorkbookClient:
    def __init__(self) -> None:
        config.ensure_dirs()
        self.session = requests.Session()
        self.resource_id: int | None = None
        self.user_name: str | None = None
        self.csrf_token: str | None = None

    def login(self, *, headless: bool = True, force: bool = False) -> bool:
        if not force and self._load_saved_cookies():
            self._setup_headers()
            if self.handshake():
                return True

        cookies = login_via_browser(headless=headless)
        self._set_cookies(cookies)
        self.csrf_token = self.session.cookies.get("CSRF-Token")
        self._setup_headers()
        if self.handshake():
            save_cookies(cookies)
            return True
        return False

    def _set_cookies(self, cookies: list[dict]) -> None:
        self.session = requests.Session()
        for cookie in cookies:
            self.session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain", ""),
                path=cookie.get("path", "/"),
            )

    def _load_saved_cookies(self) -> bool:
        cookies = load_cookies()
        if not cookies:
            return False
        self._set_cookies(cookies)
        self.csrf_token = self.session.cookies.get("CSRF-Token")
        return bool(self.csrf_token)

    def _setup_headers(self) -> None:
        self.session.headers.update({
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "csrf-token": self.csrf_token or "",
            "Origin": config.WORKBOOK_URL,
            "Referer": f"{config.WORKBOOK_URL}/",
        })

    def handshake(self) -> bool:
        response = self.session.post(
            f"{config.WORKBOOK_URL}/api/auth/handshake",
            timeout=config.API_TIMEOUT,
        )
        if response.status_code != 200 or not response.text:
            return False
        data = response.json()
        self.resource_id = data.get("Id")
        self.user_name = data.get("Name")
        return bool(self.resource_id)

    def me(self) -> dict:
        return {"resource_id": self.resource_id, "name": self.user_name}

    def get_timesheet(self, date: str) -> list[dict]:
        response = self.session.get(
            f"{config.WORKBOOK_URL}/api/json/reply/TimeEntrySheetVisualizationRequest",
            params={"ResourceId": self.resource_id, "Date": date},
            timeout=config.API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    def get_daily_entries(self, date: str) -> list[dict]:
        response = self.session.get(
            f"{config.WORKBOOK_URL}/api/json/reply/TimeEntryDailyRequest",
            params={"ResourceId": self.resource_id, "Date": date, "Week": "true"},
            timeout=config.API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    def get_allowed_jobs(self, date: str) -> list[dict]:
        response = self.session.get(
            f"{config.WORKBOOK_URL}/api/json/reply/TimeEntryAllowedJobsVisualizationCacheRequest",
            params={
                "CustomerId": 0,
                "ProjectId": 0,
                "MyClients": "true",
                "OnlyActiveProjects": "false",
                "EmployeeId": 0,
                "Date": date,
            },
            timeout=config.API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    def get_tasks_for_job(self, job_id: int) -> list[dict]:
        response = self.session.get(
            f"{config.WORKBOOK_URL}/api/json/reply/TasksTimeRegistrationRequest",
            params={
                "ResourceId": self.resource_id,
                "JobId": job_id,
                "PlanId": 0,
                "PhaseNumber": 0,
                "Active": "true",
                "IncludeExpiredTasks": "true",
                "IncludeFutureTasks": "true",
                "IncludeOnHoldTasks": "false",
                "IncludeClosedTasks": "false",
            },
            timeout=config.API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    def quick_insert(self, *, job_id: int, task_id: int | None, date: str, check_week: bool = True) -> dict:
        response = self.session.post(
            f"{config.WORKBOOK_URL}/api/json/reply/QuickInsertTimeRequest",
            json={
                "taskid": str(task_id) if task_id else "",
                "jobid": job_id,
                "resourceId": self.resource_id,
                "date": date,
                "CheckWeek": check_week,
            },
            timeout=config.API_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def update_time_entry(
        self,
        *,
        entry_id: int,
        hours: float,
        task_id: int | None,
        description: str,
        activity_id: int = 530,
        billable: bool = True,
    ) -> dict:
        response = self.session.post(
            f"{config.WORKBOOK_URL}/api/json/reply/TimeEntryUpdateRequest",
            json={
                "Id": entry_id,
                "ActivityId": activity_id,
                "Billable": billable,
                "Hours": hours if hours > 0 else None,
                "TaskId": task_id or None,
                "Description": description,
            },
            timeout=config.API_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
