"""BaseUnit: abstract contract for unit-specific automation handlers."""

from typing import Any, Dict, List, Optional, Union


def _num(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


class BaseUnit:
    """Base unit handler. Inherit and override in units/<course>/u<N>.py."""

    course: str = "generic"
    unit_index: int = 0
    unit_name: str = ""

    # Custom widget selectors or DOM overrides if unit layout deviates
    custom_selectors: Dict[str, str] = {}

    def __init__(self, course: str = "", unit_index: int = 0, unit_name: str = ""):
        if course:
            self.course = course
        if unit_index:
            self.unit_index = unit_index
        if unit_name:
            self.unit_name = unit_name

    def is_lesson_satisfied(
        self,
        lesson_meta: Dict[str, Any],
        min_score: float = 100.0,
        force: bool = False,
    ) -> bool:
        """Evaluate if lesson is truly complete."""
        if force:
            return False

        prog = _num(lesson_meta.get("progress"))
        if prog < 0.999:
            return False

        lesson_score = lesson_meta.get("score")
        if lesson_score is not None and _num(lesson_score) < min_score:
            return False

        steps = lesson_meta.get("steps") or []
        for step in steps:
            s_name = (step.get("name") or "").lower()
            if "test" in s_name or step.get("is_test"):
                s_score = step.get("score")
                if s_score is not None and _num(s_score) < min_score:
                    return False

        return True

    def on_before_lesson(self, tab: Any, lesson_meta: Dict[str, Any]) -> None:
        """Lifecycle hook before lesson automation begins."""
        pass

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        """Custom task solver override if a unit needs specific DOM handling."""
        return None

    def on_after_lesson(
        self, tab: Any, lesson_meta: Dict[str, Any], result: Dict[str, Any]
    ) -> None:
        """Lifecycle hook after lesson completes."""
        pass


class DefaultUnit(BaseUnit):
    """Fallback unit handler when no custom unit module exists."""
    pass
