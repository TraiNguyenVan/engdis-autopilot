import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
SKILL_PATH = os.path.join(REPO_ROOT, ".agents", "skills", "engdis-autopilot", "SKILL.md")


class TestSkillValidity(unittest.TestCase):
    def test_skill_file_exists(self):
        self.assertTrue(os.path.exists(SKILL_PATH), f"Missing {SKILL_PATH}")

    def test_operational_guardrails(self):
        with open(SKILL_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("two lines: username, then password", content)
        self.assertNotIn("`username:password` file", content)
        self.assertIn("small non-critical run", content)

    def test_completion_gate_documents_threshold_and_scope(self):
        with open(SKILL_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("`< 0.999`", content)
        self.assertIn("all reported lessons", content)
        self.assertIn("excluding those marked blocked", content)
        self.assertIn("including lessons outside the selected scope", content)
        self.assertNotIn("unblocked lessons remain `< 100%`", content)

    def test_compose_examples_explicitly_configure_execution(self):
        with open(SKILL_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("defaults to `ED_DRY_RUN=1`", content)
        self.assertIn("ED_DRY_RUN=0", content)
        self.assertIn("docker compose run --rm -e ED_UNATTENDED=1 engdis", content)
        self.assertNotIn('ED_UNATTENDED=1 docker compose run --rm engdis', content)

    def test_speaking_does_not_assume_universal_cap(self):
        with open(SKILL_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("cap at 67%", content)
        self.assertIn("do not infer a fixed completion percentage", content)

    def test_review_screen_does_not_prove_completion(self):
        with open(SKILL_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("review text alone does not prove", content)
        self.assertIn("verify the saved score and each required step", content)

    def test_fixture_screenshot_can_be_null(self):
        with open(SKILL_PATH, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("`screenshot` may be `null`", content)
        self.assertIn("`driver.Tab` has no `cdp` method", content)

    def test_skill_frontmatter(self):
        with open(SKILL_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertTrue(content.startswith("---"), "SKILL.md must start with ---")
        end_idx = content.find("\n---\n", 3)
        self.assertGreater(end_idx, 0, "SKILL.md must close frontmatter with ---")

        fm_text = content[3:end_idx]
        lines = [line.strip() for line in fm_text.splitlines() if line.strip()]

        data = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                data[k.strip()] = v.strip()

        self.assertEqual(data.get("name"), "engdis-autopilot")
        desc = data.get("description", "")
        self.assertTrue(desc, "Missing description")
        self.assertLessEqual(len(desc), 60, f"Description exceeds 60 chars ({len(desc)}): {desc}")
        self.assertTrue(desc.endswith("."), "Description must end with a period")

        # Ensure no host-specific paths or raw student IDs exist in skill
        self.assertNotIn("/opt/data", content)
        self.assertNotIn("ptithcm1051", content)
        self.assertNotIn("9973921", content)


if __name__ == "__main__":
    unittest.main()
