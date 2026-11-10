"""Unit 9 handler: Artificial Intelligence (Advanced 2)."""

from typing import Any, Dict, Optional
from core.base_unit import BaseUnit


class Unit08ArtificialIntelligence(BaseUnit):
    course = "a2"
    unit_index = 8
    unit_name = "Artificial Intelligence"

    def is_lesson_satisfied(self, lesson_meta, min_score=100.0, force=False):
        if force:
            return False
        # Unit 8 Lesson 5 ("The Pros and Cons of AI") has test review/progress
        # quirks where Step 4 test completion reports 75% on the top-level tree
        # while all steps are completed. Treat >= 0.75 as satisfied.
        name = lesson_meta.get("name", "")
        p = lesson_meta.get("progress", 0.0)
        if isinstance(p, list):
            p = p[0] if p else 0.0
        if "the pros and cons of ai" in name.lower() and float(p) >= 0.75:
            return True
        return super().is_lesson_satisfied(lesson_meta, min_score=min_score, force=force)

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        return None
