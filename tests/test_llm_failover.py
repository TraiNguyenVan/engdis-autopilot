import email.message
import importlib
import io
import json
import os
import socket
import unittest
import urllib.error
from unittest.mock import patch

import config
import solver


TEST_LLM_URL = "https://llm.local/v1/chat/completions"


class _Resp:
    def __init__(self, text="ok"):
        payload = json.dumps({"choices": [{"message": {"content": text}}]})
        self._data = payload.encode("utf-8")

    def read(self):
        return self._data


def _http_step(code, body):
    created = []

    def _raise(req=None, *args, **kwargs):
        fp = io.BytesIO(body.encode("utf-8"))
        err = urllib.error.HTTPError(
            TEST_LLM_URL, code, "err", email.message.Message(), fp
        )
        created.append(err)
        raise err

    _raise.created = created
    return _raise


def _scripted_urlopen(steps):
    calls = []
    idx = {"i": 0}

    def _urlopen(req, *args, **kwargs):
        model = json.loads(req.data.decode("utf-8"))["model"]
        calls.append({"model": model, "timeout": kwargs.get("timeout"), "req": req})
        i = idx["i"]
        idx["i"] = i + 1
        step = steps[i] if i < len(steps) else steps[-1]
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return step(req, *args, **kwargs)
        return step

    return _urlopen, calls


class ConfigLlmTimeoutTests(unittest.TestCase):
    def tearDown(self):
        with patch.dict(os.environ, {"ED_SKIP_DOTENV": "1"}, clear=True):
            importlib.reload(config)

    def test_default_llm_timeout_is_15(self):
        with patch.dict(os.environ, {"ED_SKIP_DOTENV": "1"}, clear=True):
            importlib.reload(config)
            self.assertEqual(config.LLM_TIMEOUT, 15)

    def test_blank_ed_llm_timeout_falls_back_to_15(self):
        with patch.dict(os.environ, {"ED_SKIP_DOTENV": "1", "ED_LLM_TIMEOUT": "  "}, clear=True):
            importlib.reload(config)
            self.assertEqual(config.LLM_TIMEOUT, 15)

    def test_custom_ed_llm_timeout_is_parsed(self):
        with patch.dict(os.environ, {"ED_SKIP_DOTENV": "1", "ED_LLM_TIMEOUT": "8"}, clear=True):
            importlib.reload(config)
            self.assertEqual(config.LLM_TIMEOUT, 8)

    def test_invalid_ed_llm_timeout_raises_value_error(self):
        for bad in ("0", "-5", "abc"):
            with self.subTest(bad=bad):
                with patch.dict(os.environ, {"ED_SKIP_DOTENV": "1", "ED_LLM_TIMEOUT": bad}, clear=True):
                    with self.assertRaises(ValueError):
                        importlib.reload(config)


