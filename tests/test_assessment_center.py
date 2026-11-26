"""Offline unit tests for Assessment Center (`TestArea.html`) support in `auto.py`.

Covers:
1. Section/part intro screen detection and advancement (`TestIntroNode` / `counter == "Intro"`),
   including fallback to `navigationService.selectedChanged({nodeId, courseNodeType: 4, selectedIndex: 1})`.
2. Multi-part `_lessonsList` progression (`Listening 1 NTE` -> `Listening 2 NTE` -> `Listening 3 NTE`)
   via `advance_next_part(t)` with `courseNodeType: 3` while preserving standard `learningArea` safety.
3. Richer `unanswered()` DOM registration check for `.DDLOptions__selected` (when `.prFITB__qaSet` or
   `.prDDL__qaSet` is present) and target `.dndZone` elements (excluding `TTpTablePlaceHolder`).
4. `#learning__tasksNav_submitTest` support and pre-submit completeness gate on `app.isTestEnv`
   (`"test-unanswered: incomplete-tasks"` when `_lessonsList.Children` has incomplete tasks).
5. Post-submit & final score screen handling on `TestArea.html` (`"Your score is 98%."` clean exit 0
   without `ed-la-dropdownlist` / `require_lesson_complete`, and multi-section continuation).
"""
import contextlib
import io
import json
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

import auto

NODE_BIN = shutil.which("node")

JS_HARNESS = r"""
globalThis.__selectedChanged = [];
const SPEC = __SPEC__;

function makeEl(raw) {
  const o = Object.assign({
    id: '',
    dg_name: '',
    innerText: '',
    textContent: '',
    offsetWidth: 0,
    offsetHeight: 0,
    innerHTML: '',
    parentElement: null,
  }, raw || {});
  const attrs = Object.assign({}, raw && raw.attrs ? raw.attrs : {});
  if (o.id && !attrs.id) attrs.id = o.id;
  if (o.dg_name && !attrs.dg_name) attrs.dg_name = o.dg_name;
  o.getAttribute = (k) => (k in attrs ? attrs[k] : null);
  const childMap = raw && raw.childrenBySelector ? raw.childrenBySelector : {};
  o.querySelector = (sel) => {
    for (const part of sel.split(',').map(s => s.trim())) {
      if (childMap[part]) return makeEl(childMap[part]);
    }
    return null;
  };
  o.click = () => {};
  return o;
}

const PROBE = new Map();
const NODES = {};
for (const [k, raw] of Object.entries(SPEC.nodes || {})) {
  NODES[k] = makeEl(raw);
  if (raw && raw.__comp !== undefined) PROBE.set(NODES[k], raw.__comp);
}
const LISTS = {};
for (const [k, arr] of Object.entries(SPEC.lists || {})) {
  LISTS[k] = (arr || []).map((raw) => {
    const el = makeEl(raw);
    if (raw && raw.__comp !== undefined) PROBE.set(el, raw.__comp);
    return el;
  });
}

if (NODES['app'] && PROBE.has(NODES['app'])) {
  const nav = PROBE.get(NODES['app']).componentInstance?.navigationService;
  if (nav && nav.__recordSelectedChanged) {
    nav.selectedChanged = (payload) => {
      globalThis.__selectedChanged.push(payload);
    };
  }
}

const ng = { probe: (el) => PROBE.get(el) || null };
const document = {
  body: { innerText: SPEC.body || '' },
  querySelector: (sel) => {
    for (const part of sel.split(',').map(s => s.trim())) {
      if (NODES[part]) return NODES[part];
      if (LISTS[part] && LISTS[part].length) return LISTS[part][0];
    }
    return null;
  },
  querySelectorAll: (sel) => {
    const out = [];
    for (const part of sel.split(',').map(s => s.trim())) {
      if (LISTS[part]) out.push(...LISTS[part]);
      else if (NODES[part]) out.push(NODES[part]);
    }
    return out;
  },
};
const window = {
  ng,
  location: { href: SPEC.url || 'https://ed22.engdis.com/Runtime/LearningArea.html' },
};
"""


