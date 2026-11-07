import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cover


class WorkerLoggingTests(unittest.TestCase):
    def test_container_uses_persistent_log_directory(self):
        entrypoint = Path(cover.HERE, 'docker', 'entrypoint.sh').read_text()
        self.assertIn('export ED_LOG_DIR=/data/logs', entrypoint)
        self.assertIn('/data/logs', entrypoint.split('mkdir -p', 1)[1].splitlines()[0])

    def test_timeout_is_distinguished_from_worker_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'auto.py').write_text("import time\ntime.sleep(10)\n")
            with patch.object(cover, 'HERE', tmp), patch.object(cover, 'PER_LESSON_TIMEOUT', 0.1):
                rc, _, _ = cover.run_lesson('Slow')
            self.assertEqual(rc, 'timeout')
            self.assertIn('exit rc=timeout', Path(tmp, 'logs', 'Slow.log').read_text())

    def test_worker_output_and_lifecycle_are_timestamped_and_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'auto.py').write_text("print('worker line', flush=True)\n")
            logdir = Path(tmp, 'persistent')
            with patch.object(cover, 'HERE', tmp), patch.dict(os.environ, {'ED_LOG_DIR': str(logdir)}):
                self.assertEqual(cover.run_lesson('Lesson')[0], 0)
                self.assertEqual(cover.run_lesson('Lesson')[0], 0)
            lines = (logdir / 'Lesson.log').read_text().splitlines()
            self.assertEqual(len(lines), 6)
            for line in lines:
                self.assertRegex(line, r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?\+00:00 ')
            self.assertEqual(sum('worker line' in line for line in lines), 2)
            self.assertEqual(sum('start ' in line for line in lines), 2)
            self.assertEqual(sum('exit rc=0' in line for line in lines), 2)
