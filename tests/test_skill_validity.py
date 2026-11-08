import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
SKILL_PATH = os.path.join(REPO_ROOT, ".agents", "skills", "engdis-autopilot", "SKILL.md")


class TestSkillValidity(unittest.TestCase):
    def test_skill_file_exists(self):
        self.assertTrue(os.path.exists(SKILL_PATH), f"Missing {SKILL_PATH}")

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
