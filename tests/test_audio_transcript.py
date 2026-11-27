import os
import subprocess
import sys
import textwrap
import threading
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import auto
import solver


class AttachTranscriptTests(unittest.TestCase):
    def test_skips_when_audio_transcript_marker_has_content(self):
        tab = Mock()
        src = "Question 1\n\nAUDIO TRANSCRIPT:\nAlready here\n[/AUDIO TRANSCRIPT]"
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
        src = "[TRANSCRIPT]\nLegacy transcript text\n[/TRANSCRIPT]\n\nQuestion 1"
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
        mock_tr.assert_called_once_with("https://cdn.example.com/audio/clip1.mp3", solver._media_cache_key("https://cdn.example.com/audio/clip1.mp3"))
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
            "[TRANSCRIPT]\nQuestion 1: What did the speaker say?",
            "AUDIO TRANSCRIPT:\nQuestion 1: What did the speaker say?",
        ):
            with patch.object(solver, "dom_transcript", return_value="Recovered DOM text"):
                out = solver.attach_transcript(tab, prompt)
            self.assertIn("AUDIO TRANSCRIPT:\nRecovered DOM text\n[/AUDIO TRANSCRIPT]", out)

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
        mock_tr.assert_called_once_with("https://cdn.example.com/audio/clip123.mp3?v=1", solver._media_cache_key("https://cdn.example.com/audio/clip123.mp3?v=1"))
        self.assertIn("AUDIO TRANSCRIPT:\nTranscribed audio text", out)

    def test_mp3_and_mp4_with_same_stem_get_distinct_cache_keys(self):
        self.assertEqual(solver._media_cache_key("https://cdn.example.com/a/clip.mp3?v=1"), solver._media_cache_key("https://cdn.example.com/a/clip.mp3?v=1#part"))
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
        self.assertIn("const srcEls = [...document.querySelectorAll('audio,video')].filter(x => x.currentSrc || x.src);", seen_js[0])
        self.assertIn("practice.length ? practice : (resource.length ? resource : all)", seen_js[0])
        self.assertIn("return 0 ? urls[urls.length - 1] : urls[0];", seen_js[0])
        self.assertIn("const visEls = srcEls.filter(isVis);", seen_js[1])
        self.assertIn("return 1 ? urls[urls.length - 1] : urls[0];", seen_js[1])

    def test_handles_transcript_for_exception_gracefully(self):
        tab = Mock()
        with patch.object(solver, "dom_transcript", return_value=None), \
             patch.object(solver, "media_url", return_value="https://cdn.example.com/audio/clip123.mp3"), \
             patch.object(solver, "transcript_for", side_effect=RuntimeError("network error")):
            out = solver.attach_transcript(tab, "Prompt")
        self.assertEqual(out, "Prompt")


class TranscriptIdentityRegressionTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux RLIMIT_FSIZE")
    def test_legacy_migration_partial_write_is_removed_and_retry_succeeds(self):
        script = textwrap.dedent('''
            import os, resource, signal, sys
            import solver
            scratch, source = sys.argv[1:]
            solver.SCRATCH = scratch
            url = "https://cdn.example.com/a/clip.mp3"
            destination = os.path.join(scratch, "tr_" + solver._media_cache_key(url) + ".txt")
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            previous = resource.getrlimit(resource.RLIMIT_FSIZE)
            resource.setrlimit(resource.RLIMIT_FSIZE, (16, previous[1]))
            try:
                try:
                    solver.migrate_legacy_transcript(url, source)
                except OSError:
                    pass
                else:
                    raise AssertionError("write did not fail")
            finally:
                resource.setrlimit(resource.RLIMIT_FSIZE, previous)
            assert not os.path.exists(destination), "partial destination was published"
            assert os.listdir(scratch) == [], os.listdir(scratch)
            solver.migrate_legacy_transcript(url, source)
            with open(destination) as f:
                assert f.read() == "original transcript " * 1000
        ''')
        with tempfile.TemporaryDirectory() as tmp:
            scratch = os.path.join(tmp, "cache")
            source = os.path.join(tmp, "legacy.txt")
            os.mkdir(scratch)
            with open(source, "w") as f:
                f.write("original transcript " * 1000)
            result = subprocess.run([sys.executable, "-c", script, scratch, source],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(source) as f:
                self.assertEqual(f.read(), "original transcript " * 1000)

    def test_transcription_cannot_overwrite_a_concurrent_migration(self):
        url = "https://cdn.example.com/a.mp4"
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b"media"
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "legacy.txt")
            with open(source, "w") as f: f.write("verified legacy")
            def transcribe(_path):
                solver.migrate_legacy_transcript(url, source)
                return "fresh transcript"
            with patch.object(solver, "SCRATCH", tmp), \
                 patch.object(solver.urllib.request, "urlopen", return_value=Response()), \
                 patch.object(solver, "transcribe_groq", side_effect=transcribe):
                solver.transcript_for(url, "ignored")
                self.assertEqual(solver.transcript_for(url, "ignored"), "verified legacy")

    def test_migration_publish_failure_cleans_temporary_file(self):
        url = "https://cdn.example.com/a.mp3"
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "legacy.txt")
            with open(source, "w") as f:
                f.write("source")
            with patch.object(solver, "SCRATCH", tmp), \
                 patch.object(solver.os, "link", side_effect=OSError("unsupported")):
                with self.assertRaises(OSError):
                    solver.migrate_legacy_transcript(url, source)
            self.assertEqual(os.listdir(tmp), ["legacy.txt"])

    def test_migration_never_overwrites_existing_transcript(self):
        url = "https://cdn.example.com/a.mp3"
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "legacy.txt")
            destination = os.path.join(tmp, f"tr_{solver._media_cache_key(url)}.txt")
            with open(source, "w") as f: f.write("source")
            with open(destination, "w") as f: f.write("existing")
            with patch.object(solver, "SCRATCH", tmp):
                with self.assertRaises(FileExistsError):
                    solver.migrate_legacy_transcript(url, source)
            with open(destination) as f: self.assertEqual(f.read(), "existing")
            with open(source) as f: self.assertEqual(f.read(), "source")
            self.assertEqual(set(os.listdir(tmp)), {"legacy.txt", os.path.basename(destination)})

    def test_concurrent_migrations_publish_only_one_complete_transcript(self):
        url = "https://cdn.example.com/a.mp3"
        with tempfile.TemporaryDirectory() as tmp:
            sources = [os.path.join(tmp, f"legacy{i}.txt") for i in range(2)]
            contents = ["first" * 5000, "second" * 5000]
            for path, text in zip(sources, contents):
                with open(path, "w") as f: f.write(text)
            barrier = threading.Barrier(2)
            real_link = os.link
            results = []
            def concurrent_link(src, dst):
                barrier.wait(timeout=5)
                return real_link(src, dst)
            def migrate(path):
                try:
                    solver.migrate_legacy_transcript(url, path)
                    results.append("success")
                except FileExistsError:
                    results.append("exists")
                except Exception as exc:
                    results.append(repr(exc))
            with patch.object(solver, "SCRATCH", tmp), patch.object(solver.os, "link", side_effect=concurrent_link):
                threads = [threading.Thread(target=migrate, args=(path,)) for path in sources]
                for thread in threads: thread.start()
                for thread in threads: thread.join(timeout=10)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertCountEqual(results, ["success", "exists"])
            destination = os.path.join(tmp, f"tr_{solver._media_cache_key(url)}.txt")
            with open(destination) as f: self.assertIn(f.read(), contents)
            self.assertEqual(set(os.listdir(tmp)), {"legacy0.txt", "legacy1.txt", os.path.basename(destination)})

    def test_fragment_does_not_change_media_type(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b"video"
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(solver, "SCRATCH", tmp), \
             patch.object(solver.urllib.request, "urlopen", return_value=Response()), \
             patch.object(solver, "transcribe_groq", return_value="text") as stt:
            solver.transcript_for("https://cdn.example.com/clip.mp4#time=1", "ignored")
            self.assertTrue(stt.call_args.args[0].endswith(".mp4"))

    def test_failed_download_cannot_be_transcribed_as_cached_media_on_retry(self):
        class BrokenResponse:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): raise OSError("interrupted")
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(solver, "SCRATCH", tmp), \
             patch.object(solver.urllib.request, "urlopen", return_value=BrokenResponse()), \
             patch.object(solver, "transcribe_groq", return_value="wrong") as stt, \
             patch("builtins.print"):
            self.assertEqual(solver.transcript_for("https://cdn.example.com/a.mp3", "a_mp3"), "")
            stt.assert_not_called()
            self.assertEqual(os.listdir(tmp), [])

    def test_query_is_part_of_identity_and_paths_never_contain_url_secrets(self):
        a = "https://user:pass@cdn.example.com/path/clip.mp3?token=secret1"
        b = "https://user:pass@cdn.example.com/path/clip.mp3?token=secret2"
        self.assertNotEqual(solver._media_cache_key(a), solver._media_cache_key(b))
        self.assertRegex(solver._media_cache_key(a), r"^[0-9a-f]{64}$")

    def test_explicitly_migrated_legacy_transcript_is_reused_only_for_target_url(self):
        first = "https://cdn.example.com/one/clip.mp3?token=secret"
        second = "https://cdn.example.com/two/clip.mp3?token=secret"
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "tr_clip.mp3.txt")
            with open(old, "w") as f:
                f.write("verified old transcript")
            with patch.object(solver, "SCRATCH", tmp), \
                 patch.object(solver.urllib.request, "urlopen", side_effect=OSError("offline")), \
                 patch("builtins.print"):
                solver.migrate_legacy_transcript(first, old)
                self.assertEqual(solver.transcript_for(first, "clip_mp3"), "verified old transcript")
                self.assertEqual(solver.transcript_for(second, "clip_mp3"), "")
                with self.assertRaises(FileExistsError):
                    solver.migrate_legacy_transcript(first, old)
            with open(old) as f:
                self.assertEqual(f.read(), "verified old transcript")

    def test_download_error_does_not_log_url_or_exception_secrets(self):
        url = "https://user:pass@cdn.example.com/private/clip.mp3?token=secret"
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(solver, "SCRATCH", tmp), \
             patch.object(solver.urllib.request, "urlopen", side_effect=OSError(url)), \
             patch("builtins.print") as printer:
            self.assertEqual(solver.transcript_for(url, "../../escape"), "")
            logs = " ".join(str(call) for call in printer.call_args_list)
            self.assertNotIn("secret", logs)
            self.assertNotIn("pass", logs)
            self.assertNotIn("/private/", logs)

    def test_legacy_name_only_transcript_is_not_reused_for_other_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "tr_clip.mp3.txt"), "w") as f:
                f.write("wrong old transcript")
            with patch.object(solver, "SCRATCH", tmp), \
                 patch.object(solver.urllib.request, "urlopen", side_effect=OSError("offline")), \
                 patch("builtins.print"):
                result = solver.transcript_for("https://cdn.example.com/two/clip.mp3", "clip_mp3")
            self.assertEqual(result, "")

    def test_distinct_paths_with_same_filename_never_reuse_transcript_or_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            urls = ["https://cdn.example.com/one/clip.mp3", "https://cdn.example.com/two/clip.mp3"]
            class Response:
                def __init__(self, data): self.data = data
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self): return self.data
            def download(req, timeout):
                return Response(b"first" if req.full_url == urls[0] else b"second")
            def transcribe(path):
                with open(path, "rb") as f:
                    return f.read().decode()
            with patch.object(solver, "SCRATCH", tmp), \
                 patch.object(solver.urllib.request, "urlopen", side_effect=download) as opener, \
                 patch.object(solver, "transcribe_groq", side_effect=transcribe):
                first = solver.transcript_for(urls[0], solver._media_cache_key(urls[0]))
                second = solver.transcript_for(urls[1], solver._media_cache_key(urls[1]))
                again = solver.transcript_for(urls[0], solver._media_cache_key(urls[0]))
            self.assertEqual((first, second, again), ("first", "second", "first"))
            self.assertEqual(opener.call_count, 2)


class TranscriptCacheCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ed-tr-cache-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_media_distinguishing_cache_without_download(self):
        url_mp3 = "https://cdn.example.com/a/clip99.mp3?token=1"
        url_mp4 = "https://cdn.example.com/v/clip99.mp4?token=1"
        with open(os.path.join(self.tmp, f"tr_{solver._media_cache_key(url_mp3)}.txt"), "w", encoding="utf-8") as f:
            f.write("Cached mp3 transcript")
        with open(os.path.join(self.tmp, f"tr_{solver._media_cache_key(url_mp4)}.txt"), "w", encoding="utf-8") as f:
            f.write("Cached mp4 transcript")
        with patch.object(solver, "SCRATCH", self.tmp), \
             patch.object(solver.urllib.request, "urlopen") as mock_open:
            out_mp3 = solver.transcript_for("https://cdn.example.com/a/clip99.mp3?token=1", "clip99_mp3")
            out_mp4 = solver.transcript_for("https://cdn.example.com/v/clip99.mp4?token=1", "clip99_mp4")
        self.assertEqual(out_mp3, "Cached mp3 transcript")
        self.assertEqual(out_mp4, "Cached mp4 transcript")
        mock_open.assert_not_called()

    def test_migrates_legacy_extensionless_cache_without_download(self):
        with open(os.path.join(self.tmp, "tr_clip99.txt"), "w", encoding="utf-8") as f:
            f.write("Cached stem transcript")
        with open(os.path.join(self.tmp, "m_clip99.mp3"), "wb") as f:
            f.write(b"mp3data")
        with patch.object(solver, "SCRATCH", self.tmp), \
             patch.object(solver.urllib.request, "urlopen") as mock_open:
            solver.migrate_legacy_transcript("https://cdn.example.com/a/clip99.mp3?token=1", os.path.join(self.tmp, "tr_clip99.txt"))
            out = solver.transcript_for("https://cdn.example.com/a/clip99.mp3?token=1", "clip99_mp3")
        self.assertEqual(out, "Cached stem transcript")
        mock_open.assert_not_called()

    def test_ignores_ambiguous_legacy_extensionless_cache_for_other_media_type(self):
        with open(os.path.join(self.tmp, "tr_clip99.txt"), "w", encoding="utf-8") as f:
            f.write("Cached mp3 transcript")
        with open(os.path.join(self.tmp, "m_clip99.mp3"), "wb") as f:
            f.write(b"mp3data")
        with patch.object(solver, "SCRATCH", self.tmp), \
             patch.object(solver.urllib.request, "urlopen", side_effect=OSError("offline")):
            out = solver.transcript_for("https://cdn.example.com/v/clip99.mp4?token=1", "clip99_mp4")
        self.assertEqual(out, "")

    def test_ignores_unverified_legacy_extensionless_cache(self):
        with open(os.path.join(self.tmp, "tr_clip99.txt"), "w", encoding="utf-8") as f:
            f.write("Orphan stem transcript")
        with patch.object(solver, "SCRATCH", self.tmp), \
             patch.object(solver.urllib.request, "urlopen", side_effect=OSError("offline")):
            out = solver.transcript_for("https://cdn.example.com/a/clip99.mp3", "clip99_mp3")
        self.assertEqual(out, "")

    def test_migrates_legacy_filename_with_extension_cache_without_download(self):
        with open(os.path.join(self.tmp, "tr_clip99.mp3.txt"), "w", encoding="utf-8") as f:
            f.write("Cached legacy ext transcript")
        with patch.object(solver, "SCRATCH", self.tmp), \
             patch.object(solver.urllib.request, "urlopen") as mock_open:
            solver.migrate_legacy_transcript("https://cdn.example.com/a/clip99.mp3?token=1", os.path.join(self.tmp, "tr_clip99.mp3.txt"))
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
        mock_tr.assert_called_once_with("https://cdn.example.com/v/vid.mp4", solver._media_cache_key("https://cdn.example.com/v/vid.mp4"))
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

    def test_main_practice_retains_transcript_across_questions_and_clears_on_step_change(self):
        states = [
            {"unit": "U1", "lesson": "L1", "step": "Step 2: Practice", "counter": "1", "total": "2", "body": "Q1"},
            {"unit": "U1", "lesson": "L1", "step": "Step 2: Practice", "counter": "2", "total": "2", "body": "Q2"},
            {"unit": "U1", "lesson": "L1", "step": "Step 3: Reading", "counter": "1", "total": "1", "body": "Q3"},
        ]
        seen = self._run_practice_iteration(
            None,
            None,
            "",
            source_side_effect=[
                {"resource": "R1", "body": "Init"},
                {"resource": "R1", "body": "Q1"},
                {"resource": "R1", "body": "Q2"},
                {"resource": "R3", "body": "Q3"},
            ],
            max_iter=3,
            states=states,
        )
        # Re-run with DOM transcript present only on Q1
        class Tab:
            def js(self, expr):
                if expr == auto.IS_TEST_JS:
                    return 0
                if "return 'mcq'" in expr:
                    return "mcq"
                return 0

        seen2 = []
        with patch.object(auto.edlib, "tab", return_value=Tab()), \
             patch.object(auto.login, "ensure_login", return_value=True), \
             patch.object(auto, "st", side_effect=states), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "poll") as poll_mock, \
             patch.object(auto, "handle_branch", return_value=None), \
             patch.object(auto, "click_text", return_value=False), \
             patch.object(auto, "advance", return_value=True), \
             patch.object(auto.solver, "source_text", side_effect=[
                 {"resource": "R1", "body": "Init"},
                 {"resource": "R1", "body": "Q1"},
                 {"resource": "R1", "body": "Q2"},
                 {"resource": "R3", "body": "Q3"},
             ]), \
             patch.object(auto.solver, "dom_transcript", side_effect=["Shared practice audio", None, None]), \
             patch.object(auto.solver, "media_url", return_value=None), \
             patch.object(auto.solver, "do_task", side_effect=lambda _t, s: (seen2.append(s), "mcq: 1/1")[1]), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto.time, "sleep"), \
             patch.dict("os.environ", {"ED_TARGET_STEP": "", "ED_UNATTENDED": "", "ED_LESSON_LOCK": ""}):
            poll_mock.wait_until.return_value = 1
            auto.main(max_iter=3)

        self.assertEqual(len(seen), 3)
        self.assertEqual(len(seen2), 3)
        self.assertIn("AUDIO TRANSCRIPT:\nShared practice audio", seen2[0])
        self.assertIn("AUDIO TRANSCRIPT:\nShared practice audio", seen2[1])
        self.assertNotIn("Shared practice audio", seen2[2])