class AskTimeoutAndFailoverTests(unittest.TestCase):
    def _run_ask(self, steps, models):
        fn, calls = _scripted_urlopen(steps)
        with patch.object(solver.urllib.request, "urlopen", side_effect=fn), \
             patch.object(solver.time, "sleep") as mock_sleep, \
             patch.object(solver, "LLM_MODELS", list(models)), \
             patch.object(solver, "LLM_URL", TEST_LLM_URL), \
             patch.object(solver, "LLM_KEY", "test-key"), \
             patch("builtins.print"):
            try:
                result = solver.ask("question")
                err = None
            except Exception as exc:  # noqa: BLE001
                result, err = None, exc
            sleeps = [c.args[0] for c in mock_sleep.call_args_list]
        for step in steps:
            for created_err in getattr(step, "created", ()):
                created_err.close()
        return result, err, calls, sleeps

    def test_default_timeout_is_15s(self):
        result, err, calls, _sleeps = self._run_ask([_Resp("ans")], ["model-a"])
        self.assertEqual((result, err), ("ans", None))
        self.assertEqual(calls[0]["timeout"], 15)

    def test_solver_llm_timeout_patch_is_respected(self):
        with patch.object(solver, "LLM_TIMEOUT", 8):
            result, err, calls, _sleeps = self._run_ask([_Resp("ans")], ["model-a"])
        self.assertEqual((result, err), ("ans", None))
        self.assertEqual(calls[0]["timeout"], 8)

    def test_config_llm_timeout_patch_is_respected(self):
        with patch.object(config, "LLM_TIMEOUT", 6):
            result, err, calls, _sleeps = self._run_ask([_Resp("ans")], ["model-a"])
        self.assertEqual((result, err), ("ans", None))
        self.assertEqual(calls[0]["timeout"], 6)

    def test_ed_llm_timeout_env_reload_propagates_to_ask(self):
        try:
            with patch.dict(os.environ, {"ED_SKIP_DOTENV": "1", "ED_LLM_TIMEOUT": "7"}, clear=True):
                importlib.reload(config)
                result, err, calls, _sleeps = self._run_ask([_Resp("ans")], ["model-a"])
            self.assertEqual((result, err), ("ans", None))
            self.assertEqual(calls[0]["timeout"], 7)
        finally:
            with patch.dict(os.environ, {"ED_SKIP_DOTENV": "1"}, clear=True):
                importlib.reload(config)

    def test_multi_model_timeout_fails_over_immediately_without_backoff(self):
        result, err, calls, sleeps = self._run_ask(
            [TimeoutError("timed out"), _Resp("fallback-ok")],
            ["ag/gemini-3.8-flash", "gpt-4o-mini"],
        )
        self.assertEqual((result, err), ("fallback-ok", None))
        self.assertEqual([c["model"] for c in calls], ["ag/gemini-3.8-flash", "gpt-4o-mini"])
        self.assertEqual(sleeps, [])

    def test_multi_model_socket_timeout_and_urlerror_fail_over_immediately(self):
        result, err, calls, sleeps = self._run_ask(
            [
                socket.timeout("read timed out"),
                urllib.error.URLError(TimeoutError("connect timed out")),
                _Resp("third-model-ok"),
            ],
            ["model-1", "model-2", "model-3"],
        )
        self.assertEqual((result, err), ("third-model-ok", None))
        self.assertEqual([c["model"] for c in calls], ["model-1", "model-2", "model-3"])
        self.assertEqual(sleeps, [])

    def test_multi_model_connection_error_fails_over_immediately(self):
        result, err, calls, sleeps = self._run_ask(
            [ConnectionError("connection reset"), _Resp("ok-2")],
            ["model-1", "model-2"],
        )
        self.assertEqual((result, err), ("ok-2", None))
        self.assertEqual([c["model"] for c in calls], ["model-1", "model-2"])
        self.assertEqual(sleeps, [])

    def test_multi_model_http_5xx_fails_over_immediately(self):
        result, err, calls, sleeps = self._run_ask(
            [_http_step(503, "upstream unavailable"), _Resp("ok-2")],
            ["model-1", "model-2"],
        )
        self.assertEqual((result, err), ("ok-2", None))
        self.assertEqual([c["model"] for c in calls], ["model-1", "model-2"])
        self.assertEqual(sleeps, [])

    def test_multi_model_pool_round_1_retains_full_retries_when_round_0_exhausted(self):
        result, err, calls, sleeps = self._run_ask(
            [TimeoutError("all down")],
            ["model-a", "model-b"],
        )
        self.assertIsNone(result)
        self.assertIsInstance(err, TimeoutError)
        # Round 0: 1 fast try per model; Round 1: full 4 tries per model
        expected_models = ["model-a", "model-b"] + ["model-a"] * 4 + ["model-b"] * 4
        self.assertEqual([c["model"] for c in calls], expected_models)
        self.assertEqual(sleeps, [8, 2, 4, 6, 2, 4, 6])

    def test_multi_model_recovers_on_pool_round_1_retry(self):
        result, err, calls, sleeps = self._run_ask(
            [
                TimeoutError("m-a r0"),
                TimeoutError("m-b r0"),
                TimeoutError("m-a r1 try1"),
                _Resp("recovered"),
            ],
            ["model-a", "model-b"],
        )
        self.assertEqual((result, err), ("recovered", None))
        self.assertEqual([c["model"] for c in calls], ["model-a", "model-b", "model-a", "model-a"])
        self.assertEqual(sleeps, [8, 2])

    def test_single_model_timeout_preserves_four_attempts_per_round(self):
        result, err, calls, sleeps = self._run_ask(
            [TimeoutError("single model timeout")],
            ["only-model"],
        )
        self.assertIsNone(result)
        self.assertIsInstance(err, TimeoutError)
        self.assertEqual(len(calls), 8)
        self.assertEqual(sleeps, [2, 4, 6, 8, 2, 4, 6])

    def test_multi_model_429_rpm_preserves_backoff_on_same_model(self):
        result, err, calls, sleeps = self._run_ask(
            [_http_step(429, '{"error":"rate limit exceeded"}'), _Resp("after-rpm")],
            ["model-a", "model-b"],
        )
        self.assertEqual((result, err), ("after-rpm", None))
        self.assertEqual([c["model"] for c in calls], ["model-a", "model-a"])
        self.assertEqual(sleeps, [8])

    def test_multi_model_429_tpd_switches_immediately_without_sleep(self):
        result, err, calls, sleeps = self._run_ask(
            [_http_step(429, "tokens per day limit reached"), _Resp("from-b")],
            ["model-a", "model-b"],
        )
        self.assertEqual((result, err), ("from-b", None))
        self.assertEqual([c["model"] for c in calls], ["model-a", "model-b"])
        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()
