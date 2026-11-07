import importlib
import os
import unittest
from unittest.mock import patch


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        with patch.dict(os.environ, {"ED_SKIP_DOTENV": "1"}, clear=True):
            import config
            importlib.reload(config)
            self.assertEqual(config.CDP_PORT, 9225)
            self.assertEqual(config.LLM_URL, "https://api.openai.com/v1/chat/completions")
            self.assertEqual(config.LLM_KEY, "")
            self.assertEqual(config.LLM_MODELS, ["gpt-4o-mini"])
            self.assertEqual(config.SCRATCH, "/opt/data/cache/scratch/ed22u1")
            self.assertEqual(config.REPORT_DIR, ".")
            self.assertEqual(config.CRED_PATH, "")
            self.assertEqual(config.DRY_RUN, False)

    def test_custom_env_openai(self):
        custom_env = {
            "ED_SKIP_DOTENV": "1",
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
            "ED_SKIP_DOTENV": "1",
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
        with patch.dict(os.environ, {"ED_SKIP_DOTENV": "1", "ED_CDP_PORT": "not-a-number"}, clear=True):
            import config
            with self.assertRaises(ValueError):
                importlib.reload(config)

    def test_load_dotenv(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w+", delete=False) as f:
            f.write("TEST_DOTENV_KEY=hello_world\n# comment\nINVALID_LINE\n")
            temp_path = f.name
        try:
            with patch.dict(os.environ, {}, clear=True):
                import config
                config._load_dotenv(temp_path)
                self.assertEqual(os.environ.get("TEST_DOTENV_KEY"), "hello_world")
        finally:
            os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
