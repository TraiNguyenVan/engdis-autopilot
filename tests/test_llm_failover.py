from contextlib import contextmanager
import email.message
import http.server
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch

import config
import solver


TEST_LLM_URL = "https://llm.local/v1/chat/completions"
REPO_ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def _isolated_config_reload(env_updates, clear=True):
    """Reload `config` under isolated os.environ and restore exact module state on exit."""
    saved_config = dict(config.__dict__)
    try:
        with patch.dict(os.environ, env_updates, clear=clear):
            importlib.reload(config)
            yield config
    finally:
        config.__dict__.clear()
        config.__dict__.update(saved_config)


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
    def test_default_llm_timeout_is_15(self):
        with _isolated_config_reload({"ED_SKIP_DOTENV": "1"}, clear=True):
            self.assertEqual(config.LLM_TIMEOUT, 15)

    def test_blank_ed_llm_timeout_falls_back_to_15(self):
        with _isolated_config_reload({"ED_SKIP_DOTENV": "1", "ED_LLM_TIMEOUT": "  "}, clear=True):
            self.assertEqual(config.LLM_TIMEOUT, 15)

    def test_custom_ed_llm_timeout_is_parsed(self):
        with _isolated_config_reload({"ED_SKIP_DOTENV": "1", "ED_LLM_TIMEOUT": "8"}, clear=True):
            self.assertEqual(config.LLM_TIMEOUT, 8)

    def test_invalid_ed_llm_timeout_raises_value_error(self):
        for bad in ("0", "-5", "abc"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    with _isolated_config_reload({"ED_SKIP_DOTENV": "1", "ED_LLM_TIMEOUT": bad}, clear=True):
                        pass

    def test_reload_helper_restores_caller_config_state(self):
        with patch.object(config, "LLM_TIMEOUT", 9):
            with _isolated_config_reload({"ED_SKIP_DOTENV": "1", "ED_LLM_TIMEOUT": "4"}, clear=True):
                self.assertEqual(config.LLM_TIMEOUT, 4)
            self.assertEqual(config.LLM_TIMEOUT, 9)

    def test_running_test_config_defaults_preserves_ed_llm_timeout_for_ask(self):
        from tests import test_config

        with _isolated_config_reload({"ED_SKIP_DOTENV": "1", "ED_LLM_TIMEOUT": "8"}, clear=True):
            self.assertEqual(config.LLM_TIMEOUT, 8)
            suite_result = unittest.TestResult()
            test_config.TestConfig("test_defaults").run(suite_result)
            self.assertEqual(config.LLM_TIMEOUT, 8)

            fn, calls = _scripted_urlopen([_Resp("ok-after-test-defaults")])
            with patch.object(solver.urllib.request, "urlopen", side_effect=fn), \
                 patch.object(solver, "LLM_MODELS", ["model-a"]), \
                 patch.object(solver, "LLM_URL", TEST_LLM_URL), \
                 patch.object(solver, "LLM_KEY", "k"), \
                 patch.object(solver, "LLM_TIMEOUT", solver._ConfigTimeout(8)), \
                 patch("builtins.print"):
                ans = solver.ask("hi")
            self.assertEqual(ans, "ok-after-test-defaults")
            self.assertEqual(calls[0]["timeout"], 8)


class ComposeEnvPropagationTests(unittest.TestCase):
    def test_compose_yaml_declares_ed_llm_timeout_passthrough(self):
        compose_text = (REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn("ED_LLM_TIMEOUT=${ED_LLM_TIMEOUT:-15}", compose_text)

    def test_docker_compose_config_propagates_ed_llm_timeout(self):
        if not shutil.which("docker"):
            self.skipTest("docker CLI not installed")
        env = dict(os.environ, ED_LLM_TIMEOUT="8")
        proc = subprocess.run(
            ["docker", "compose", "-f", str(REPO_ROOT / "compose.yaml"), "config", "--format", "json"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            self.skipTest(f"docker compose config unavailable: {proc.stderr.strip()}")
        rendered = json.loads(proc.stdout)
        svc_env = rendered["services"]["engdis"]["environment"]
        self.assertEqual(str(svc_env.get("ED_LLM_TIMEOUT")), "8")


class AskTimeoutAndFailoverTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(config, "LLM_TIMEOUT", 15))
        self.enterContext(patch.object(solver, "LLM_TIMEOUT", solver._ConfigTimeout(15)))

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
        with _isolated_config_reload({"ED_SKIP_DOTENV": "1"}, clear=True):
            result, err, calls, _sleeps = self._run_ask([_Resp("ans")], ["model-a"])
        self.assertEqual((result, err), ("ans", None))
        self.assertEqual(calls[0]["timeout"], 15)

    def test_solver_llm_timeout_patch_is_respected_even_when_matching_import_env(self):
        with patch.object(config, "LLM_TIMEOUT", 15), \
             patch.object(solver, "LLM_TIMEOUT", 8):
            result, err, calls, _sleeps = self._run_ask([_Resp("ans")], ["model-a"])
        self.assertEqual((result, err), ("ans", None))
        self.assertEqual(calls[0]["timeout"], 8)

    def test_config_llm_timeout_patch_is_respected(self):
        with patch.object(config, "LLM_TIMEOUT", 6):
            result, err, calls, _sleeps = self._run_ask([_Resp("ans")], ["model-a"])
        self.assertEqual((result, err), ("ans", None))
        self.assertEqual(calls[0]["timeout"], 6)

    def test_ed_llm_timeout_env_reload_propagates_to_ask_and_restores_state(self):
        with patch.object(config, "LLM_TIMEOUT", 12):
            with _isolated_config_reload({"ED_SKIP_DOTENV": "1", "ED_LLM_TIMEOUT": "7"}, clear=True):
                result, err, calls, _sleeps = self._run_ask([_Resp("ans")], ["model-a"])
            self.assertEqual((result, err), ("ans", None))
            self.assertEqual(calls[0]["timeout"], 7)
            self.assertEqual(config.LLM_TIMEOUT, 12)

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


class TotalDeadlineStreamingTests(unittest.TestCase):
    def _run_loopback_scenario(self, slow_mode):
        seen_models = []
        stop_drip = threading.Event()

        class _DripHandler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                req_body = json.loads(self.rfile.read(length).decode("utf-8"))
                model = req_body["model"]
                seen_models.append(model)

                if model == "slow-model":
                    try:
                        if slow_mode == "body":
                            self.send_response(200)
                            self.send_header("Content-Type", "text/event-stream")
                            self.end_headers()
                            for _ in range(12):
                                if stop_drip.is_set():
                                    break
                                self.wfile.write(b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n')
                                self.wfile.flush()
                                stop_drip.wait(0.2)
                        elif slow_mode == "headers":
                            self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                            self.wfile.flush()
                            for idx in range(12):
                                if stop_drip.is_set():
                                    break
                                self.wfile.write(f"X-Drip-{idx}: slow\r\n".encode("ascii"))
                                self.wfile.flush()
                                stop_drip.wait(0.2)
                            self.wfile.write(b"Content-Length: 2\r\n\r\n{}")
                            self.wfile.flush()
                        elif slow_mode == "chunk_framing":
                            self.wfile.write(
                                b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                            )
                            self.wfile.flush()
                            for _ in range(12):
                                if stop_drip.is_set():
                                    break
                                # Drip hex digits of chunk size without CRLF so readline blocks
                                self.wfile.write(b"0")
                                self.wfile.flush()
                                stop_drip.wait(0.2)
                        elif slow_mode == "http_error_body":
                            self.send_response(503)
                            self.send_header("Content-Type", "text/plain")
                            self.end_headers()
                            for _ in range(12):
                                if stop_drip.is_set():
                                    break
                                self.wfile.write(b"upstream overload ")
                                self.wfile.flush()
                                stop_drip.wait(0.2)
                    except OSError:
                        pass
                    return

                payload = json.dumps(
                    {"choices": [{"message": {"content": "fast-fallback-ok"}}]}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _DripHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
            start = time.monotonic()
            with patch.object(solver, "LLM_URL", url), \
                 patch.object(solver, "LLM_MODELS", ["slow-model", "fast-model"]), \
                 patch.object(solver, "LLM_TIMEOUT", 1), \
                 patch.object(solver, "LLM_KEY", ""), \
                 patch("builtins.print"):
                answer = solver.ask("ping")
            elapsed = time.monotonic() - start
        finally:
            stop_drip.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        return answer, seen_models, elapsed

    def test_periodic_streaming_body_exceeding_total_deadline_fails_over(self):
        answer, seen_models, elapsed = self._run_loopback_scenario("body")
        self.assertEqual(answer, "fast-fallback-ok")
        self.assertEqual(seen_models, ["slow-model", "fast-model"])
        self.assertLess(elapsed, 1.35)

    def test_slow_drip_response_headers_enforces_wall_clock_deadline(self):
        answer, seen_models, elapsed = self._run_loopback_scenario("headers")
        self.assertEqual(answer, "fast-fallback-ok")
        self.assertEqual(seen_models, ["slow-model", "fast-model"])
        self.assertLess(elapsed, 1.35)

    def test_slow_drip_chunk_framing_enforces_wall_clock_deadline(self):
        answer, seen_models, elapsed = self._run_loopback_scenario("chunk_framing")
        self.assertEqual(answer, "fast-fallback-ok")
        self.assertEqual(seen_models, ["slow-model", "fast-model"])
        self.assertLess(elapsed, 1.35)

    def test_slow_drip_http_error_body_enforces_wall_clock_deadline(self):
        answer, seen_models, elapsed = self._run_loopback_scenario("http_error_body")
        self.assertEqual(answer, "fast-fallback-ok")
        self.assertEqual(seen_models, ["slow-model", "fast-model"])
        self.assertLess(elapsed, 1.35)


if __name__ == "__main__":
    unittest.main()
