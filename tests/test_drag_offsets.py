"""Offline unit tests for solve_drag drop retry offsets, scroll recheck, and word-bank exclusion."""
import json
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

import edlib
import solver


def _eval_js_in_node(harness_js, expr_js):
    """Execute generated browser JS expression against a minimal mock DOM in Node."""
    node = shutil.which("node")
    if not node:
        return None
    script = f"{harness_js}\nconst __res = {expr_js};\nprocess.stdout.write(JSON.stringify(__res));\n"
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10, check=True)
    return json.loads(proc.stdout)


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
                {"n": "3", "id": "", "cx": 350, "cy": 671, "count": 0},
                {"n": "TTpTablePlaceHolder", "id": "TTpTablePlaceHolder", "cx": 350, "cy": 643, "count": 1},
            ],
        }

        drags = []

        def fake_drag(x1, y1, x2, y2):
            drags.append((x1, y1, x2, y2))
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
            "zones": [{"n": "3", "id": "", "cx": 350, "cy": 671, "count": 0}],
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

    def test_preserves_legacy_vertical_offsets_including_plus_eight(self):
        """Regression test: preserve base vertical retry offsets (-4, +4, +8) so cases needing y=+8 still pass."""
        self.assertIn((0, -4), solver._DRAG_DROP_OFFSETS)
        self.assertIn((0, 4), solver._DRAG_DROP_OFFSETS)
        self.assertIn((0, 8), solver._DRAG_DROP_OFFSETS)

        zone_state = {"0": []}
        snapshot_zones = [{"n": "0", "id": "", "label": "", "items": []}]
        tab = _make_drag_tab(
            snapshot_zones,
            ["phrase"],
            zone_state,
            scroll_meta={"scrolled": 0, "w": 120, "h": 14},
        )
        # Even with a short h=14 zone rect, dy=+8 must NOT be clamped away.
        rects = {
            "items": [{"t": "phrase", "cx": 200, "cy": 100, "w": 80, "h": 24}],
            "zones": [{"n": "0", "id": "", "cx": 200, "cy": 300, "w": 120, "h": 14, "count": 0}],
        }

        drags = []

        def fake_drag(x1, y1, x2, y2):
            drags.append((x2 - 200, y2 - 300))
            if (x2, y2) == (200, 308):
                zone_state["0"] = ["phrase"]

        tab.drag_xy.side_effect = fake_drag

        with patch.object(solver, "ask_json", return_value={"map": {"0": "phrase"}}), \
             patch.object(solver.edlib, "rects", return_value=rects), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_drag(tab, "ctx")

        self.assertEqual(res, "drag: 0=ok")
        self.assertIn((0, 8), drags)

    def test_offsets_clamped_when_narrow_zone_width_known(self):
        zone_state = {"0": []}
        snapshot_zones = [{"n": "0", "id": "", "label": "", "items": []}]
        tab = _make_drag_tab(snapshot_zones, ["word"], zone_state)
        rects = {
            "items": [{"t": "word", "cx": 200, "cy": 260}],
            "zones": [{"n": "0", "id": "", "cx": 200, "cy": 300, "w": 30, "h": 20, "count": 0}],
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
            "zones": [{"n": "0", "id": "z0", "cx": 200, "cy": 200, "count": 0}],
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

    def test_id_only_bank_propagated_through_rects_dispatch_and_prefilled_clear(self):
        """Regression test: ID-only bank clears prefilled targets instead of returning 'drag: already' untouched,
        exposes id in edlib.rects(), and routes to 'drag' in do_task()."""
        # 1. edlib.rects(t) exposes zone id so _is_bank_zone() matches ID-only banks.
        rects_tab = Mock()
        rects_tab.js.return_value = {"items": [], "zones": []}
        edlib.rects(rects_tab)
        rects_js = rects_tab.js.call_args.args[0]
        self.assertIn("id:e.id", rects_js.replace(" ", ""))

        if shutil.which("node"):
            dom_harness = """
              const itemEl = { innerText: ' correct ', getBoundingClientRect: () => ({x: 10, y: 20, width: 80, height: 24}) };
              const z0 = { id: 'z0', getAttribute: k => k === 'dg_name' ? '0' : null,
                           querySelectorAll: () => [{ innerText: 'wrong' }],
                           getBoundingClientRect: () => ({x: 100, y: 200, width: 120, height: 28}) };
              const bankEl = { id: 'TTpTablePlaceHolder', getAttribute: () => null,
                               querySelectorAll: () => [itemEl],
                               getBoundingClientRect: () => ({x: 10, y: 20, width: 300, height: 40}) };
              global.document = {
                querySelectorAll: sel => sel === '.dnditem' ? [itemEl] : (sel === '.dndZone' ? [z0, bankEl] : [])
              };
            """
            parsed_rects = _eval_js_in_node(dom_harness, rects_js)
            bank_rect = next(z for z in parsed_rects["zones"] if solver._is_bank_zone(z))
            self.assertIsNone(bank_rect["n"])
            self.assertEqual(bank_rect["id"], "TTpTablePlaceHolder")

        # 2. do_task() classifier dispatches ID-only bank to solve_drag, not solve_sequence.
        dispatch_scripts = []
        dispatch_tab = Mock()

        def dispatch_js(expr):
            dispatch_scripts.append(expr)
            if len(dispatch_scripts) == 1:
                return 1
            if shutil.which("node"):
                harness = """
                  global.window = {};
                  const matches = sel => sel.includes('#TTpTablePlaceHolder')
                    || sel === '.dnditem' || sel === '.dndZone';
                  global.document = {
                    querySelector: sel => matches(sel) ? {} : null,
                    querySelectorAll: sel => (sel === '.dnditem' || sel === '.dndZone') ? [{}] : []
                  };
                """
                return _eval_js_in_node(harness, expr)
            return "drag" if "#TTpTablePlaceHolder" in expr else "sequence"

        dispatch_tab.js.side_effect = dispatch_js
        with patch.object(solver, "solve_drag", return_value="drag: 0=ok") as mock_drag, \
             patch.object(solver, "solve_sequence", return_value="sequence: ok") as mock_seq:
            out = solver.do_task(dispatch_tab, "ctx")
        self.assertEqual(out, "drag: 0=ok")
        mock_drag.assert_called_once()
        mock_seq.assert_not_called()
        self.assertIn("#TTpTablePlaceHolder", dispatch_scripts[1])

        # 3. Prefilled target with ID-only bank clears wrong item to bank and solves, NEVER returning 'drag: already' unmoved.
        zone_state = {"0": ["wrong"]}
        bank_state = ["correct"]

        def dynamic_snapshot():
            return (
                [
                    {"n": "0", "id": "z0", "label": "Blank 0", "items": list(zone_state["0"])},
                    {"n": None, "id": "TTpTablePlaceHolder", "label": "", "items": list(bank_state)},
                ],
                list(bank_state),
            )

        tab = Mock()

        def prefill_js(expr):
            if "scrollIntoView" in expr:
                return {"scrolled": 0, "w": 120, "h": 28}
            if "return { zones: zones, bank: bank };" in expr:
                zs, bk = dynamic_snapshot()
                return {"zones": zs, "bank": bk}
            if "ed-la-matching" in expr:
                return "Fill blank"
            if 'dg_name="0"' in expr:
                return list(zone_state["0"])
            return []

        tab.js.side_effect = prefill_js

        def dynamic_rects(_t):
            items = []
            for w in zone_state["0"]:
                items.append({"t": w, "cx": 200, "cy": 300})
            for w in bank_state:
                items.append({"t": w, "cx": 60, "cy": 80})
            return {
                "items": items,
                "zones": [
                    {"n": "0", "id": "z0", "cx": 200, "cy": 300, "count": len(zone_state["0"])},
                    {"n": None, "id": "TTpTablePlaceHolder", "cx": 60, "cy": 80, "count": len(bank_state)},
                ],
            }

        def prefill_drag(x1, y1, x2, y2):
            if (x2, y2) == (60, 80) and zone_state["0"]:
                moved = zone_state["0"].pop(0)
                bank_state.append(moved)
            elif abs(x2 - 200) <= 30 and abs(y2 - 300) <= 10:
                if "correct" in bank_state:
                    bank_state.remove("correct")
                zone_state["0"] = ["correct"]

        tab.drag_xy.side_effect = prefill_drag

        with patch.object(solver, "ask_json", return_value={"map": {"0": "correct"}}), \
             patch.object(solver.edlib, "rects", side_effect=dynamic_rects), \
             patch.object(solver.time, "sleep"), \
             patch("builtins.print"):
            res = solver.solve_drag(tab, "ctx")

        self.assertEqual(res, "drag: 0=ok")
        self.assertEqual(zone_state["0"], ["correct"])

        # 4. Even if bank rect is completely missing in rects(), prefilled target must NOT report 'drag: already' without moving.
        stuck_state = {"0": ["wrong"]}
        tab_no_bank = _make_drag_tab(
            [{"n": "0", "id": "z0", "label": "", "items": ["wrong"]}],
            ["correct"],
            stuck_state,
        )
        rects_no_bank = {
            "items": [{"t": "wrong", "cx": 200, "cy": 300}, {"t": "correct", "cx": 60, "cy": 80}],
            "zones": [{"n": "0", "id": "z0", "cx": 200, "cy": 300, "count": 1}],
        }
        with patch.object(solver, "ask_json", return_value={"map": {"0": "correct"}}) as mock_ask, \
             patch.object(solver.edlib, "rects", return_value=rects_no_bank), \
             patch.object(solver.time, "sleep"), \
             patch("builtins.print"):
            res_no_bank = solver.solve_drag(tab_no_bank, "ctx")

        self.assertNotEqual(res_no_bank, "drag: already")
        self.assertTrue(mock_ask.called)

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

    def test_scrolls_off_viewport_and_rechecks_source_when_target_scroll_moves_source_offscreen(self):
        """Regression test: scrolling target after source can push source offscreen; both endpoints must be rechecked."""
        events = []
        zone_state = {"0": ["alpha"]}
        snapshot_zones = [{"n": "0", "id": "", "label": "", "items": []}]
        tab = _make_drag_tab(
            snapshot_zones,
            ["alpha"],
            zone_state,
            scroll_meta={"scrolled": 1, "w": 120, "h": 28, "sourceInView": True, "targetInView": True},
        )
        orig_side_effect = tab.js.side_effect
        captured_scroll_js = []

        def tracked_js(expr):
            if "scrollIntoView" in expr:
                events.append("scroll")
                captured_scroll_js.append(expr)
            return orig_side_effect(expr)

        tab.js.side_effect = tracked_js

        def tracked_rects(_t):
            events.append("rects")
            return {
                "items": [{"t": "alpha", "cx": 100, "cy": 100}],
                "zones": [{"n": "0", "id": "", "cx": 200, "cy": 250, "count": 0}],
            }

        with patch.object(solver, "ask_json", return_value={"map": {"0": "alpha"}}), \
             patch.object(solver.edlib, "rects", side_effect=tracked_rects), \
             patch.object(solver.time, "sleep") as mock_sleep:
            res = solver.solve_drag(tab, "ctx")

        self.assertEqual(res, "drag: 0=ok")
        self.assertEqual(events[:2], ["scroll", "rects"])
        self.assertIn(0.1, [c.args[0] for c in mock_sleep.call_args_list if c.args])

        scroll_expr = captured_scroll_js[0]
        self.assertIn("sourceInView", scroll_expr)
        self.assertIn("targetInView", scroll_expr)

        if shutil.which("node"):
            # Case A: z.scrollIntoView over-scrolls (e.g. aligns z near top), pushing source item above y=0,
            # while both endpoints fit in the 600px viewport when reconciled via window.scrollBy.
            over_scroll_harness = """
              let scrollY = 0;
              const itAbs = { top: 100, height: 30, left: 40, width: 90 };
              const zAbs  = { top: 620, height: 30, left: 40, width: 140 };
              const rectOf = b => ({
                top: b.top - scrollY, bottom: b.top + b.height - scrollY,
                left: b.left, right: b.left + b.width,
                x: b.left, y: b.top - scrollY, width: b.width, height: b.height
              });
              const itEl = {
                innerText: 'alpha', parentElement: null,
                getBoundingClientRect: () => rectOf(itAbs),
                scrollIntoView: () => { scrollY = itAbs.top; }
              };
              const zEl = {
                parentElement: null,
                getBoundingClientRect: () => rectOf(zAbs),
                // Over-scrolls z to y=100, which pushes itEl to y = 100 - 520 = -420 (offscreen!).
                scrollIntoView: () => { scrollY = zAbs.top - 100; }
              };
              global.window = {
                innerHeight: 600, innerWidth: 1024, scrollX: 0, scrollY: 0,
                scrollBy: (_dx, dy) => { scrollY += dy; global.window.scrollY = scrollY; }
              };
              global.document = {
                body: {}, documentElement: { clientHeight: 600, clientWidth: 1024 },
                querySelector: () => zEl,
                querySelectorAll: sel => sel === '.dnditem' ? [itEl] : []
              };
            """
            meta_a = _eval_js_in_node(over_scroll_harness, scroll_expr)
            self.assertEqual(meta_a["scrolled"], 1)
            self.assertTrue(meta_a["sourceInView"])
            self.assertTrue(meta_a["targetInView"])

            # Case B: Source and target are 900px apart (> 600px viewport); z.scrollIntoView moves source offscreen,
            # recheck brings source endpoint back into view so drag start is not offscreen.
            far_apart_harness = """
              let scrollY = 0;
              const itAbs = { top: 50, height: 30, left: 40, width: 90 };
              const zAbs  = { top: 950, height: 30, left: 40, width: 140 };
              const rectOf = b => ({
                top: b.top - scrollY, bottom: b.top + b.height - scrollY,
                left: b.left, right: b.left + b.width,
                x: b.left, y: b.top - scrollY, width: b.width, height: b.height
              });
              const itEl = {
                innerText: 'alpha', parentElement: null,
                getBoundingClientRect: () => rectOf(itAbs),
                scrollIntoView: () => { scrollY = Math.max(0, itAbs.top - 20); }
              };
              const zEl = {
                parentElement: null,
                getBoundingClientRect: () => rectOf(zAbs),
                scrollIntoView: () => { scrollY = zAbs.top + zAbs.height - 600; }
              };
              global.window = {
                innerHeight: 600, innerWidth: 1024, scrollX: 0, scrollY: 0,
                scrollBy: (_dx, dy) => { scrollY += dy; global.window.scrollY = scrollY; }
              };
              global.document = {
                body: {}, documentElement: { clientHeight: 600, clientWidth: 1024 },
                querySelector: () => zEl,
                querySelectorAll: sel => sel === '.dnditem' ? [itEl] : []
              };
            """
            meta_b = _eval_js_in_node(far_apart_harness, scroll_expr)
            self.assertEqual(meta_b["scrolled"], 1)
            self.assertTrue(meta_b["sourceInView"])


if __name__ == "__main__":
    unittest.main()
