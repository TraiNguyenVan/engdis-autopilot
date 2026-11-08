import contextlib
import io
import unittest
from unittest.mock import patch

import auto


class CompletionTests(unittest.TestCase):
    def run_last_step(self, progress, counter: str | None = '1'):
        class Tab:
            def js(self, script):
                if "name === 'practice'" in script or "name === 'test'" in script:
                    return False
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


class FakeClock:
    """Deterministic stand-in for the time module inside auto."""

    def __init__(self, step=1.0):
        self.now = 0.0
        self.step = step

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(float(seconds or 0), self.step)


class StepsCompleteTests(unittest.TestCase):
    def test_steps_complete_requires_every_step(self):
        self.assertTrue(auto.steps_complete([1, 1, 0.999]))
        self.assertFalse(auto.steps_complete([1, 1, 0.5]))
        self.assertFalse(auto.steps_complete([1, 1, None]))
        self.assertFalse(auto.steps_complete([]))
        self.assertFalse(auto.steps_complete(None))

    def test_steps_complete_rejects_booleans(self):
        self.assertFalse(auto.steps_complete([True, True]))

    def test_require_lesson_complete_polls_past_lagging_test_progress(self):
        reads = iter([[1, 1, 1, 1, 1, 0], [1, 1, 1, 1, 1, 0], [1, 1, 1, 1, 1, 1]])

        class Tab:
            def js(self, script):
                return next(reads)

        output = io.StringIO()
        with patch.object(auto, 'time', FakeClock()), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as ctx:
                auto.require_lesson_complete(Tab(), timeout=5.0)
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn('lesson complete', output.getvalue().lower())

    def test_require_lesson_complete_times_out_on_real_incompletion(self):
        class Tab:
            def js(self, script):
                return [1, 1, 1, 1, 1, 0]

        output = io.StringIO()
        with patch.object(auto, 'time', FakeClock()), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as ctx:
                auto.require_lesson_complete(Tab(), timeout=3.0)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn('lesson-incomplete', output.getvalue().lower())


if __name__ == '__main__':
    unittest.main()
