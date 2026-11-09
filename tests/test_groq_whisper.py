import json
import os
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

import config
import solver


class TestGroqWhisper(unittest.TestCase):
    def setUp(self):
        self.tmp_mp3 = "/tmp/test_whisper_dummy.mp3"
        with open(self.tmp_mp3, "wb") as f:
            f.write(b"dummy mp3 data")

    def tearDown(self):
        if os.path.exists(self.tmp_mp3):
            os.remove(self.tmp_mp3)

    def test_transcribe_groq_missing_key(self):
        with patch.object(config, "GROQ_API_KEY", ""):
            res = solver.transcribe_groq(self.tmp_mp3)
            self.assertEqual(res, "")

    def test_transcribe_groq_missing_file(self):
        with patch.object(config, "GROQ_API_KEY", "test-key"):
            res = solver.transcribe_groq("/nonexistent/file.mp3")
            self.assertEqual(res, "")

    @patch("urllib.request.urlopen")
    def test_transcribe_groq_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"text": "Hello world from Groq"}).encode()
        mock_urlopen.return_value = mock_resp

        with patch.object(config, "GROQ_API_KEY", "gsk_test123"):
            res = solver.transcribe_groq(self.tmp_mp3)
            self.assertEqual(res, "Hello world from Groq")
            self.assertTrue(mock_urlopen.called)

    @patch("urllib.request.urlopen")
    def test_transcribe_groq_api_failure(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("500 Server Error")

        with patch.object(config, "GROQ_API_KEY", "gsk_test123"):
            res = solver.transcribe_groq(self.tmp_mp3)
            self.assertEqual(res, "")


if __name__ == "__main__":
    unittest.main()
