"""Pins the solver.py behaviour merged from the upstream 100% handoff.

Covers: two-round model pool in ask(), TPD-vs-RPM 429 handling, strict=False
JSON, Groq video/mp4 uploads, urllib media download in transcript_for (no
ffmpeg), the mp3-only input_audio fallback, and play_media's ended latch.
"""
import base64
import email.message
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
import warnings
from unittest.mock import patch

import config
import solver


LAST_ERR_URL = "https://llm.local/v1/chat/completions"


class _Resp:
    """Minimal urlopen() result: .read() plus context-manager protocol."""

    def __init__(self, data):
        self._data = data if isinstance(data, bytes) else data.encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ok_body(text="hello", model="m"):
    return json.dumps({"choices": [{"message": {"content": text, "model": model}}]})


def _http_error(code, body, url=LAST_ERR_URL):
    return urllib.error.HTTPError(url, code, "err", email.message.Message(),
                                  io.BytesIO(body.encode()))


def _http(code, body):
    """Step for a scripted urlopen: raises a FRESH HTTPError on every call.

    A reused exception instance would be drained by ask()'s e.read(), so the
    body has to be rebuilt per attempt.
    """

    def _step(req=None, *a, **k):
        raise _http_error(code, body)

    return _step


def _scripted(steps):
    """urlopen replacement that walks `steps` and records every call.

    A callable step is invoked (and may raise); the final step repeats.
    """
    calls = []
    state = {"i": 0}

    def _fn(req, *args, **kwargs):
        calls.append({"req": req, "args": args, "kwargs": kwargs})
        i = state["i"]
        state["i"] = i + 1
        step = steps[i] if i < len(steps) else steps[-1]
        if callable(step):
            return step(req, *args, **kwargs)
        return step

    return _fn, calls


