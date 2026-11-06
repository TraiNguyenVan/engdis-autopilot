import json
import tempfile
import unittest
from pathlib import Path

import dashboard_data

class DataTest(unittest.TestCase):
    def test_empty_and_processes(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d); proc = r / "proc"; proc.mkdir()
            s = dashboard_data.snapshot(r, proc, now=100)
            self.assertFalse(s["running"]); self.assertIsNone(s["report"])
            for pid, command in (("1", b"python3\0cover.py\0" + b"3\0"), ("2", b"python3\0auto.py\090\0"), ("3", b"python3\0dashboard_server.py\0")):
                p = proc / pid; p.mkdir(); (p / "cmdline").write_bytes(command)
            s = dashboard_data.snapshot(r, proc)
            self.assertEqual({p["script"] for p in s["processes"]}, {"cover.py", "auto.py"})
    def test_report_and_safe_activity(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d); proc = r / "proc"; proc.mkdir(); (r / "logs").mkdir()
            (r / "cover_report_u3.json").write_text(json.dumps({"unit":"U", "unit_progress":[.8], "lessons":{"A":{"final":1}, "B":{"final":[.5],"blocked":True,"rc":3}}}))
            (r / "logs" / "A.log").write_text("secret-token-123 SPEAK-BLOCKED\n")
            s = dashboard_data.snapshot(r, proc)
            self.assertEqual(s["report"]["progress"], .8); self.assertIsNone(s["report"]["lessons"][0]["score"])
            self.assertNotIn("secret-token-123", json.dumps(s)); self.assertEqual(s["activity"]["type"], "Speaking blocked")
    def test_bad_report_and_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d); proc = r / "proc"; proc.mkdir()
            (r / "cover_report_u3.json").write_text("{")
            (r / "cover_report_u4.json").symlink_to("/etc/passwd")
            s = dashboard_data.snapshot(r, proc)
            self.assertIsNone(s["report"]); self.assertTrue(s["errors"])

if __name__ == "__main__": unittest.main()
