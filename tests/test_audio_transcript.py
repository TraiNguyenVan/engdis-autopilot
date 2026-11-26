import os
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import auto
import solver


class AttachTranscriptTests(unittest.TestCase):
    def test_skips_when_audio_transcript_marker_has_content(self):
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

    def test_skips_when_legacy_bracket_transcript_marker_has_content(self):
        tab = Mock()
        src = "[TRANSCRIPT]\nLegacy transcript text\n\nQuestion 1"
        with patch.object(solver, "dom_transcript") as mock_dom, \
             patch.object(solver, "media_url") as mock_url, \
             patch.object(solver, "transcript_for") as mock_tr:
            out = solver.attach_transcript(tab, src)
        self.assertEqual(out, src)
        mock_dom.assert_not_called()
        mock_url.assert_not_called()
        mock_tr.assert_not_called()

    def test_does_not_skip_when_prompt_mentions_word_transcript(self):
        tab = Mock()
        prompt = "Read the academic transcript instructions and listen to the recording."
        with patch.object(solver, "dom_transcript", return_value=None), \
             patch.object(solver, "media_url", return_value="https://cdn.example.com/audio/clip1.mp3"), \
             patch.object(solver, "transcript_for", return_value="Actual spoken words") as mock_tr:
            out = solver.attach_transcript(tab, prompt)
        mock_tr.assert_called_once_with("https://cdn.example.com/audio/clip1.mp3", "clip1_mp3")
        self.assertIn("AUDIO TRANSCRIPT:\nActual spoken words", out)

    def test_does_not_skip_when_marker_has_empty_content(self):
        tab = Mock()
        prompt = "Prompt\n\nAUDIO TRANSCRIPT:\n   "
        with patch.object(solver, "dom_transcript", return_value="Recovered DOM text"):
            out = solver.attach_transcript(tab, prompt)
        self.assertIn("AUDIO TRANSCRIPT:\nRecovered DOM text", out)

    def test_does_not_skip_when_empty_marker_precedes_question_text(self):
        tab = Mock()
        for prompt in (
            "[TRANSCRIPT]\n\nQuestion 1: What did the speaker say?",
            "AUDIO TRANSCRIPT:\n\nQuestion 1: What did the speaker say?",
        ):
            with patch.object(solver, "dom_transcript", return_value="Recovered DOM text"):
                out = solver.attach_transcript(tab, prompt)
            self.assertIn("AUDIO TRANSCRIPT:\nRecovered DOM text", out)

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

    def test_falls_back_to_media_transcript_for_with_media_distinguishing_key(self):
        tab = Mock()
        with patch.object(solver, "dom_transcript", return_value=None), \
             patch.object(solver, "media_url", return_value="https://cdn.example.com/audio/clip123.mp3?v=1"), \
             patch.object(solver, "transcript_for", return_value="Transcribed audio text") as mock_tr:
            out = solver.attach_transcript(tab, "Prompt")
        mock_tr.assert_called_once_with("https://cdn.example.com/audio/clip123.mp3?v=1", "clip123_mp3")
        self.assertIn("AUDIO TRANSCRIPT:\nTranscribed audio text", out)

    def test_mp3_and_mp4_with_same_stem_get_distinct_cache_keys(self):
        self.assertEqual(solver._media_cache_key("https://cdn.example.com/a/clip.mp3?v=1"), "clip_mp3")
        self.assertEqual(solver._media_cache_key("https://cdn.example.com/v/clip.mp4?v=1"), "clip_mp4")
        self.assertNotEqual(
            solver._media_cache_key("https://cdn.example.com/a/clip.mp3"),
            solver._media_cache_key("https://cdn.example.com/v/clip.mp4"),
        )

    def test_prefer_last_media_passes_flag_to_media_url(self):
        tab = Mock()
        with patch.object(solver, "dom_transcript", return_value=None), \
             patch.object(solver, "media_url", return_value="https://cdn.example.com/audio/last.mp3") as mock_url, \
             patch.object(solver, "transcript_for", return_value="Last clip text"):
            out = solver.attach_transcript(tab, "Prompt", label="test", prefer_last_media=True)
        mock_url.assert_called_once_with(tab, prefer_last=True)
        self.assertIn("AUDIO TRANSCRIPT:\nLast clip text", out)

    def test_media_url_js_uses_first_by_default_and_last_when_requested(self):
        seen_js = []

        class FakeTab:
            def js(self, expr):
                seen_js.append(expr)
                return "https://cdn.example.com/audio/a.mp3"

        tab = FakeTab()
        solver.media_url(tab)
        solver.media_url(tab, prefer_last=True)
        self.assertIn("const urls = 0 ? all : (scoped.length ? scoped : all);", seen_js[0])
        self.assertIn("return 0 ? urls[urls.length - 1] : urls[0];", seen_js[0])
        self.assertIn("const urls = 1 ? all : (scoped.length ? scoped : all);", seen_js[1])
        self.assertIn("return 1 ? urls[urls.length - 1] : urls[0];", seen_js[1])

    def test_handles_transcript_for_exception_gracefully(self):
        tab = Mock()
        with patch.object(solver, "dom_transcript", return_value=None), \
             patch.object(solver, "media_url", return_value="https://cdn.example.com/audio/clip123.mp3"), \
             patch.object(solver, "transcript_for", side_effect=RuntimeError("network error")):
            out = solver.attach_transcript(tab, "Prompt")
        self.assertEqual(out, "Prompt")


class TranscriptCacheCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ed-tr-cache-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_media_distinguishing_cache_without_download(self):
        with open(os.path.join(self.tmp, "tr_clip99_mp3.txt"), "w", encoding="utf-8") as f:
            f.write("Cached mp3 transcript")
        with open(os.path.join(self.tmp, "tr_clip99_mp4.txt"), "w", encoding="utf-8") as f:
            f.write("Cached mp4 transcript")
        with patch.object(solver, "SCRATCH", self.tmp), \
             patch.object(solver.urllib.request, "urlopen") as mock_open:
            out_mp3 = solver.transcript_for("https://cdn.example.com/a/clip99.mp3?token=1", "clip99_mp3")
            out_mp4 = solver.transcript_for("https://cdn.example.com/v/clip99.mp4?token=1", "clip99_mp4")
        self.assertEqual(out_mp3, "Cached mp3 transcript")
        self.assertEqual(out_mp4, "Cached mp4 transcript")
        mock_open.assert_not_called()

    def test_reads_legacy_extensionless_cache_without_download(self):
        with open(os.path.join(self.tmp, "tr_clip99.txt"), "w", encoding="utf-8") as f:
            f.write("Cached stem transcript")
        with patch.object(solver, "SCRATCH", self.tmp), \
             patch.object(solver.urllib.request, "urlopen") as mock_open:
            out = solver.transcript_for("https://cdn.example.com/a/clip99.mp3?token=1", "clip99_mp3")
        self.assertEqual(out, "Cached stem transcript")
        mock_open.assert_not_called()

    def test_reads_legacy_filename_with_extension_cache_without_download(self):
        with open(os.path.join(self.tmp, "tr_clip99.mp3.txt"), "w", encoding="utf-8") as f:
            f.write("Cached legacy ext transcript")
        with patch.object(solver, "SCRATCH", self.tmp), \
             patch.object(solver.urllib.request, "urlopen") as mock_open:
            out = solver.transcript_for("https://cdn.example.com/a/clip99.mp3?token=1", "clip99_mp3")
        self.assertEqual(out, "Cached legacy ext transcript")
        mock_open.assert_not_called()


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

    def test_handle_test_uses_prefer_last_media_and_extensionless_key(self):
        tab = Mock()
        seen = []

        def fake_do_task(_t, src):
            seen.append(src)
            return "mcq: 1/1"

        with patch.object(auto.solver, "dom_transcript", return_value=None), \
             patch.object(auto.solver, "media_url", return_value="https://cdn.example.com/v/vid.mp4") as mock_url, \
             patch.object(auto.solver, "transcript_for", return_value="ASR test audio") as mock_tr, \
             patch.object(auto.solver, "do_task", side_effect=fake_do_task), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "st", return_value={"total": "2", "counter": "1"}):
            res = auto.handle_test(tab, "Read the transcript prompt")
        mock_url.assert_called_once_with(tab, prefer_last=True)
        mock_tr.assert_called_once_with("https://cdn.example.com/v/vid.mp4", "vid_mp4")
        self.assertEqual(res, "mcq: 1/1")
        self.assertEqual(len(seen), 1)
        self.assertIn("AUDIO TRANSCRIPT:\nASR test audio", seen[0])

    def _run_practice_iteration(self, dom_val, media_val, asr_val, source_side_effect=None, max_iter=1, states=None):
        class Tab:
            def js(self, expr):
                if expr == auto.IS_TEST_JS:
                    return 0
                if "return 'mcq'" in expr:
                    return "mcq"
                return 0

        default_state = {
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

        st_patch = (
            patch.object(auto, "st", side_effect=states)
            if states is not None
            else patch.object(auto, "st", return_value=default_state)
        )
        src_patch = (
            patch.object(auto.solver, "source_text", side_effect=source_side_effect)
            if source_side_effect is not None
            else patch.object(auto.solver, "source_text", return_value={"resource": "", "body": "Practice question"})
        )

        with patch.object(auto.edlib, "tab", return_value=Tab()), \
             patch.object(auto.login, "ensure_login", return_value=True), \
             st_patch, \
             patch.object(auto, "update_live_status"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "poll") as poll_mock, \
             patch.object(auto, "handle_branch", return_value=None), \
             patch.object(auto, "click_text", return_value=False), \
             patch.object(auto, "advance", return_value=True), \
             src_patch, \
             patch.object(auto.solver, "dom_transcript", return_value=dom_val), \
             patch.object(auto.solver, "media_url", return_value=media_val), \
             patch.object(auto.solver, "transcript_for", return_value=asr_val), \
             patch.object(auto.solver, "do_task", side_effect=fake_do_task), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto.time, "sleep"), \
             patch.dict("os.environ", {"ED_TARGET_STEP": "", "ED_UNATTENDED": "", "ED_LESSON_LOCK": ""}):
            poll_mock.wait_until.return_value = 1
            auto.main(max_iter=max_iter)
        return seen

    def test_main_practice_attaches_dom_transcript_before_do_task(self):
        seen = self._run_practice_iteration("DOM practice audio", None, "")
        self.assertEqual(len(seen), 1)
        self.assertIn("AUDIO TRANSCRIPT:\nDOM practice audio", seen[0])

    def test_main_practice_falls_back_to_transcript_for_before_do_task(self):
        seen = self._run_practice_iteration(None, "https://cdn.example.com/a/p1.mp3", "ASR practice audio")
        self.assertEqual(len(seen), 1)
        self.assertIn("AUDIO TRANSCRIPT:\nASR practice audio", seen[0])

    def test_main_practice_preserves_lesson_resource_when_task_resource_empty(self):
        seen = self._run_practice_iteration(
            None,
            "https://cdn.example.com/a/p1.mp3",
            "ASR practice audio",
            source_side_effect=[
                {"resource": "Explore passage context", "body": "Initial body"},
                {"resource": "", "body": "Practice question"},
            ],
        )
        self.assertEqual(len(seen), 1)
        self.assertIn("Explore passage context", seen[0])
        self.assertIn("AUDIO TRANSCRIPT:\nASR practice audio", seen[0])


