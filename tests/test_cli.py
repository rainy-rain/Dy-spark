"""Tests for the command-line surface.

These exist because of a real bug: `--cdp` was registered only on the top-level
parser, so `dspark scan --cdp http://...` — which is how anyone would type it —
failed with "unrecognized arguments". Checking `--help` output had looked fine;
nothing had actually *run* the flag.

So these tests parse real command lines rather than inspecting help text.
"""

from __future__ import annotations

import unittest

from dspark.__main__ import build_parser

CDP = "http://127.0.0.1:9222"


class SharedOptionTests(unittest.TestCase):
    """Options must work on either side of the subcommand."""

    def test_cdp_after_the_subcommand(self) -> None:
        args = build_parser().parse_args(["scan", "--cdp", CDP])
        self.assertEqual(args.cdp, CDP)

    def test_cdp_before_the_subcommand(self) -> None:
        args = build_parser().parse_args(["--cdp", CDP, "scan"])
        self.assertEqual(args.cdp, CDP)

    def test_a_pre_subcommand_value_survives_the_subparser(self) -> None:
        """The argparse parents trap: a subparser default can blank this out."""
        args = build_parser().parse_args(["--cdp", CDP, "scan"])
        self.assertEqual(
            args.cdp, CDP, "the subparser's default overwrote a supplied --cdp"
        )

    def test_verbose_after_the_subcommand(self) -> None:
        self.assertTrue(build_parser().parse_args(["scan", "-v"]).verbose)

    def test_verbose_before_the_subcommand(self) -> None:
        self.assertTrue(build_parser().parse_args(["-v", "scan"]).verbose)

    def test_absent_shared_options_do_not_raise(self) -> None:
        args = build_parser().parse_args(["scan"])
        self.assertIsNone(getattr(args, "cdp", None))
        self.assertFalse(getattr(args, "verbose", False))


class EveryCommandAcceptsSharedOptionsTests(unittest.TestCase):
    """Every subcommand, not just the one that happened to be tried by hand."""

    COMMANDS = [
        ["login"],
        ["status"],
        ["probe"],
        ["scan"],
        ["pick"],
        ["config"],
        ["send", "--yes"],
        ["send"],
        ["analyze"],
        ["analyze", "some.html"],
        ["edge"],
        ["edge", "--port", "9333"],
    ]

    def test_cdp_is_accepted_after_each_subcommand(self) -> None:
        for command in self.COMMANDS:
            with self.subTest(command=command):
                args = build_parser().parse_args(command + ["--cdp", CDP])
                self.assertEqual(args.cdp, CDP)

    def test_verbose_is_accepted_after_each_subcommand(self) -> None:
        for command in self.COMMANDS:
            with self.subTest(command=command):
                args = build_parser().parse_args(command + ["-v"])
                self.assertTrue(args.verbose)


class ExistingArgumentsStillWorkTests(unittest.TestCase):
    def test_edge_port(self) -> None:
        args = build_parser().parse_args(["edge", "--port", "9333"])
        self.assertEqual(args.port, 9333)

    def test_edge_defaults(self) -> None:
        args = build_parser().parse_args(["edge"])
        self.assertEqual(args.port, 9222)

    def test_edge_has_no_force_flag(self) -> None:
        """--force existed only to close a browser before using the *default*
        profile. The dedicated profile coexists with a running browser, so the
        flag is gone — and with it, the ability to lose someone's open tabs."""
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["edge", "--force"])

    def test_send_yes(self) -> None:
        self.assertTrue(build_parser().parse_args(["send", "--yes"]).yes)
        self.assertFalse(build_parser().parse_args(["send"]).yes)

    def test_send_message_option(self) -> None:
        args = build_parser().parse_args(["send", "--yes", "--message", "hi there"])
        self.assertTrue(args.yes)
        self.assertEqual(args.message, "hi there")

    def test_send_message_defaults_to_none(self) -> None:
        self.assertIsNone(build_parser().parse_args(["send"]).message)

    def test_send_message_survives_chinese(self) -> None:
        """The one-click wrapper types this at the keyboard."""
        args = build_parser().parse_args(["send", "--message", "晚上好"])
        self.assertEqual(args.message, "晚上好")

    def test_send_emoji_flag(self) -> None:
        self.assertTrue(build_parser().parse_args(["send", "--emoji"]).emoji)
        self.assertFalse(build_parser().parse_args(["send"]).emoji)

    def test_send_emoji_and_message_are_independent(self) -> None:
        """Option 2 in the wrapper passes --emoji and no --message at all."""
        args = build_parser().parse_args(["send", "--yes", "--emoji"])
        self.assertTrue(args.emoji)
        self.assertIsNone(args.message)

    def test_analyze_optional_html(self) -> None:
        self.assertEqual(
            build_parser().parse_args(["analyze", "dump.html"]).html, "dump.html"
        )
        self.assertIsNone(build_parser().parse_args(["analyze"]).html)

    def test_config_path_override(self) -> None:
        args = build_parser().parse_args(["--config", "other.yaml", "scan"])
        self.assertEqual(args.config, "other.yaml")

    def test_command_is_required(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args([])


if __name__ == "__main__":
    unittest.main(verbosity=2)
