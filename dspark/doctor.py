"""Check that everything dspark needs is actually present, and say how to fix it.

Written for the fresh-clone case. `git clone` brings the source and nothing else:
no virtualenv, no browser, no `config.yaml`, no saved login. Each of those fails
in a different way, and the original messages said what broke without saying what
to do about it — which is fine on the machine it was written on and useless to
anyone else.

Two smaller things this gets right, because they surprise people:

  * Edge or Chrome being installed is enough to *attach* to a browser, so
    Playwright's own 700 MB Chromium is only needed for `login` (or any run
    without `--cdp`). Not having it is therefore a warning, not a blocker.
  * "Not logged in" has two different fixes depending on the mode, and the check
    says which one applies.
"""

from __future__ import annotations

import os
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import cdp, console, links
from .config import DEFAULT_CONFIG_PATH, Config, ConfigError

MIN_PYTHON = (3, 10)

# Kept local so the check bodies read plainly; the values live in links.py so
# they cannot drift away from the README's own links.
REPO_URL = links.REPO
README_URL = links.INSTALL
TEMPLATE_URL = links.TEMPLATE

PYTHON_DOCS = links.PYTHON
PLAYWRIGHT_DOCS = links.PLAYWRIGHT
EDGE_DOCS = links.EDGE
DOUYIN_URL = links.DOUYIN

NETWORK_TIMEOUT_S = 4.0


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""
    problem: str = ""
    fix: list[str] = field(default_factory=list)
    docs: str | None = None
    # A warning still gets printed with its fix, but does not fail the run.
    blocking: bool = True


# ---------------------------------------------------------------------------
# individual checks
# ---------------------------------------------------------------------------


def _check_python() -> Result:
    have = sys.version_info[:2]
    good = have >= MIN_PYTHON
    return Result(
        name="python",
        ok=good,
        detail=f"{have[0]}.{have[1]} (need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)",
        problem=(
            f"Python {have[0]}.{have[1]} is too old. dspark needs "
            f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer."
        ),
        fix=[
            "Install Python 3.12 from the link below.",
            "On Windows you can also run: winget install Python.Python.3.12",
            "Then rebuild the virtualenv: python -m venv .venv",
        ],
        docs=PYTHON_DOCS,
    )


def _check_config(path: Path) -> Result:
    if not path.exists():
        return Result(
            name="config.yaml",
            ok=False,
            detail=f"missing ({path})",
            problem=f"{path} does not exist. A clone ships only the template.",
            fix=[
                "copy config.example.yaml config.yaml",
                "   (macOS / Linux: cp config.example.yaml config.yaml)",
                "Leave `sending.enabled: false` until a dry run looks right.",
            ],
            docs=README_URL,
        )

    try:
        Config.load(path)
    except ConfigError as exc:
        return Result(
            name="config.yaml",
            ok=False,
            detail="invalid",
            problem=str(exc),
            fix=[
                "Open config.yaml and correct the key named above.",
                f"The template with working defaults: {TEMPLATE_URL}",
            ],
            docs=README_URL,
        )

    return Result(name="config.yaml", ok=True, detail=str(path))


def _check_playwright() -> Result:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return Result(
            name="playwright",
            ok=False,
            detail="not installed",
            problem="The Playwright package is not installed, so no browser can be driven.",
            fix=[
                "From the project folder:",
                r"   .venv\Scripts\pip install -r requirements.txt",
                "   (macOS / Linux: .venv/bin/pip install -r requirements.txt)",
            ],
            docs=PLAYWRIGHT_DOCS,
        )
    return Result(name="playwright", ok=True, detail="installed")


def _playwright_roots() -> list[Path]:
    roots: list[Path] = []
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override:
        roots.append(Path(override))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "ms-playwright")
    roots.append(Path.home() / ".cache" / "ms-playwright")
    return roots


def _playwright_chromium() -> Path | None:
    patterns = (
        "chromium-*/chrome-win/chrome.exe",
        "chromium-*/chrome-linux/chrome",
        "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
    )
    for root in _playwright_roots():
        if not root.is_dir():
            continue
        for pattern in patterns:
            found = sorted(root.glob(pattern))
            if found:
                return found[-1]
    return None


def _check_browser() -> Result:
    """A system browser is enough: `dspark edge` attaches to it over CDP."""
    found = cdp.find_browser()
    if found:
        exe, name = found
        return Result(name="browser", ok=True, detail=f"{name} ({exe})")
    return Result(
        name="browser",
        ok=False,
        detail="no Edge or Chrome found",
        problem=(
            "No Microsoft Edge or Google Chrome was found. One of them is what "
            "dspark drives."
        ),
        fix=[
            "Install Microsoft Edge (fastest, and no 700 MB download for dspark):",
            f"   {EDGE_DOCS}",
            "Or install Google Chrome: https://www.google.com/chrome/",
            "Or let Playwright supply its own Chromium:",
            "   python -m playwright install chromium",
        ],
        docs=EDGE_DOCS,
    )


