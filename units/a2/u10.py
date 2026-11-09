"""Unit 10 handler: Space Exploration (Advanced 2)."""

from typing import Any, Dict, Optional
from core.base_unit import BaseUnit


class Unit10SpaceExploration(BaseUnit):
    course = "a2"
    unit_index = 9
    unit_name = "Space Exploration"

    test_answers = {}
    transcripts = {}
    zone_maps = {}

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        return None
