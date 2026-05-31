# workbook-cli

Agent-friendly CLI for Workbook timesheets. It uses Playwright to authenticate through Workbook/Okta, stores its own session state, and talks directly to Workbook's internal JSON API.

The CLI is designed for agents: input is JSON on the command line or stdin, and output is JSON by default. For human use, pass `--format table` before the command group to render Rich tables.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/rossmeyerza/workbook-cli/main/install.sh | bash
```

Local development:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
python -m playwright install chromium
workbook-cli config init --email you@company.com --password '...'
```

## State

No state is shared with other timesheet tools.

```text
~/.config/workbook-cli/.env
~/.local/share/workbook-cli/session_state/api_cookies.json
~/.local/share/workbook-cli/session_state/browser_state.json
~/.local/share/workbook-cli/cache/jobs.json
```

## Auth

```bash
workbook-cli auth
workbook-cli auth --headed
workbook-cli auth status --pretty
workbook-cli --format table auth status
workbook-cli auth clear
```

Headless auth uses `WORKBOOK_EMAIL` and `WORKBOOK_PASSWORD` from `~/.config/workbook-cli/.env`, fills the Okta/Microsoft login form, prints the MFA number when one is displayed, and saves Workbook cookies.

## Jobs

```bash
workbook-cli jobs refresh --pretty
workbook-cli jobs search nespresso --pretty
workbook-cli jobs tasks 465430 --pretty
workbook-cli --format table jobs search nespresso
workbook-cli --format table jobs tasks 465430
```

## Timesheets

Show current week:

```bash
workbook-cli timesheet show --pretty
workbook-cli --format table timesheet show
```

Submit JSON:

```bash
workbook-cli timesheet submit --json '[
  {
    "job_id": 465430,
    "task_id": 2886954,
    "description": "AMC technical readiness assessment.",
    "hours": {"Mon": 2, "Tue": 2, "Wed": 1.5}
  }
]' --pretty
```

Use stdin:

```bash
printf '%s\n' '[{"job_id":465430,"task_id":2886954,"hours":{"Mon":1},"description":"Review work"}]' \
  | workbook-cli timesheet submit --json -
```

Dry run:

```bash
workbook-cli timesheet submit --dry-run --json '[{"job_id":465430,"task_id":2886954,"hours":{"Mon":1}}]' --pretty
workbook-cli --format table timesheet submit --dry-run --json '[{"job_id":465430,"task_id":2886954,"hours":{"Mon":1}}]'
```

Previous week:

```bash
workbook-cli timesheet --week-offset -1 show --pretty
workbook-cli timesheet --week-offset -1 submit --json '[...]'
```

## JSON Schema

Batch submission expects a JSON array:

```json
[
  {
    "job_id": 465430,
    "task_id": 2886954,
    "description": "Default description",
    "hours": {"Mon": 2, "Tue": 2},
    "descriptions": {"Mon": "Optional per-day override"},
    "activity_id": 530,
    "billable": true
  }
]
```

`hours` can also be a number, which applies to every weekday.

## Notes

Workbook's API is internal and undocumented. This CLI validates sessions through `POST /api/auth/handshake`, reads timesheets with `TimeEntryDailyRequest`, inserts rows with `QuickInsertTimeRequest`, and updates cells with `TimeEntryUpdateRequest`.
