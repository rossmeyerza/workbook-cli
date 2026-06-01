from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from rich.console import Console

from . import config

console = Console(stderr=True)


class AuthDebug:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.dir: Path | None = None
        if enabled:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.dir = config.DEBUG_DIR / f"auth-{stamp}"
            self.dir.mkdir(parents=True, exist_ok=True)

    def capture(self, page, label: str) -> None:
        if not self.enabled or self.dir is None:
            return

        safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "-", label).strip("-")
        screenshot = self.dir / f"{safe_label}.png"
        dom_json = self.dir / f"{safe_label}.json"

        try:
            page.screenshot(path=str(screenshot), full_page=True)
        except Exception as exc:
            console.print(f"[dim]Could not save auth screenshot {safe_label}: {exc}[/]")

        try:
            data = page.evaluate("""() => ({
                url: location.href,
                title: document.title,
                inputs: [...document.querySelectorAll('input')].map((el) => ({
                    type: el.getAttribute('type'),
                    name: el.getAttribute('name'),
                    id: el.id,
                    autocomplete: el.getAttribute('autocomplete'),
                    placeholder: el.getAttribute('placeholder'),
                    value: el.value ? '<redacted>' : '',
                    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                })),
                buttons: [...document.querySelectorAll('button,input[type=button],input[type=submit],a')].map((el) => ({
                    tag: el.tagName,
                    type: el.getAttribute('type'),
                    name: el.getAttribute('name'),
                    id: el.id,
                    href: el.href || '',
                    text: (el.innerText || el.value || '').trim().slice(0, 120),
                    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                })),
                bodyText: document.body.innerText.slice(0, 2000)
            })""")
            dom_json.write_text(json.dumps(self._redact(data), indent=2))
            dom_json.chmod(0o600)
        except Exception as exc:
            console.print(f"[dim]Could not save auth DOM {safe_label}: {exc}[/]")

    def announce(self) -> None:
        if self.enabled and self.dir is not None:
            console.print(f"[yellow]Auth debug artifacts: {self.dir}[/]")

    def _redact(self, value):
        secrets = [config.WORKBOOK_EMAIL, config.WORKBOOK_PASSWORD]
        if isinstance(value, str):
            redacted = value
            for secret in secrets:
                if secret:
                    redacted = redacted.replace(secret, "<redacted>")
            return redacted
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, dict):
            return {key: self._redact(item) for key, item in value.items()}
        return value


def _saml_url() -> str:
    return f"{config.WORKBOOK_URL.rstrip('/')}/api/auth/saml"


def _workbook_host() -> str:
    return urlparse(config.WORKBOOK_URL).netloc


def _workbook_url_pattern() -> re.Pattern:
    host = re.escape(_workbook_host())
    return re.compile(rf".*{host}.*")


def _is_login_page(page) -> bool:
    url = page.url.lower()
    if "login.microsoft" in url or "okta" in url:
        return True
    try:
        return bool(page.locator('input[type="email"], input[type="password"], [name="credentials.passcode"]').count())
    except Exception:
        return False


def _click_okta_login_if_present(page) -> bool:
    try:
        clicked = page.evaluate("""() => {
            const controls = [...document.querySelectorAll('a,button,input[type="button"],input[type="submit"]')];
            const target = controls.find((el) => {
                const text = `${el.innerText || ''} ${el.value || ''} ${el.getAttribute('aria-label') || ''} ${el.href || ''}`;
                return /okta|single sign|sso|saml/i.test(text);
            });
            if (!target) return false;
            target.click();
            return true;
        }""")
        if clicked:
            console.print("[dim]  Clicked Workbook Okta login[/]")
            page.wait_for_timeout(3000)
            return True
    except Exception:
        pass
    return False


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
        for selector in (
            'input[type="email"]',
            'input[name="identifier"]',
            'input[name="loginfmt"]',
            'input[name="username"]',
            '[name="credentials.username"]',
        ):
            try:
                page.wait_for_selector(selector, timeout=3000)
                page.fill(selector, email)
                break
            except Exception:
                continue
        else:
            return False

        for selector in (
            'input[type="submit"]',
            'button[type="submit"]',
            "#idSIButton9",
            "#okta-signin-submit",
        ):
            try:
                button = page.locator(selector).first
                if button.is_visible(timeout=2000):
                    button.click()
                    break
            except Exception:
                continue

        console.print(f"[dim]  Entered email: {email}[/]")
        page.wait_for_timeout(3000)
        return True
    except Exception as exc:
        console.print(f"[red]Failed to enter email: {exc}[/]")
        return False


