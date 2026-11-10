"""Unit 6 handler: Tell Me About It (Advanced 2)."""

from typing import Any, Dict, Optional
from core.base_unit import BaseUnit


class Unit05TellMeAboutIt(BaseUnit):
    course = "a2"
    unit_index = 5
    unit_name = "Tell Me About It"

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        return None
