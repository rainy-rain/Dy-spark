"""The commands: login, status, probe, send.

Flow, and why it is split this way:

    login   open a real window, you scan the QR code, the session is saved
    status  confirm the saved session still works before you rely on it
    probe   dump what the message page actually contains, to fix selectors
    send    do the work — dry run unless --yes is also given

`probe` exists because the selectors in `selectors.py` could not be verified
without an account. It is the intended first step once `login` succeeds.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import analyze, console, selectors
from .browser import human_type, open_session, pause
from .config import Config

DIAGNOSTICS_DIR = Path("diagnostics")
LOGIN_WAIT_SECONDS = 300


@dataclass
class Conversation:
    """One row in the private-message list."""

    index: int
    name: str
    has_spark: bool
    # Read from the badge itself, purely so `scan` can be checked by eye:
    # "张三 129 days" is far easier to trust than a bare yes/no.
    spark_days: int | None = None
    spark_variant: str | None = None
    # Avatar URL. Stable across scrolls, unlike `index` — use this to find the
    # row again when it is time to click it.
    identity: str = ""


# The list is virtualised, so collecting it means scrolling through it.
MAX_SCROLL_STEPS = 60
SCROLL_PAUSE_S = 0.7
# Consecutive scrolls that add nothing before calling the end reached.
STAGNANT_LIMIT = 3
# Consecutive "cannot scroll yet" results tolerated before giving up. The list
# is filled asynchronously, so early attempts can legitimately find no scrollable
# container.
SCROLL_ERROR_LIMIT = 6
# Rewinding the list is not instant: setting scrollTop = 0 does not make a
# virtualised list re-render, so the rows have to be watched until they change.
REWIND_ATTEMPTS = 10
REWIND_PAUSE_S = 0.6


# ---------------------------------------------------------------------------
# Small page helpers
# ---------------------------------------------------------------------------


async def _visible(page: Any, selector: str, timeout_ms: int = 1500) -> bool:
    """True if anything matching `selector` is currently on screen."""
    try:
        await page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
        return True
    except Exception:
        return False


def _login_advice(cfg: Config) -> str:
    """What to tell a user who is not logged in.

    Mode-dependent: in attached mode `dspark login` does nothing useful, because
    the session belongs to the browser that was attached to, not to dspark.
    """
    if cfg.browser.cdp_url:
        return "Sign in inside the attached browser window, then run this again."
    return "Run: python -m dspark login"


async def _looks_logged_in(session: Any) -> bool:
    """Is this browser actually signed in?

    Order of evidence, strongest first:

    1. **A visible login prompt means logged out, full stop.** This has to come
       before the cookies. Douyin sets `passport_csrf_token` and `uid_tt` for
       anonymous visitors, so a cookie-first check reports "logged in" for a
       browser sitting on a QR code — which is exactly what happened, on a real
       /chat, under a modal reading 登录后免费畅享高清视频.
    2. Then a session cookie, which cannot exist without a sign-in.
    3. Then a DOM marker, which is the weakest of the three because it was
       guessed at rather than read off the page.
    """
    if await _visible(session.page, selectors.LOGGED_OUT_HINT, timeout_ms=1500):
        return False

    names = await session.cookie_names()
    if any(name in names for name in selectors.LOGGED_IN_COOKIES):
        return True

    return await _visible(session.page, selectors.LOGGED_IN_HINT, timeout_ms=2500)


async def _wait_for_login(session: Any, timeout_s: int = LOGIN_WAIT_SECONDS) -> bool:
    """Block until the user finishes scanning the QR code."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await _looks_logged_in(session):
            return True
        remaining = int(deadline - time.monotonic())
        console.verbose(f"still waiting for login ({remaining}s left)")
        await asyncio.sleep(2)
    return False


