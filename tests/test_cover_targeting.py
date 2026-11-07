import unittest
import cover


class TestCoverTargeting(unittest.TestCase):
    def test_filter_lessons_by_index_or_name(self):
        lessons = [
            {"j": 0, "name": "Intro", "progress": 1.0, "done": True},
            {"j": 1, "name": "Wedding Plans", "progress": 0.667, "done": False},
            {"j": 2, "name": "Review", "progress": 0.667, "done": False},
        ]
        # Match by index
        filtered = cover.filter_lessons(lessons, lesson_spec="1")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "Wedding Plans")

        # Match by name substring
        filtered = cover.filter_lessons(lessons, lesson_spec="Wedding")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "Wedding Plans")

    def test_filter_lessons_test_only_mode(self):
        lessons = [
            {"j": 0, "name": "Intro", "progress": 1.0, "done": True},
            {"j": 1, "name": "Wedding Plans", "progress": 0.667, "done": False},
            {"j": 2, "name": "Close Relationship", "progress": 0.333, "done": False},
        ]
        # In test-only mode, only lessons with progress >= 0.60 and < 0.999 (explore+practice done) are picked
        filtered = cover.filter_lessons(lessons, test_only=True)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "Wedding Plans")

    def test_filter_lessons_skips(self):
        lessons = [
            {"j": 0, "name": "Speaking Practice", "progress": 0.667, "done": False},
            {"j": 1, "name": "Wedding Plans", "progress": 0.667, "done": False},
        ]
        filtered = cover.filter_lessons(lessons, skips=["speaking"])
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "Wedding Plans")


if __name__ == "__main__":
    unittest.main()