def _enter_password(page, password: str) -> bool:
    if not password:
        return False
    try:
        for selector in (
            '[name="credentials.passcode"]',
            'input[type="password"]:visible',
        ):
            try:
                page.wait_for_selector(selector, timeout=15000)
                page.wait_for_timeout(500)
                page.fill(selector, password)
                break
            except Exception:
                continue
        else:
            console.print("[red]Could not find password field[/]")
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
                    break
            except Exception:
                continue

        console.print("[dim]  Entered password[/]")
        page.wait_for_timeout(3000)
        return True
    except Exception as exc:
        console.print(f"[red]Failed to enter password: {exc}[/]")
        return False


def _find_mfa_number(page) -> str | None:
    return page.evaluate("""() => {
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


def _wait_for_mfa_or_workbook(page) -> None:
    console.print("[dim]Waiting for MFA challenge...[/]")
    mfa_number = None

    for _ in range(30):
        page.wait_for_timeout(500)
        mfa_number = _find_mfa_number(page)
        if mfa_number:
            break
        try:
            url = page.url.lower()
            if _workbook_host().lower() in url and "login" not in url and "authn" not in url:
                return
        except Exception:
            pass

    if mfa_number:
        console.print(
            f"\n[bold yellow]MFA Verification: tap"
            f" [bold white on blue] {mfa_number} [/]"
            f" in your authenticator app[/]\n"
        )
    else:
        console.print("[yellow]Approve the MFA push notification on your phone...[/]")

    console.print("[dim]Waiting for MFA approval (up to 3 minutes)...[/]")
    try:
        page.wait_for_url(_workbook_url_pattern(), timeout=180000)
        page.wait_for_timeout(8000)
    except Exception as exc:
        console.print(f"[yellow]Timed out waiting for Workbook redirect: {exc}[/]")


def login_via_browser(*, headless: bool = True, debug_auth: bool = False) -> list[dict]:
    config.ensure_dirs()
    if headless and (not config.WORKBOOK_EMAIL or not config.WORKBOOK_PASSWORD):
        raise RuntimeError("Headless auth requires WORKBOOK_EMAIL and WORKBOOK_PASSWORD")

    console.print("[cyan]Starting Workbook auth...[/]" if headless else "[cyan]Opening browser for Workbook auth...[/]")
    debug = AuthDebug(debug_auth)

    with sync_playwright() as p:
        if headless:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 720})
        else:
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
            context = browser.new_context(no_viewport=True)
        if debug.enabled and debug.dir is not None:
            context.tracing.start(screenshots=True, snapshots=True, sources=False)
        page = context.new_page()

        page.goto(config.WORKBOOK_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        debug.capture(page, "01-workbook-open")

        if _click_okta_login_if_present(page):
            debug.capture(page, "02-after-okta-click")
        elif not _is_login_page(page):
            page.goto(_saml_url(), wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            debug.capture(page, "02-after-saml-fallback")

        current_url = page.url
        on_login_page = (
            "login.microsoftonline.com" in current_url
            or "login.microsoft" in current_url
            or "okta" in current_url.lower()
            or _is_login_page(page)
        )

        if on_login_page and config.WORKBOOK_EMAIL:
            _enter_email(page, config.WORKBOOK_EMAIL)
            debug.capture(page, "03-after-email")

        if on_login_page and config.WORKBOOK_PASSWORD:
            _enter_password(page, config.WORKBOOK_PASSWORD)
            debug.capture(page, "04-after-password")

        if on_login_page:
            _wait_for_mfa_or_workbook(page)
            debug.capture(page, "05-after-mfa-wait")

        try:
            page.goto(config.WORKBOOK_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(8000)
            debug.capture(page, "06-workbook-final")
        except Exception:
            pass

        cookies = context.cookies()
        context.storage_state(path=str(config.BROWSER_STATE_FILE))
        config.BROWSER_STATE_FILE.chmod(0o600)
        if debug.enabled and debug.dir is not None:
            context.tracing.stop(path=str(debug.dir / "trace.zip"))
        context.close()
        browser.close()

    debug.announce()
    return cookies