async def _goto_messages(cfg: Config, session: Any) -> bool:
    """Navigate to the private-message list. False means we clearly did not arrive.

    Verified on the live site: clicking the message entry while logged out does
    not raise — Douyin just bounces you to the featured feed. Trusting the click
    would leave the caller reading an empty list and blaming the selectors, so
    arrival is confirmed explicitly.
    """
    page = session.page

    async def arrived(timeout_ms: int = 3000) -> bool:
        """Wait for the list to render.

        The real /chat paints loading skeletons first, so a fixed sleep is a
        guess that gets shorter as the network gets slower. Waiting for the
        element is the same code with none of the guessing.
        """
        return await _visible(page, selectors.MESSAGE_LIST, timeout_ms=timeout_ms)

    if cfg.douyin.navigate_via_home:
        await page.goto(cfg.douyin.home_url, wait_until="domcontentloaded")
        await asyncio.sleep(2.0)
        try:
            # Let Playwright wait for the entry rather than assuming it is
            # already painted.
            await page.locator(selectors.MESSAGE_ENTRY).first.click(timeout=10000)
            console.verbose("clicked the message entry")
        except Exception as exc:
            console.warn("Could not click the message entry.")
            console.verbose(f"message entry click failed: {exc}")

    if await arrived(timeout_ms=12000):
        return True

    console.verbose(f"not there yet ({page.url}); trying messages_url directly")
    await page.goto(cfg.douyin.messages_url, wait_until="domcontentloaded")

    if await arrived(timeout_ms=15000):
        return True

    console.warn("The message list never appeared.")
    console.info(f"  ended up at : {page.url}")
    if await _visible(page, selectors.LOGGED_OUT_HINT, timeout_ms=1200):
        console.info("  A 登录 button is on screen, so you are logged out.")
        console.info(f"  {_login_advice(cfg)}")
    else:
        console.info("  Otherwise MESSAGE_LIST is stale: python -m dspark probe")
    return False


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


async def login(cfg: Config) -> int:
    console.step("Login")

    if cfg.browser.cdp_url:
        # In attached mode the browser's own profile holds the session, so there
        # is nothing for dspark to save. Telling someone to scan a QR code that
        # will never appear is worse than saying so plainly.
        console.warn("Attached mode is on (--cdp), so dspark does not manage the login.")
        console.info("Sign in inside that browser window instead, then check with:")
        console.info("    python -m dspark status")
        return 0

    async with open_session(cfg, use_saved_state=False, headless=False) as session:
        await session.page.goto(cfg.douyin.home_url, wait_until="domcontentloaded")

        console.info("A browser window is open.")
        console.info("Scan the QR code with the Douyin app on your phone.")
        console.info(f"Waiting up to {LOGIN_WAIT_SECONDS // 60} minutes...")

        if not await _wait_for_login(session):
            console.error("Timed out. Nothing was saved.")
            return 1

        await session.save_state(cfg.session_file)

    console.ok(f"Login saved to {cfg.session_file}")
    console.info("Later runs reuse it. Delete that file to log in again.")
    console.info("Next step: python -m dspark probe")
    return 0


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


async def status(cfg: Config) -> int:
    console.step("Session status")

    if cfg.browser.cdp_url:
        # In attached mode the session lives in that browser's own profile and
        # the storage-state file is irrelevant. Checking it anyway would report
        # "not logged in" for a browser that is perfectly logged in.
        console.info(f"Attached mode : {cfg.browser.cdp_url}")
        console.info("The login belongs to that browser's profile, not to a file.")
    elif not cfg.session_file.exists():
        console.warn(f"No saved session at {cfg.session_file}")
        console.info("Either run: python -m dspark login")
        console.info("or attach to your own browser: python -m dspark edge")
        return 1
    else:
        saved_at = datetime.fromtimestamp(cfg.session_file.stat().st_mtime)
        age_days = (datetime.now() - saved_at).days
        console.info(f"Session file : {cfg.session_file}")
        console.info(f"Saved        : {saved_at:%Y-%m-%d %H:%M} ({age_days} day(s) ago)")

    async with open_session(cfg, headless=True) as session:
        await session.page.goto(cfg.douyin.home_url, wait_until="domcontentloaded")
        await asyncio.sleep(3.0)

        if await _looks_logged_in(session):
            console.ok("Still logged in.")
            return 0

    console.warn("Not logged in.")
    console.info(_login_advice(cfg))
    return 1


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

