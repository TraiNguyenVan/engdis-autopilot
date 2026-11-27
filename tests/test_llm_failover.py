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
import urllib.request
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


class ResolverTimeoutTests(unittest.TestCase):
    def test_four_stalled_resolutions_do_not_starve_healthy_host(self):
        release = threading.Event()
        original = socket.getaddrinfo
        entered = []

        def resolver(host, *args, **kwargs):
            if host == "stalled.invalid":
                entered.append(host)
                release.wait(10)
                raise OSError("injected resolver failure")
            return original(host, *args, **kwargs)

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                body = b'{"choices":[{"message":{"content":"healthy"}}]}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1",
                                         "http_proxy": "http://127.0.0.1:1",
                                         "NO_PROXY": "*", "no_proxy": "*"}), \
                 patch.object(socket, "getaddrinfo", side_effect=resolver):
                for _ in range(4):
                    with self.assertRaises((TimeoutError, urllib.error.URLError)):
                        solver._fetch_with_deadline(urllib.request.Request("http://stalled.invalid/"), 0.15)
                self.assertEqual(len(entered), 4)
                req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/", data=b"{}")
                body, err, _ = solver._fetch_with_deadline(req, 2)
                self.assertIsNone(err)
                self.assertEqual(json.loads(body or "{}")["choices"][0]["message"]["content"], "healthy")
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join()
            for worker in list(threading.enumerate()):
                if worker.name in ("ed-llm-fetch", "ed-llm-resolve"):
                    worker.join(2)

    def test_one_stalled_lookup_does_not_block_healthy_fallback(self):
        release = threading.Event()
        resolver_started = threading.Event()
        original_getaddrinfo = socket.getaddrinfo

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                body = json.dumps({"choices": [{"message": {"content": "healthy"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def selective_resolver(host, *args, **kwargs):
            if host == "stalled.invalid":
                resolver_started.set()
                release.wait(5)
                raise OSError("injected resolver failure")
            return original_getaddrinfo(host, *args, **kwargs)

        try:
            with patch.dict(os.environ, {"NO_PROXY": "*", "no_proxy": "*"}), \
                 patch.object(socket, "getaddrinfo", side_effect=selective_resolver):
                start = time.monotonic()
                with self.assertRaises((TimeoutError, urllib.error.URLError)) as caught:
                    solver._fetch_with_deadline(urllib.request.Request("http://stalled.invalid/"), 0.2)
                if isinstance(caught.exception, urllib.error.URLError):
                    self.assertIsInstance(caught.exception.reason, TimeoutError)
                self.assertTrue(resolver_started.is_set())
                req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/", data=b"{}")
                body, err, _ = solver._fetch_with_deadline(req, 1)
                self.assertIsNotNone(body)
                self.assertEqual(json.loads(body or "{}")["choices"][0]["message"]["content"], "healthy")
                self.assertIsNone(err)
                self.assertLess(time.monotonic() - start, 1.2)
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join()
            for worker in list(threading.enumerate()):
                if worker.name == "ed-llm-fetch":
                    worker.join(2)


class TruncatedResponseTests(unittest.TestCase):
    def test_truncated_sse_fixture_ignores_proxy_with_empty_no_proxy(self):
        env = {"HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
               "NO_PROXY": "", "no_proxy": ""}
        with patch.dict(os.environ, env), patch.object(solver.time, "sleep"):
            self._check_truncated_length_delimited_sse_fails_over()

    def test_truncated_length_delimited_sse_fails_over(self):
        self._check_truncated_length_delimited_sse_fails_over()

    def _check_truncated_length_delimited_sse_fails_over(self):
        seen_models = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen_models.append(request["model"])
                if request["model"] == "first":
                    payload = b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload) + 100))
                    self.end_headers()
                    self.wfile.write(payload)
                    self.close_connection = True
                else:
                    payload = json.dumps({"choices": [{"message": {"content": "complete"}}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}), \
                 patch.object(solver, "LLM_URL", f"http://127.0.0.1:{server.server_port}/"), \
                 patch.object(solver, "LLM_MODELS", ["first", "second"]), \
                 patch.object(solver, "LLM_TIMEOUT", 1), \
                 patch.object(solver, "LLM_KEY", ""), \
                 patch("builtins.print"):
                answer = solver.ask("ping")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(answer, "complete")
        self.assertEqual(seen_models, ["first", "second"])


class TotalDeadlineStreamingTests(unittest.TestCase):
    def _run_loopback_scenario(self, slow_mode):
        seen_models = []
        stop_drip = threading.Event()
        peer_disconnected = threading.Event()

        class _DripHandler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                pass

            def _wait_or_detect_close(self, delay):
                # Poll socket readability with MSG_PEEK so we detect client-side
                # SHUT_RDWR / close immediately even before the next write.
                end = time.monotonic() + delay
                while not stop_drip.is_set():
                    rem = end - time.monotonic()
                    if rem <= 0:
                        return True
                    self.connection.settimeout(min(0.05, rem))
                    try:
                        data = self.connection.recv(1, socket.MSG_PEEK)
                        if data == b"":
                            peer_disconnected.set()
                            return False
                    except TimeoutError:
                        continue
                    except OSError:
                        peer_disconnected.set()
                        return False
                return False

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
                            for _ in range(20):
                                self.wfile.write(b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n')
                                self.wfile.flush()
                                if not self._wait_or_detect_close(0.2):
                                    break
                        elif slow_mode == "headers":
                            self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                            self.wfile.flush()
                            for idx in range(20):
                                # Drip incomplete header fragments too, matching review repro
                                self.wfile.write(f"X-Drip-{idx}: partial".encode("ascii"))
                                self.wfile.flush()
                                if not self._wait_or_detect_close(0.2):
                                    break
                                self.wfile.write(b"\r\n")
                                self.wfile.flush()
                        elif slow_mode == "chunk_framing":
                            self.wfile.write(
                                b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                            )
                            self.wfile.flush()
                            for _ in range(20):
                                self.wfile.write(b"0")
                                self.wfile.flush()
                                if not self._wait_or_detect_close(0.2):
                                    break
                        elif slow_mode == "http_error_body":
                            self.send_response(503)
                            self.send_header("Content-Type", "text/plain")
                            self.end_headers()
                            for _ in range(20):
                                self.wfile.write(b"upstream overload ")
                                self.wfile.flush()
                                if not self._wait_or_detect_close(0.2):
                                    break
                    except OSError:
                        peer_disconnected.set()
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
            with patch.dict(os.environ, {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}), \
                 patch.object(solver, "LLM_URL", url), \
                 patch.object(solver, "LLM_MODELS", ["slow-model", "fast-model"]), \
                 patch.object(solver, "LLM_TIMEOUT", 1), \
                 patch.object(solver, "LLM_KEY", ""), \
                 patch("builtins.print"):
                answer = solver.ask("ping")
            elapsed = time.monotonic() - start
            # Verify BEFORE server teardown (while server would still be dripping for ~4s)
            # that zero ed-llm-fetch worker threads remain alive and peer socket closed!
            leaked_workers = [
                t for t in threading.enumerate()
                if t.name == "ed-llm-fetch" and t.is_alive()
            ]
            closed_promptly = peer_disconnected.wait(timeout=0.3)
        finally:
            stop_drip.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        return answer, seen_models, elapsed, leaked_workers, closed_promptly

    def test_periodic_streaming_body_exceeding_total_deadline_fails_over(self):
        answer, seen_models, elapsed, leaked, closed = self._run_loopback_scenario("body")
        self.assertEqual(answer, "fast-fallback-ok")
        self.assertEqual(seen_models, ["slow-model", "fast-model"])
        self.assertLess(elapsed, 1.35)
        self.assertEqual(leaked, [])
        self.assertTrue(closed)

    def test_slow_drip_response_headers_enforces_deadline_and_stops_worker_and_socket(self):
        answer, seen_models, elapsed, leaked, closed = self._run_loopback_scenario("headers")
        self.assertEqual(answer, "fast-fallback-ok")
        self.assertEqual(seen_models, ["slow-model", "fast-model"])
        self.assertLess(elapsed, 1.35)
        self.assertEqual(leaked, [], "Timed-out header worker thread must terminate on deadline")
        self.assertTrue(closed, "Timed-out header client socket must close on deadline")

    def test_slow_drip_chunk_framing_enforces_wall_clock_deadline(self):
        answer, seen_models, elapsed, leaked, closed = self._run_loopback_scenario("chunk_framing")
        self.assertEqual(answer, "fast-fallback-ok")
        self.assertEqual(seen_models, ["slow-model", "fast-model"])
        self.assertLess(elapsed, 1.35)
        self.assertEqual(leaked, [])
        self.assertTrue(closed)

    def test_slow_drip_http_error_body_enforces_wall_clock_deadline(self):
        answer, seen_models, elapsed, leaked, closed = self._run_loopback_scenario("http_error_body")
        self.assertEqual(answer, "fast-fallback-ok")
        self.assertEqual(seen_models, ["slow-model", "fast-model"])
        self.assertLess(elapsed, 1.35)
        self.assertEqual(leaked, [])
        self.assertTrue(closed)


if __name__ == "__main__":
    unittest.main()
