"""Offline tests for the environment check.

No browser, no network: the checks that would need either are exercised through
their pure parts, and the reporting is tested on constructed results.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from dspark import doctor, links
from dspark.config import ConfigError

from . import test_logic


class PureCheckTests(unittest.TestCase):
    def test_python_check_passes_on_a_supported_interpreter(self) -> None:
        result = doctor._check_python()
        self.assertEqual(result.ok, sys.version_info[:2] >= doctor.MIN_PYTHON)
        self.assertIn("need", result.detail)

    def test_missing_config_reports_the_copy_command(self) -> None:
        missing = Path("does-not-exist-anywhere.yaml")
        result = doctor._check_config(missing)
        self.assertFalse(result.ok)
        self.assertTrue(result.blocking, "a missing config stops everything")
        joined = " ".join(result.fix)
        self.assertIn("config.example.yaml", joined)
        self.assertIn("config.yaml", joined)

    def test_broken_config_is_reported_not_raised(self) -> None:
        """doctor must survive a bad config — it is what you run to diagnose one."""
        import tempfile

        path = Path(tempfile.mkdtemp()) / "config.yaml"
        path.write_text("sending: [unclosed", encoding="utf-8")
        result = doctor._check_config(path)
        self.assertFalse(result.ok)
        self.assertIn("YAML", result.problem)

    def test_valid_config_passes(self) -> None:
        import tempfile

        path = Path(tempfile.mkdtemp()) / "config.yaml"
        path.write_text("sending:\n  strategy: spark\n", encoding="utf-8")
        self.assertTrue(doctor._check_config(path).ok)

    def test_missing_chromium_is_a_warning_not_a_blocker(self) -> None:
        """Attaching to a system browser does not need it.

        Treating it as fatal would refuse to run on the setup the README
        actually recommends.
        """
        result = doctor._check_chromium()
        if result.ok:
            self.skipTest("Chromium happens to be installed here")
        self.assertFalse(result.blocking)
        self.assertIn("login", result.problem)

    def test_port_extraction_handles_urls_and_junk(self) -> None:
        self.assertEqual(doctor._port_from("http://127.0.0.1:9222"), 9222)
        self.assertEqual(doctor._port_from("http://localhost:9333/"), 9333)
        self.assertEqual(doctor._port_from("nonsense"), 9222)

    def test_every_check_that_can_fail_says_how_to_fix_it(self) -> None:
        """The whole point of this module: no dead-end messages."""
        cases = [
            doctor._check_config(Path("nope.yaml")),
        ]
        for result in cases:
            if result.ok:
                continue
            self.assertTrue(
                result.fix, f"{result.name} failed without offering a fix"
            )


class ReportTests(unittest.TestCase):
    def test_links_point_at_the_repository(self) -> None:
        self.assertTrue(links.REPO.startswith("https://github.com/"))
        self.assertIn("README.md", links.README)
        # Anchors must stay pointed at headings that exist in the Chinese README.
        for url in (links.INSTALL, links.CONFIG, links.TROUBLESHOOTING):
            self.assertTrue(url.startswith(links.README), url)

    def test_every_url_is_https(self) -> None:
        for name in dir(links):
            if name.isupper():
                value = getattr(links, name)
                if isinstance(value, str) and "://" in value:
                    self.assertTrue(
                        value.startswith("https://"), f"links.{name} is not https"
                    )


class DoctorExitCodeTests(unittest.TestCase):
    def test_blocking_problem_exits_non_zero(self) -> None:
        blocking = doctor.Result(
            name="config.yaml", ok=False, problem="missing", fix=["do a thing"]
        )
        with mock.patch.object(doctor, "_check_config", return_value=blocking):
            with mock.patch.object(doctor, "_check_python") as py:
                py.return_value = doctor.Result(name="python", ok=True)
                code = doctor.run(Path("ignored.yaml"), tools_only=True)
        self.assertEqual(code, 1)

    def test_only_warnings_exits_zero(self) -> None:
        """A missing Chromium must not stop a run that attaches to Edge."""
        warn = doctor.Result(
            name="chromium", ok=False, blocking=False, problem="absent", fix=["x"]
        )
        ok = doctor.Result(name="python", ok=True)
        with mock.patch.object(doctor, "_check_python", return_value=ok):
            with mock.patch.object(doctor, "_check_config", return_value=ok):
                with mock.patch.object(doctor, "_check_playwright", return_value=ok):
                    with mock.patch.object(doctor, "_check_browser", return_value=ok):
                        with mock.patch.object(
                            doctor, "_check_chromium", return_value=warn
                        ):
                            code = doctor.run(Path("ignored.yaml"), tools_only=True)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
