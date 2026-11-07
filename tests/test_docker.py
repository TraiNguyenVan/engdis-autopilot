import os
import unittest
from pathlib import Path


class TestDockerConfiguration(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent.parent

    def test_dockerfile_contents(self):
        df = self.root / "Dockerfile"
        self.assertTrue(df.exists(), "Dockerfile must exist")
        content = df.read_text(encoding="utf-8")
        self.assertIn("python:3.11-slim", content)
        self.assertIn("chromium", content)
        self.assertIn("ffmpeg", content)
        self.assertIn("useradd", content)
        self.assertIn("USER engdis", content)

    def test_compose_ram_limit_tight(self):
        compose = self.root / "compose.yaml"
        self.assertTrue(compose.exists(), "compose.yaml must exist")
        content = compose.read_text(encoding="utf-8")
        self.assertIn("mem_limit", content)
        self.assertIn("1280m", content)
        self.assertIn('shm_size: "256m"', content)
        self.assertIn("ED_USER=${ED_USER:-}", content)
        self.assertIn("ED_PASS=${ED_PASS:-}", content)

    def test_entrypoint_exists_and_handles_cleanup(self):
        entrypoint = self.root / "docker" / "entrypoint.sh"
        self.assertTrue(entrypoint.exists(), "docker/entrypoint.sh must exist")
        content = entrypoint.read_text(encoding="utf-8")
        self.assertIn("trap cleanup EXIT INT TERM", content)
        self.assertIn("cover.py", content)


if __name__ == "__main__":
    unittest.main()