def run_node_js(expr, *, nodes=None, lists=None, url=None, body=""):
    assert NODE_BIN, "node binary required"
    spec = {"nodes": nodes or {}, "lists": lists or {}, "url": url, "body": body}
    script = (
        JS_HARNESS.replace("__SPEC__", json.dumps(spec))
        + f"\nconst __res = ({expr});\n"
        + "process.stdout.write(JSON.stringify({res: __res ?? null, selectedChanged: globalThis.__selectedChanged}));"
    )
    proc = subprocess.run([NODE_BIN, "-e", script], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(f"node failed: {proc.stderr or proc.stdout}")
    return json.loads(proc.stdout)


def run_q_js(body_expr, **kwargs):
    return run_node_js("(() => {" + body_expr + "})()", **kwargs)


@unittest.skipUnless(NODE_BIN, "node required for JS evaluation tests")
class TestIntroHandlingTests(unittest.TestCase):
    def test_is_test_intro_screen_matches_intro_counter_and_testintronode(self):
        self.assertTrue(auto.is_test_intro_screen({"counter": "Intro", "step": "Listening 1"}))
        self.assertTrue(auto.is_test_intro_screen({"counter": None, "step": "TestIntroNode:101"}))
        self.assertTrue(auto.is_test_intro_screen({"counter": "", "step": "TestIntroNode"}))
        self.assertFalse(auto.is_test_intro_screen({"counter": "1", "step": "Listening 1:102"}))
        self.assertFalse(auto.is_test_intro_screen({"counter": "1", "step": "Step 3: Test"}))

    def test_advance_test_intro_uses_steps_list_fallback_when_advance_fails(self):
        app_node = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_stepsList": {
                            "SelectedIndex": 0,
                            "Children": [
                                {"NodeId": "intro-0", "Name": "TestIntroNode"},
                                {"NodeId": "step-1", "Name": "Listening 1", "IsLocked": True},
                            ],
                        },
                    },
                }
            }
        }
        out = run_node_js(auto.ADVANCE_TEST_INTRO_STEP_JS, nodes={"app": app_node})
        self.assertEqual(out["res"], 1)
        self.assertEqual(
            out["selectedChanged"],
            [{"nodeId": "step-1", "courseNodeType": 4, "selectedIndex": 1}],
        )

        tab = Mock()
        tab.js.return_value = 1
        with patch.object(auto, "advance", return_value=False) as adv_mock:
            self.assertTrue(auto.advance_test_intro(tab))
        adv_mock.assert_called_once_with(tab)

    def test_main_advances_past_testintronode_without_calling_handle_test(self):
        class Tab:
            def js(self, expr):
                if expr == auto.IS_TEST_JS:
                    return True
                if expr == auto.ADVANCE_TEST_INTRO_STEP_JS:
                    return 1
                return 0

        states = [
            {
                "unit": "",
                "lesson": "",
                "step": "TestIntroNode:500",
                "counter": "Intro",
                "total": "30",
                "body": "Section 1: Listening Comprehension",
            },
            {
                "unit": "",
                "lesson": "",
                "step": "Listening 1:501",
                "counter": "1",
                "total": "30",
                "body": "Question 1",
            },
        ]
        with patch.object(auto.edlib, "tab", return_value=Tab()), \
             patch.object(auto.login, "ensure_login", return_value=True), \
             patch.object(auto, "st", side_effect=states), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto.solver, "source_text", return_value={"resource": "", "body": ""}), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "advance", side_effect=[False, True]), \
             patch.object(auto, "handle_test", return_value="mcq: A") as handle_test_mock, \
             patch.object(auto.poll, "wait_until", return_value=1), \
             patch.object(auto.time, "sleep"):
            auto.main(max_iter=2)

        # Iter 1 advanced past TestIntroNode without calling handle_test; Iter 2 solved Q1.
        self.assertEqual(handle_test_mock.call_count, 1)

    def test_st_step_reports_testintronode_even_without_node_id(self):
        tab = Mock()
        tab.js.return_value = None
        auto.st(tab)
        step_js = tab.js.call_args_list[0].args[0]
        app_node = {
            "__comp": {
                "componentInstance": {
                    "navigationService": {
                        "_stepsList": {
                            "SelectedNode": {"Name": "TestIntroNode", "NodeId": 0}
                        }
                    }
                }
            }
        }
        out = run_node_js(step_js, nodes={"app": app_node})
        self.assertEqual(out["res"], "TestIntroNode")

    def test_testintronode_guard_is_bounded_so_stuck_intro_falls_through(self):
        class Tab:
            def js(self, expr):
                if expr == auto.IS_TEST_JS:
                    return True
                return 0

        state = {
            "unit": "",
            "lesson": "",
            "step": "TestIntroNode",
            "counter": "Intro",
            "total": "10",
            "body": "Intro screen",
        }
        with patch.object(auto.edlib, "tab", return_value=Tab()), \
             patch.object(auto.login, "ensure_login", return_value=True), \
             patch.object(auto, "st", return_value=state), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto.solver, "source_text", return_value={"resource": "", "body": ""}), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "advance", return_value=False), \
             patch.object(auto, "handle_test", return_value="test-unanswered: other: Intro") as ht_mock, \
             patch.object(auto.poll, "wait_until", return_value=0), \
             patch.object(auto.time, "sleep"):
            auto.main(max_iter=4)

        # First 3 iterations try advancing past intro; 4th falls through to normal test handling.
        self.assertEqual(ht_mock.call_count, 1)


