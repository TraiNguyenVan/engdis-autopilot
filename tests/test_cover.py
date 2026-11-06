import unittest
from cover import parse_unit_specs, match_course


class TestParseUnitSpecs(unittest.TestCase):
    def test_single_unit(self):
        self.assertEqual(parse_unit_specs("0"), [0])
        self.assertEqual(parse_unit_specs("8"), [8])
        self.assertEqual(parse_unit_specs(5), [5])

    def test_range_hyphen(self):
        self.assertEqual(parse_unit_specs("8-9"), [8, 9])
        self.assertEqual(parse_unit_specs("1-3"), [1, 2, 3])

    def test_range_dots(self):
        self.assertEqual(parse_unit_specs("8..9"), [8, 9])
        self.assertEqual(parse_unit_specs("0..2"), [0, 1, 2])

    def test_comma_separated(self):
        self.assertEqual(parse_unit_specs("7,8,9"), [7, 8, 9])
        self.assertEqual(parse_unit_specs("0, 5, 8"), [0, 5, 8])

    def test_mixed(self):
        self.assertEqual(parse_unit_specs("0,2,4-6,8..9"), [0, 2, 4, 5, 6, 8, 9])
        self.assertEqual(parse_unit_specs("8, 8-9"), [8, 9])

    def test_all_keyword(self):
        self.assertEqual(parse_unit_specs("all", total_units=5), [0, 1, 2, 3, 4])
        self.assertEqual(parse_unit_specs("ALL", total_units=10), list(range(10)))

    def test_default_empty(self):
        self.assertEqual(parse_unit_specs(""), [0])
        self.assertEqual(parse_unit_specs(None), [0])

    def test_bounds_filtering(self):
        self.assertEqual(parse_unit_specs("8-15", total_units=10), [8, 9])

    def test_invalid_spec_raises(self):
        with self.assertRaises(ValueError):
            parse_unit_specs("abc")
        with self.assertRaises(ValueError):
            parse_unit_specs("20-30", total_units=10)


class TestMatchCourse(unittest.TestCase):
    def setUp(self):
        self.courses = [
            {"CourseId": 44205, "courseName": "Basic 3"},
            {"CourseId": 44845, "courseName": "Intermediate 1"},
            {"CourseId": 45689, "courseName": "Advanced 2"},
            {"CourseId": 45742, "courseName": "Advanced 3"},
        ]

    def test_exact_name(self):
        c = match_course("Advanced 3", self.courses)
        self.assertIsNotNone(c)
        assert c is not None
        self.assertEqual(c["CourseId"], 45742)

    def test_case_insensitive_name(self):
        c = match_course("advanced 2", self.courses)
        self.assertIsNotNone(c)
        assert c is not None
        self.assertEqual(c["CourseId"], 45689)

    def test_numeric_id(self):
        c = match_course("45742", self.courses)
        self.assertIsNotNone(c)
        assert c is not None
        self.assertEqual(c["courseName"], "Advanced 3")

    def test_shorthand(self):
        c3 = match_course("a3", self.courses)
        self.assertIsNotNone(c3)
        assert c3 is not None
        self.assertEqual(c3["CourseId"], 45742)

        c2 = match_course("adv2", self.courses)
        self.assertIsNotNone(c2)
        assert c2 is not None
        self.assertEqual(c2["CourseId"], 45689)

    def test_empty_or_not_found(self):
        self.assertIsNone(match_course("", self.courses))
        self.assertIsNone(match_course("NonExistent Course", self.courses))


if __name__ == "__main__":
    unittest.main()
