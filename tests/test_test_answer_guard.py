import unittest
from unittest.mock import Mock, patch

import auto


class TestAnswerGuard(unittest.TestCase):
    def test_llm_timeout_stops_without_submit(self):
        tab = Mock()
        tab.js.return_value = ''
        with patch.object(auto.solver, 'dom_transcript', return_value=''), \
             patch.object(auto.solver, 'do_task', side_effect=TimeoutError('LLM timeout')), \
             patch.object(auto, 'click') as click:
            with self.assertRaises(TimeoutError):
                auto.handle_test(tab, '')
        click.assert_not_called()

    def test_unchecked_mcq_after_retry_does_not_submit_last_question(self):
        tab = Mock()
        tab.js.return_value = ''
        def query(_tab, expr):
            if '.prMCQ__qaSet' in expr:
                return 1
            if '.prMCQ__answers--checked' in expr:
                return 0
            return 1
        with patch.object(auto.solver, 'dom_transcript', return_value=''), \
             patch.object(auto.solver, 'do_task', return_value='mcq: answer'), \
             patch.object(auto, 'q', side_effect=query), \
             patch.object(auto, 'click') as click, \
             patch.object(auto.time, 'sleep'), \
             patch.object(auto, 'st', return_value={'total': '2', 'counter': '2'}), \
             patch.object(auto.poll, 'wait_until'):
            result = auto.handle_test(tab, '')
        self.assertTrue(result.startswith('test-unanswered:'), result)
        click.assert_not_called()

    def test_main_does_not_advance_unanswered_test(self):
        class Tab:
            def js(self, script):
                if 'if (app?.isTestEnv)' in script:
                    return True
                return 0

        state = {'unit': 'Unit 1', 'lesson': 'L', 'step': 'Test',
                 'counter': '1', 'total': '2', 'body': ''}
        with patch.object(auto.edlib, 'tab', return_value=Tab()), \
             patch.object(auto.login, 'ensure_login', return_value=True), \
             patch.object(auto, 'st', return_value=state), \
             patch.object(auto, 'update_live_status'), \
             patch.object(auto.solver, 'source_text', return_value={'resource': '', 'body': ''}), \
             patch.object(auto.solver, 'neutralize'), \
             patch.object(auto, 'q', return_value=0), \
             patch.object(auto, 'handle_test', return_value='test-unanswered: timeout'), \
             patch.object(auto, 'advance') as advance:
            auto.main(1)
        advance.assert_not_called()

    def test_unrecognized_question_after_retry_does_not_submit(self):
        tab = Mock()
        tab.js.return_value = ''
        with patch.object(auto.solver, 'dom_transcript', return_value=''), \
             patch.object(auto.solver, 'do_task', return_value='other: missing'), \
             patch.object(auto, 'q', return_value=1), \
             patch.object(auto, 'click') as click, \
             patch.object(auto.time, 'sleep'), \
             patch.object(auto, 'st', return_value={'total': '2', 'counter': '2'}), \
             patch.object(auto.poll, 'wait_until'):
            result = auto.handle_test(tab, '')
        self.assertTrue(result.startswith('test-unanswered:'), result)
        click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
