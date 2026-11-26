import unittest
from unittest.mock import Mock, patch

import auto
import solver


class AttachTranscriptTests(unittest.TestCase):
    def test_skips_when_transcript_already_present(self):
        tab = Mock()
        src = "Question 1\n\nAUDIO TRANSCRIPT:\nAlready here"
        with patch.object(solver, "dom_transcript") as mock_dom, \
             patch.object(solver, "media_url") as mock_url, \
             patch.object(solver, "transcript_for") as mock_tr:
            out = solver.attach_transcript(tab, src)
        self.assertEqual(out, src)
        mock_dom.assert_not_called()
        mock_url.assert_not_called()
        mock_tr.assert_not_called()

    def test_attaches_dom_transcript_without_media_fallback(self):
        tab = Mock()
        with patch.object(solver, "dom_transcript", return_value="Speaker A: Hello"), \
             patch.object(solver, "media_url") as mock_url, \
             patch.object(solver, "transcript_for") as mock_tr:
            out = solver.attach_transcript(tab, "Prompt")
        self.assertIn("AUDIO TRANSCRIPT:\nSpeaker A: Hello", out)
        self.assertTrue(out.startswith("Prompt\n\nAUDIO TRANSCRIPT:\n"))
        mock_url.assert_not_called()
        mock_tr.assert_not_called()

    def test_falls_back_to_media_transcript_for(self):
        tab = Mock()
        with patch.object(solver, "dom_transcript", return_value=None), \
             patch.object(solver, "media_url", return_value="https://cdn.example.com/audio/clip123.mp3?v=1"), \
             patch.object(solver, "transcript_for", return_value="Transcribed audio text") as mock_tr:
            out = solver.attach_transcript(tab, "Prompt")
        mock_tr.assert_called_once_with("https://cdn.example.com/audio/clip123.mp3?v=1", "clip123.mp3")
        self.assertIn("AUDIO TRANSCRIPT:\nTranscribed audio text", out)

    def test_handles_transcript_for_exception_gracefully(self):
        tab = Mock()
        with patch.object(solver, "dom_transcript", return_value=None), \
             patch.object(solver, "media_url", return_value="https://cdn.example.com/audio/clip123.mp3"), \
             patch.object(solver, "transcript_for", side_effect=RuntimeError("network error")):
            out = solver.attach_transcript(tab, "Prompt")
        self.assertEqual(out, "Prompt")


class AutoTranscriptIntegrationTests(unittest.TestCase):
    def test_handle_test_attaches_dom_transcript_before_do_task(self):
        tab = Mock()
        seen = []

        def fake_do_task(_t, src):
            seen.append(src)
            return "mcq: 1/1"

        with patch.object(auto.solver, "dom_transcript", return_value="DOM test audio"), \
             patch.object(auto.solver, "do_task", side_effect=fake_do_task), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "st", return_value={"total": "2", "counter": "1"}):
            res = auto.handle_test(tab, "Test question")
        self.assertEqual(res, "mcq: 1/1")
        self.assertEqual(len(seen), 1)
        self.assertIn("AUDIO TRANSCRIPT:\nDOM test audio", seen[0])

    def test_handle_test_falls_back_to_transcript_for_before_do_task(self):
        tab = Mock()
        seen = []

        def fake_do_task(_t, src):
            seen.append(src)
            return "mcq: 1/1"

        with patch.object(auto.solver, "dom_transcript", return_value=None), \
             patch.object(auto.solver, "media_url", return_value="https://cdn.example.com/v/vid.mp4"), \
             patch.object(auto.solver, "transcript_for", return_value="ASR test audio"), \
             patch.object(auto.solver, "do_task", side_effect=fake_do_task), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "st", return_value={"total": "2", "counter": "1"}):
            res = auto.handle_test(tab, "Test question")
        self.assertEqual(res, "mcq: 1/1")
        self.assertEqual(len(seen), 1)
        self.assertIn("AUDIO TRANSCRIPT:\nASR test audio", seen[0])

    def _run_practice_iteration(self, dom_val, media_val, asr_val):
        class Tab:
            def js(self, expr):
                if expr == auto.IS_TEST_JS:
                    return 0
                if "return 'mcq'" in expr:
                    return "mcq"
                return 0

        state = {
            "unit": "Unit 1",
            "lesson": "Listening Lesson",
            "step": "Step 2: Practice",
            "counter": "1",
            "total": "2",
            "body": "Listen and answer",
        }
        seen = []

        def fake_do_task(_t, src):
            seen.append(src)
            return "mcq: 1/1"

        with patch.object(auto.edlib, "tab", return_value=Tab()), \
             patch.object(auto.login, "ensure_login", return_value=True), \
             patch.object(auto, "st", return_value=state), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "poll") as poll_mock, \
             patch.object(auto, "handle_branch", return_value=None), \
             patch.object(auto, "click_text", return_value=False), \
             patch.object(auto, "advance", return_value=True), \
             patch.object(auto.solver, "source_text", return_value={"resource": "", "body": "Practice question"}), \
             patch.object(auto.solver, "dom_transcript", return_value=dom_val), \
             patch.object(auto.solver, "media_url", return_value=media_val), \
             patch.object(auto.solver, "transcript_for", return_value=asr_val), \
             patch.object(auto.solver, "do_task", side_effect=fake_do_task), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto.time, "sleep"), \
             patch.dict("os.environ", {"ED_TARGET_STEP": "", "ED_UNATTENDED": "", "ED_LESSON_LOCK": ""}):
            poll_mock.wait_until.return_value = 1
            auto.main(max_iter=1)
        return seen

    def test_main_practice_attaches_dom_transcript_before_do_task(self):
        seen = self._run_practice_iteration("DOM practice audio", None, "")
        self.assertEqual(len(seen), 1)
        self.assertIn("AUDIO TRANSCRIPT:\nDOM practice audio", seen[0])

    def test_main_practice_falls_back_to_transcript_for_before_do_task(self):
        seen = self._run_practice_iteration(None, "https://cdn.example.com/a/p1.mp3", "ASR practice audio")
        self.assertEqual(len(seen), 1)
        self.assertIn("AUDIO TRANSCRIPT:\nASR practice audio", seen[0])


if __name__ == "__main__":
    unittest.main()
