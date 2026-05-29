from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def read_json_arg(value: str | None, file_path: str | None = None) -> Any:
    if file_path:
        return json.loads(Path(file_path).expanduser().read_text())
    if value == "-":
        return json.loads(sys.stdin.read())
    if value:
        return json.loads(value)
    raise ValueError("Provide --json, --json-file, or --json - for stdin")


def print_json(data: Any, *, pretty: bool = False) -> None:
    if pretty:
        print(json.dumps(data, indent=2, sort_keys=False))
    else:
        print(json.dumps(data, separators=(",", ":"), sort_keys=False))
