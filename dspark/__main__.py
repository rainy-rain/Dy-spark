"""Command-line entry point.

    python -m dspark config        show the resolved configuration
    python -m dspark login         scan the QR code once, save the session
    python -m dspark status        is the saved session still valid?
    python -m dspark probe         dump the message page (for fixing selectors)
    python -m dspark pick          click an element to get its selector
    python -m dspark send          dry run - lists what it would do
    python -m dspark send --yes    actually send
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

from . import __version__, console
from .config import DEFAULT_CONFIG_PATH, Config, ConfigError


def shared_options() -> argparse.ArgumentParser:
    """Options accepted both before and after the subcommand.

    argparse only recognises a parent option *before* the subcommand, but
    everybody types `dspark scan --cdp ...`. Repeating these on every subparser
    fixes that.

    The defaults are SUPPRESS deliberately. With an ordinary default, the
    subparser would set its own value when the flag is absent and silently blank
    out one supplied before the subcommand — the classic argparse parents trap.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show every page action as it happens",
    )
    common.add_argument(
        "--cdp",
        metavar="URL",
        default=argparse.SUPPRESS,
        help=(
            "attach to a browser you already have open instead of launching one, "
            "e.g. --cdp http://127.0.0.1:9222 (reuses your existing login)"
        ),
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    common = shared_options()

    parser = argparse.ArgumentParser(
        prog="dspark",
        description="Keep your Douyin chat streaks alive from the command line.",
        epilog="Start with `login`, then `scan`, then `send` (dry run) and `send --yes`.",
        parents=[common],
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        metavar="PATH",
        help="config file to use (default: config.yaml)",
    )
    parser.add_argument("--version", action="version", version=f"dspark {__version__}")

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    sub.add_parser(
        "login",
        parents=[common],
        help="open a browser and save the login (scan the QR once)",
    )
    sub.add_parser(
        "status", parents=[common], help="check whether the saved login still works"
    )
    sub.add_parser(
        "probe",
        parents=[common],
        help="dump the message page so selectors can be fixed",
    )
    sub.add_parser(
        "scan",
        parents=[common],
        help="list every conversation and whether it has a spark (sends nothing)",
    )
    sub.add_parser(
        "pick",
        parents=[common],
        help="click elements in a live browser to get their selectors",
    )

    analyze_cmd = sub.add_parser(
        "analyze",
        parents=[common],
        help="work out selectors from a dumped page, offline",
    )
    analyze_cmd.add_argument(
        "html",
        nargs="?",
        default=None,
        metavar="FILE",
        help="HTML file to read; defaults to the newest diagnostics/probe-*.html",
    )

    sub.add_parser(
        "config", parents=[common], help="print the resolved configuration and exit"
    )

    edge_cmd = sub.add_parser(
        "edge",
        parents=[common],
        help="get an attachable Edge/Chrome running (opens the debugging port)",
    )
    edge_cmd.add_argument(
        "--force",
        action="store_true",
        help="close a running browser first (loses unsaved tabs)",
    )
    edge_cmd.add_argument(
        "--port",
        type=int,
        default=9222,
        metavar="N",
        help="debugging port to open (default 9222)",
    )
    edge_cmd.add_argument(
        "--profile",
        default=None,
        metavar="DIR",
        help=(
            "browser profile directory to use. Defaults to .edge-profile inside "
            "the project. Must NOT be the browser's default profile: Edge 136+ "
            "refuses the debugging port there."
        ),
    )

    send = sub.add_parser(
        "send", parents=[common], help="send a streak-keeping message"
    )
    send.add_argument(
        "--yes",
        action="store_true",
        help="actually send; without this flag the run is a dry run",
    )
    send.add_argument(
        "--message",
        default=None,
        metavar="TEXT",
        help=(
            "send exactly this text instead of picking from sending.messages. "
            "Useful when the message is decided at the keyboard."
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    console.enable_utf8()

    args = build_parser().parse_args(argv)

    # `analyze` reads a saved HTML file: no config, no browser, no network.
    # `edge` only starts a browser. Both are handled before the config is loaded
    # so they still work if config.yaml is missing or broken.
    if args.command == "analyze":
        from . import analyze

        return analyze.run(Path(args.html) if args.html else None)

    if args.command == "edge":
        from . import cdp

        return cdp.run(
            force=args.force,
            port=args.port,
            profile=Path(args.profile) if args.profile else None,
        )

    try:
        cfg = Config.load(Path(args.config))
    except ConfigError as exc:
        console.error(str(exc))
        return 2

    # Shared options use SUPPRESS defaults, so they may be absent entirely.
    verbose = bool(getattr(args, "verbose", False))
    cdp_url = getattr(args, "cdp", None)

    if verbose or cfg.logging.verbose:
        console.set_verbose(True)

    # --cdp wins over the config file.
    if cdp_url:
        cfg.browser.cdp_url = cdp_url

    if cfg.logging.save_to_file:
        console.start_file_log(Path("diagnostics") / f"dspark-{datetime.now():%Y%m%d}.log")

    console.verbose(f"config loaded from {cfg.source_path}")

    # Imported after the config is known good: it pulls in the browser layer,
    # which is the part that needs Playwright installed.
    from . import picker, streak

    try:
        handlers = {
            "login": lambda: streak.login(cfg),
            "status": lambda: streak.status(cfg),
            "probe": lambda: streak.probe(cfg),
            "scan": lambda: streak.scan(cfg),
            "pick": lambda: picker.run(cfg),
            "send": lambda: streak.send(
                cfg, confirmed=args.yes, message=args.message
            ),
        }

        if args.command == "config":
            return streak.show_config(cfg)

        return asyncio.run(handlers[args.command]())
    except KeyboardInterrupt:
        console.warn("Interrupted.")
        return 130
    finally:
        console.close_file_log()


if __name__ == "__main__":
    raise SystemExit(main())
