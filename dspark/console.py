"""Terminal output, optionally mirrored to a log file.

Deliberately ASCII markers: a Windows console on a legacy code page mangles
box-drawing characters, and a tool that prints mojibake is worse than one that
prints plain text. The file log is UTF-8 so Chinese names survive.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import IO

_VERBOSE = False
_logfile: IO[str] | None = None


def enable_utf8() -> None:
    """Force UTF-8 stdout so Chinese friend names survive on Windows."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def start_file_log(path: Path) -> None:
    """Mirror everything that follows into `path` (appending)."""
    global _logfile
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _logfile = path.open("a", encoding="utf-8")
        _logfile.write(f"\n===== {stamp()} =====\n")
        _logfile.flush()
    except OSError:
        _logfile = None


def close_file_log() -> None:
    global _logfile
    if _logfile is not None:
        try:
            _logfile.close()
        finally:
            _logfile = None


def set_verbose(value: bool) -> None:
    global _VERBOSE
    _VERBOSE = value


def is_verbose() -> bool:
    return _VERBOSE


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _emit(text: str, *, to_stderr: bool = False) -> None:
    # flush=True matters whenever stdout is a pipe: block buffering would let an
    # unbuffered stderr line overtake it and print out of order.
    print(text, file=sys.stderr if to_stderr else sys.stdout, flush=True)
    if _logfile is not None:
        _logfile.write(text + "\n")
        _logfile.flush()


def step(title: str) -> None:
    _emit(f"\n--- {title} ---")


def info(message: str) -> None:
    _emit(f"[i] {message}")


def ok(message: str) -> None:
    _emit(f"[ok] {message}")


def warn(message: str) -> None:
    _emit(f"[!] {message}")


def error(message: str) -> None:
    _emit(f"[x] {message}", to_stderr=True)


def verbose(message: str) -> None:
    if _VERBOSE:
        _emit(f"    . {message}")


def problem(message: str) -> None:
    """Like `error()`, but on stdout.

    `error()` goes to stderr so that `2>` captures failures. That is right for a
    one-line "this failed", and wrong for a multi-line block that only makes
    sense in order: redirected, the stdout half and the stderr half get separated
    and the explanation ends up printed after the lines it explains.
    """
    _emit(f"[x] {message}")


def remedy(
    problem_text: str,
    steps: list[str] | tuple[str, ...] = (),
    docs: str | None = None,
    *,
    level: str = "error",
) -> None:
    """Report a problem *and* what to do about it.

    A message that only says what broke is half a message. On a fresh clone the
    usual cause is a missing prerequisite rather than a bug — no venv, no
    Chromium, no config.yaml, no login — and the person reading it has never seen
    this codebase. So every blocking error names the fix, in order, and links to
    something that explains it properly.

    The whole block goes to stdout, deliberately: see `problem()`.
    """
    if level == "warn":
        _emit(f"[!] {problem_text}")
    else:
        _emit(f"[x] {problem_text}")
    if steps:
        info("How to fix:")
        for index, step_text in enumerate(steps, start=1):
            info(f"  {index}. {step_text}")
    if docs:
        info(f"  Docs: {docs}")
