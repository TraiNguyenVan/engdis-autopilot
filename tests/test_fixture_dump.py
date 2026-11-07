import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

import solver


class TestFixtureDump(unittest.TestCase):
    def test_dump_task_creates_json_file(self):
        tab = MagicMock()
        tab.js.side_effect = [
            # DUMP_TASK_JS payload
            {
                "html": "<div class='prMCQ__qaSet'><p>Question 1</p></div>",
                "practiceData": {"itemId": 12345, "templateId": "mcq"},
                "body": "Question 1\nOption A\nOption B",
                "url": "https://ed22.engdis.com/Runtime/learningArea.html"
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "test_fixture.json")
            meta = {"lesson": "Astrology", "step": "Practice", "counter": 2}
            res = solver.dump_task(tab, out_file, meta=meta)
            self.assertTrue(os.path.exists(out_file))
            self.assertEqual(res, out_file)
            with open(out_file, "r") as f:
                data = json.load(f)
            self.assertIn("html", data)
            self.assertEqual(data["meta"]["lesson"], "Astrology")
            self.assertIn("prMCQ__qaSet", data["html"])


if __name__ == "__main__":
    unittest.main()
