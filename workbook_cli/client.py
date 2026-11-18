from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import playwright
import requests

from . import config
from .auth import load_cookies, login_via_browser, save_cookies


class WorkbookAPIError(RuntimeError):
    """A Workbook request failed.

    ``may_have_succeeded`` is true when no safe retry decision can be made.
    """

    def __init__(self, message: str, *, may_have_succeeded: bool = False) -> None:
        super().__init__(message)
        self.may_have_succeeded = may_have_succeeded


def _workbook_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except (ValueError, requests.JSONDecodeError):
        data = None

    if isinstance(data, dict):
        for key in ("ErrorMessage", "Message", "message"):
            if data.get(key):
                return str(data[key])
        status = data.get("ResponseStatus")
        if isinstance(status, dict):
            for key in ("Message", "ErrorCode"):
                if status.get(key):
                    return str(status[key])
    return f"Workbook returned HTTP {response.status_code}"


def _read_csrf_token(session: requests.Session) -> str:
    """Return the CSRF cookie value, URL-decoded.

    Workbook URL-encodes the base64 padding in its Set-Cookie (``...%3D%3D``).
    The real browser client decodes it back to ``==`` before putting it in the
    ``csrf-token`` request header; sending the encoded form yields a 403 with
    an empty body on every mutating POST.
    """
    raw = session.cookies.get("CSRF-Token") or ""
    return unquote(raw)


