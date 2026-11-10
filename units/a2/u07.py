"""Unit 8 handler: Interviews (Advanced 2)."""

from typing import Any, Dict, Optional
from core.base_unit import BaseUnit


class Unit07Interviews(BaseUnit):
    course = "a2"
    unit_index = 7
    unit_name = "Interviews"

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        return None
