from workbook_cli.cli import build_parser


def parse(args: list[str]):
    return build_parser().parse_args(args)


def test_format_before_domain() -> None:
    args = parse(["--format", "table", "timesheet", "show"])

    assert args.format == "table"
    assert args.domain == "timesheet"
    assert args.timesheet_command == "show"


def test_format_between_domain_and_command() -> None:
    args = parse(["timesheet", "--format", "table", "show"])

    assert args.format == "table"
    assert args.timesheet_command == "show"


def test_format_after_leaf_command() -> None:
    args = parse(["timesheet", "show", "--format", "table"])

    assert args.format == "table"
    assert args.timesheet_command == "show"


def test_pretty_after_leaf_command() -> None:
    args = parse(["jobs", "search", "nespresso", "--pretty"])

    assert args.pretty is True
    assert args.query == "nespresso"


def test_json_remains_default() -> None:
    args = parse(["jobs", "search", "nespresso"])

    assert args.format == "json"
    assert args.pretty is False
