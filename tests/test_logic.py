"""Unit tests for the parts that need no browser.

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v

Everything here is deliberately offline: config parsing, validation, and the
target-selection strategies. Those are the parts that decide *who gets a
message*, so they are worth pinning down properly. Anything that needs a real
page is verified by the `probe` / `pick` commands instead.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dspark import streak
from dspark.config import Config, ConfigError
from dspark.streak import (
    Conversation,
    _apply_cap,
    _matching_targets,
    _select_targets,
)


def load(text: str) -> Config:
    """Write `text` to a temp config file and load it."""
    directory = Path(tempfile.mkdtemp(prefix="dspark-test-"))
    path = directory / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return Config.load(path)


def sender(
    strategy: str = "spark",
    targets: str = "[]",
    cap: int = 100,
    messages: str = '["."]',
) -> Config:
    """A config with values written in explicitly.

    The cap default matches the shipped one. A lower value here once made
    `test_the_default_cap_...` pass while testing this helper's default rather
    than the config's — the test was green and meaningless.
    """
    return load(
        f"""
sending:
  enabled: false
  strategy: {strategy}
  targets: {targets}
  messages: {messages}
  delay_between_ms: [1, 2]
  max_per_run: {cap}
"""
    )


class DefaultsTests(unittest.TestCase):
    def test_empty_config_gets_safe_defaults(self) -> None:
        cfg = load("{}")
        self.assertFalse(cfg.sending.enabled, "sending must default to off")
        self.assertEqual(cfg.sending.strategy, "spark")
        self.assertFalse(cfg.browser.headless, "browser should be visible by default")
        self.assertEqual(cfg.sending.max_per_run, 100)
        self.assertEqual(cfg.browser.typing_delay_ms, (45, 170))

    def test_session_path_resolves_next_to_the_config(self) -> None:
        cfg = load("session_file: .session/state.json")
        self.assertTrue(cfg.session_file.is_absolute())
        self.assertEqual(cfg.session_file.parent, cfg.root / ".session")
        self.assertEqual(cfg.session_file.name, "state.json")


class ValidationTests(unittest.TestCase):
    def test_missing_file_is_reported_with_a_hint(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            Config.load(Path(tempfile.mkdtemp()) / "config.yaml")
        self.assertIn("config file not found", str(ctx.exception))
        self.assertIn("config.example.yaml", str(ctx.exception))

    def test_invalid_yaml_names_the_problem(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            load("sending: [unclosed")
        self.assertIn("not valid YAML", str(ctx.exception))

    def test_unknown_strategy_is_rejected(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            sender(strategy="nonsense")
        self.assertIn("must be one of", str(ctx.exception))

    def test_list_strategy_needs_targets(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            sender(strategy="list", targets="[]")
        self.assertIn("targets", str(ctx.exception))

    def test_enabled_sending_without_messages_is_allowed(self) -> None:
        """Emoji mode means "nothing to type" is a valid configuration.

        This used to raise. That was correct while text was the only way to send,
        and wrong the moment `--emoji` existed: a run that sends the 续火花 emoji
        from the panel needs no message text at all, so the check rejected a
        perfectly usable config. `send` reports an empty pool at the point it
        actually matters instead.
        """
        cfg = load(
            """
sending:
  enabled: true
  messages: []
"""
        )
        self.assertTrue(cfg.sending.enabled)
        self.assertEqual(cfg.sending.messages, [])

    def test_emoji_label_defaults_to_the_streak_emoji(self) -> None:
        self.assertEqual(load("{}").sending.emoji_label, "续火花")

    def test_emoji_label_can_be_overridden(self) -> None:
        cfg = load("sending:\n  emoji_label: 比心\n")
        self.assertEqual(cfg.sending.emoji_label, "比心")

    def test_inverted_range_is_rejected(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            load("sending:\n  delay_between_ms: [9000, 1000]\n")
        self.assertIn("min <= max", str(ctx.exception))

    def test_wrong_length_range_is_rejected(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            load("sending:\n  delay_between_ms: [1000]\n")
        self.assertIn("two-element list", str(ctx.exception))

    def test_non_numeric_range_is_rejected(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            load('sending:\n  delay_between_ms: ["soon", "later"]\n')
        self.assertIn("whole numbers", str(ctx.exception))

    def test_zero_max_per_run_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            sender(cap=0)


def convo(index: int, name: str, spark: bool) -> Conversation:
    return Conversation(index=index, name=name, has_spark=spark)


class SparkVariantTests(unittest.TestCase):
    """Which flame assets count as a streak worth renewing."""

    def test_empty_whitelist_allows_every_variant(self) -> None:
        cfg = sender()
        for variant in ("normal_normal.png", "blue_normal.png", "gray_normal.png"):
            with self.subTest(variant=variant):
                self.assertTrue(cfg.sending.allows_variant(variant))

    def test_empty_whitelist_allows_a_missing_variant(self) -> None:
        self.assertTrue(sender().sending.allows_variant(None))

    def test_whitelist_narrows_the_set(self) -> None:
        cfg = load(
            """
sending:
  spark_variants: ["gray_normal.png"]
