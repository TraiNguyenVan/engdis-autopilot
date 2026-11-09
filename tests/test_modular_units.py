"""Tests for modular unit architecture and completed-account test reengineering."""

import unittest
from unittest.mock import MagicMock, Mock, patch

from core.base_unit import BaseUnit, DefaultUnit
from core.unit_loader import get_unit_handler, normalize_course_slug
from units.a2.u04 import Unit04TooMuchWork
import cover


class TestBaseUnit(unittest.TestCase):
    def test_is_lesson_satisfied_progress_only(self):
        unit = BaseUnit()
        # Incomplete progress
        self.assertFalse(unit.is_lesson_satisfied({"progress": 0.667}))
        # Complete progress without score
        self.assertTrue(unit.is_lesson_satisfied({"progress": 1.0}))
        # Force flag bypasses completion
        self.assertFalse(unit.is_lesson_satisfied({"progress": 1.0}, force=True))

    def test_is_lesson_satisfied_with_low_scores(self):
        unit = BaseUnit()
        # 100% progress but low lesson score (e.g. 40%) -> must NOT be satisfied
        self.assertFalse(
            unit.is_lesson_satisfied({"progress": 1.0, "score": 40}, min_score=80.0)
        )
        self.assertFalse(
            unit.is_lesson_satisfied({"progress": 1.0, "score": 80}, min_score=100.0)
        )
        # 100% progress and 100% score -> satisfied
        self.assertTrue(
            unit.is_lesson_satisfied({"progress": 1.0, "score": 100}, min_score=100.0)
        )

    def test_is_lesson_satisfied_with_step_scores(self):
        unit = BaseUnit()
        lesson_data = {
            "progress": 1.0,
            "score": None,
            "steps": [
                {"name": "Explore", "progress": 1.0, "score": None},
                {"name": "Practice", "progress": 1.0, "score": None},
                {"name": "Test", "progress": 1.0, "score": 60},
            ],
        }
        # Step score 60 is below 80 and 100 -> must return False
        self.assertFalse(unit.is_lesson_satisfied(lesson_data, min_score=80.0))
        self.assertFalse(unit.is_lesson_satisfied(lesson_data, min_score=100.0))

        # Update test step score to 100
        lesson_data["steps"][2]["score"] = 100
        self.assertTrue(unit.is_lesson_satisfied(lesson_data, min_score=100.0))

    def test_get_test_answer(self):
        unit = Unit04TooMuchWork()
        # Exact match
        self.assertEqual(unit.get_test_answer("Do vs. Make", "do homework"), "do")
        self.assertEqual(unit.get_test_answer("Do vs. Make", "make a decision"), "make")
        # Substring match on lesson name and question
        self.assertEqual(
            unit.get_test_answer("Lesson 5: Common Errors: Do vs. Make", "Please do homework today"),
            "do",
        )
        # Non-existent answer returns None
        self.assertIsNone(unit.get_test_answer("Do vs. Make", "completely unknown question"))
        self.assertIsNone(unit.get_test_answer("Unknown Lesson", "any question"))


class TestUnitLoader(unittest.TestCase):
    def test_normalize_course_slug(self):
        self.assertEqual(normalize_course_slug("Advanced 2"), "a2")
        self.assertEqual(normalize_course_slug("Advanced 3"), "a3")
        self.assertEqual(normalize_course_slug("Basic 1"), "b1")
        self.assertEqual(normalize_course_slug("Intermediate 2"), "i2")
        self.assertEqual(normalize_course_slug("Custom Course Name!"), "custom_course_name")
        self.assertEqual(normalize_course_slug(None), "generic")

    def test_get_unit_handler_finds_unit(self):
        # Unit 4 in Advanced 2 (0-based index 3)
        handler = get_unit_handler("Advanced 2", 3, "Too Much Work")
        self.assertIsInstance(handler, Unit04TooMuchWork)
        self.assertEqual(handler.course, "a2")
        self.assertEqual(handler.unit_index, 3)

    def test_get_unit_handler_fallback_to_default(self):
        # Non-existent unit handler returns DefaultUnit
        handler = get_unit_handler("Advanced 2", 9, "Review")
        self.assertIsInstance(handler, DefaultUnit)
        self.assertEqual(handler.course, "a2")
        self.assertEqual(handler.unit_index, 9)
        # Default unit returns None for task and test answers
        self.assertIsNone(handler.on_task(None, {"type": "mcq"}))
        self.assertIsNone(handler.get_test_answer("Review", "q1"))


class TestCompletedAccountFilter(unittest.TestCase):
    def test_filter_lessons_force_mode(self):
        lessons = [
            {"j": 0, "name": "Intro", "progress": 1.0, "done": True, "score": 100},
            {"j": 1, "name": "Work", "progress": 1.0, "done": True, "score": 40},
            {"j": 2, "name": "Review", "progress": 0.667, "done": False, "score": None},
        ]
        # In force mode, all lessons are kept regardless of 100% progress
        filtered = cover.filter_lessons(lessons, force=True)
        self.assertEqual(len(filtered), 3)

    def test_filter_lessons_score_aware(self):
        lessons = [
            {"j": 0, "name": "Intro", "progress": 1.0, "done": True, "score": 100},
            {"j": 1, "name": "Work", "progress": 1.0, "done": True, "score": 40},
            {"j": 2, "name": "Review", "progress": 1.0, "done": True, "score": 80},
        ]
        # Targeting 100% score: Work (40%) and Review (80%) must be included
        filtered = cover.filter_lessons(lessons, min_score=100.0)
        names = [l["name"] for l in filtered]
        self.assertIn("Work", names)
        self.assertIn("Review", names)
        self.assertNotIn("Intro", names)


class TestAutoUnitIntegration(unittest.TestCase):
    def test_handle_test_uses_unit_transcript(self):
        import auto

        class Tab:
            def js(self, script):
                if "audio,video" in script:
                    return "https://ed22.engdis.com/media/audio/a2glsqe.mp3"
                return ""

        handler = Unit04TooMuchWork()

        with patch.object(auto.solver, "dom_transcript", return_value=""), \
             patch.object(auto.solver, "do_task", return_value="mcq: picked A") as mock_do_task, \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "st", return_value={"total": "2", "counter": "1"}), \
             patch.object(auto.poll, "wait_until"):
            res = auto.handle_test(Tab(), "Test question", unit_handler=handler, lesson_name="Sequence")
            self.assertEqual(res, "mcq: picked A")
            called_src = mock_do_task.call_args[0][1]
            self.assertIn("Sequence listening task transcript", called_src)

    def test_handle_test_uses_unit_task_override(self):
        import auto

        class Tab:
            def js(self, script):
                return ""

        handler = Unit04TooMuchWork()
        handler.on_task = Mock(return_value="mcq: 100% verified")

        with patch.object(auto.solver, "dom_transcript", return_value=""), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "st", return_value={"total": "2", "counter": "1"}), \
             patch.object(auto.poll, "wait_until"):
            res = auto.handle_test(Tab(), "Test question", unit_handler=handler, lesson_name="Too Much Work")
            self.assertEqual(res, "mcq: 100% verified")
            handler.on_task.assert_called_once()


if __name__ == "__main__":
    unittest.main()
