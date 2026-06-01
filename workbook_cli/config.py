from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "workbook-cli"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "workbook-cli"
SESSION_DIR = DATA_DIR / "session_state"
CACHE_DIR = DATA_DIR / "cache"
DEBUG_DIR = DATA_DIR / "debug"

CONFIG_FILE = CONFIG_DIR / ".env"
PROJECT_ENV_FILE = PACKAGE_ROOT / ".env"

load_dotenv(PROJECT_ENV_FILE)
load_dotenv(CONFIG_FILE, override=True)

WORKBOOK_URL = os.environ.get("WORKBOOK_URL", "https://wunderman.workbook.dk").rstrip("/")
WORKBOOK_EMAIL = os.environ.get("WORKBOOK_EMAIL", os.environ.get("MS_EMAIL", ""))
WORKBOOK_PASSWORD = os.environ.get("WORKBOOK_PASSWORD", os.environ.get("MS_PASSWORD", ""))

COOKIES_FILE = SESSION_DIR / "api_cookies.json"
BROWSER_STATE_FILE = SESSION_DIR / "browser_state.json"
JOBS_CACHE_FILE = CACHE_DIR / "jobs.json"

API_TIMEOUT = int(os.environ.get("WORKBOOK_API_TIMEOUT", "30"))
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