@unittest.skipUnless(NODE_BIN, "node required for JS evaluation tests")
class MultiPartProgressionTests(unittest.TestCase):
    def test_advance_next_part_moves_across_lessons_list_parts(self):
        app_node = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_lessonsList": {
                            "SelectedIndex": 0,
                            "Children": [
                                {"NodeId": "L1", "Name": "Listening 1 NTE"},
                                {"NodeId": "L2", "Name": "Listening 2 NTE", "IsLocked": True},
                                {"NodeId": "L3", "Name": "Listening 3 NTE", "IsLocked": True},
                            ],
                        },
                    },
                }
            }
        }
        out = run_node_js(
            auto.ADVANCE_NEXT_PART_JS,
            nodes={"app": app_node},
            url="https://ed22.engdis.com/Runtime/TestArea.html",
        )
        self.assertEqual(out["res"], 1)
        self.assertEqual(
            out["selectedChanged"],
            [{"nodeId": "L2", "courseNodeType": 3, "selectedIndex": 1}],
        )

    def test_advance_next_part_uses_selected_node_fallback_and_stops_at_end(self):
        app_mid = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_lessonsList": {
                            "SelectedNode": {"NodeId": "L2"},
                            "Children": [
                                {"NodeId": "L1", "Name": "Listening 1 NTE"},
                                {"NodeId": "L2", "Name": "Listening 2 NTE"},
                                {"NodeId": "L3", "Name": "Listening 3 NTE"},
                            ],
                        },
                    },
                }
            }
        }
        out_mid = run_node_js(auto.ADVANCE_NEXT_PART_JS, nodes={"app": app_mid})
        self.assertEqual(out_mid["res"], 1)
        self.assertEqual(
            out_mid["selectedChanged"],
            [{"nodeId": "L3", "courseNodeType": 3, "selectedIndex": 2}],
        )

        app_last = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_lessonsList": {
                            "SelectedIndex": 2,
                            "Children": [
                                {"NodeId": "L1"},
                                {"NodeId": "L2"},
                                {"NodeId": "L3"},
                            ],
                        },
                    },
                }
            }
        }
        out_last = run_node_js(auto.ADVANCE_NEXT_PART_JS, nodes={"app": app_last})
        self.assertEqual(out_last["res"], 0)
        self.assertEqual(out_last["selectedChanged"], [])

    def test_advance_next_part_refuses_standard_course_lessons_with_dropdown(self):
        app_course = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": False,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_lessonsList": {
                            "SelectedIndex": 0,
                            "Children": [{"NodeId": "L1"}, {"NodeId": "L2"}],
                        },
                    },
                }
            }
        }
        out = run_node_js(
            auto.ADVANCE_NEXT_PART_JS,
            nodes={"app": app_course},
            lists={"ed-la-dropdownlist": [{"innerText": "Lesson 1"}, {"innerText": "Practice"}]},
        )
        self.assertEqual(out["res"], 0)
        self.assertEqual(out["selectedChanged"], [])

    def test_main_calls_advance_next_part_at_part_boundary_10_of_30(self):
        class Tab:
            def js(self, expr):
                if expr == auto.IS_TEST_JS:
                    return True
                return 0

        state = {
            "unit": "",
            "lesson": "",
            "step": "Listening 1 NTE:10",
            "counter": "10",
            "total": "30",
            "body": "Question 10",
        }
        with patch.object(auto.edlib, "tab", return_value=Tab()), \
             patch.object(auto.login, "ensure_login", return_value=True), \
             patch.object(auto, "st", return_value=state), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto.solver, "source_text", return_value={"resource": "", "body": ""}), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto.poll, "wait_until", return_value=1), \
             patch.object(auto, "handle_test", return_value="mcq: B"), \
             patch.object(auto, "advance", return_value=False), \
             patch.object(auto, "advance_next_part", return_value=True) as next_part_mock, \
             patch.object(auto.time, "sleep"):
            auto.main(max_iter=1)

        next_part_mock.assert_called_once()