class WorkbookClient:
    def __init__(self) -> None:
        config.ensure_dirs()
        self.session = requests.Session()
        self.resource_id: int | None = None
        self.user_name: str | None = None
        self.csrf_token: str | None = None
        self.last_error: str = ""

    @staticmethod
    def browser_status() -> dict:
        """Return the expected Chromium path without starting a browser."""
        package_dir = Path(playwright.__file__).resolve().parent
        browsers_file = package_dir / "driver" / "package" / "browsers.json"
        data = json.loads(browsers_file.read_text())
        revisions = {
            item["name"]: item["revision"]
            for item in data.get("browsers", [])
            if item.get("name") in {"chromium", "chromium-headless-shell"}
        }
        configured_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        if configured_root == "0":
            browser_root = package_dir / "driver" / "package" / ".local-browsers"
        elif configured_root:
            browser_root = Path(configured_root).expanduser()
        else:
            browser_root = Path.home() / ".cache" / "ms-playwright"

        chromium_dir = browser_root / f"chromium-{revisions.get('chromium', 'unknown')}"
        headless_dir = browser_root / f"chromium_headless_shell-{revisions.get('chromium-headless-shell', 'unknown')}"
        executable_candidates = [
            chromium_dir / "chrome-linux64" / "chrome",
            chromium_dir / "chrome-linux" / "chrome",
        ]
        headless_candidates = [
            headless_dir / "chrome-headless-shell-linux64" / "chrome-headless-shell",
            headless_dir / "chrome-linux" / "headless_shell",
        ]
        executable = next((path for path in executable_candidates if path.is_file()), executable_candidates[0])
        headless_executable = next((path for path in headless_candidates if path.is_file()), headless_candidates[0])
        return {
            "installed": executable.is_file() and headless_executable.is_file(),
            "executable": str(executable),
            "headless_executable": str(headless_executable),
        }

    def login_saved(self) -> bool:
        """Check saved cookies without starting an interactive login."""
        self.last_error = ""
        if not self._load_saved_cookies():
            self.last_error = "No usable saved Workbook session was found"
            return False
        self._setup_headers()
        try:
            ok = self.handshake()
        except Exception as exc:
            self.last_error = f"Saved Workbook session check failed: {exc}"
            return False
        if not ok:
            self.last_error = "Saved Workbook session has expired"
        return ok

    def login(self, *, headless: bool = True, force: bool = False, debug_auth: bool = False) -> bool:
        if not force and self.login_saved():
            return True

        browser = self.browser_status()
        if not browser["installed"]:
            raise RuntimeError(
                "Playwright Chromium is not installed. Run: "
                f"{Path(__file__).resolve().parent.parent / '.venv/bin/python'} "
                "-m playwright install chromium"
            )

        cookies = login_via_browser(headless=headless, debug_auth=debug_auth)
        self._set_cookies(cookies)
        self._ensure_csrf_token()
        self._setup_headers()
        if self.handshake():
            save_cookies(self._cookies_for_save())
            return True
        raise RuntimeError("Workbook authentication failed: handshake did not return a user session")

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
        self.csrf_token = _read_csrf_token(self.session)
        return bool(self.csrf_token)

    def _cookies_for_save(self) -> list[dict]:
        return [
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
            }
            for cookie in self.session.cookies
        ]

    def _setup_headers(self) -> None:
        self.session.headers.update({
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "csrf-token": self.csrf_token or "",
            "Origin": config.WORKBOOK_URL,
            "Referer": f"{config.WORKBOOK_URL}/",
            # As of mid-2026 Workbook rejects timesheet POSTs (403, empty body)
            # without these headers. Server only checks presence; values are
            # arbitrary in the real client.
            "workbook-sender": "404",
            "workbook-container": "#ui-id-17",
            "workbook-communicationid": "236843154224",
        })

    def _ensure_csrf_token(self) -> None:
        self.csrf_token = _read_csrf_token(self.session)
        if self.csrf_token:
            return

        response = self.session.get(
            f"{config.WORKBOOK_URL}/api/auth/currentsession",
            params={"CSRFCookie": "true"},
            timeout=config.API_TIMEOUT,
        )
        if response.status_code not in (200, 204):
            raise RuntimeError(
                f"Workbook authentication failed: current session returned HTTP {response.status_code}"
            )

        self.csrf_token = _read_csrf_token(self.session)
        if not self.csrf_token:
            raise RuntimeError("Workbook authentication failed: CSRF-Token cookie was not set")

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

    def _list_response(self, response: requests.Response, operation: str) -> list[dict]:
        if not response.ok:
            raise WorkbookAPIError(_workbook_error_message(response))
        try:
            data = response.json()
        except ValueError as exc:
            raise WorkbookAPIError(f"Workbook returned invalid JSON for {operation}") from exc
        if not isinstance(data, list):
            raise WorkbookAPIError(f"Workbook returned unexpected data for {operation}")
        return data

    def _write_mutation_log(
        self,
        operation: str,
        payload: dict,
        *,
        response: requests.Response | None = None,
        error: str = "",
    ) -> None:
        """Write a diagnostic record without cookies, credentials, or descriptions."""
        config.ensure_dirs()
        safe_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"Description"}
        }
        if "Description" in payload:
            safe_payload["description_length"] = len(str(payload.get("Description") or ""))
        safe_error = error
        for private_value in (
            str(payload.get("Description") or ""),
            config.WORKBOOK_EMAIL,
            config.WORKBOOK_PASSWORD,
        ):
            if private_value:
                safe_error = safe_error.replace(private_value, "<redacted>")
        record = {
            "operation": operation,
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "payload": safe_payload,
            "http_status": response.status_code if response is not None else None,
            "error": safe_error,
        }
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = config.LOG_DIR / f"mutation_{stamp}_{operation}.json"
        path.write_text(json.dumps(record, indent=2) + "\n")
        path.chmod(0o600)

    def _mutating_post(self, endpoint: str, payload: dict, operation: str) -> dict:
        url = f"{config.WORKBOOK_URL}/api/json/reply/{endpoint}"
        try:
            response = self.session.post(url, json=payload, timeout=config.API_TIMEOUT)
        except requests.RequestException as exc:
            message = f"Workbook {operation} request did not complete: {exc}"
            self.last_error = message
            self._write_mutation_log(operation, payload, error=message)
            raise WorkbookAPIError(message, may_have_succeeded=True) from exc

        if not response.ok:
            message = _workbook_error_message(response)
            self.last_error = message
            self._write_mutation_log(operation, payload, response=response, error=message)
            raise WorkbookAPIError(message, may_have_succeeded=response.status_code >= 500)

        try:
            data = response.json()
        except ValueError as exc:
            message = f"Workbook returned invalid JSON after {operation}"
            self.last_error = message
            self._write_mutation_log(operation, payload, response=response, error=message)
            raise WorkbookAPIError(message, may_have_succeeded=True) from exc
        if not isinstance(data, dict):
            message = f"Workbook returned unexpected data after {operation}"
            self.last_error = message
            self._write_mutation_log(operation, payload, response=response, error=message)
            raise WorkbookAPIError(message, may_have_succeeded=True)
        self.last_error = ""
        self._write_mutation_log(operation, payload, response=response)
        return data

    def me(self) -> dict:
        return {"resource_id": self.resource_id, "name": self.user_name}

    def get_timesheet(self, date: str) -> list[dict]:
        response = self.session.get(
            f"{config.WORKBOOK_URL}/api/json/reply/TimeEntrySheetVisualizationRequest",
            params={"ResourceId": self.resource_id, "Date": date},
            timeout=config.API_TIMEOUT,
        )
        return self._list_response(response, "timesheet read")

    def get_daily_entries(self, date: str) -> list[dict]:
        response = self.session.get(
            f"{config.WORKBOOK_URL}/api/json/reply/TimeEntryDailyRequest",
            params={"ResourceId": self.resource_id, "Date": date, "Week": "true"},
            timeout=config.API_TIMEOUT,
        )
        return self._list_response(response, "daily entry read")

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
        return self._list_response(response, "job list")

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
        return self._list_response(response, "task list")

    def quick_insert(self, *, job_id: int, task_id: int | None, date: str, check_week: bool = True) -> dict:
        return self._mutating_post(
            "QuickInsertTimeRequest",
            {
                "taskid": str(task_id) if task_id else None,
                "jobid": job_id,
                "resourceId": self.resource_id,
                "date": date,
                "CheckWeek": check_week,
            },
            "quick_insert",
        )

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
        return self._mutating_post(
            "TimeEntryUpdateRequest",
            {
                "Id": entry_id,
                "ActivityId": activity_id,
                "Billable": billable,
                "Hours": hours,
                "TaskId": task_id or None,
                "Description": description,
            },
            "update_time_entry",
        )
