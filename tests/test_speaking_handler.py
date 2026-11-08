import json
import unittest
from unittest.mock import Mock, patch

import auto


class SpeakingHandlerTests(unittest.TestCase):
    def test_handle_speaking_clicks_enabled_start(self):
        tab = Mock()
        # q(Try again) -> 0; q(chooseCaracterArrow) -> 0
        with patch.object(auto, "q", return_value=0), \
             patch.object(auto, "click_text", return_value=0), \
             patch.object(auto.time, "sleep"):
            tab.js.side_effect = [
                1,  # querySelector .openSpeech__btnStart: clicked
            ]
            result = auto.handle_speaking(tab, "")
        self.assertEqual(result, "speak: clicked")

    def test_handle_speaking_bridges_disabled_open_speech(self):
        tab = Mock()
        with patch.object(auto, "q", return_value=0), \
             patch.object(auto, "click_text", return_value=0), \
             patch.object(auto.time, "sleep"):
            tab.js.side_effect = [
                0,    # clicked start (disabled in DOM)
                4,    # nav.setProgress invoked on task 4
            ]
            result = auto.handle_speaking(tab, "")
        self.assertEqual(result, "speak: bridged task 4")

    def test_handle_speaking_blocked_when_no_nav(self):
        tab = Mock()
        with patch.object(auto, "q", return_value=0), \
             patch.object(auto, "click_text", return_value=0):
            tab.js.side_effect = [
                0,     # start disabled
                None,  # nav missing
            ]
            result = auto.handle_speaking(tab, "")
        self.assertEqual(result, "speak: blocked")

    def test_handle_speaking_blocked_on_server_rejection(self):
        tab = Mock()
        with patch.object(auto, "q", side_effect=lambda _t, expr: 1 if "Try again" in expr else 0):
            result = auto.handle_speaking(tab, "")
        self.assertEqual(result, "speak: blocked")


class TestClassificationTests(unittest.TestCase):
    def test_is_test_prefers_practice_step_node_name(self):
        self.assertIn("'practice'", auto.IS_TEST_JS)

    def test_handle_test_redirects_speaking_widget(self):
        tab = Mock()
        tab.js.side_effect = [
            "",                                      # audio/video query (no media)
            "openSpeech__btn openSpeech__btnStart",  # speak_widget detection
        ]
        with patch.object(auto.solver, "dom_transcript", return_value=""), \
             patch.object(auto.solver, "do_task", return_value="other: text prompt"), \
             patch.object(auto, "handle_speaking", return_value="speak: clicked") as mock_speak:
            result = auto.handle_test(tab, "")
        self.assertEqual(result, "speak: clicked")
        mock_speak.assert_called_once_with(tab, "")


if __name__ == "__main__":
    unittest.main()
