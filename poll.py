"""Condition polling helpers. Replaces fixed sleeps that guess how long the SPA takes."""

import time


def wait_until(read, pred, timeout=6.0, interval=0.15, settle=0.0,
               clock=time.monotonic, sleeper=time.sleep):
    """Poll read() until pred(value) is true, or timeout elapses.

    Returns the last value read. Applies `settle` seconds once, after the
    predicate first becomes true, to let the DOM finish the transition.
    """
    end = clock() + timeout
    value = read()
    if pred(value):
        if settle:
            sleeper(settle)
        return value
    while clock() < end:
        sleeper(interval)
        value = read()
        if pred(value):
            if settle:
                sleeper(settle)
            return value
    return value
