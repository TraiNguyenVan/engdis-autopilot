import unittest
from unittest.mock import Mock, patch

import solver


class SequenceSolverTests(unittest.TestCase):
    def test_do_task_classifies_sequence_when_sequence_zone_present(self):
        tab = Mock()
        tab.js.side_effect = [
            1,          # ready check
            "sequence"  # kind
        ]
        with patch.object(solver, "solve_sequence", return_value="sequence: ok") as mock_seq:
            result = solver.do_task(tab, "context")
        self.assertEqual(result, "sequence: ok")
        mock_seq.assert_called_once_with(tab, "context")

    def test_solve_sequence_reorders_items_via_drag(self):
        tab = Mock()
        items_raw = [
            {"zone": "0", "text": "Sentence B"},
            {"zone": "1", "text": "Sentence A"}
        ]
        def mock_js(expr):
            if "dg_name" in expr and "unique" in expr:
                return items_raw
            if "already" in expr or "includes" in expr:
                return 0
            return items_raw
        tab.js.side_effect = mock_js

        rects = {
            "items": [
                {"t": "Sentence B", "cx": 100, "cy": 100},
                {"t": "Sentence A", "cx": 100, "cy": 200}
            ],
            "zones": [
                {"n": "0", "cx": 100, "cy": 100},
                {"n": "1", "cx": 100, "cy": 200}
            ]
        }

        with patch.object(solver, "neutralize"), \
             patch.object(solver, "jso"), \
             patch.object(solver, "time"), \
             patch.object(solver, "ask_json", return_value={"order": [2, 1]}), \
             patch.object(solver.edlib, "rects", return_value=rects):
            res = solver.solve_sequence(tab, "source transcript")

        self.assertEqual(res, "sequence: ok")
        self.assertTrue(tab.drag_xy.called)

    def test_solve_sequence_handles_empty_order_gracefully(self):
        tab = Mock()
        tab.js.return_value = [{"zone": "0", "text": "B"}, {"zone": "1", "text": "A"}]
        with patch.object(solver, "neutralize"), \
             patch.object(solver, "jso"), \
             patch.object(solver, "time"), \
             patch.object(solver, "ask_json", return_value=None):
            res = solver.solve_sequence(tab, "")
        self.assertEqual(res, "sequence: EMPTY-ORDER")


if __name__ == "__main__":
    unittest.main()
