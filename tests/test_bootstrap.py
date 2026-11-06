import unittest
from unittest.mock import patch, MagicMock
import bootstrap_browser

class TestBootstrapBrowser(unittest.TestCase):
    def test_chrome_flags_generation(self):
        flags = bootstrap_browser.build_chrome_flags(
            chrome_bin="/usr/bin/chromium",
            port=9225,
            profile_dir="/tmp/profile"
        )
        self.assertEqual(flags[0], "/usr/bin/chromium")
        self.assertIn("--headless=new", flags)
        self.assertIn("--remote-debugging-port=9225", flags)
        self.assertIn("--user-data-dir=/tmp/profile", flags)
        self.assertIn("--use-fake-ui-for-media-stream", flags)
        self.assertIn("--autoplay-policy=no-user-gesture-required", flags)
        self.assertEqual(flags[-1], "about:blank")

    @patch("urllib.request.urlopen")
    def test_wait_for_cdp_ready(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = b'{"Browser": "Chrome/120.0"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        ready = bootstrap_browser.wait_for_cdp(port=9225, timeout=2.0)
        self.assertTrue(ready)

if __name__ == "__main__":
    unittest.main()