@unittest.skipUnless(NODE_BIN, "node required for JS evaluation tests")
class UnansweredAndPreSubmitGateTests(unittest.TestCase):
    def test_unanswered_detects_empty_ddl_options_when_fitb_or_ddl_present(self):
        unanswered_fitb = run_q_js(
            auto.UNANSWERED_TEST_DOM_JS,
            lists={
                ".prFITB__qaSet": [{}],
                ".DDLOptions__selected": [{"innerText": "chosen"}, {"innerText": "   "}],
            },
        )["res"]
        self.assertEqual(unanswered_fitb, 1)

        answered_ddl = run_q_js(
            auto.UNANSWERED_TEST_DOM_JS,
            lists={
                ".prDDL__qaSet": [{}],
                ".DDLOptions__selected": [{"innerText": "went"}, {"innerText": "gone"}],
            },
        )["res"]
        self.assertEqual(answered_ddl, 0)

    def test_unanswered_detects_empty_target_dndzone_ignoring_placeholder_bank(self):
        unanswered_dnd = run_q_js(
            auto.UNANSWERED_TEST_DOM_JS,
            lists={
                ".dndZone": [
                    {"dg_name": "TTpTablePlaceHolder", "innerText": "word1"},
                    {"dg_name": "0", "childrenBySelector": {".dnditem": {"innerText": "word2"}}},
                    {"dg_name": "1", "innerText": ""},
                ]
            },
        )["res"]
        self.assertEqual(unanswered_dnd, 1)

        # All target zones filled while bank (both dg_name and id TTpTablePlaceHolder) is now empty
        answered_dnd = run_q_js(
            auto.UNANSWERED_TEST_DOM_JS,
            lists={
                ".dndZone": [
                    {"dg_name": "TTpTablePlaceHolder", "innerText": ""},
                    {"id": "TTpTablePlaceHolder", "innerText": ""},
                    {"dg_name": "0", "childrenBySelector": {".dnditem": {"innerText": ""}}},
                    {"dg_name": "1", "innerText": "word2"},
                ]
            },
        )["res"]
        self.assertEqual(answered_dnd, 0)

    def test_pre_submit_gate_blocks_incomplete_tasks_and_jumps_to_first_incomplete(self):
        app_incomplete = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_lessonsList": {
                            "SelectedIndex": 2,
                            "Children": [
                                {"NodeId": "L1", "Name": "Part 1", "IsDone": True, "Progress": 1},
                                {
                                    "NodeId": "L2",
                                    "Name": "Part 2",
                                    "IsDone": False,
                                    "Progress": 0,
                                    "Children": [
                                        {"NodeId": "T11", "Name": "Q11", "IsDone": False, "Progress": 0}
                                    ],
                                },
                                {"NodeId": "L3", "Name": "Part 3", "IsDone": True, "Progress": 1},
                            ],
                        },
                    },
                }
            }
        }
        out = run_node_js(auto.HAS_INCOMPLETE_ASSESSMENT_TASKS_JS, nodes={"app": app_incomplete})
        self.assertEqual(out["res"], 1)
        self.assertEqual(
            out["selectedChanged"],
            [{"nodeId": "L2", "courseNodeType": 3, "selectedIndex": 1}],
        )

    def test_pre_submit_gate_allows_submit_when_all_previous_tasks_done_and_current_answered(self):
        app_complete = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_lessonsList": {
                            "SelectedIndex": 1,
                            "Children": [
                                {"NodeId": "L1", "Name": "Part 1", "IsDone": True, "Progress": 1},
                                {"NodeId": "L2", "Name": "Part 2", "IsDone": False, "Progress": 0},
                            ],
                        },
                        "_tasksList": {
                            "SelectedIndex": 1,
                            "Children": [
                                {"NodeId": "Q19", "IsDone": True, "Progress": 1},
                                {"NodeId": "Q20", "IsDone": False, "Progress": 0},
                            ],
                        },
                    },
                }
            }
        }
        out = run_node_js(auto.HAS_INCOMPLETE_ASSESSMENT_TASKS_JS, nodes={"app": app_complete})
        self.assertEqual(out["res"], 0)
        self.assertEqual(out["selectedChanged"], [])

    def test_handle_test_blocks_partial_exam_submit_on_is_last(self):
        tab = Mock()
        tab.js.side_effect = lambda expr: 1 if expr == auto.HAS_INCOMPLETE_ASSESSMENT_TASKS_JS else ""
        with patch.object(auto.solver, "dom_transcript", return_value=""), \
             patch.object(auto.solver, "do_task", return_value="mcq: C"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "st", return_value={"total": "30", "counter": "30"}), \
             patch.object(auto, "click") as click_mock:
            res = auto.handle_test(tab, "Question 30")

        self.assertEqual(res, "test-unanswered: incomplete-tasks")
        click_mock.assert_not_called()

    def test_handle_test_returns_unanswered_when_ddl_or_dnd_remains_empty_after_retry(self):
        for kind_out, lists in [
            ("fitb: 0=noopt", {".prFITB__qaSet": [{}], ".DDLOptions__selected": [{"innerText": ""}]}),
            ("drag: 0=FAIL", {".dndZone": [{"dg_name": "TTpTablePlaceHolder", "innerText": "x"}, {"dg_name": "0", "innerText": ""}]}),
        ]:
            tab = Mock()
            tab.js.side_effect = lambda expr, _lists=lists: (
                run_node_js(expr, lists=_lists)["res"] if "mcqUnanswered" in expr else ""
            )
            with patch.object(auto.solver, "dom_transcript", return_value=""), \
                 patch.object(auto.solver, "do_task", return_value=kind_out) as do_mock, \
                 patch.object(auto, "click") as click_mock, \
                 patch.object(auto.time, "sleep"):
                res = auto.handle_test(tab, "Question")
            self.assertEqual(do_mock.call_count, 2)
            self.assertEqual(res, f"test-unanswered: {kind_out}")
            click_mock.assert_not_called()

    def test_handle_test_submits_with_testarea_submit_selector_and_reads_your_score_is(self):
        tab = Mock()
        tab.js.return_value = ""
        with patch.object(auto.solver, "dom_transcript", return_value=""), \
             patch.object(auto.solver, "do_task", return_value="mcq: D"), \
             patch.object(auto, "q", side_effect=lambda _t, expr: 0 if "mcqUnanswered" in expr else 1), \
             patch.object(auto, "st", return_value={"total": "30", "counter": "30"}), \
             patch.object(auto, "has_incomplete_assessment_tasks", return_value=False), \
             patch.object(auto, "click") as click_mock, \
             patch.object(auto.poll, "wait_until", side_effect=[1, "You have completed the Placement Final Test.\nYour score is 98%."]), \
             patch.object(auto.time, "sleep"):
            res = auto.handle_test(tab, "Question 30")

        self.assertTrue(res.startswith("test-submit"), res)
        self.assertIn("Your score is 98%.", res)
        clicked_selectors = [c.args[1] for c in click_mock.call_args_list]
        self.assertTrue(any("#learning__tasksNav_submitTest" in s for s in clicked_selectors))


