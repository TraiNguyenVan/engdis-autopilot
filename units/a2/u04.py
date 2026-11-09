"""Unit 4 handler: Too Much Work (Advanced 2)."""

from typing import Any, Dict, List, Optional, Union
from core.base_unit import BaseUnit


class Unit04TooMuchWork(BaseUnit):
    course = "a2"
    unit_index = 3
    unit_name = "Too Much Work"

    # Deterministic test answer keys for 100% score
    test_answers = {
        "Do vs. Make": {
            "do homework": "do",
            "make a mistake": "make",
            "do your best": "do",
            "make a decision": "make",
            "do research": "do",
            "make a phone call": "make",
        },
        "Work 4": {
            "1": "a",
            "2": "c",
            "3": "b",
            "4": "d",
        },
        "Working From Home": {
            "1": "true",
            "2": "false",
        },
        "Sequence": {
            "first": 1,
            "then": 2,
            "next": 3,
            "finally": 4,
        },
    }

    # Transcripts for listening exercises
    transcripts = {
        "a2glsqe": "Sequence listening task transcript",
        "a2gedme": "Do vs Make transcript",
        "a2veahp06": "Work 4 vocabulary transcript",
    }

    # Custom drag-drop mappings for Lesson 2 / Lesson 4
    zone_maps = {
        "Working From Home": {
            "telecommuting": "advantages",
            "isolation": "disadvantages",
            "flexibility": "advantages",
            "distractions": "disadvantages",
        }
    }

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        """Custom overrides for Unit 4 quirks (e.g. speaking bridge or custom DnD)."""
        lesson_name = task_state.get("lesson", "")
        task_type = task_state.get("type", "")

        # Example override: speaking task bypass on "Too Much Work"
        if "Too Much Work" in lesson_name and task_type == "speak":
            # Can trigger special bridge or fallback
            return None

        # Fallback to generic solver
        return None
