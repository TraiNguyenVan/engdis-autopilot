"""Unit 1 handler: Business Careers (Advanced 2)."""

from typing import Any, Dict, Optional
from core.base_unit import BaseUnit


class Unit01BusinessCareers(BaseUnit):
    course = "a2"
    unit_index = 0
    unit_name = "Business Careers"

    # Deterministic test answer keys for 100% score
    test_answers = {}

    # Media transcripts
    transcripts = {}

    # Custom drag-drop / sequence mappings
    zone_maps = {}

    def on_task(self, tab: Any, task_state: Dict[str, Any]) -> Optional[str]:
        return None
