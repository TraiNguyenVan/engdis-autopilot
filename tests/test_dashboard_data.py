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

    def test_live_status_and_diagnostic_events(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d); proc = r / "proc"; proc.mkdir()
            # write live status
            (r / "live_status.json").write_text(json.dumps({
                "unit": "Unit 5",
                "lesson": "Lesson 1",
                "step": "Step 2: Practice",
                "task": "3",
                "total_tasks": "6",
                "progress": 0.5,
                "last_action": "solve_mcq"
            }))
            # write events.jsonl
            diag_dir = r / "logs_diag"
            diag_dir.mkdir()
            (diag_dir / "events.jsonl").write_text(
                json.dumps({"time": "2026-11-06T10:00:00Z", "lesson": "L1", "step": "S2", "task": "1", "type": "mcq", "result": "ok", "duration_s": 1.2, "advanced": True}) + "\n" +
                json.dumps({"time": "2026-11-06T10:00:05Z", "lesson": "L1", "step": "S2", "task": "2", "type": "drag", "result": "fail", "duration_s": 2.5, "advanced": False}) + "\n"
            )
            s = dashboard_data.snapshot(r, proc)
            self.assertIsNotNone(s["live"])
            self.assertEqual(s["live"]["lesson"], "Lesson 1")
            self.assertEqual(s["live"]["progress"], 0.5)
            self.assertEqual(len(s["recent_events"]), 2)
            self.assertEqual(s["recent_events"][-1]["type"], "drag")

if __name__ == "__main__": unittest.main()