class SolverMainTranscriptTests(unittest.TestCase):
    def test_solver_main_keeps_lesson_transcript_within_step_and_clears_on_step_change(self):
        class Tab:
            def js(self, expr):
                return ""

        states = [
            {"url": "https://lms.example.com/lesson", "lesson": "L1", "step": "Step 2", "counter": "1", "total": "2"},
            {"url": "https://lms.example.com/lesson", "lesson": "L1", "step": "Step 2", "counter": "2", "total": "2"},
            {"url": "https://lms.example.com/lesson", "lesson": "L1", "step": "Step 3", "counter": "1", "total": "1"},
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
                 {"resource": "R2", "body": "Q1 Step 3"},
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

    def test_resolve_task_transcript_retains_bounded_legacy_bracket_transcript(self):
        tab = Mock()
        state = {}
        with patch.object(solver, "dom_transcript", return_value=None), \
             patch.object(solver, "media_url", return_value=None):
            s1 = solver.resolve_task_transcript(
                tab, "[TRANSCRIPT]\nLegacy bounded audio\n[/TRANSCRIPT]\n\nQ1", ("L1", "Step 2"), state
            )
            s2 = solver.resolve_task_transcript(tab, "Q2", ("L1", "Step 2"), state)
            s3 = solver.resolve_task_transcript(tab, "Q3", ("L1", "Step 3"), state)
        self.assertIn("Legacy bounded audio", s1)
        self.assertIn("Legacy bounded audio", s2)
        self.assertNotIn("Legacy bounded audio", s3)

    def test_resolve_task_transcript_does_not_reuse_previous_clip_when_new_clip_fails(self):
        tab = Mock()
        state = {}
        with patch.object(solver, "dom_transcript", return_value=None), \
             patch.object(solver, "media_url", side_effect=[
                 "https://cdn.example.com/a/clip1.mp3",
                 "https://cdn.example.com/a/clip1.mp3",
                 "https://cdn.example.com/a/clip2.mp3",
                 "https://cdn.example.com/a/clip2.mp3",
             ]), \
             patch.object(solver, "transcript_for", side_effect=["Clip 1 transcript", ""]):
            s1 = solver.resolve_task_transcript(tab, "Q1", ("L1", "Step 2: Practice"), state)
            s2 = solver.resolve_task_transcript(tab, "Q2", ("L1", "Step 2: Practice"), state)
        self.assertIn("Clip 1 transcript", s1)
        self.assertNotIn("Clip 1 transcript", s2)
        self.assertEqual(s2, "Q2")


if __name__ == "__main__":
    unittest.main()