class AssessmentScoreAndSectionTransitionTests(unittest.TestCase):
    def test_main_exits_zero_on_testarea_score_screen_without_require_lesson_complete(self):
        class Tab:
            def js(self, expr):
                if expr == auto.IS_TEST_AREA_JS:
                    return True
                return 0

        state = {
            "unit": "",
            "lesson": "",
            "step": "Result",
            "counter": None,
            "total": None,
            "body": "You have completed the Advanced 3 Final Test.\nYour score is 98%.",
        }
        buf = io.StringIO()
        with patch.object(auto.edlib, "tab", return_value=Tab()), \
             patch.object(auto.login, "ensure_login", return_value=True), \
             patch.object(auto, "st", return_value=state), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto.solver, "source_text", return_value={"resource": "", "body": state["body"]}), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "require_lesson_complete") as req_mock, \
             contextlib.redirect_stdout(buf):
            rc = auto.main(max_iter=3)

        self.assertIsNone(rc)
        req_mock.assert_not_called()
        self.assertIn("Your score is 98%.", buf.getvalue())

    def test_main_continues_to_next_section_after_section_submit_and_exits_after_final_section(self):
        bodies = iter([
            "Section 2: Reading Comprehension",  # post-submit after Section 1
            "You have completed the Final Test.\nYour score is 96%.",  # post-submit after Section 2
        ])

        class Tab:
            def js(self, expr):
                if expr == auto.IS_TEST_JS:
                    return True
                if expr == auto.IS_TEST_AREA_JS:
                    return True
                if "document.body?.innerText" in expr:
                    return next(bodies)
                return 0

        states = [
            {
                "unit": "",
                "lesson": "",
                "step": "Listening 3:103",
                "counter": "30",
                "total": "30",
                "body": "Section 1 Question 30",
            },
            {
                "unit": "",
                "lesson": "",
                "step": "Reading 2:202",
                "counter": "20",
                "total": "20",
                "body": "Section 2 Question 20",
            },
        ]
        handle_outputs = iter([
            "test-submit []",  # Section 1 transitions directly to Section 2
            "test-submit ['Your score is 96%.']",  # Final section shows score
        ])
        buf = io.StringIO()
        with patch.object(auto.edlib, "tab", return_value=Tab()), \
             patch.object(auto.login, "ensure_login", return_value=True), \
             patch.object(auto, "st", side_effect=states), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto.solver, "source_text", return_value={"resource": "", "body": ""}), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto.poll, "wait_until", return_value=1), \
             patch.object(auto, "handle_test", side_effect=lambda *a, **kw: next(handle_outputs)) as ht_mock, \
             patch.object(auto, "require_lesson_complete") as req_mock, \
             contextlib.redirect_stdout(buf):
            rc = auto.main(max_iter=5)

        self.assertIsNone(rc)
        self.assertEqual(ht_mock.call_count, 2)
        req_mock.assert_not_called()
        self.assertIn("Your score is 96%.", buf.getvalue())

    def test_standard_course_lesson_score_screen_still_calls_require_lesson_complete(self):
        class Tab:
            def js(self, expr):
                if expr == auto.IS_TEST_AREA_JS:
                    return False
                return 0

        state = {
            "unit": "Unit 1",
            "lesson": "Lesson 2",
            "step": "Test",
            "counter": "5",
            "total": "5",
            "body": "Your test score is: 100%",
        }
        buf = io.StringIO()
        with patch.object(auto.edlib, "tab", return_value=Tab()), \
             patch.object(auto.login, "ensure_login", return_value=True), \
             patch.object(auto, "st", return_value=state), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto.solver, "source_text", return_value={"resource": "", "body": state["body"]}), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto.solver, "set_next_step", return_value="last step"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "require_lesson_complete", side_effect=SystemExit(0)) as req_mock, \
             patch.object(auto.time, "sleep"), \
             contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                auto.main(max_iter=1)

        self.assertEqual(ctx.exception.code, 0)
        req_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
