import importlib
import os
import unittest
from unittest.mock import patch


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            import config
            importlib.reload(config)
            self.assertEqual(config.CDP_PORT, 9225)
            self.assertEqual(config.LLM_URL, "https://api.openai.com/v1/chat/completions")
            self.assertEqual(config.LLM_KEY, "")
            self.assertEqual(config.LLM_MODELS, ["gpt-4o-mini"])
            self.assertEqual(config.SCRATCH, "/opt/data/cache/scratch/ed22u1")
            self.assertEqual(config.REPORT_DIR, ".")
            self.assertEqual(config.CRED_PATH, "/opt/data/.config/engdis/cred")
            self.assertEqual(config.DRY_RUN, False)

    def test_custom_env_openai(self):
        custom_env = {
            "ED_CDP_PORT": "9333",
            "OPENAI_BASE_URL": "http://localhost:11434/v1",
            "OPENAI_API_KEY": "test-key-123",
            "OPENAI_MODEL": "llama3.2,mistral",
            "ED_SCRATCH": "/tmp/custom-scratch",
            "ED_REPORT_DIR": "/data/reports",
            "ED_CRED": "/run/secrets/cred",
            "ED_DRY_RUN": "1",
        }
        with patch.dict(os.environ, custom_env, clear=True):
            import config
            importlib.reload(config)
            self.assertEqual(config.CDP_PORT, 9333)
            self.assertEqual(config.LLM_URL, "http://localhost:11434/v1/chat/completions")
            self.assertEqual(config.LLM_KEY, "test-key-123")
            self.assertEqual(config.LLM_MODELS, ["llama3.2", "mistral"])
            self.assertEqual(config.SCRATCH, "/tmp/custom-scratch")
            self.assertEqual(config.REPORT_DIR, "/data/reports")
            self.assertEqual(config.CRED_PATH, "/run/secrets/cred")
            self.assertEqual(config.DRY_RUN, True)

    def test_custom_env_ed_llm_url_backwards_compatible(self):
        custom_env = {
            "ED_LLM_URL": "http://custom-host:8080/v1/chat/completions",
            "NINEROUTER_API_KEY": "legacy-key",
            "ED_LLM_MODELS": "model-a,model-b",
        }
        with patch.dict(os.environ, custom_env, clear=True):
            import config
            importlib.reload(config)
            self.assertEqual(config.LLM_URL, "http://custom-host:8080/v1/chat/completions")
            self.assertEqual(config.LLM_KEY, "legacy-key")
            self.assertEqual(config.LLM_MODELS, ["model-a", "model-b"])

    def test_invalid_cdp_port(self):
        with patch.dict(os.environ, {"ED_CDP_PORT": "not-a-number"}, clear=True):
            import config
            with self.assertRaises(ValueError):
                importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
