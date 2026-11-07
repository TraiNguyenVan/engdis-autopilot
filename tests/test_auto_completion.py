import contextlib
import io
import unittest
from unittest.mock import patch

import auto


class CompletionTests(unittest.TestCase):
    def run_last_step(self, progress, counter: str | None = '1'):
        class Tab:
            def js(self, script):
                if 'STEP_PROGRESS_MARKER' in script or 'navigationService?._stepsList?.SelectedNode' in script:
                    return 0 if counter is None else 1
                if 'dropDownListObj' in script:
                    return progress
                return False

        state = {'unit': 'Unit 1', 'lesson': 'Lesson 3', 'step': 'Test',
                 'counter': counter, 'total': '1', 'body': ''}
        output = io.StringIO()
        with patch.object(auto.edlib, 'tab', return_value=Tab()), \
             patch.object(auto.login, 'ensure_login', return_value=True), \
             patch.object(auto, 'st', return_value=state), \
             patch.object(auto, 'update_live_status'), \
             patch.object(auto.solver, 'source_text', return_value={'resource': '', 'body': ''}), \
             patch.object(auto.solver, 'neutralize'), \
             patch.object(auto, 'advance', return_value=False), \
             patch.object(auto, 'q', return_value=0), \
             patch.object(auto.poll, 'wait_until'), \
             patch.object(auto.solver, 'play_media', return_value=False), \
             patch.object(auto.solver, 'set_next_step', return_value='last step'), \
             patch.object(auto.time, 'sleep'), contextlib.redirect_stdout(output):
            try:
                auto.main(1)
            except SystemExit as exc:
                return output.getvalue(), exc.code
        return output.getvalue(), None

    def test_missing_progress_does_not_prove_completion(self):
        output, code = self.run_last_step(None)
        self.assertNotIn('lesson complete', output.lower())
        self.assertEqual(code, 2)

    def test_completed_last_step_does_not_prove_lesson_complete(self):
        output, code = self.run_last_step([1, 1, 1, 0.5, 1])
        self.assertNotIn('lesson complete', output.lower())
        self.assertEqual(code, 2)

    def test_counterless_last_step_requires_all_steps_complete(self):
        output, code = self.run_last_step([1, 1, 1, 0.5, 1], counter=None)
        self.assertNotIn('lesson complete', output.lower())
        self.assertEqual(code, 2)

    def test_all_steps_complete_allows_completion(self):
        output, code = self.run_last_step([1, 1, 1, 1, 1])
        self.assertIn('lesson complete', output.lower())
        self.assertEqual(code, 0)


if __name__ == '__main__':
    unittest.main()
