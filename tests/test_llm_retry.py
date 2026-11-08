import json
import unittest
from unittest.mock import patch

import solver


class _Resp:
    def __init__(self, body: str):
        self._body = body

    def read(self):
        return self._body.encode()


class LlmRetryTests(unittest.TestCase):
    def test_ask_retries_transient_disconnect(self):
        ok = json.dumps({"choices": [{"message": {"content": "hello"}}]})
        with patch.object(solver.urllib.request, "urlopen",
                          side_effect=[ConnectionError("boom"), ConnectionError("boom"), _Resp(ok)]), \
             patch.object(solver, "time") as mock_time, \
             patch.object(solver, "LLM_MODELS", ["test-model"]):
            self.assertEqual(solver.ask("hi"), "hello")
        self.assertEqual(mock_time.sleep.call_count, 2)

    def test_ask_gives_up_after_four_attempts(self):
        with patch.object(solver.urllib.request, "urlopen",
                          side_effect=ConnectionError("down")), \
             patch.object(solver, "time") as mock_time, \
             patch.object(solver, "LLM_MODELS", ["test-model"]):
            with self.assertRaises(ConnectionError):
                solver.ask("hi")
        self.assertEqual(mock_time.sleep.call_count, 3)


if __name__ == "__main__":
    unittest.main()
