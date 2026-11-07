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

    def test_parse_unit_specs(self):
        # Single unit
        self.assertEqual(cover.parse_unit_specs("5"), [5])
        # Range with hyphen
        self.assertEqual(cover.parse_unit_specs("5-9"), [5, 6, 7, 8, 9])
        # Range with dots
        self.assertEqual(cover.parse_unit_specs("1..3"), [1, 2, 3])
        # List with commas and semicolons
        self.assertEqual(cover.parse_unit_specs("0, 2; 4"), [0, 2, 4])
        # Mixed list and range
        self.assertEqual(cover.parse_unit_specs("0, 2-4, 6"), [0, 2, 3, 4, 6])
        # All
        self.assertEqual(cover.parse_unit_specs("all", total_units=5), [0, 1, 2, 3, 4])
        # Defaults
        self.assertEqual(cover.parse_unit_specs(""), [0])
        self.assertEqual(cover.parse_unit_specs(None), [0])
        # Invalid spec or out of bounds
        with self.assertRaises(ValueError):
            cover.parse_unit_specs("abc")
        with self.assertRaises(ValueError):
            cover.parse_unit_specs("12-15", total_units=10)


if __name__ == "__main__":
    unittest.main()
