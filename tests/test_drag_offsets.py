"""Offline unit tests for solve_drag drop retry offsets and word-bank exclusion."""
import unittest
from unittest.mock import Mock, patch

import solver


def _make_drag_tab(snapshot_zones, snapshot_bank, zone_items_state, scroll_meta=None):
    """Build an offline mock Tab simulating DOM state for solve_drag."""
    tab = Mock()
    js_scripts = []

    def mock_js(expr):
        js_scripts.append(expr)
        if "scrollIntoView" in expr:
            return scroll_meta if scroll_meta is not None else {"scrolled": 0, "w": None, "h": None}
        if "return { zones: zones, bank: bank };" in expr:
            return {"zones": snapshot_zones, "bank": snapshot_bank}
        if "ed-la-matching" in expr:
            return "Complete the email using words from the bank."
        for zid, items in zone_items_state.items():
            if f'dg_name="{zid}"' in expr:
                return list(items)
        return []

    tab.js.side_effect = mock_js
    tab.js_scripts = js_scripts
    return tab


class DragOffsetsAndBankExclusionTests(unittest.TestCase):
    def test_horizontal_offset_succeeds_when_center_and_vertical_fail(self):
        """Reproduces live Adv2 Final Test S2 Q5: target zone directly below tile fails at dx=0, succeeds with horizontal dx."""
        zone_state = {"3": []}
        snapshot_zones = [
            {"n": "3", "id": "", "label": "Blank 3", "items": []},
            {"n": "TTpTablePlaceHolder", "id": "TTpTablePlaceHolder", "label": "", "items": ["sales force"]},
        ]
        tab = _make_drag_tab(
            snapshot_zones,
            ["sales force"],
            zone_state,
            scroll_meta={"scrolled": 0, "w": 142, "h": 28},
        )

        # Source tile (cx=350, cy=643, w=97) sits directly above zones[3] (cx=350, cy=671, w=142).
        rects = {
            "items": [{"t": "sales force", "cx": 350, "cy": 643}],
            "zones": [
                {"n": "3", "cx": 350, "cy": 671, "count": 0},
                {"n": "TTpTablePlaceHolder", "cx": 350, "cy": 643, "count": 1},
            ],
        }

        drags = []

        def fake_drag(x1, y1, x2, y2):
            drags.append((x1, y1, x2, y2))
            # Center / vertical-only drops (dx == 0) fail; horizontal offset inside w=142 succeeds.
            if abs(x2 - 350) >= 15 and abs(x2 - 350) <= 67:
                zone_state["3"] = ["sales force"]

        tab.drag_xy.side_effect = fake_drag

        with patch.object(solver, "ask_json", return_value={"map": {"3": "sales force"}}), \
             patch.object(solver.edlib, "rects", return_value=rects), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_drag(tab, "source email context")

        self.assertEqual(res, "drag: 3=ok")
        self.assertEqual(len(drags), 2)
        self.assertEqual(drags[0], (350, 643, 350, 671))   # attempt 0: (0, 0) fails
        self.assertEqual(drags[1], (350, 643, 325, 671))   # attempt 1: (-25, 0) succeeds

    def test_positive_horizontal_offset_succeeds_when_center_and_left_fail(self):
        zone_state = {"3": []}
        snapshot_zones = [
            {"n": "3", "id": "", "label": "", "items": []},
            {"n": "TTpTablePlaceHolder", "id": "", "label": "", "items": ["sales force"]},
        ]
        tab = _make_drag_tab(snapshot_zones, ["sales force"], zone_state)
        rects = {
            "items": [{"t": "sales force", "cx": 350, "cy": 643}],
            "zones": [{"n": "3", "cx": 350, "cy": 671, "count": 0}],
        }

        drags = []

        def fake_drag(x1, y1, x2, y2):
            drags.append((x2 - 350, y2 - 671))
            if x2 - 350 > 0:
                zone_state["3"] = ["sales force"]

        tab.drag_xy.side_effect = fake_drag

        with patch.object(solver, "ask_json", return_value={"map": {"3": "sales force"}}), \
             patch.object(solver.edlib, "rects", return_value=rects), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_drag(tab, "ctx")

        self.assertEqual(res, "drag: 3=ok")
        self.assertEqual(drags, [(0, 0), (-25, 0), (25, 0)])

    def test_offsets_clamped_when_narrow_zone_width_known(self):
        zone_state = {"0": []}
        snapshot_zones = [{"n": "0", "id": "", "label": "", "items": []}]
        tab = _make_drag_tab(snapshot_zones, ["word"], zone_state)
        # Zone width is 30px -> valid x span is [185, 215]; unclamped -25/+25 would miss.
        rects = {
            "items": [{"t": "word", "cx": 200, "cy": 260}],
            "zones": [{"n": "0", "cx": 200, "cy": 300, "w": 30, "h": 20, "count": 0}],
        }

        drags = []

        def fake_drag(x1, y1, x2, y2):
            drags.append((x2, y2))
            if x2 != 200 and 185 < x2 < 215:
                zone_state["0"] = ["word"]

        tab.drag_xy.side_effect = fake_drag

        with patch.object(solver, "ask_json", return_value={"map": {"0": "word"}}), \
             patch.object(solver.edlib, "rects", return_value=rects), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_drag(tab, "ctx")

        self.assertEqual(res, "drag: 0=ok")
        self.assertEqual(drags[0], (200, 300))
        self.assertTrue(185 < drags[1][0] < 200)

    def test_bank_zones_excluded_by_dg_name_and_id(self):
        self.assertTrue(solver._is_bank_zone({"n": "TTpTablePlaceHolder", "id": ""}))
        self.assertTrue(solver._is_bank_zone({"n": None, "id": "TTpTablePlaceHolder"}))
        self.assertTrue(solver._is_bank_zone({"n": "", "id": "TTpTablePlaceHolder"}))
        self.assertFalse(solver._is_bank_zone({"n": "0", "id": "zone_0"}))
        self.assertFalse(solver._is_bank_zone(None))

        zone_state = {"0": ["sales force"]}
        snapshot_zones = [
            {"n": "0", "id": "z0", "label": "Topic A", "items": []},
            {"n": "TTpTablePlaceHolder", "id": "", "label": "Bank1", "items": ["sales force"]},
            {"n": None, "id": "TTpTablePlaceHolder", "label": "Bank2", "items": ["extra"]},
        ]
        tab = _make_drag_tab(snapshot_zones, ["sales force", "extra"], zone_state)
        rects = {
            "items": [{"t": "sales force", "cx": 100, "cy": 100}],
            "zones": [{"n": "0", "cx": 200, "cy": 200, "count": 0}],
        }

        captured_prompts = []

        def fake_ask_json(q, max_tokens=2000):
            captured_prompts.append(q)
            return {"map": {"0": "sales force", "TTpTablePlaceHolder": "extra"}}

        with patch.object(solver, "ask_json", side_effect=fake_ask_json), \
             patch.object(solver.edlib, "rects", return_value=rects), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_drag(tab, "ctx")

        self.assertEqual(res, "drag: 0=ok")
        self.assertEqual(len(captured_prompts), 1)
        target_section = captured_prompts[0].split("Word bank (to place):")[0]
        self.assertIn("[id=0] Topic A", target_section)
        self.assertNotIn("TTpTablePlaceHolder", target_section)
        self.assertNotIn("Bank1", target_section)
        self.assertNotIn("Bank2", target_section)

    def test_drag_snapshot_checks_both_dg_name_and_id_for_bank(self):
        tab = Mock()
        tab.js.return_value = {
            "zones": [
                {"n": "0", "id": "", "label": "L0", "items": []},
                {"n": None, "id": "TTpTablePlaceHolder", "label": "", "items": ["tile"]},
            ],
            "bank": ["tile"],
        }
        zones, bank = solver._drag_snapshot(tab)
        script = tab.js.call_args.args[0]
        self.assertIn("dg_name", script)
        self.assertIn("z.id === 'TTpTablePlaceHolder'", script)
        self.assertEqual([z["n"] for z in zones if not solver._is_bank_zone(z)], ["0"])
        self.assertEqual(bank, ["tile"])

    def test_scrolls_off_viewport_before_measuring_rects(self):
        events = []
        zone_state = {"0": ["alpha"]}
        snapshot_zones = [{"n": "0", "id": "", "label": "", "items": []}]
        tab = _make_drag_tab(
            snapshot_zones,
            ["alpha"],
            zone_state,
            scroll_meta={"scrolled": 1, "w": 120, "h": 28},
        )
        orig_side_effect = tab.js.side_effect

        def tracked_js(expr):
            if "scrollIntoView" in expr:
                events.append("scroll")
            return orig_side_effect(expr)

        tab.js.side_effect = tracked_js

        def tracked_rects(_t):
            events.append("rects")
            return {
                "items": [{"t": "alpha", "cx": 100, "cy": 100}],
                "zones": [{"n": "0", "cx": 200, "cy": 250, "count": 0}],
            }

        with patch.object(solver, "ask_json", return_value={"map": {"0": "alpha"}}), \
             patch.object(solver.edlib, "rects", side_effect=tracked_rects), \
             patch.object(solver.time, "sleep") as mock_sleep:
            res = solver.solve_drag(tab, "ctx")

        self.assertEqual(res, "drag: 0=ok")
        self.assertEqual(events[:2], ["scroll", "rects"])
        self.assertIn(0.1, [c.args[0] for c in mock_sleep.call_args_list if c.args])


if __name__ == "__main__":
    unittest.main()
