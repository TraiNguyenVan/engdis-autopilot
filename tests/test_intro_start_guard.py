import unittest

import auto


class IntroStartGuardTests(unittest.TestCase):
    """The merged test-intro shortcut must stay bounded.

    Clicking the intro node resets the loop's `prev` signature, so an intro that
    never advances cannot trip the 4-tick stall detector. The guard allows three
    attempts per (lesson, step) and then lets normal screen handling run.
    """

    def test_allows_three_attempts_then_stops(self):
        tries = {}
        key = ("Lesson A", "Step 3: Test")
        self.assertTrue(auto.next_intro_attempt(tries, key))
        self.assertTrue(auto.next_intro_attempt(tries, key))
        self.assertTrue(auto.next_intro_attempt(tries, key))
        self.assertFalse(auto.next_intro_attempt(tries, key))
        self.assertFalse(auto.next_intro_attempt(tries, key))

    def test_counts_per_lesson_and_step(self):
        tries = {}
        a = ("Lesson A", "Step 3: Test")
        b = ("Lesson B", "Step 3: Test")
        for _ in range(3):
            auto.next_intro_attempt(tries, a)
        self.assertFalse(auto.next_intro_attempt(tries, a))
        self.assertTrue(auto.next_intro_attempt(tries, b))

    def test_custom_limit(self):
        tries = {}
        key = ("Lesson A", "Step 3: Test")
        self.assertTrue(auto.next_intro_attempt(tries, key, limit=1))
        self.assertFalse(auto.next_intro_attempt(tries, key, limit=1))


if __name__ == "__main__":
    unittest.main()