# Every element carrying a data-e2e hook, which is the attribute Douyin keeps
# more stable than its hashed class names.
_E2E_SCRIPT = """
() => {
  const rows = [];
  document.querySelectorAll('[data-e2e]').forEach((el) => {
    rows.push({
      e2e:  el.getAttribute('data-e2e'),
      tag:  el.tagName.toLowerCase(),
      text: (el.innerText || '').trim().slice(0, 40),
      cls:  String(el.className || '').slice(0, 70)
    });
  });
  return rows;
}
"""


async def probe(cfg: Config) -> int:
    console.step("Probe")
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    async with open_session(cfg, headless=cfg.browser.headless) as session:
        page = session.page
        await _goto_messages(cfg, session)

        logged_in = await _looks_logged_in(session)
        console.info(f"URL        : {page.url}")
        console.info(f"Logged in  : {logged_in}")

        rows: list[dict[str, Any]] = []
        try:
            rows = await page.evaluate(_E2E_SCRIPT)
        except Exception as exc:
            console.warn(f"Could not read data-e2e hooks: {exc}")

        # Collapse duplicates: only the distinct hook names matter.
        seen: dict[str, dict[str, Any]] = {}
        for row in rows:
            seen.setdefault(row["e2e"], row)

        json_path = DIAGNOSTICS_DIR / f"probe-{stamp}.json"
        html_path = DIAGNOSTICS_DIR / f"probe-{stamp}.html"
        png_path = DIAGNOSTICS_DIR / f"probe-{stamp}.png"

        json_path.write_text(
            json.dumps(
                {"url": page.url, "logged_in": logged_in, "hooks": list(seen.values())},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        html_text = await page.content()
        html_path.write_text(html_text, encoding="utf-8")
        try:
            await page.screenshot(path=str(png_path))
        except Exception as exc:
            console.verbose(f"screenshot failed: {exc}")

        console.ok(f"{len(seen)} distinct data-e2e hook(s) found")
        for hook in sorted(seen.values(), key=lambda r: r["e2e"]):
            text = hook["text"].replace("\n", " ")
            console.info(f"  {hook['e2e']:<34} <{hook['tag']}> {text[:30]}")

        console.info(f"JSON       : {json_path}")
        console.info(f"HTML       : {html_path}")
        console.info(f"Screenshot : {png_path}")

        # Analyse what was just dumped, so the selectors can be worked out
        # without running a second command.
        console.step("Analysis")
        report = analyze.analyse(html_text)
        for line in analyze.summarise(report):
            print(line)

    console.step("What to do with this")
    console.info("Compare the above with dspark/selectors.py.")
    console.info("`python -m dspark analyze` re-runs the analysis on the saved file.")
    return 0


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


async def _row_snapshot(cfg: Config, item: Any) -> tuple[str, Conversation] | None:
    """Parse one rendered row into (identity, conversation)."""
    try:
        html = await item.evaluate("el => el.outerHTML")
    except Exception as exc:
        console.verbose(f"row read failed: {exc}")
        return None

    node = analyze.parse(html or "")
    info = analyze.spark_info(node)
    name = analyze.row_name(node) or "(unnamed)"
    avatar = analyze.row_avatar(node)

    # Identity has to survive scrolling AND stay unique.
    #
    # A row index stops meaning anything once nodes recycle, so it is no good.
    # The avatar URL is stable, but not unique on its own: friends without a
    # custom picture all share Douyin's default avatar asset, so several rows
    # can carry an identical src. Pairing it with the name keeps them apart
    # while still surviving a scroll.
    identity = (
        f"{avatar}|{name}"
        if avatar
        else f"{name}|{info.present}|{info.days}|{info.variant}"
    )

    return identity, Conversation(
        index=-1,
        name=name,
        has_spark=info.present and cfg.sending.allows_variant(info.variant),
        spark_days=info.days,
        spark_variant=info.variant,
        identity=identity,
    )


async def _visible_rows(cfg: Config, session: Any) -> list[Conversation]:
    """Parse whatever rows happen to be rendered right now."""
    items = session.page.locator(selectors.CONVERSATION_ITEM)
    count = await items.count()
    rows: list[Conversation] = []

    for index in range(count):
        snapshot = await _row_snapshot(cfg, items.nth(index))
        if snapshot is not None:
            rows.append(snapshot[1])

    return rows


# Scrolls the conversation list by one screen.
#
# Done in JS rather than with locator.scroll_into_view_if_needed(), because that
# waits for an element to be "stable" — and in a virtualised list the element
# being scrolled is exactly what keeps getting recycled. It failed with
# "Target page, context or browser has been closed" mid-scroll, which stopped
# collection two screens in. Scrolling the container itself has nothing to go
# stale.
_SCROLL_JS = """
(mode) => {
  const row = document.querySelector('[data-e2e="conversation-item"]');
  if (!row) return { error: 'no conversation rows on screen' };

  let el = row.parentElement;
  while (el && el !== document.body) {
    const style = getComputedStyle(el);
    const scrollable = (style.overflowY === 'auto' || style.overflowY === 'scroll')
      && el.scrollHeight > el.clientHeight + 20;
    if (scrollable) break;
    el = el.parentElement;
  }
  if (!el || el === document.body) return { error: 'no scrollable list container' };

  const before = el.scrollTop;
  const max = el.scrollHeight - el.clientHeight;
  if (mode === 'top') {
    el.scrollTop = 0;
  } else {
    // Half a screen, not most of one. The virtualiser can render fewer rows
    // than fit on screen, in which case a 0.85-screen jump steps straight over
    // a band of conversations — which is how a search for a specific friend
    // reported "not in the list" for somebody who was plainly in it.
    el.scrollTop = Math.min(before + el.clientHeight * 0.5, max);
  }
  return { before: before, after: el.scrollTop, max: max };
}
"""


async def _scroll_list(page: Any, mode: str = "down") -> dict[str, Any] | str:
    """Scroll the list. mode is "down" for one screen, "top" to rewind."""
    try:
        result = await page.evaluate(_SCROLL_JS, mode)
    except Exception as exc:
        return f"scroll failed: {exc}"
    if not isinstance(result, dict):
        return f"unexpected scroll result: {result!r}"
    return result


async def _first_visible(cfg: Config, session: Any) -> Conversation | None:
    rows = await _visible_rows(cfg, session)
    return rows[0] if rows else None


async def _rewind_list(cfg: Config, session: Any) -> None:
    """Scroll the conversation list back to the top, and confirm it re-rendered.

    Setting `scrollTop = 0` fixes the position but NOT the rendered rows: the
    list is virtualised and paints from its own state. Collecting during that
    window once produced the *tail* of the list first and missed the top nine
    conversations entirely — while reporting a complete list. So the rows are
    watched until they actually change.
    """
    page = session.page
    started = await _first_visible(cfg, session)
    started_identity = started.identity if started else ""

    for attempt in range(REWIND_ATTEMPTS):
        report = await _scroll_list(page, "top")
        if isinstance(report, str):
            await asyncio.sleep(REWIND_PAUSE_S)
            continue

        if attempt == 0 and report["before"] <= 0:
            console.verbose("the list was already at the top")
            return

        await asyncio.sleep(REWIND_PAUSE_S)
        current = await _first_visible(cfg, session)
        if current is not None and current.identity != started_identity:
            console.verbose(
                f"rewound the list (was {report['before']:.0f}px); "
                f"first row is now {current.name!r}"
            )
            return

    console.verbose(
        "the first row never changed after rewinding; the top may have been missed"
    )


async def _collect_conversations(cfg: Config, session: Any) -> list[Conversation]:
    """Every conversation in the list, not just the ones currently rendered.

    /chat virtualises its list: it keeps roughly a screenful of rows in the DOM
    and recycles them as you scroll. Reading it once therefore returns a window
    onto the list, not the list.

    An earlier version did exactly that and reported 13 conversations with
    complete confidence — the dangerous kind of wrong, because the answer looks
    finished. This walks the list instead: read, scroll, read again, and keep
    whatever is new, identified by avatar URL because a row index stops meaning
    anything once nodes have been recycled.
    """
    page = session.page
    items = page.locator(selectors.CONVERSATION_ITEM)

    # Rewind to the top, and do not believe it until the rows change.
    #
    # Douyin restores the list's scroll position across reloads, so a page left
    # scrolled down comes back scrolled down. See _rewind_list for why the rows
    # have to be watched rather than trusted.
    await _rewind_list(cfg, session)

    # Let the first render settle before walking it: /chat fills the list
    # asynchronously, and scrolling before it overflows finds nothing to scroll.
    previous = -1
    for _ in range(10):
        count = await items.count()
        if count == previous and count > 0:
            break
        previous = count
        await asyncio.sleep(0.5)
    console.verbose(f"first render settled at {previous} row(s)")

    found: dict[str, Conversation] = {}
    order: list[str] = []
    stagnant = 0
    scroll_errors = 0

    for step in range(MAX_SCROLL_STEPS):
        size_before = len(found)

        for convo in await _visible_rows(cfg, session):
            if convo.identity not in found:
                found[convo.identity] = convo
                order.append(convo.identity)

        report = await _scroll_list(page)
        if isinstance(report, str):
            # Not fatal. The list may still be growing, in which case there is
            # legitimately nothing to scroll yet. Retry, but do stop eventually
            # if the container never appears.
            scroll_errors += 1
            console.verbose(f"scroll {step + 1}: {report} (attempt {scroll_errors})")
            if scroll_errors >= SCROLL_ERROR_LIMIT:
                console.verbose("giving up on scrolling; keeping what was collected")
                break
            await asyncio.sleep(SCROLL_PAUSE_S)
            continue

        scroll_errors = 0
        at_bottom = report["after"] >= report["max"] - 2
        console.verbose(
            f"scroll {step + 1}: {len(found)} conversation(s), "
            f"{report['after']:.0f}/{report['max']:.0f}px"
            + (" (bottom)" if at_bottom else "")
        )

        # Reached the bottom and learned nothing new, repeatedly: the list is done.
        if at_bottom and len(found) == size_before:
            stagnant += 1
            if stagnant >= STAGNANT_LIMIT:
                break
        else:
            stagnant = 0

        await asyncio.sleep(SCROLL_PAUSE_S)

    console.verbose(f"collected {len(found)} conversation(s)")
    return [found[key] for key in order]


async def _search_and_click(cfg: Config, session: Any, convo: Conversation) -> bool:
    """One top-to-bottom sweep looking for `convo`, clicking it if found."""
    page = session.page
    items = page.locator(selectors.CONVERSATION_ITEM)

    for attempt in range(MAX_SCROLL_STEPS):
        count = await items.count()
        for index in range(count):
            snapshot = await _row_snapshot(cfg, items.nth(index))
            if snapshot is not None and snapshot[0] == convo.identity:
                console.verbose(
                    f"found {convo.name!r} on screen {attempt + 1} of the search"
                )
                await items.nth(index).click(timeout=8000)
                return True

        report = await _scroll_list(page)
        if isinstance(report, str):
            return False

        console.verbose(
            f"searching for {convo.name!r}: screen {attempt + 1}, "
            f"{report['after']:.0f}/{report['max']:.0f}px"
        )

        # Already at the bottom and still not found: it is not in this list.
        if report["after"] <= report["before"] and attempt > 0:
            return False

        await asyncio.sleep(SCROLL_PAUSE_S)

    return False


async def _open_conversation(
    cfg: Config, session: Any, convo: Conversation, *, sweeps: int = 2
) -> bool:
    """Scroll to a conversation and click it.

    Searches by identity rather than reusing an index from the scan, because the
    list recycles nodes and that index may now point at a different friend.

    Rewinds before every sweep. `_collect_conversations` leaves the list at the
    bottom, and the search only walks downward — so without the rewind it looked
    for the first targets (which live at the top) from the very bottom and
    reported "Could not find ... in the list" for every one of them. Rewinding
    once up front is also not enough: sending a message moves that conversation
    to the top of a recency-ordered list, so the order shifts underneath us.

    Two sweeps, because one occasionally misses. A single sweep found 26 of 29 on
    one run and 29 of 29 on the next, with no code change between them — a
    flake, and in this loop a flake is a friend whose streak breaks. A second
    sweep from the top costs a couple of seconds and removes most of that risk.
    """
    for sweep in range(max(1, sweeps)):
        await _rewind_list(cfg, session)
        if await _search_and_click(cfg, session, convo):
            return True
        if sweep + 1 < sweeps:
            console.verbose(f"{convo.name!r} not found; sweeping again from the top")

    return False


def _print_table(conversations: list[Conversation]) -> None:
    """Every row, so the detection can be checked by eye before sending."""
    header = f"{'#':>3}  {'spark':<5}  {'days':>5}  {'variant':<18}  name"
    console.info(header)
    console.info("-" * len(header))

    for position, convo in enumerate(conversations, start=1):
        mark = "yes" if convo.has_spark else "-"
        days = str(convo.spark_days) if convo.spark_days is not None else "-"
        variant = convo.spark_variant or "-"
        console.info(
            f"{position:>3}  {mark:<5}  {days:>5}  {variant:<18}  {convo.name}"
        )


async def scan(cfg: Config) -> int:
    """List every conversation and whether it has a spark. Sends nothing.

    This exists because the requirement is "only message the ones that already
    have a spark". A yes/no flag is not checkable by eye; a name next to a day
    count is. Run this, read the table, and only then enable sending.
    """
    console.step("Scan")

    async with open_session(cfg) as session:
        if not await _looks_logged_in(session):
            await session.page.goto(cfg.douyin.home_url, wait_until="domcontentloaded")
            await asyncio.sleep(2.0)
            if not await _looks_logged_in(session):
                console.error(f"Not logged in. {_login_advice(cfg)}")
                return 1

        if not await _goto_messages(cfg, session):
            return 1

        conversations = await _collect_conversations(cfg, session)
        if not conversations:
            console.error("No conversations found.")
            console.info("Run `python -m dspark probe` and check the selectors.")
            return 1

        console.info("")
        _print_table(conversations)

        with_spark = [c for c in conversations if c.has_spark]
        console.info("")
        console.ok(
            f"{len(conversations)} conversation(s) found by scrolling the whole "
            f"list, {len(with_spark)} with a spark"
        )

        if cfg.sending.spark_variants:
            console.info(f"variant filter: {', '.join(cfg.sending.spark_variants)}")

        # Report the selection the same way `send` will make it, so the two
        # commands can never disagree about how many people are about to be
        # messaged. An earlier version said "29" here while `send` did 20.
        matched = _matching_targets(cfg, conversations)
        targets, dropped = _apply_cap(cfg, matched)

        console.info(
            f"strategy `{cfg.sending.strategy}` matches {len(matched)} conversation(s); "
            f"max_per_run {cfg.sending.max_per_run} -> {len(targets)} would be messaged"
        )
        _warn_if_capped(cfg, matched, dropped)

        console.info("Nothing was sent.")

    return 0


def _matching_targets(cfg: Config, conversations: list[Conversation]) -> list[Conversation]:
    """Everyone the strategy selects, before the per-run ceiling."""
    strategy = cfg.sending.strategy

    if strategy == "all":
        return list(conversations)

    if strategy == "list":
        wanted = {name.strip() for name in cfg.sending.targets}
        picks = [c for c in conversations if c.name in wanted]
        missing = wanted - {c.name for c in conversations}
        for name in sorted(missing):
            console.warn(f"`{name}` is in sending.targets but is not in the list.")
        return picks

    return [c for c in conversations if c.has_spark]


def _apply_cap(cfg: Config, matched: list[Conversation]) -> tuple[list[Conversation], int]:
    """Apply `max_per_run`. Returns (kept, how many were dropped).

    The dropped count is returned rather than swallowed because a silent
    truncation is the worst possible failure here: the friends left out simply
    lose their streak, and the run reports success while it happens.
    """
    cap = cfg.sending.max_per_run
    if len(matched) <= cap:
        return matched, 0
    return matched[:cap], len(matched) - cap


def _warn_if_capped(cfg: Config, matched: list[Conversation], dropped: int) -> None:
    if not dropped:
        return
    console.warn(
        f"{len(matched)} conversation(s) match, but sending.max_per_run is "
        f"{cfg.sending.max_per_run} — so {dropped} would be skipped and their "
        f"streaks would break."
    )
    console.info(
        f"  Raise `sending.max_per_run` to at least {len(matched)} in config.yaml."
    )


def _select_targets(cfg: Config, conversations: list[Conversation]) -> list[Conversation]:
    """Apply the strategy, then the ceiling. Kept for the tests."""
    matched = _matching_targets(cfg, conversations)
    targets, _ = _apply_cap(cfg, matched)
    return targets


# Reads the composer's current contents.
#
# The composer is a Slate editor (`data-slate-editor="true"`), and an empty one
# is not empty: it holds a zero-width space (U+200B). JS's String.trim() does
# NOT strip that, so without the explicit replace every successful send would
# look like a failed one. Hence the character-class strip here.
_COMPOSER_JS = """
() => {
  const el = document.querySelector(
    'div[data-e2e="msg-input"] [data-slate-editor="true"], '
    + 'div[data-slate-editor="true"][contenteditable="true"], '
    + 'div[contenteditable="true"], textarea'
  );
  if (!el) return null;
  const raw = ('value' in el && el.value !== undefined)
    ? el.value : (el.innerText || el.textContent || '');
  return String(raw).replace(/[\\u200b-\\u200d\\ufeff]/g, '');
}
"""


async def _composer_text(session: Any) -> str:
    """What the composer currently holds, zero-width padding removed.

    Returns "" when the composer cannot be found, which callers treat as "no
    text" — the safe reading, since it only ever suppresses a fallback click.
    """
    try:
        return await session.page.evaluate(_COMPOSER_JS) or ""
    except Exception as exc:
        console.verbose(f"composer read failed: {exc}")
        return ""


async def _input_still_has_text(session: Any) -> bool:
    return bool((await _composer_text(session)).strip())


async def _send_to(cfg: Config, session: Any, convo: Conversation, message: str) -> bool:
    """Open one conversation and send one message."""
    page = session.page

    try:
        if not await _open_conversation(cfg, session, convo):
            console.warn(f"Could not find {convo.name!r} in the list.")
            return False
        await asyncio.sleep(1.5)

        await human_type(page, selectors.MESSAGE_INPUT, message, cfg.browser.typing_delay_ms)
        await asyncio.sleep(0.5)

        # Slate may ignore synthetic input where a textarea would not. Check the
        # text actually landed before pressing Enter, so a silent no-op is
        # reported instead of being mistaken for a sent message.
        landed = await _composer_text(session)
        if message.strip() and message.strip() not in landed:
            console.warn(
                f"The composer did not take the text (holds {landed[:40]!r})."
            )
            console.info("  Re-run with -v to watch the page, or check MESSAGE_INPUT.")
            return False

        # Web chats usually send on Enter.
        await page.keyboard.press("Enter")
        await asyncio.sleep(1.0)

        # Some ignore Enter and need the button.
        if await _input_still_has_text(session):
            console.verbose("Enter did not send; trying the send button")
            button = page.locator(selectors.SEND_BUTTON).first
            if await button.count():
                await button.click(timeout=5000)
                await asyncio.sleep(1.0)

        return True
    except Exception as exc:
        console.verbose(f"send to {convo.name} failed: {exc}")
        return False


async def send(
    cfg: Config, *, confirmed: bool, message: str | None = None
) -> int:
    console.step("Send")

    dry_run = not confirmed

    # `--message` replaces the configured pool for this run. The one-click
    # wrapper asks for the text at the keyboard, and typing it there beats
    # editing config.yaml and starting over.
    pool = [message] if message else list(cfg.sending.messages)
    if not pool:
        console.error("Nothing to send: pass --message, or set sending.messages.")
        return 1

    # The switch guards *sending*, not inspecting. A dry run sends nothing, so
    # requiring `sending.enabled` for it only stops people from looking before
    # they leap — the opposite of what the switch is for.
    if not dry_run and not cfg.sending.enabled:
        console.error(
            "Sending is switched off (`sending.enabled: false` in config.yaml), so "
            "nothing was sent. Turn it on once a dry run looks right."
        )
        return 1

    if dry_run:
        console.warn("DRY RUN - nothing will be sent. Add --yes to send for real.")

    async with open_session(cfg) as session:
        if not await _looks_logged_in(session):
            await session.page.goto(cfg.douyin.home_url, wait_until="domcontentloaded")
            await asyncio.sleep(2.0)
            if not await _looks_logged_in(session):
                console.error(f"Not logged in. {_login_advice(cfg)}")
                return 1

        if not await _goto_messages(cfg, session):
            return 1

        conversations = await _collect_conversations(cfg, session)
        console.info(f"Conversations found: {len(conversations)}")

        if not conversations:
            console.error("No conversations matched CONVERSATION_ITEM.")
            console.info("The selectors need updating: python -m dspark probe")
            return 1

        matched = _matching_targets(cfg, conversations)
        targets, dropped = _apply_cap(cfg, matched)

        if not targets:
            if cfg.sending.strategy == "spark":
                console.ok("No conversation is showing a spark right now.")
            else:
                console.ok("Nobody matched the configured targets.")
            return 0

        _warn_if_capped(cfg, matched, dropped)

        console.info(f"Strategy `{cfg.sending.strategy}` selected {len(targets)} friend(s):")
        for convo in targets:
            mark = "spark" if convo.has_spark else "     "
            console.info(f"  [{mark}] {convo.name}")

        if not dry_run:
            # Say plainly what is about to go out, before it goes out.
            what = pool[0] if len(pool) == 1 else f"one of {len(pool)} variants"
            console.info(f"message: {what!r}")

        sent = 0
        failed = 0

        for position, convo in enumerate(targets, start=1):
            text = random.choice(pool)
            label = f"[{position}/{len(targets)}]"

            if dry_run:
                console.info(f"{label} would send {text!r} to {convo.name}")
                continue

            if await _send_to(cfg, session, convo, text):
                sent += 1
                console.ok(f"{label} sent {text!r} to {convo.name}")
            else:
                failed += 1
                console.warn(f"{label} could not send to {convo.name}")

            if position < len(targets):
                # Random gap: a perfectly regular cadence is easy to spot.
                await pause(*cfg.sending.delay_between_ms)

        console.step("Summary")
        console.info(f"sent={sent}  failed={failed}  dry_run={dry_run}")
        if dry_run:
            console.info("Nothing was actually sent. Re-run with --yes when ready.")

    return 0


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def show_config(cfg: Config) -> int:
    console.step("Resolved configuration")
    print(json.dumps(cfg.as_dict(), ensure_ascii=False, indent=2))
    console.info(f"\nLoaded from: {cfg.source_path}")
    return 0