class _Clock:
    """Deterministic clock so play_media's polling loop stays bounded."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        self.now += 0.6
        return self.now


class _FakeTab:
    def __init__(self, replies):
        self.replies = list(replies)
        self.scripts = []

    def js(self, script):
        self.scripts.append(script)
        if not self.replies:
            return "waiting"
        return self.replies.pop(0)


class ModuleWiringTests(unittest.TestCase):
    def test_models_pool_is_a_copy_of_config(self):
        # Only the copy semantics are asserted here: other tests reload
        # `config` (importlib.reload) to exercise `.env` handling, so a value
        # comparison against the reloaded module would depend on test order.
        self.assertIsInstance(solver.LLM_MODELS, list)
        self.assertIsNot(solver.LLM_MODELS, config.LLM_MODELS)


class AskPoolTests(unittest.TestCase):
    def _ask(self, steps, models, key=None, audio_b64=None):
        fn, calls = _scripted(steps)
        with patch.object(solver.urllib.request, "urlopen", side_effect=fn), \
             patch.object(solver.time, "sleep") as mock_sleep, \
             patch.object(solver, "LLM_MODELS", list(models)), \
             patch.object(solver, "LLM_KEY", key), \
             patch.object(solver, "LLM_URL", LAST_ERR_URL), \
             patch("builtins.print"):
            try:
                result = solver.ask("hi", audio_b64=audio_b64)
                error = None
            except Exception as exc:  # noqa: BLE001 - test inspects it
                result, error = None, exc
            sleep_args = [c.args[0] if c.args else None for c in mock_sleep.call_args_list]
        return result, error, calls, sleep_args

    def test_tpd_429_switches_to_next_model_without_sleeping(self):
        result, err, calls, sleeps = self._ask(
            [_http(429, '{"error":{"message":"TPD limit reached"}}'), _Resp(_ok_body("hi"))],
            ["model-a", "model-b"],
        )
        self.assertEqual((result, err, sleeps), ("hi", None, []))

    def test_tpd_429_second_request_uses_next_model(self):
        _r, _e, calls, _s = self._ask(
            [_http(429, "tokens per day exceeded"), _Resp(_ok_body("hi"))],
            ["model-a", "model-b"],
        )
        self.assertEqual(json.loads(calls[1]["req"].data)["model"], "model-b")

    def test_rpm_429_without_tpd_body_sleeps_eight_seconds(self):
        result, err, _calls, sleeps = self._ask(
            [_http(429, '{"error":"rate limit exceeded"}'), _Resp(_ok_body("hi"))],
            ["model-a"],
        )
        self.assertEqual((result, err, sleeps), ("hi", None, [8]))

    def test_rpm_429_keeps_retrying_same_model_with_growing_backoff(self):
        _r, err, calls, sleeps = self._ask(
            [_http(429, "rate limit exceeded")], ["model-a"]
        )
        self.assertIsInstance(err, urllib.error.HTTPError)
        self.assertEqual(len(calls), 8)
        self.assertEqual(sleeps, [8, 16, 24, 32, 8, 8, 16, 24, 32])

    def test_pool_exhausted_retries_pool_exactly_once(self):
        _r, err, calls, _s = self._ask([_http(500, "server error")], ["only-model"])
        self.assertIsInstance(err, urllib.error.HTTPError)
        self.assertEqual(getattr(err, "code", None), 500)
        self.assertEqual(len(calls), 8)  # 4 attempts x 2 pool rounds

    def test_non_rpm_error_backs_off_shorter_than_rate_limit(self):
        result, err, _calls, sleeps = self._ask(
            [_http(500, "server error"), _Resp(_ok_body("hi"))], ["model-a"]
        )
        self.assertEqual((result, err, sleeps), ("hi", None, [2]))

    def test_request_uses_curl_user_agent_and_15s_timeout(self):
        _r, _e, calls, _s = self._ask([_Resp(_ok_body("hi"))], ["model-a"], key="k")
        req = calls[0]["req"]
        headers = {k.lower(): v for k, v in req.headers.items()}
        self.assertEqual(headers.get("user-agent"), "curl/8.4.0")
        self.assertEqual(calls[0]["kwargs"].get("timeout"), 15)

    def test_request_sends_bearer_auth_when_key_configured(self):
        _r, _e, calls, _s = self._ask([_Resp(_ok_body("hi"))], ["model-a"], key="sekret")
        headers = {k.lower(): v for k, v in calls[0]["req"].headers.items()}
        self.assertEqual(headers.get("authorization"), "Bearer sekret")

    def test_audio_b64_is_sent_as_input_audio_content(self):
        _r, _e, calls, _s = self._ask(
            [_Resp(_ok_body("hi"))], ["model-a"], audio_b64="QUJD"
        )
        payload = json.loads(calls[0]["req"].data)
        audio_parts = [p for p in payload["messages"][0]["content"]
                       if p.get("type") == "input_audio"]
        self.assertEqual(audio_parts[0]["input_audio"]["data"], "QUJD")


class AskJsonTests(unittest.TestCase):
    def test_ask_json_tolerates_raw_control_character(self):
        raw = '{"answer": "a\x01b"}'
        with patch.object(solver, "ask", return_value=raw), patch("builtins.print"):
            self.assertEqual(solver.ask_json("q"), {"answer": "a\x01b"})

    def test_plain_jsonloads_rejects_the_same_control_character(self):
        with self.assertRaises(json.JSONDecodeError):
            json.loads('{"answer": "a\x01b"}')

    def test_ask_json_returns_none_when_no_object_present(self):
        with patch.object(solver, "ask", return_value="no json here"), \
             patch("builtins.print"):
            self.assertIsNone(solver.ask_json("q"))


class TranscribeGroqTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ed-handoff-groq-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, filename, steps):
        path = os.path.join(self.tmp, filename)
        with open(path, "wb") as f:
            f.write(b"MEDIADATA")
        fn, calls = _scripted(steps)
        with patch.object(solver.urllib.request, "urlopen", side_effect=fn), \
             patch.object(solver.config, "GROQ_API_KEY", "gsk_test"), \
             patch.object(solver.config, "GROQ_BASE_URL", "https://groq.local/v1"), \
             patch("builtins.print"):
            return solver.transcribe_groq(path), calls

    def test_mp4_upload_uses_video_mime_and_real_filename(self):
        text, calls = self._run(
            "clip.mp4", [_Resp(json.dumps({"text": "spoken words"}))]
        )
        body = calls[0]["req"].data
        self.assertEqual((text, b'filename="clip.mp4"' in body), ("spoken words", True))

    def test_mp4_upload_declares_video_mp4_content_type(self):
        _t, calls = self._run(
            "clip.mp4", [_Resp(json.dumps({"text": "spoken words"}))]
        )
        self.assertIn(b"Content-Type: video/mp4", calls[0]["req"].data)

    def test_mp3_upload_declares_audio_mpeg(self):
        _t, calls = self._run(
            "voice.mp3", [_Resp(json.dumps({"text": "spoken"}))]
        )
        self.assertIn(b"Content-Type: audio/mpeg", calls[0]["req"].data)

    def test_upload_posts_to_groq_transcriptions_endpoint(self):
        _t, calls = self._run(
            "clip.mp4", [_Resp(json.dumps({"text": "spoken"}))]
        )
        self.assertEqual(calls[0]["req"].full_url,
                         "https://groq.local/v1/audio/transcriptions")

    def test_empty_api_key_short_circuits_without_network(self):
        path = os.path.join(self.tmp, "clip.mp4")
        with open(path, "wb") as f:
            f.write(b"MEDIADATA")
        fn, calls = _scripted([_Resp(json.dumps({"text": "x"}))])
        with patch.object(solver.urllib.request, "urlopen", side_effect=fn), \
             patch.object(solver.config, "GROQ_API_KEY", ""), \
             patch("builtins.print"):
            self.assertEqual(solver.transcribe_groq(path), "")
        self.assertEqual(calls, [])


class TranscriptForTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ed-handoff-tr-")
        # solver.py leaks handles when it writes/caches transcripts; that is
        # solver's bug to fix, not something these behaviour pins should flag.
        self._quiet = warnings.catch_warnings()
        self._quiet.__enter__()
        warnings.simplefilter("ignore", ResourceWarning)

    def tearDown(self):
        self._quiet.__exit__(None, None, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _call(self, url, steps, key="k1", groq="", ask_result="spoken"):
        fn, calls = _scripted(steps)
        with patch.object(solver.urllib.request, "urlopen", side_effect=fn), \
             patch.object(solver, "SCRATCH", self.tmp), \
             patch.object(solver.config, "GROQ_API_KEY", "gsk_test"), \
             patch.object(solver, "transcribe_groq", return_value=groq), \
             patch.object(solver, "ask", return_value=ask_result) as mock_ask, \
             patch.object(solver.subprocess, "run") as mock_run, \
             patch("builtins.print"):
            out = solver.transcript_for(url, key)
        return out, calls, mock_ask, mock_run

    def test_mp4_url_downloads_to_mp4_media_file(self):
        out, _c, _a, _r = self._call(
            "https://cdn.example.com/audio/clip.mp4", [_Resp(b"MEDIADATA")], groq="t"
        )
        media = os.path.join(self.tmp, "m_k1.mp4")
        with open(media, "rb") as f:
            self.assertEqual((out, f.read()), ("t", b"MEDIADATA"))

    def test_mp4_url_never_shells_out_to_ffmpeg(self):
        _o, _c, _a, mock_run = self._call(
            "https://cdn.example.com/audio/clip.mp4", [_Resp(b"MEDIADATA")], groq="t"
        )
        self.assertEqual(mock_run.call_count, 0)

    def test_query_string_is_stripped_before_extension_detection(self):
        _o, _c, _a, _r = self._call(
            "https://cdn.example.com/audio/CLIP.MP4?token=abc123",
            [_Resp(b"MEDIADATA")], groq="t",
        )
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "m_k1.mp4")))

    def test_unknown_extension_falls_back_to_mp3_media_file(self):
        _o, _c, _a, _r = self._call(
            "https://cdn.example.com/stream?id=9", [_Resp(b"MEDIADATA")], groq="t"
        )
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "m_k1.mp3")))

    def test_download_request_uses_browser_user_agent(self):
        _o, calls, _a, _r = self._call(
            "https://cdn.example.com/clip.mp4", [_Resp(b"MEDIADATA")], groq="t"
        )
        headers = {k.lower(): v for k, v in calls[0]["req"].headers.items()}
        self.assertEqual(headers.get("user-agent"), "Mozilla/5.0")

    def test_non_mp3_skips_multimodal_input_audio_fallback(self):
        out, _c, mock_ask, _r = self._call(
            "https://cdn.example.com/clip.mp4", [_Resp(b"MEDIADATA")], groq=""
        )
        self.assertEqual((out, mock_ask.call_count), ("", 0))

    def test_mp3_uses_multimodal_input_audio_fallback(self):
        out, _c, mock_ask, _r = self._call(
            "https://cdn.example.com/voice.mp3", [_Resp(b"MEDIADATA")], groq=""
        )
        expected = base64.b64encode(b"MEDIADATA").decode()
        self.assertEqual((out, mock_ask.call_args.kwargs.get("audio_b64")),
                         ("spoken", expected))

    def test_transcript_is_cached_and_reused_without_refetching(self):
        path = os.path.join(self.tmp, "tr_k1.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("cached text")
        out, calls, _a, _r = self._call(
            "https://cdn.example.com/clip.mp4", [_Resp(b"MEDIADATA")], groq="t"
        )
        self.assertEqual((out, calls), ("cached text", []))

    def test_groq_transcript_is_persisted_to_cache_file(self):
        self._call("https://cdn.example.com/clip.mp4", [_Resp(b"MEDIADATA")], groq="hi there")
        path = os.path.join(self.tmp, "tr_k1.txt")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "hi there")


class PlayMediaTests(unittest.TestCase):
    def _play(self, replies, quick=False):
        tab = _FakeTab(replies)
        clock = _Clock()
        with patch.object(solver.time, "time", clock.time), \
             patch.object(solver.time, "sleep", lambda *_: None):
            return solver.play_media(tab, timeout=45, quick=quick), tab

    def test_playing_then_waiting_transition_counts_as_finished(self):
        done, tab = self._play([1, 1, "playing", "waiting"])
        self.assertTrue(done)

    def test_waiting_before_play_does_not_count_as_finished(self):
        done, tab = self._play([1, 1, "waiting", "playing", "waiting"])
        self.assertTrue(done)
        self.assertEqual(len(tab.scripts), 5)

    def test_ended_listener_latches_window_flag(self):
        _done, tab = self._play([1, 1, "ended"])
        setup = tab.scripts[1]
        self.assertIn("addEventListener('ended'", setup)
        self.assertIn("_mediaEndedLatched = true", setup)

    def test_latched_ended_state_finishes_immediately(self):
        done, tab = self._play([1, 1, "ended"])
        self.assertEqual((done, len(tab.scripts)), (True, 3))

    def test_no_media_returns_false_without_polling(self):
        done, tab = self._play([0])
        self.assertEqual((done, len(tab.scripts)), (False, 1))


if __name__ == "__main__":
    unittest.main()
