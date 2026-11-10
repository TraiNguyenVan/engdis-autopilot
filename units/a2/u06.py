"""Unit 7 handler: Economics (Advanced 2)."""

from typing import Any, Dict, Optional
from core.base_unit import BaseUnit


class Unit06Economics(BaseUnit):
    course = "a2"
    unit_index = 6
    unit_name = "Economics"

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        return None
