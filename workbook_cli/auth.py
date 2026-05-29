from __future__ import annotations

import json
import re

from playwright.sync_api import sync_playwright
from rich.console import Console

from . import config

console = Console(stderr=True)


def save_cookies(cookies: list[dict]) -> None:
    config.ensure_dirs()
    config.COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
    config.COOKIES_FILE.chmod(0o600)


def load_cookies() -> list[dict]:
    if not config.COOKIES_FILE.exists():
        return []
    try:
        data = json.loads(config.COOKIES_FILE.read_text())
    except Exception:
        return []
    return data if isinstance(data, list) else []


def clear_auth_state() -> None:
    for path in (config.COOKIES_FILE, config.BROWSER_STATE_FILE):
        if path.exists():
            path.unlink()


def _enter_email(page, email: str) -> bool:
    if not email:
        return False
    try:
        page.wait_for_selector('input[type="email"]', timeout=10000)
        page.fill('input[type="email"]', email)
        page.click('input[type="submit"]')
        page.wait_for_timeout(2500)
        return True
    except Exception:
        return False


def _enter_password(page, password: str) -> bool:
    if not password:
        return False
    for selector in (
        '[name="credentials.passcode"]',
        'input[type="password"]:visible',
        'input[type="password"]',
    ):
        try:
            page.wait_for_selector(selector, timeout=12000)
            page.fill(selector, password)
            break
        except Exception:
            continue
    else:
        return False

    for selector in (
        'button[type="submit"]',
        'input[type="submit"]',
        'input[value="Sign in"]',
        "#okta-signin-submit",
    ):
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=2000):
                button.click()
                page.wait_for_timeout(2500)
                return True
        except Exception:
            continue
    return True


def _find_mfa_number(page) -> str | None:
    try:
        value = page.evaluate("""() => {
            for (const sel of [
                '[data-se="challenge-number"]',
                '[data-se="number-challenge"]',
                '[class*="number-challenge"]',
                '[class*="challenge-number"]'
            ]) {
                const el = document.querySelector(sel);
                const text = el?.textContent?.trim() ?? '';
                if (/^\\d{1,3}$/.test(text)) return text;
            }
            let best = null;
            let bestSize = 0;
            for (const el of document.querySelectorAll('h1,h2,h3,span,div,p,strong,b')) {
                const text = el.textContent?.trim() ?? '';
                if (!/^\\d{1,3}$/.test(text)) continue;
                const rect = el.getBoundingClientRect();
                if (!rect.width || !rect.height) continue;
                const size = parseFloat(getComputedStyle(el).fontSize);
                if (size > bestSize) { best = text; bestSize = size; }
            }
            return best;
        }""")
        return value if value else None
    except Exception:
        return None


def _wait_for_mfa_or_workbook(page) -> None:
    mfa_number = None
    for _ in range(40):
        page.wait_for_timeout(500)
        if "workbook.dk" in page.url and "login" not in page.url:
            return
        mfa_number = _find_mfa_number(page)
        if mfa_number:
            break

    if mfa_number:
        console.print(
            f"\n[bold yellow]MFA Verification: tap "
            f"[bold white on blue] {mfa_number} [/]"
            f" in your authenticator app[/]\n"
        )
    else:
        console.print("[yellow]Approve the MFA push notification if prompted...[/]")

    try:
        page.wait_for_url(re.compile(r".*workbook\.dk.*"), timeout=180000)
        page.wait_for_timeout(5000)
    except Exception as exc:
        console.print(f"[yellow]Timed out waiting for Workbook redirect: {exc}[/]")


def login_via_browser(*, headless: bool = True) -> list[dict]:
    config.ensure_dirs()
    if headless and (not config.WORKBOOK_EMAIL or not config.WORKBOOK_PASSWORD):
        raise RuntimeError("Headless auth requires WORKBOOK_EMAIL and WORKBOOK_PASSWORD")

    console.print("[cyan]Starting Workbook auth...[/]" if headless else "[cyan]Opening browser for Workbook auth...[/]")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=[] if headless else ["--start-maximized"])
        context_options = {"viewport": {"width": 1280, "height": 720}} if headless else {"no_viewport": True}
        if config.BROWSER_STATE_FILE.exists():
            context_options["storage_state"] = str(config.BROWSER_STATE_FILE)
        context = browser.new_context(**context_options)
        page = context.new_page()

        page.goto(config.WORKBOOK_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        login_url = page.url.lower()
        on_login_page = "login.microsoft" in login_url or "okta" in login_url
        if on_login_page:
            _enter_email(page, config.WORKBOOK_EMAIL)
            _enter_password(page, config.WORKBOOK_PASSWORD)
            _wait_for_mfa_or_workbook(page)
        else:
            try:
                page.wait_for_url(re.compile(r".*workbook\.dk.*"), timeout=30000)
            except Exception:
                pass

        page.goto(config.WORKBOOK_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        cookies = context.cookies()
        context.storage_state(path=str(config.BROWSER_STATE_FILE))
        config.BROWSER_STATE_FILE.chmod(0o600)
        context.close()
        browser.close()

    save_cookies(cookies)
    return cookies