def _check_chromium() -> Result:
    found = _playwright_chromium()
    if found:
        return Result(name="chromium", ok=True, detail=str(found))
    return Result(
        name="chromium",
        ok=False,
        blocking=False,
        detail="not installed (only needed for `login`)",
        problem=(
            "Playwright's bundled Chromium is not installed. Only the `login` "
            "command (and any run without --cdp) needs it."
        ),
        fix=[
            "If you use `python -m dspark edge` and pass --cdp, ignore this.",
            "Otherwise install it once (about 700 MB):",
            "   python -m playwright install chromium",
        ],
        docs=PLAYWRIGHT_DOCS,
    )


def _port_from(url: str) -> int:
    try:
        tail = url.rsplit(":", 1)[1]
        return int(tail.strip("/").split("/")[0])
    except (IndexError, ValueError):
        return cdp.DEFAULT_PORT


def _check_login(cfg: Config) -> Result:
    path = Path(cfg.session_file)
    if path.exists():
        return Result(name="saved login", ok=True, detail=str(path))
    return Result(
        name="saved login",
        ok=False,
        blocking=False,
        detail="none saved yet",
        problem=(
            "No saved Douyin login. Depending on how you run dspark, that is "
            "either expected or the thing to fix."
        ),
        fix=[
            "Using `dspark edge` + --cdp: just sign in once in the window it "
            "opened. The profile remembers it; nothing is written here.",
            "Using `dspark login`: run it and scan the QR code once.",
        ],
        docs=README_URL,
    )


def _check_attachable(cfg: Config) -> Result:
    url = cfg.browser.cdp_url or f"http://127.0.0.1:{cdp.DEFAULT_PORT}"
    info = cdp.devtools_version(_port_from(url))
    if info:
        return Result(
            name="debug port",
            ok=True,
            detail=f"{info.get('Browser', 'browser')} on {url}",
        )
    return Result(
        name="debug port",
        ok=False,
        blocking=False,
        detail=f"nothing listening on {url}",
        problem=(
            f"Nothing is listening on {url}, so dspark cannot attach to a "
            "browser yet."
        ),
        fix=[
            "Run this first, in this same folder:",
            "   python -m dspark edge",
            "It opens its OWN browser profile, so any Edge or Chrome you already "
            "have open is left untouched.",
            "Then sign in to Douyin once in the window it opens.",
        ],
        docs=README_URL,
    )


def _check_network() -> Result:
    try:
        with socket.create_connection(("www.douyin.com", 443), NETWORK_TIMEOUT_S):
            pass
    except OSError as exc:
        return Result(
            name="network",
            ok=False,
            blocking=False,
            detail="cannot reach douyin.com",
            problem=f"Could not connect to douyin.com: {exc}",
            fix=[
                "Check the internet connection.",
                "If a proxy or VPN is running, make sure it covers this program "
                "too — a system-wide proxy usually does, a browser-only one does not.",
                f"Check that {DOUYIN_URL} loads in your browser.",
            ],
            docs=DOUYIN_URL,
        )
    return Result(name="network", ok=True, detail="douyin.com reachable")


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def run(config_path: Path | None = None, *, tools_only: bool = False) -> int:
    """Run the checks and report.

    `tools_only` stops after "is everything installed". The browser-attached and
    network checks are skipped, because they answer a different question — "can
    it run right now" — and a wrapper that is about to start the browser itself
    would only be told, every single run, that the browser is not started yet.
    """
    console.step("Environment check")

    path = Path(config_path) if config_path else Path(DEFAULT_CONFIG_PATH)

    results = [
        _check_python(),
        _check_config(path),
        _check_playwright(),
        _check_browser(),
        _check_chromium(),
    ]

    cfg: Config | None = None
    try:
        cfg = Config.load(path)
    except ConfigError:
        cfg = None
    if cfg is not None and not tools_only:
        results.extend(
            [
                _check_login(cfg),
                _check_attachable(cfg),
                _check_network(),
            ]
        )

    for result in results:
        console.verdict(result.ok, result.name, result.detail)

    blocking = [r for r in results if not r.ok and r.blocking]
    warnings = [r for r in results if not r.ok and not r.blocking]

    console.step("Result")

    if blocking:
        console.problem(
            f"{len(blocking)} problem(s) will stop dspark from working. "
            "Fix these first:"
        )
        for result in blocking:
            console.remedy(result.problem, result.fix, result.docs)
        return 1

    if warnings:
        console.warn(
            f"{len(warnings)} thing(s) to know about — not fatal, but they will "
            "bite in some modes:"
        )
        for result in warnings:
            console.remedy(result.problem, result.fix, result.docs, level="warn")
        console.ok("Nothing blocking. You can run dspark.")
        return 0

    console.ok("Everything dspark needs is present.")
    if tools_only:
        console.info("Tools are all here. Start a browser with: python -m dspark edge")
    else:
        console.info(f"Next: python -m dspark scan   (repo and docs: {REPO_URL})")
    return 0
