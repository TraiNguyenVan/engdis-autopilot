"""Unit 10 handler: Space Exploration (Advanced 2)."""

from typing import Any, Dict, Optional
from core.base_unit import BaseUnit


class Unit00TellingTheTruth(BaseUnit):
    course = "a2"
    unit_index = 0
    unit_name = "Telling The Truth"

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        return None
