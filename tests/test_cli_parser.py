from workbook_cli.cli import build_parser, normalize_legacy_submit_json


def parse(args: list[str]):
    return build_parser().parse_args(args)


def test_table_before_domain() -> None:
    args = parse(["--table", "timesheet", "show"])

    assert args.format == "table"
    assert args.domain == "timesheet"
    assert args.timesheet_command == "show"


def test_table_between_domain_and_command() -> None:
    args = parse(["timesheet", "--table", "show"])

    assert args.format == "table"
    assert args.timesheet_command == "show"


def test_table_after_leaf_command() -> None:
    args = parse(["timesheet", "show", "--table"])

    assert args.format == "table"
    assert args.timesheet_command == "show"


def test_json_after_table_wins() -> None:
    args = parse(["--table", "timesheet", "show", "--json"])

    assert args.format == "json"


def test_pretty_after_leaf_command() -> None:
    args = parse(["jobs", "search", "nespresso", "--pretty"])

    assert args.pretty is True
    assert args.query == "nespresso"


def test_json_remains_default() -> None:
    args = parse(["jobs", "search", "nespresso"])

    assert args.format == "json"
    assert args.pretty is False


def test_format_alias_still_works() -> None:
    args = parse(["timesheet", "show", "--format", "table"])

    assert args.format == "table"


def test_legacy_submit_json_payload_is_normalized() -> None:
    args = normalize_legacy_submit_json([
        "timesheet",
        "submit",
        "--json",
        '[{"job_id":1,"hours":{"Mon":1}}]',
        "--table",
    ])

    assert args == [
        "timesheet",
        "submit",
        "--input-json",
        '[{"job_id":1,"hours":{"Mon":1}}]',
        "--table",
    ]


def test_legacy_submit_json_stdin_is_normalized() -> None:
    args = normalize_legacy_submit_json(["timesheet", "submit", "--json", "-"])

    assert args == ["timesheet", "submit", "--input-json", "-"]