class SolverMainTranscriptTests(unittest.TestCase):
    def test_solver_main_keeps_lesson_transcript_when_media_disappears_on_next_task(self):
        class Tab:
            def js(self, expr):
                return ""

        states = [
            {"url": "https://lms.example.com/lesson", "lesson": "L1", "step": "Step 2", "counter": "1", "total": "2"},
            {"url": "https://lms.example.com/lesson", "lesson": "L1", "step": "Step 2", "counter": "2", "total": "2"},
            {"url": "https://lms.example.com/lesson", "lesson": "L2", "step": "Step 2", "counter": "1", "total": "1"},
        ]
        seen = []

        def fake_do_task(_t, src):
            seen.append(src)
            return "mcq: ok"

        with patch.object(solver.edlib, "tab", return_value=Tab()), \
             patch.object(solver, "state", side_effect=states), \
             patch.object(solver, "source_text", side_effect=[
                 {"resource": "R1", "body": "Init"},
                 {"resource": "R1", "body": "Q1"},
                 {"resource": "R1", "body": "Q2"},
                 {"resource": "R2", "body": "Init L2"},
                 {"resource": "R2", "body": "Q1 L2"},
             ]), \
             patch.object(solver, "dom_transcript", side_effect=["Shared L1 transcript", None, None]), \
             patch.object(solver, "media_url", return_value=None), \
             patch.object(solver, "jso", return_value=0), \
             patch.object(solver, "neutralize"), \
             patch.object(solver, "do_task", side_effect=fake_do_task), \
             patch.object(solver, "next_task"), \
             patch.object(solver.time, "sleep"):
            solver.main(max_tasks=3)

        self.assertEqual(len(seen), 3)
        self.assertIn("AUDIO TRANSCRIPT:\nShared L1 transcript", seen[0])
        self.assertIn("AUDIO TRANSCRIPT:\nShared L1 transcript", seen[1])
        self.assertNotIn("Shared L1 transcript", seen[2])


if __name__ == "__main__":
    unittest.main()
