"""Unit 4 handler: Too Much Work (Advanced 2)."""

from typing import Any, Dict, Optional
from core.base_unit import BaseUnit


class Unit03TooMuchWork(BaseUnit):
    course = "a2"
    unit_index = 3
    unit_name = "Too Much Work"

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        return None
