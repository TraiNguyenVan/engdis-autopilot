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

    # Verified 100% test answers: { lesson_id_or_name: { question_matcher: answer_data } }
    test_answers: Dict[Union[int, str], Any] = {}

    # Audio/Video transcripts: { media_id_or_title: transcript_text }
    transcripts: Dict[str, str] = {}

    # Custom drag-and-drop zone maps: { template_or_question: { item: target_zone } }
    zone_maps: Dict[str, Dict[str, str]] = {}

    # Custom selectors / button mappings
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
        """Evaluate if lesson is truly complete.

        Prevents false positives on finished accounts where progress is 100%
        but test score is low (e.g. 40% or 60%).
        """
        if force:
            return False

        prog = _num(lesson_meta.get("progress"))
        if prog < 0.999:
            return False

        # If overall lesson score exists and is below threshold, it's not satisfied
        lesson_score = lesson_meta.get("score")
        if lesson_score is not None and _num(lesson_score) < min_score:
            return False

        # Inspect step-level score if available (e.g. Test step)
        steps = lesson_meta.get("steps") or []
        for step in steps:
            s_name = (step.get("name") or "").lower()
            if "test" in s_name or step.get("is_test"):
                s_score = step.get("score")
                if s_score is not None and _num(s_score) < min_score:
                    return False

        return True

    def get_test_answer(
        self,
        lesson_name_or_idx: Union[int, str],
        question_text: str,
        options: Optional[List[str]] = None,
    ) -> Optional[Any]:
        """Lookup deterministic verified test answer for 100% score."""
        # 1. Exact lesson match
        answers = self.test_answers.get(lesson_name_or_idx)
        if not answers and isinstance(lesson_name_or_idx, str):
            # Try case-insensitive or substring match
            for k, v in self.test_answers.items():
                if isinstance(k, str) and k.lower() in lesson_name_or_idx.lower():
                    answers = v
                    break

        if not answers:
            return None

        # 2. Match question text or index
        if question_text in answers:
            return answers[question_text]

        # Case-insensitive substring match on question
        q_clean = question_text.strip().lower()
        for q_key, ans in answers.items():
            if str(q_key).lower() in q_clean or q_clean in str(q_key).lower():
                return ans

        return None

    def on_before_lesson(self, tab: Any, lesson_meta: Dict[str, Any]) -> None:
        """Lifecycle hook before lesson automation begins."""
        pass

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        """Custom task solver override. Return str if handled, None to fallback."""
        return None

    def on_after_lesson(
        self, tab: Any, lesson_meta: Dict[str, Any], result: Dict[str, Any]
    ) -> None:
        """Lifecycle hook after lesson completes."""
        pass


class DefaultUnit(BaseUnit):
    """Fallback unit handler when no custom unit module exists."""
    pass
