---
name: workbook-cli
description: Use when an agent needs to authenticate with Workbook, search Workbook jobs/tasks, inspect timesheets, or submit Workbook timesheet entries through the local workbook-cli command. Use this for Workbook timesheet automation, job/task lookup, and JSON-based timesheet submission.
---

# Workbook CLI

Use `workbook-cli` for Workbook timesheet work. It is designed for agents: JSON is the default output, and timesheet submission accepts JSON input.

## Safety

- Prefer read-only commands first: `me`, `jobs search`, `jobs tasks`, `timesheet show`.
- Before writing timesheets, run `timesheet submit --dry-run`.
- Only run a non-dry-run submit when the requested job IDs, task IDs, dates, hours, and descriptions are clear.
- Do not invent job or task IDs. Search or ask the user.

## Output

JSON is default:

```bash
workbook-cli timesheet show
```

Use tables only for human-facing responses:

```bash
workbook-cli timesheet show --table
```

## Auth

```bash
workbook-cli auth status
workbook-cli me
```

If auth is missing or expired:

```bash
workbook-cli auth
```

Use a visible browser if headless Okta/MFA fails:

```bash
workbook-cli auth --headed
```

## Job And Task Lookup

```bash
workbook-cli jobs search "nespresso"
workbook-cli jobs tasks 465430
workbook-cli jobs refresh
```

Never invent job/task IDs. Use search results or ask the user.

## Timesheet Inspection

```bash
workbook-cli timesheet show
workbook-cli timesheet --week-offset -1 show
```

## Timesheet Submission

Preferred payload flag is `--input-json`.

Dry run first:

```bash
workbook-cli timesheet submit --dry-run --input-json '[
  {
    "job_id": 465430,
    "task_id": 2886954,
    "description": "Reviewed campaign requirements and prepared implementation notes.",
    "hours": {"Mon": 2, "Tue": 1.5}
  }
]'
```

Submit after confirmation:

```bash
workbook-cli timesheet submit --input-json '[
  {
    "job_id": 465430,
    "task_id": 2886954,
    "description": "Reviewed campaign requirements and prepared implementation notes.",
    "hours": {"Mon": 2, "Tue": 1.5}
  }
]'
```

Use stdin for generated payloads:

```bash
printf '%s\n' '[{"job_id":465430,"task_id":2886954,"hours":{"Mon":1},"description":"Reviewed work."}]' \
  | workbook-cli timesheet submit --dry-run --input-json -
```

## Payload Shape

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

`hours` may also be a number, which applies to every weekday.
