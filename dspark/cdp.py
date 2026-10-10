"""Getting an attachable Edge/Chrome running.

Two traps, in order, and this module exists to step over both.

**Trap 1 — the flag is ignored while the browser is already running.**
`--remote-debugging-port` only takes effect at launch. Start Edge normally, then
run it again with the flag, and the second invocation just opens a tab in the
existing process: no port, and no error to explain why.

**Trap 2 — Edge 136+ ignores the flag on the default profile.**
Measured on a real machine: Edge 155.0.4283.45 launched as

    msedge.exe --remote-debugging-port=9222

does keep the switch in its command line (visible in `Win32_Process`) and does
open a window — and never opens the port. The reason is the profile it used:
`...\\AppData\\Local\\Microsoft\\Edge\\User Data`, the *default* one. From
Chromium 136 the debugging port is refused there on purpose, to stop local
malware from attaching to an already-signed-in browser and lifting its session.

So the port can only be had with an explicit, non-default `--user-data-dir`.
That means a separate browser profile, which means signing in to Douyin once
inside it. Once is all: the profile is a real Chromium profile and keeps its
cookies, so every later run attaches with no QR code.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import console

DEFAULT_PORT = 9222

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Deliberately inside the project rather than the default location: the default
# one is exactly what Edge 136+ refuses to open a debugging port on.
DEFAULT_PROFILE = PROJECT_ROOT / ".edge-profile"

EDGE_PATHS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)

CHROME_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)

# Closing someone else's browser loses their tabs, so this is never implicit.
FORCE_HINT = (
    "The browser is running without the debugging port, so the port is closed and\n"
    "every attach will fail. Close it completely (every window, and the tray icon),\n"
    "then run this command again.\n\n"
    "To let dspark do it for you — which closes every window and loses any\n"
    "unsaved tabs — add --force."
)


def find_browser() -> tuple[Path, str] | None:
    """The first installed Chromium-family browser, with its name."""
    for path in EDGE_PATHS:
        if path.exists():
            return path, "Edge"
    for path in CHROME_PATHS:
        if path.exists():
            return path, "Chrome"
    return None


def port_open(port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> bool:
    """Cheap TCP probe: something is listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.6)
        return sock.connect_ex((host, port)) == 0


def devtools_version(port: int = DEFAULT_PORT) -> dict | None:
    """Ask the DevTools endpoint who it is. None when it is not answering."""
    url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=2.0) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def browser_running() -> bool:
    """Any Edge or Chrome process at all."""
    for name in ("msedge.exe", "chrome.exe"):
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if name.lower() in (result.stdout or "").lower():
            return True
    return False


def close_browsers() -> None:
    """Ask every Edge/Chrome window to go away. Destructive: tabs are lost."""
    for name in ("msedge.exe", "chrome.exe"):
        try:
            subprocess.run(
                ["taskkill", "/IM", name, "/F"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def launch(exe: Path, port: int = DEFAULT_PORT, profile: Path | None = None) -> Path:
    """Start the browser with the debugging port open, detached from dspark.

    Always passes an explicit `--user-data-dir`. Omitting it produces a browser
    that looks perfectly fine and a port that never opens, because Edge 136+
    refuses the debugging port on the default profile. Returns the profile used.
    """
    profile = Path(profile) if profile else DEFAULT_PROFILE
    profile.mkdir(parents=True, exist_ok=True)

    flags = 0
    # Detach so the browser outlives this process.
    for attribute in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        flags |= getattr(subprocess, attribute, 0)

    subprocess.Popen(  # noqa: S603 - fixed, known-good executable path
        [
            str(exe),
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    return profile


def wait_for_devtools(port: int = DEFAULT_PORT, timeout_s: float = 25.0) -> dict | None:
    """Poll until the DevTools endpoint answers, or give up."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        info = devtools_version(port)
        if info:
            return info
        time.sleep(0.7)
    return None


def run(force: bool = False, port: int = DEFAULT_PORT, profile: Path | None = None) -> int:
    """The `edge` command: make an attachable browser available."""
    console.step("Attachable browser")

    profile = Path(profile) if profile else DEFAULT_PROFILE

    # Already good? Say so and stop. Nothing is launched or closed.
    info = devtools_version(port)
    if info:
        console.ok(f"{info.get('Browser', 'browser')} is already listening on {port}.")
        console.info(f"Run: python -m dspark scan --cdp http://127.0.0.1:{port}")
        return 0

    found = find_browser()
    if not found:
        console.error("No Edge or Chrome installation found.")
        console.info("Install one, or use `python -m dspark login` instead.")
        return 1

    exe, name = found
    fresh = not (profile / "Default").exists()

    console.info(f"browser : {name}  ({exe})")
    console.info(f"port    : {port}  (not listening)")
    console.info(f"profile : {profile}  ({'new' if fresh else 'existing'})")
    console.info("")
    console.info(
        "A separate profile is required: Edge 136+ refuses the debugging port on"
    )
    console.info("the default one, on purpose, so signed-in sessions cannot be")
    console.info("attached to by other programs. The cost is one sign-in here.")

    if browser_running():
        if not force:
            console.warn(f"{name} is already running.")
            console.info("")
            for line in FORCE_HINT.splitlines():
                console.info(line)
            return 1

        console.warn(f"Closing every {name} window (--force). Unsaved tabs are lost.")
        close_browsers()
        time.sleep(2.5)

    console.info("")
    console.info(f"Launching {name} with --remote-debugging-port={port} ...")
    launch(exe, port, profile)

    console.info("Waiting for the DevTools endpoint ...")
    info = wait_for_devtools(port)
    if not info:
        console.error("The port never opened.")
        console.info("")
        console.info(f"Check that {name} actually started, then re-run.")
        console.info(f"If it did start, confirm the profile is not the default one:")
        console.info(f"    {profile}")
        return 1

    console.ok(f"Ready: {info.get('Browser', name)} on port {port}")
    console.info("")
    if fresh:
        console.warn("This is a NEW browser profile - sign in to Douyin in it now.")
    console.info("Next:")
    console.info("  1. In that window, open https://www.douyin.com/chat and log in.")
    console.info("     The login is remembered in this profile from then on.")
    console.info(f"  2. python -m dspark scan --cdp http://127.0.0.1:{port}")
    return 0
