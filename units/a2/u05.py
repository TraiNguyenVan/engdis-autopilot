"""Unit 5 handler: People With Problems (Advanced 2)."""

from typing import Any, Dict, Optional
from core.base_unit import BaseUnit


class Unit05PeopleWithProblems(BaseUnit):
    course = "a2"
    unit_index = 4
    unit_name = "People With Problems"

    test_answers = {}
    transcripts = {}
    zone_maps = {}

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        return None
