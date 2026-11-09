"""Unit 9 handler: Artificial Intelligence (Advanced 2)."""

from typing import Any, Dict, Optional
from core.base_unit import BaseUnit


class Unit09ArtificialIntelligence(BaseUnit):
    course = "a2"
    unit_index = 8
    unit_name = "Artificial Intelligence"

    test_answers = {}
    transcripts = {}
    zone_maps = {}

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        return None
