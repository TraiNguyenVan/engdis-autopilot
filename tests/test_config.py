import os
import unittest
from unittest.mock import patch

class TestConfig(unittest.TestCase):
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            import config
            importlib.reload(config)
            self.assertEqual(config.CDP_PORT, 9225)
            self.assertEqual(config.LLM_URL, "http://100.85.59.117:20128/v1/chat/completions")
            self.assertEqual(config.SCRATCH, "/opt/data/cache/scratch/ed22u1")
            self.assertEqual(config.REPORT_DIR, ".")
            self.assertEqual(config.CRED_PATH, "/opt/data/.config/engdis/cred")
            self.assertEqual(config.DRY_RUN, False)

    def test_custom_env(self):
        custom_env = {
            "ED_CDP_PORT": "9333",
            "ED_LLM_URL": "https://custom-gateway.local/v1/chat/completions",
            "ED_SCRATCH": "/tmp/custom-scratch",
            "ED_REPORT_DIR": "/data/reports",
            "ED_CRED": "/run/secrets/cred",
            "ED_DRY_RUN": "1",
        }
        with patch.dict(os.environ, custom_env, clear=True):
            import importlib
            import config
            importlib.reload(config)
            self.assertEqual(config.CDP_PORT, 9333)
            self.assertEqual(config.LLM_URL, "https://custom-gateway.local/v1/chat/completions")
            self.assertEqual(config.SCRATCH, "/tmp/custom-scratch")
            self.assertEqual(config.REPORT_DIR, "/data/reports")
            self.assertEqual(config.CRED_PATH, "/run/secrets/cred")
            self.assertEqual(config.DRY_RUN, True)

    def test_invalid_cdp_port(self):
        with patch.dict(os.environ, {"ED_CDP_PORT": "not-a-number"}, clear=True):
            import importlib
            import config
            with self.assertRaises(ValueError):
                importlib.reload(config)

if __name__ == "__main__":
    unittest.main()
