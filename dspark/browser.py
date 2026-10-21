"""Playwright session handling.

Login persistence
-----------------
The session is stored with Playwright's own `storageState` — cookies plus
localStorage, serialised to JSON. This is the same approach laizan takes: its
`ipc/auth.ts` is barely twenty lines and all it does is call
`loginAndStorageState()` and remember whether a saved state exists. The browser
opens once, *you* scan the QR code, and every later run reuses the JSON.

Nothing here ever types a password or a verification code. If Douyin wants a
human, the run stops and says so.
"""

from __future__ import annotations

import asyncio
import os
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from . import console, links
from .config import Config

# Playwright's bundled Chromium advertises "HeadlessChrome" in its user agent,
# which is a needless giveaway. This is an ordinary desktop Chrome string.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# `playwright install chromium` normally downloads into a per-user cache outside
# the project (on Windows, %LOCALAPPDATA%\ms-playwright). Keeping the copy
# inside the project instead makes the tool self-contained: move the folder to
# another machine and it still runs, without touching that machine's AppData.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_BROWSERS = PROJECT_ROOT / ".browsers"


def use_local_browsers() -> None:
    """Point Playwright at the in-project browser copy, when there is one."""
    if LOCAL_BROWSERS.is_dir() and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(LOCAL_BROWSERS)
        console.verbose(f"using bundled browsers at {LOCAL_BROWSERS}")


def require_playwright() -> None:
    """Fail with an actionable message instead of a bare ImportError."""
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        console.remedy(
            "Playwright is not installed, so no browser can be driven.",
            [
                "From the project folder:",
                r"   .venv\Scripts\pip install -r requirements.txt",
                "   (macOS / Linux: .venv/bin/pip install -r requirements.txt)",
                "If you need `dspark login` rather than `dspark edge`, also run:",
                "   python -m playwright install chromium",
            ],
            links.PLAYWRIGHT,
        )
        raise SystemExit(1) from None


async def pause(low_ms: int, high_ms: int) -> None:
    """Sleep for a random interval in the given range."""
    await asyncio.sleep(random.randint(low_ms, high_ms) / 1000)


@dataclass
class Session:
    playwright: Any
    browser: Any
    context: Any
    page: Any
    # False when we attached to a browser the user already had open. In that
    # case the browser is theirs and must be left running on the way out.
    owns_browser: bool = True

    async def save_state(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.context.storage_state(path=str(path))

    async def cookie_names(self) -> set[str]:
        return {cookie["name"] for cookie in await self.context.cookies()}


def _pick_page(context: Any, prefer: str = "/chat") -> Any:
    """An existing tab is better than a new one: it already carries the session."""
    pages = [p for p in context.pages if not p.is_closed()]
    for page in pages:
        if prefer in (page.url or ""):
            return page
    return pages[0] if pages else None


@asynccontextmanager
async def open_session(
    cfg: Config,
    *,
    use_saved_state: bool = True,
    headless: bool | None = None,
    cdp_url: str | None = None,
) -> AsyncIterator[Session]:
    """Open a browser, or attach to one that is already open.

    Passing `cdp_url` attaches to a browser the user started themselves (Edge
    with `--remote-debugging-port`). That is the difference between "log in
    again with a QR code" and "use the session you already have".
    """
    require_playwright()
    use_local_browsers()
    from playwright.async_api import async_playwright

    if headless is None:
        headless = cfg.browser.headless

    cdp_url = cdp_url or cfg.browser.cdp_url or None
    state_path = cfg.session_file
    reuse = use_saved_state and state_path.exists()

    playwright = await async_playwright().start()

    if cdp_url:
        console.info(f"Attaching to the browser at {cdp_url} ...")
        try:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:
            console.remedy(
                f"Could not attach to a browser at {cdp_url}.",
                [
                    "Start one first, in this same folder:",
                    "   python -m dspark edge",
                    "It opens its OWN browser profile, so any Edge or Chrome you "
                    "already have open is left alone.",
                    "Then sign in to Douyin once in the window it opens.",
                    "For a full environment check, run scan.bat — step 1 checks "
                    "all eight prerequisites and says how to fix each one.",
                ],
                links.INSTALL,
            )
            console.verbose(f"connect_over_cdp failed: {exc}")
            await playwright.stop()
            raise SystemExit(1) from None

        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = _pick_page(context)
        if page is None:
            page = await context.new_page()

        console.ok(f"Attached. Existing tab: {page.url}")
        owns_browser = False
    else:
        console.verbose(f"launching chromium (headless={headless}, reuse_login={reuse})")
        browser = await playwright.chromium.launch(
            headless=headless,
            slow_mo=cfg.browser.slow_mo_ms or None,
            # Removes the automation marker Chromium sets on navigator. Without
            # it Douyin's own front-end occasionally misbehaves in ways that look
            # like selector bugs but are not.
            args=["--disable-blink-features=AutomationControlled"],
        )

        context_kwargs: dict[str, Any] = {
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "viewport": {"width": 1440, "height": 900},
            "user_agent": USER_AGENT,
        }
        if reuse:
            context_kwargs["storage_state"] = str(state_path)

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        owns_browser = True

    session = Session(playwright, browser, context, page, owns_browser=owns_browser)
    try:
        yield session
    finally:
        console.verbose("closing browser")
        # Cleanup must never turn a finished run into a traceback. Every one of
        # these throws if the user already closed the window themselves - which
        # is exactly what `pick` tells them to do, and what a curious user does
        # during `login`. A bare try/finally does NOT swallow that: the
        # exception escapes and the run looks like a crash.
        if session.owns_browser:
            closers = (
                ("context", context.close),
                ("browser", browser.close),
                ("playwright", playwright.stop),
            )
        else:
            # Someone else's browser: disconnect, do not shut it down.
            closers = (("playwright", playwright.stop),)

        for label, closer in closers:
            try:
                await closer()
            except Exception as exc:
                console.verbose(f"{label} close ignored: {type(exc).__name__}: {exc}")


async def human_type(page: Any, selector: str, text: str, delay: tuple[int, int]) -> None:
    """Type into the composer with an uneven per-keystroke delay.

    Two things this is not:

    * Not `fill()`. The composer is a Slate editor
      (`div[data-slate-editor="true"]`), not an `<input>`, and `fill()` does
      nothing to it. It needs a click to focus and then real key events.
    * Not a constant delay. A perfectly even typing rhythm is one of the easiest
      things for a site to flag, so the gap is randomised per character.
    """
    element = page.locator(selector).first
    await element.click()
    # Let Slate settle into its focused state before the first keystroke.
    await asyncio.sleep(0.25)

    for char in text:
        await page.keyboard.type(char)
        await asyncio.sleep(random.randint(delay[0], delay[1]) / 1000)
