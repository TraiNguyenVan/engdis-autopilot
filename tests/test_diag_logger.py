import unittest
import tempfile
import json
import shutil
from pathlib import Path
from diag_logger import DiagnosticLogger

class TestDiagnosticLogger(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.logger = DiagnosticLogger(log_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_log_task_writes_jsonl(self):
        evt = self.logger.log_task(
            unit="Unit 5",
            lesson="Soap Opera",
            step="Practice",
            task="6/6",
            kind="drag",
            attempt=1,
            duration_s=12.5,
            result="failed",
            advanced=False,
            details={"error": "0=FAIL 1=FAIL"}
        )
        self.assertEqual(evt["result"], "failed")
        self.assertEqual(evt["type"], "drag")

        events_file = Path(self.test_dir) / "events.jsonl"
        self.assertTrue(events_file.exists())
        lines = events_file.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        data = json.loads(lines[0])
        self.assertEqual(data["task"], "6/6")
        self.assertEqual(data["details"]["error"], "0=FAIL 1=FAIL")

    def test_save_failure_evidence(self):
        saved = self.logger.save_failure_evidence(
            task_sig="task_6",
            dom_snippet="<div>failed widget</div>",
            screenshot_bytes=b"\x89PNG\r\n\x1a\nfake",
            error_msg="stuck on drag"
        )
        self.assertIn("meta", saved)
        self.assertIn("screenshot", saved)
        self.assertTrue(Path(saved["meta"]).exists())
        self.assertTrue(Path(saved["screenshot"]).exists())

if __name__ == "__main__":
    unittest.main()
