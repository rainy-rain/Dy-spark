"""Tests for the browser-launching helpers.

Nothing here starts a browser or touches the network beyond a TCP probe to a
port that is deliberately closed, so it stays fast and safe to run anywhere.
"""

from __future__ import annotations

import unittest

from dspark import cdp


class PortProbeTests(unittest.TestCase):
    def test_a_closed_port_is_reported_closed(self) -> None:
        # Port 9 is the discard port; nothing listens on it.
        self.assertFalse(cdp.port_open(9))

    def test_an_absurd_port_is_reported_closed(self) -> None:
        self.assertFalse(cdp.port_open(59123))


class DevtoolsProbeTests(unittest.TestCase):
    def test_no_answer_returns_none_rather_than_raising(self) -> None:
        """The caller branches on None; it must never see an exception."""
        self.assertIsNone(cdp.devtools_version(9))

    def test_waiting_gives_up_rather_than_hanging(self) -> None:
        import time

        started = time.monotonic()
        result = cdp.wait_for_devtools(9, timeout_s=1.5)
        elapsed = time.monotonic() - started
        self.assertIsNone(result)
        self.assertLess(elapsed, 6.0, "wait_for_devtools overran its timeout")


class BrowserDiscoveryTests(unittest.TestCase):
    def test_find_browser_is_honest(self) -> None:
        found = cdp.find_browser()
        if found is None:
            self.skipTest("no Chromium-family browser installed")
        path, name = found
        self.assertTrue(path.exists(), f"{path} does not exist")
        self.assertIn(name, ("Edge", "Chrome"))

    def test_edge_paths_are_absolute(self) -> None:
        for path in cdp.EDGE_PATHS + cdp.CHROME_PATHS:
            with self.subTest(path=path):
                self.assertTrue(path.is_absolute())


if __name__ == "__main__":
    unittest.main(verbosity=2)
