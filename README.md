# workbook-cli

Agent-friendly CLI for Workbook timesheets. It uses Playwright to authenticate through Workbook/Okta, stores its own session state, and talks directly to Workbook's internal JSON API.

The CLI is designed for agents: input is JSON on the command line or stdin, and output is JSON by default. For human use, pass `--table` to render Rich tables. Use `--json` to explicitly request JSON output.

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
~/.local/share/workbook-cli/submissions/
~/.local/share/workbook-cli/logs/
```

## Auth

```bash
workbook-cli auth
workbook-cli auth --headed
workbook-cli auth status --pretty
workbook-cli --table auth status
workbook-cli auth status --table
workbook-cli auth clear
```

Headless auth uses `WORKBOOK_EMAIL` and `WORKBOOK_PASSWORD` from `~/.config/workbook-cli/.env`, fills the Okta/Microsoft login form, prints the MFA number when one is displayed, and saves Workbook cookies.

`auth status` checks only the saved session. It does not open a browser. If the browser is missing, repair it with:

```bash
~/.local/lib/workbook-cli/.venv/bin/python -m playwright install chromium
```

## Jobs

```bash
workbook-cli jobs refresh --pretty
workbook-cli jobs search nespresso --pretty
workbook-cli jobs tasks 465430 --pretty
workbook-cli --table jobs search nespresso
workbook-cli --table jobs tasks 465430
workbook-cli jobs search nespresso --table
workbook-cli jobs tasks 465430 --table
```

`jobs list` and `jobs search` use the local cache when it exists. They do not require authentication. Search includes job numbers and task numbers.

## Timesheets

Show current week:

```bash
workbook-cli timesheet show --pretty
workbook-cli --table timesheet show
workbook-cli timesheet show --table
```

Submit JSON:

```bash
workbook-cli timesheet submit --input-json '[
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
  | workbook-cli timesheet submit --input-json -
```

Dry run:

```bash
workbook-cli timesheet submit --dry-run --input-json '[{"job_id":465430,"task_id":2886954,"hours":{"Mon":1}}]' --pretty
workbook-cli --table timesheet submit --dry-run --input-json '[{"job_id":465430,"task_id":2886954,"hours":{"Mon":1}}]'
workbook-cli timesheet submit --dry-run --input-json '[{"job_id":465430,"task_id":2886954,"hours":{"Mon":1}}]' --table
```

Each live submission uses a durable journal. The CLI reads the changed cell back from Workbook before it reports success. If a run stops or a response is uncertain, use the journal path from the result:

```bash
workbook-cli timesheet submit --resume ~/.local/share/workbook-cli/submissions/submission_8092_2026-09-07_abcd1234.json --pretty
```

You can select a journal path for a new submission:

```bash
workbook-cli timesheet submit --journal ./submission.json --json-file ./timesheet.json
```

The CLI does not retry a write when Workbook might already have accepted it. It first uses the saved pre-write state and a readback to resolve the result. Mutation logs do not store cookies, credentials, or description text.

A completed journal also prevents an unintended repeat of the same batch. Use a new `--journal` path only when you intend to apply the same batch again.

Previous week:

```bash
workbook-cli timesheet --week-offset -1 show --pretty
workbook-cli timesheet --week-offset -1 submit --input-json '[...]'
```

## Clear a timesheet entry

Use `timesheet show` to find the entry ID in the correct week. Replace `ENTRY_ID` with that ID. Preview the change first.

```bash
workbook-cli timesheet delete ENTRY_ID
workbook-cli timesheet delete ENTRY_ID --confirm
```

For MCP, use `timesheet_delete` with `entry_id`. Set `confirm: true` only after explicit approval. For a different week, use `week_offset` in MCP or `--week-offset` before `delete` in the CLI.

The command sets hours to zero. It does not request a row deletion. It checks the entry again after the update and does not retry a write. Regular batch submissions still skip zero-hour values.

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

`--input-json` is the preferred payload flag. The older `timesheet submit --json '[...]'` form still works for compatibility, but `--json` by itself means JSON output.

`hours` can also be a number, which applies to every weekday.

Hours must be finite and non-negative. Job IDs and task IDs must be valid positive integers. The CLI rejects the complete batch before any write if one field is invalid.

## Notes

Workbook's API is internal and undocumented. This CLI validates sessions through `POST /api/auth/handshake`, reads timesheets with `TimeEntryDailyRequest`, inserts rows with `QuickInsertTimeRequest`, and updates cells with `TimeEntryUpdateRequest`.
