import unittest

from poll import wait_until


class FakeClock:
    """Deterministic clock: sleep() advances now()."""

    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, d):
        self.t += d


class WaitUntilTests(unittest.TestCase):
    def test_returns_immediately_when_predicate_already_true(self):
        clock = FakeClock()
        reads = {"n": 0}

        def read():
            reads["n"] += 1
            return "ready"

        out = wait_until(read, lambda v: v == "ready", timeout=5.0,
                         interval=0.15, clock=clock.now, sleeper=clock.sleep)
        self.assertEqual(out, "ready")
        self.assertEqual(reads["n"], 1)
        self.assertEqual(clock.t, 0.0)

    def test_returns_as_soon_as_predicate_flips(self):
        clock = FakeClock()
        seq = iter([None, None, "x", "x"])

        out = wait_until(lambda: next(seq), lambda v: v == "x", timeout=5.0,
                         interval=0.15, clock=clock.now, sleeper=clock.sleep)
        self.assertEqual(out, "x")
        self.assertAlmostEqual(clock.t, 0.30, places=6)

    def test_gives_up_at_timeout_and_returns_last_value(self):
        clock = FakeClock()

        out = wait_until(lambda: None, lambda v: v is not None, timeout=1.0,
                         interval=0.15, clock=clock.now, sleeper=clock.sleep)
        self.assertIsNone(out)
        self.assertGreaterEqual(clock.t, 1.0)
        self.assertLessEqual(clock.t, 1.2)

    def test_settle_is_applied_only_after_a_change(self):
        clock = FakeClock()
        seq = iter([0, 1])

        wait_until(lambda: next(seq), lambda v: v == 1, timeout=5.0,
                   interval=0.15, settle=0.2, clock=clock.now, sleeper=clock.sleep)
        self.assertAlmostEqual(clock.t, 0.35, places=6)


if __name__ == "__main__":
    unittest.main()