"""
        )
        self.assertTrue(cfg.sending.allows_variant("gray_normal.png"))
        self.assertFalse(cfg.sending.allows_variant("blue_normal.png"))

    def test_a_missing_variant_is_refused_when_a_whitelist_exists(self) -> None:
        cfg = load('sending:\n  spark_variants: ["gray_normal.png"]\n')
        self.assertFalse(
            cfg.sending.allows_variant(None),
            "with a whitelist, an unreadable variant must not be assumed good",
        )


class ComposerJSTests(unittest.TestCase):
    """Guards for the JS that reads the composer.

    The script is built inside a Python string, so a single missing backslash
    turns the character class `[\\u200b-...]` into `[u200b-...]` — which matches
    the literal letters u, 2, 0, b. That would silently break the emptiness
    check and make every successful send look like a failure. Cheap to guard.
    """

    def test_zero_width_escapes_survive_python_escaping(self) -> None:
        for escape in (r"\u200b", r"\u200d", r"\ufeff"):
            with self.subTest(escape=escape):
                self.assertIn(
                    escape,
                    streak._COMPOSER_JS,
                    f"{escape} must reach the browser as a JS escape",
                )

    def test_the_script_targets_the_slate_editor(self) -> None:
        self.assertIn("data-slate-editor", streak._COMPOSER_JS)

    def test_the_script_also_accepts_a_plain_textarea(self) -> None:
        self.assertIn("textarea", streak._COMPOSER_JS)


class CapTruncationTests(unittest.TestCase):
    """A silent truncation is the worst failure this tool can have.

    The friends left out simply lose their streak, and the run still reports
    success — which is exactly what happened once, on a real account: 29 people
    matched and 20 were messaged, with no warning at all. These tests pin the
    reporting, and the default that caused it.
    """

    def test_the_default_cap_does_not_truncate_a_realistic_list(self) -> None:
        people = [convo(i, f"p{i}", True) for i in range(42)]
        # Deliberately omits max_per_run: this is about the *shipped* default,
        # not about whatever the test helper happens to pass in.
        cfg = load("sending:\n  strategy: spark\n")
        kept, dropped = _apply_cap(cfg, _matching_targets(cfg, people))
        self.assertEqual(dropped, 0, "the default cap silently dropped friends")
        self.assertEqual(len(kept), 42)

    def test_truncation_is_reported_not_swallowed(self) -> None:
        people = [convo(i, f"p{i}", True) for i in range(30)]
        cfg = sender(strategy="spark", cap=20)
        matched = _matching_targets(cfg, people)
        kept, dropped = _apply_cap(cfg, matched)
        self.assertEqual(len(matched), 30)
        self.assertEqual(len(kept), 20)
        self.assertEqual(dropped, 10, "the dropped count must be reported")

    def test_nothing_is_dropped_under_the_cap(self) -> None:
        people = [convo(i, f"p{i}", True) for i in range(5)]
        cfg = sender(strategy="spark", cap=20)
        kept, dropped = _apply_cap(cfg, _matching_targets(cfg, people))
        self.assertEqual((len(kept), dropped), (5, 0))

    def test_matching_ignores_the_cap_entirely(self) -> None:
        """Scan and send must agree, so matching cannot apply the cap itself."""
        people = [convo(i, f"p{i}", True) for i in range(30)]
        cfg = sender(strategy="spark", cap=5)
        self.assertEqual(len(_matching_targets(cfg, people)), 30)

    def test_select_targets_still_applies_the_cap(self) -> None:
        people = [convo(i, f"p{i}", True) for i in range(30)]
        cfg = sender(strategy="spark", cap=5)
        self.assertEqual(len(_select_targets(cfg, people)), 5)


class TargetSelectionTests(unittest.TestCase):
    """Who actually gets a message - the part with real consequences."""

    def setUp(self) -> None:
        self.people = [
            convo(0, "Alice", True),
            convo(1, "Bob", False),
            convo(2, "Carol", True),
            convo(3, "Dave", False),
        ]

    def test_spark_strategy_picks_only_streaks(self) -> None:
        picked = _select_targets(sender(strategy="spark"), self.people)
        self.assertEqual([c.name for c in picked], ["Alice", "Carol"])

    def test_list_strategy_picks_only_named(self) -> None:
        cfg = sender(strategy="list", targets='["Bob", "Dave"]')
        picked = _select_targets(cfg, self.people)
        self.assertEqual([c.name for c in picked], ["Bob", "Dave"])

    def test_list_strategy_ignores_names_that_are_absent(self) -> None:
        cfg = sender(strategy="list", targets='["Alice", "Nobody"]')
        picked = _select_targets(cfg, self.people)
        self.assertEqual([c.name for c in picked], ["Alice"])

    def test_all_strategy_picks_everyone(self) -> None:
        picked = _select_targets(sender(strategy="all"), self.people)
        self.assertEqual(len(picked), 4)

    def test_max_per_run_caps_the_result(self) -> None:
        cfg = sender(strategy="all", cap=2)
        picked = _select_targets(cfg, self.people)
        self.assertEqual(len(picked), 2)
        self.assertEqual([c.name for c in picked], ["Alice", "Bob"])

    def test_cap_applies_to_the_spark_strategy_too(self) -> None:
        cfg = sender(strategy="spark", cap=1)
        picked = _select_targets(cfg, self.people)
        self.assertEqual([c.name for c in picked], ["Alice"])

    def test_nothing_matches_is_not_an_error(self) -> None:
        picked = _select_targets(sender(strategy="list", targets='["Nobody"]'), self.people)
        self.assertEqual(picked, [])

    def test_empty_conversation_list_yields_nothing(self) -> None:
        for strategy, targets in (("spark", "[]"), ("all", "[]"), ("list", '["x"]')):
            with self.subTest(strategy=strategy):
                cfg = sender(strategy=strategy, targets=targets)
                self.assertEqual(_select_targets(cfg, []), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
