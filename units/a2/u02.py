"""Unit 2 handler: Agreeing And Disagreeing (Advanced 2)."""

from typing import Any, Dict, Optional
from core.base_unit import BaseUnit


class Unit02AgreeingAndDisagreeing(BaseUnit):
    course = "a2"
    unit_index = 2
    unit_name = "Agreeing And Disagreeing"

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        return None
