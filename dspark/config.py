"""Configuration loading and validation.

A malformed config should fail loudly at startup with a message that names the
offending key, not blow up halfway through a run with a KeyError.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")
EXAMPLE_CONFIG_PATH = Path("config.example.yaml")


class ConfigError(Exception):
    """The config file is missing, unreadable, or invalid."""


def _pair(value: Any, key: str, minimum: int = 0) -> tuple[int, int]:
    """Coerce a two-element list into a validated (low, high) tuple."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ConfigError(f"`{key}` must be a two-element list like [1000, 3000]")
    try:
        low, high = int(value[0]), int(value[1])
    except (TypeError, ValueError):
        raise ConfigError(f"`{key}` must contain whole numbers, got {value!r}") from None
    if low < minimum or high < low:
        raise ConfigError(
            f"`{key}` must satisfy {minimum} <= min <= max, got [{low}, {high}]"
        )
    return low, high


def _str_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"`{key}` must be a list")
    return [str(item) for item in value]


@dataclass
class BrowserConfig:
    headless: bool = False
    typing_delay_ms: tuple[int, int] = (45, 170)
    slow_mo_ms: int = 120
    # Attach to a browser the user already has open (Edge/Chrome started with
    # --remote-debugging-port) instead of launching a fresh one. Reuses their
    # existing login, so no QR code is needed.
    cdp_url: str = ""


@dataclass
class DouyinConfig:
    home_url: str = "https://www.douyin.com/"
    # Confirmed: /chat is the private-message page.
    messages_url: str = "https://www.douyin.com/chat"
    # Straight to /chat by default. Clicking the 消息 entry from the home page
    # also works, but it warns "Could not click the message entry" on a real
    # account and then falls back here anyway — a detour that prints a scary
    # line and adds nothing. Kept as an option for if /chat ever moves.
    navigate_via_home: bool = False


@dataclass
class SendingConfig:
    enabled: bool = False
    strategy: str = "spark"
    targets: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    delay_between_ms: tuple[int, int] = (5000, 15000)
    # A runaway guard, not a budget. It must sit above any realistic friend
    # count, because silently truncating means silently letting streaks die —
    # and the run still reports success. `send` now shouts when it truncates.
    max_per_run: int = 100
    # Which flame assets count as "has a spark". Empty means all of them.
    # Known assets: normal_normal.png, blue_normal.png, gray_normal.png.
    # A grey flame sits on a 129-day streak, so grey is a *normal* list
    # appearance, not an absent streak - hence all three by default.
    spark_variants: list[str] = field(default_factory=list)
    # The label of the emoji to send in emoji mode. Douyin's panel labels every
    # entry, so this picks one by name instead of by position — position would
    # break the moment the panel is reordered.
    emoji_label: str = "续火花"

    VALID_STRATEGIES = ("spark", "list", "all")

    def allows_variant(self, variant: str | None) -> bool:
        """Whether this flame asset should count as a spark worth renewing."""
        if not self.spark_variants:
            return True
        return bool(variant) and variant in self.spark_variants

    def validate(self) -> None:
        if self.strategy not in self.VALID_STRATEGIES:
            raise ConfigError(
                f"`sending.strategy` must be one of {', '.join(self.VALID_STRATEGIES)}; "
                f"got {self.strategy!r}"
            )
        if self.strategy == "list" and not self.targets:
            raise ConfigError(
                "`sending.strategy` is `list` but `sending.targets` is empty — "
                "add the friend names you want to message, or switch to `spark`."
            )
        # There used to be a hard "enabled but no messages" error here. Emoji mode
        # made it wrong: a run that sends the 续火花 emoji needs no text at all, so
        # the check would reject a perfectly valid configuration. `send` reports an
        # empty message pool at the point it actually matters.
        if self.max_per_run < 1:
            raise ConfigError("`sending.max_per_run` must be at least 1")


@dataclass
class LoggingConfig:
    verbose: bool = False
    save_to_file: bool = True


@dataclass
class Config:
    session_file: Path
    browser: BrowserConfig
    douyin: DouyinConfig
    sending: SendingConfig
    logging: LoggingConfig
    source_path: Path

    @property
    def root(self) -> Path:
        """Directory the config lives in — relative paths resolve from here."""
        return self.source_path.parent

    @classmethod
    def load(cls, path: Path) -> "Config":
        path = Path(path)
        if not path.exists():
            hint = (
                f" Copy the template first:\n"
                f"    cp {EXAMPLE_CONFIG_PATH} {DEFAULT_CONFIG_PATH}"
                if path.name == DEFAULT_CONFIG_PATH.name
                else ""
            )
            raise ConfigError(f"config file not found: {path}.{hint}")

        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

        if not isinstance(raw, dict):
            raise ConfigError(f"{path} must contain a YAML mapping at the top level")

        browser_raw = raw.get("browser") or {}
        douyin_raw = raw.get("douyin") or {}
        sending_raw = raw.get("sending") or {}
        logging_raw = raw.get("logging") or {}

        session_file = Path(raw.get("session_file") or ".session/storage_state.json")
        if not session_file.is_absolute():
            session_file = (path.parent / session_file).resolve()

        sending = SendingConfig(
            enabled=bool(sending_raw.get("enabled", False)),
            strategy=str(sending_raw.get("strategy", "spark")),
            targets=_str_list(sending_raw.get("targets"), "sending.targets"),
            messages=_str_list(sending_raw.get("messages"), "sending.messages"),
            delay_between_ms=_pair(
                sending_raw.get("delay_between_ms", [5000, 15000]),
                "sending.delay_between_ms",
            ),
            max_per_run=int(sending_raw.get("max_per_run", 100)),
            spark_variants=_str_list(
                sending_raw.get("spark_variants"), "sending.spark_variants"
            ),
            emoji_label=str(sending_raw.get("emoji_label", "续火花")),
        )
        sending.validate()

        return cls(
            session_file=session_file,
            browser=BrowserConfig(
                headless=bool(browser_raw.get("headless", False)),
                typing_delay_ms=_pair(
                    browser_raw.get("typing_delay_ms", [45, 170]),
                    "browser.typing_delay_ms",
                ),
                slow_mo_ms=int(browser_raw.get("slow_mo_ms", 120)),
                cdp_url=str(browser_raw.get("cdp_url") or ""),
            ),
            douyin=DouyinConfig(
                home_url=str(douyin_raw.get("home_url", "https://www.douyin.com/")),
                messages_url=str(
                    douyin_raw.get("messages_url", "https://www.douyin.com/chat")
                ),
                navigate_via_home=bool(douyin_raw.get("navigate_via_home", False)),
            ),
            sending=sending,
            logging=LoggingConfig(
                verbose=bool(logging_raw.get("verbose", False)),
                save_to_file=bool(logging_raw.get("save_to_file", True)),
            ),
            source_path=path.resolve(),
        )

    def as_dict(self) -> dict[str, Any]:
        """Config with secrets-free, display-friendly types."""
        data = dataclasses.asdict(self)
        data.pop("source_path", None)
        data["session_file"] = str(self.session_file)
        return data
