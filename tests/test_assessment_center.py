"""Offline unit & regression tests for Assessment Center (`TestArea.html`) support in `auto.py`.

Covers all live-observed Assessment Center behaviors and fail-closed review guards:
1. Target tab selection (`TestArea.html` preferred over `learningArea`) & live session recognition
   so `login.ensure_login` never navigates away from an open assessment tab.
2. Section/part intro handling (`TestIntroNode` / `Intro`) with positive Assessment Center mode check,
   current-step intro verification (`curIdx -> curIdx + 1`, never jumping backwards to `steps[1]`),
   and verified state transition.
3. Multi-part `_lessonsList` progression (`advance_next_part`) requiring positive Assessment Center mode,
   staying within the current section boundary, and verifying state transition.
4. Richer `unanswered()` guard rejecting solver error/nodata outputs (`fitb: nodata`, `open: nodata`,
   `EMPTY-MAP`, `=FAIL`, etc.) and requiring positive DOM evidence of a registered answer.
5. Pre-submit completeness gate failing closed (`completeness-unknown`) when assessment/lesson/task
   data is missing or `NodeId` is undefined, and scoping strictly to the current section boundary
   without side-effect navigation to future sections.
6. Post-submit verification: stopping immediately (`rc=6`) on unverified/failed submission without
   repeating submit, and never manufacturing `Progress`/`IsDone` on assessments or unconfirmed submits.
7. Final completion verification: distinguishing genuine final completion from intermediate section
   scores, remaining incomplete sections, or question prompts containing `"your score is"`.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import MagicMock, Mock, patch

import auto

NODE_BIN = shutil.which("node")

JS_HARNESS = r"""
globalThis.__selectedChanged = [];
const SPEC = __SPEC__;

function makeEl(raw) {
  const o = Object.assign({
    id: '',
    dg_name: '',
    value: '',
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
  const classes = Array.isArray(raw && raw.classes) ? raw.classes : [];
  o.classList = { contains: (c) => classes.includes(c) };
  const childMap = raw && raw.childrenBySelector ? raw.childrenBySelector : {};
  o.querySelector = (sel) => {
    for (const part of sel.split(',').map(s => s.trim())) {
      if (childMap[part]) return makeEl(childMap[part]);
    }
    return null;
  };
  o.getClientRects = () => ((o.offsetWidth || o.offsetHeight) ? [{}] : []);
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
class TargetTabAndSessionTests(unittest.TestCase):
    def test_select_target_tab_default_mode_uses_edlib_tab_even_when_testarea_open(self):
        default_tab = Mock()
        with patch.dict(os.environ, {"ED_ASSESSMENT": ""}), \
             patch.object(auto.sys, "argv", ["auto.py"]), \
             patch.object(auto.edlib, "tab", return_value=default_tab) as edlib_tab_fn, \
             patch.object(auto.edlib.driver.urllib.request, "urlopen") as urlopen_fn:
            picked = auto.select_target_tab(port=9999)

        self.assertIs(picked, default_tab)
        edlib_tab_fn.assert_called_once_with()
        urlopen_fn.assert_not_called()

    def test_select_target_tab_prefers_testarea_tab_over_learningarea_when_requested(self):
        fake_targets = [
            {
                "type": "page",
                "url": "https://ed22.engdis.com/Runtime/learningArea.html",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9999/devtools/page/lesson",
            },
            {
                "type": "page",
                "url": "https://ed22.engdis.com/Runtime/TestArea.html?testId=42",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9999/devtools/page/exam",
            },
        ]
        resp = io.StringIO(json.dumps(fake_targets))
        fake_tab = Mock()
        with patch.dict(os.environ, {"ED_ASSESSMENT": "1"}), \
             patch.object(auto.edlib.driver.urllib.request, "urlopen", return_value=resp), \
             patch.object(auto.edlib.driver, "Tab", return_value=fake_tab) as tab_cls:
            picked = auto.select_target_tab(port=9999)

        self.assertIs(picked, fake_tab)
        tab_cls.assert_called_once_with("ws://127.0.0.1:9999/devtools/page/exam")

    def test_select_target_tab_fails_closed_when_assessment_requested_without_exam_tab(self):
        fake_targets = [
            {
                "type": "page",
                "url": "https://ed22.engdis.com/Runtime/learningArea.html",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9999/devtools/page/lesson",
            }
        ]
        resp = io.StringIO(json.dumps(fake_targets))
        buf = io.StringIO()
        with patch.dict(os.environ, {"ED_ASSESSMENT": "1"}), \
             patch.object(auto.edlib.driver.urllib.request, "urlopen", return_value=resp), \
             contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                auto.select_target_tab(port=9999)
        self.assertEqual(ctx.exception.code, 6)
        self.assertIn("NO-ASSESSMENT-TAB", buf.getvalue())

    def test_ensure_session_recognizes_live_testarea_and_never_navigates_to_login(self):
        app_node = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {"_lessonsList": {"Children": []}},
                }
            }
        }
        live = run_node_js(
            auto.IS_LIVE_ASSESSMENT_SESSION_JS,
            nodes={"app": app_node, "#pmContainer": {}},
            url="https://ed22.engdis.com/Runtime/TestArea.html",
            body="Question 1 of 30",
        )["res"]
        self.assertTrue(live)

        tab = Mock()
        tab.js.side_effect = lambda expr: (
            True if expr in (auto.IS_LIVE_ASSESSMENT_SESSION_JS, auto.IS_TEST_AREA_JS) else False
        )
        with patch.object(auto.login, "ensure_login") as login_mock:
            self.assertTrue(auto.ensure_session(tab, assessment_locked=True))
        login_mock.assert_not_called()

        # Expired session on TestArea.html must return False WITHOUT calling login.ensure_login(t)
        dead = run_node_js(
            auto.IS_LIVE_ASSESSMENT_SESSION_JS,
            nodes={"app": app_node},
            url="https://ed22.engdis.com/Runtime/TestArea.html",
            body="Member Login",
        )["res"]
        self.assertFalse(dead)

        tab_dead = Mock()
        tab_dead.js.side_effect = lambda expr: (
            False if expr == auto.IS_LIVE_ASSESSMENT_SESSION_JS else True
        )
        with patch.object(auto.login, "ensure_login") as login_mock:
            self.assertFalse(auto.ensure_session(tab_dead, assessment_locked=True))
        login_mock.assert_not_called()

    def test_main_stops_immediately_if_assessment_tab_leaves_testarea(self):
        test_area_checks = iter([True, False])

        class Tab:
            def js(self, expr):
                if expr == auto.IS_TEST_AREA_JS:
                    return next(test_area_checks)
                if expr == auto.IS_LIVE_ASSESSMENT_SESSION_JS:
                    return True
                return 0

        state = {"unit": "", "lesson": "", "step": "", "counter": None, "total": None, "body": "Hello Student"}
        buf = io.StringIO()
        with patch.object(auto.edlib, "tab", return_value=Tab()), \
             patch.object(auto, "st", return_value=state), \
             contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                auto.main(max_iter=2)
        self.assertEqual(ctx.exception.code, 6)
        self.assertIn("ASSESSMENT-TAB-LOST", buf.getvalue())


@unittest.skipUnless(NODE_BIN, "node required for JS evaluation tests")
class TestIntroHandlingTests(unittest.TestCase):
    def test_is_test_intro_screen_matches_intro_counter_and_testintronode(self):
        self.assertTrue(auto.is_test_intro_screen({"counter": "Intro", "step": "Listening 1"}))
        self.assertTrue(auto.is_test_intro_screen({"counter": None, "step": "TestIntroNode:101"}))
        self.assertTrue(auto.is_test_intro_screen({"counter": "", "step": "TestIntroNode"}))
        self.assertFalse(auto.is_test_intro_screen({"counter": "1", "step": "Listening 1:102"}))
        self.assertFalse(auto.is_test_intro_screen({"counter": "1", "step": "Step 3: Test"}))

    def test_advance_test_intro_advances_from_current_intro_index_and_verifies_transition(self):
        # Intro at index 2 advances to index 3 (never hardcoded index 1)
        app_node = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_stepsList": {
                            "SelectedIndex": 2,
                            "SelectedNode": {"NodeId": "intro-2"},
                            "Children": [
                                {"NodeId": "intro-0", "Name": "TestIntroNode"},
                                {"NodeId": "step-1", "Name": "Part 1"},
                                {"NodeId": "intro-2", "Name": "TestIntroNode"},
                                {"NodeId": "step-3", "Name": "Part 2", "IsLocked": True},
                            ],
                        },
                    },
                }
            }
        }
        out = run_node_js(
            auto.ADVANCE_TEST_INTRO_STEP_JS,
            nodes={"app": app_node},
            url="https://ed22.engdis.com/Runtime/TestArea.html",
        )
        self.assertEqual(out["res"], 1)
        self.assertEqual(
            out["selectedChanged"],
            [{"nodeId": "step-3", "courseNodeType": 4, "selectedIndex": 3}],
        )

        # Transition verification: returns False if NAV_STATE_SIG_JS never changes
        unchanged_tab = Mock()
        unchanged_tab.js.side_effect = lambda expr: (
            "sig-before" if expr == auto.NAV_STATE_SIG_JS else (1 if expr == auto.ADVANCE_TEST_INTRO_STEP_JS else 0)
        )
        with patch.object(auto, "advance", return_value=False), \
             patch.object(auto.poll, "wait_until", return_value="sig-before"):
            self.assertFalse(auto.advance_test_intro(unchanged_tab))

        # Returns True once NAV_STATE_SIG_JS changes
        changed_tab = Mock()
        changed_tab.js.side_effect = lambda expr: (
            "sig-before" if expr == auto.NAV_STATE_SIG_JS else (1 if expr == auto.ADVANCE_TEST_INTRO_STEP_JS else 0)
        )
        with patch.object(auto, "advance", return_value=False), \
             patch.object(auto.poll, "wait_until", return_value="sig-after"):
            self.assertTrue(auto.advance_test_intro(changed_tab))

    def test_advance_test_intro_refuses_outside_assessment_or_on_non_intro_step(self):
        # Course lesson (isTestEnv=False, LearningArea URL, even if dropdown not yet mounted)
        course_app = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": False,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_stepsList": {
                            "SelectedIndex": 2,
                            "Children": [
                                {"NodeId": "s0", "Name": "Explore"},
                                {"NodeId": "s1", "Name": "Practice"},
                                {"NodeId": "s2", "Name": "Test"},
                            ],
                        },
                    },
                }
            }
        }
        out_course = run_node_js(auto.ADVANCE_TEST_INTRO_STEP_JS, nodes={"app": course_app})
        self.assertEqual(out_course["res"], 0)
        self.assertEqual(out_course["selectedChanged"], [])

        # Assessment mode, but current step is NOT an intro node (must not jump backwards or skip)
        non_intro_app = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_stepsList": {
                            "SelectedIndex": 1,
                            "Children": [
                                {"NodeId": "intro-0", "Name": "TestIntroNode"},
                                {"NodeId": "step-1", "Name": "Listening 1"},
                                {"NodeId": "step-2", "Name": "Listening 2"},
                            ],
                        },
                    },
                }
            }
        }
        out_non_intro = run_node_js(
            auto.ADVANCE_TEST_INTRO_STEP_JS,
            nodes={"app": non_intro_app},
            url="https://ed22.engdis.com/Runtime/TestArea.html",
        )
        self.assertEqual(out_non_intro["res"], 0)
        self.assertEqual(out_non_intro["selectedChanged"], [])

    def test_main_advances_past_testintronode_without_calling_handle_test(self):
        class Tab:
            def js(self, expr):
                if expr in (auto.IS_TEST_JS, auto.IS_TEST_AREA_JS, auto.IS_LIVE_ASSESSMENT_SESSION_JS):
                    return True
                if expr == auto.ADVANCE_TEST_INTRO_STEP_JS:
                    return 1
                if expr == auto.NAV_STATE_SIG_JS:
                    return "sig-0"
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
             patch.object(auto, "st", side_effect=states), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto.solver, "source_text", return_value={"resource": "", "body": ""}), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "advance", side_effect=[False, True]), \
             patch.object(auto, "handle_test", return_value="mcq: A") as handle_test_mock, \
             patch.object(auto.poll, "wait_until", side_effect=["sig-1", 1]), \
             patch.object(auto.time, "sleep"):
            auto.main(max_iter=2)

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

    def test_failed_test_intro_does_not_reset_prev_stall_detector(self):
        class Tab:
            def js(self, expr):
                if expr in (auto.IS_TEST_JS, auto.IS_TEST_AREA_JS, auto.IS_LIVE_ASSESSMENT_SESSION_JS):
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
             patch.object(auto, "st", return_value=state), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto.solver, "source_text", return_value={"resource": "", "body": ""}), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto.solver, "dump_task", return_value="/tmp/stuck.json"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "advance_test_intro", return_value=False), \
             patch.object(auto, "handle_test", return_value="test-unanswered: other: Intro"), \
             patch.object(auto.poll, "wait_until", return_value=0), \
             patch.object(auto.time, "sleep"), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                auto.main(max_iter=6)

        # Because moved=False does not reset prev, the 4-tick stall detector fires cleanly (rc=6).
        self.assertEqual(ctx.exception.code, 6)


@unittest.skipUnless(NODE_BIN, "node required for JS evaluation tests")
class MultiPartProgressionTests(unittest.TestCase):
    def test_advance_next_part_moves_within_same_section_and_stops_before_next_section(self):
        app_part1 = {
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
                                {"NodeId": "R1", "Name": "Reading 1 NTE", "IsLocked": True},
                            ],
                        },
                    },
                }
            }
        }
        out = run_node_js(
            auto.ADVANCE_NEXT_PART_JS,
            nodes={"app": app_part1},
            url="https://ed22.engdis.com/Runtime/TestArea.html",
        )
        self.assertEqual(out["res"], 1)
        self.assertEqual(
            out["selectedChanged"],
            [{"nodeId": "L2", "courseNodeType": 3, "selectedIndex": 1}],
        )

        # At Listening 2 NTE, next item is Reading 1 NTE (different section) -> must NOT cross without submit
        app_part2 = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_lessonsList": {
                            "SelectedIndex": 1,
                            "Children": [
                                {"NodeId": "L1", "Name": "Listening 1 NTE"},
                                {"NodeId": "L2", "Name": "Listening 2 NTE"},
                                {"NodeId": "R1", "Name": "Reading 1 NTE"},
                            ],
                        },
                    },
                }
            }
        }
        out_boundary = run_node_js(
            auto.ADVANCE_NEXT_PART_JS,
            nodes={"app": app_part2},
            url="https://ed22.engdis.com/Runtime/TestArea.html",
        )
        self.assertEqual(out_boundary["res"], 0)
        self.assertEqual(out_boundary["selectedChanged"], [])

    def test_advance_next_part_requires_positive_assessment_mode_even_without_dropdown(self):
        app_course = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": False,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_lessonsList": {
                            "SelectedIndex": 0,
                            "Children": [
                                {"NodeId": "L1", "Name": "Part 1"},
                                {"NodeId": "L2", "Name": "Part 2"},
                            ],
                        },
                    },
                }
            }
        }
        # Even when ed-la-dropdownlist is absent, LearningArea.html + isTestEnv=False must NOT fire
        out = run_node_js(
            auto.ADVANCE_NEXT_PART_JS,
            nodes={"app": app_course},
            url="https://ed22.engdis.com/Runtime/LearningArea.html",
        )
        self.assertEqual(out["res"], 0)
        self.assertEqual(out["selectedChanged"], [])

    def test_advance_next_part_verifies_state_transition(self):
        tab = Mock()
        tab.js.side_effect = lambda expr: (
            "same-sig" if expr == auto.NAV_STATE_SIG_JS else (1 if expr == auto.ADVANCE_NEXT_PART_JS else 0)
        )
        with patch.object(auto.poll, "wait_until", return_value="same-sig"):
            self.assertFalse(auto.advance_next_part(tab))

        with patch.object(auto.poll, "wait_until", return_value="moved-sig"):
            self.assertTrue(auto.advance_next_part(tab))

    def test_main_calls_advance_next_part_at_part_boundary_10_of_30(self):
        class Tab:
            def js(self, expr):
                if expr in (auto.IS_TEST_JS, auto.IS_TEST_AREA_JS, auto.IS_LIVE_ASSESSMENT_SESSION_JS):
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
    def test_unanswered_requires_positive_dom_evidence_and_checks_all_ddl_and_dnd(self):
        # Empty DOM (no widgets at all) must be treated as unanswered (1)
        self.assertEqual(run_q_js(auto.UNANSWERED_TEST_DOM_JS)["res"], 1)

        # .prFITB__qaSet present with no rendered dropdowns/inputs -> unanswered (1)
        self.assertEqual(
            run_q_js(auto.UNANSWERED_TEST_DOM_JS, lists={".prFITB__qaSet": [{}]})["res"],
            1,
        )

        # .DDLOptions__selected empty even WITHOUT .prFITB__qaSet wrapper -> unanswered (1)
        self.assertEqual(
            run_q_js(auto.UNANSWERED_TEST_DOM_JS, lists={".DDLOptions__selected": [{"innerText": ""}]})["res"],
            1,
        )

        # All .DDLOptions__selected filled -> answered (0)
        self.assertEqual(
            run_q_js(
                auto.UNANSWERED_TEST_DOM_JS,
                lists={".DDLOptions__selected": [{"innerText": "went"}, {"innerText": "gone"}]},
            )["res"],
            0,
        )

        # Target dndZone empty -> unanswered (1); all targets filled while bank empty -> answered (0)
        self.assertEqual(
            run_q_js(
                auto.UNANSWERED_TEST_DOM_JS,
                lists={
                    ".dndZone": [
                        {"dg_name": "TTpTablePlaceHolder", "innerText": "word1"},
                        {"dg_name": "0", "childrenBySelector": {".dnditem": {"innerText": "word2"}}},
                        {"dg_name": "1", "innerText": ""},
                    ]
                },
            )["res"],
            1,
        )
        self.assertEqual(
            run_q_js(
                auto.UNANSWERED_TEST_DOM_JS,
                lists={
                    ".dndZone": [
                        {"dg_name": "TTpTablePlaceHolder", "innerText": ""},
                        {"id": "TTpTablePlaceHolder", "innerText": ""},
                        {"dg_name": "0", "childrenBySelector": {".dnditem": {"innerText": ""}}},
                        {"dg_name": "1", "innerText": "word2"},
                    ]
                },
            )["res"],
            0,
        )

    def test_solver_failure_outputs_like_fitb_nodata_never_pass_unanswered_or_submit(self):
        failures = [
            "fitb: nodata",
            "open: nodata",
            "open: 0",
            "drag: EMPTY-MAP",
            "drag: 0=ok 1=FAIL",
            "sequence: EMPTY-ORDER",
            "cloze: no-targets",
            "lcloze: none",
            "select_text: no spans",
            "mcq:",
            "speak: blocked",
        ]
        for bad in failures:
            tab = Mock()
            tab.js.return_value = ""
            with patch.object(auto.solver, "dom_transcript", return_value=""), \
                 patch.object(auto.solver, "do_task", return_value=bad) as do_mock, \
                 patch.object(auto, "q", return_value=0), \
                 patch.object(auto, "st", return_value={"total": "10", "counter": "10"}), \
                 patch.object(auto, "click") as click_mock, \
                 patch.object(auto.time, "sleep"):
                res = auto.handle_test(tab, "Question 10")
            self.assertEqual(do_mock.call_count, 2, bad)
            self.assertEqual(res, f"test-unanswered: {bad}", bad)
            click_mock.assert_not_called()

    def test_submit_gate_fails_closed_when_assessment_or_lesson_data_is_missing(self):
        # TestArea URL with missing Angular probe -> 'unknown', NOT 'ready'
        out_no_ng = run_node_js(
            auto.ASSESSMENT_SUBMIT_STATE_JS,
            url="https://ed22.engdis.com/Runtime/TestArea.html",
        )
        self.assertEqual(out_no_ng["res"], "unknown")

        # Empty _lessonsList.Children -> 'unknown'
        app_empty = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {"_lessonsList": {"Children": []}},
                }
            }
        }
        out_empty = run_node_js(auto.ASSESSMENT_SUBMIT_STATE_JS, nodes={"app": app_empty})
        self.assertEqual(out_empty["res"], "unknown")

        # handle_test blocks submission when completeness is unknown
        tab = Mock()
        tab.js.side_effect = lambda expr: (
            True if expr == auto.IS_TEST_AREA_JS else ("unknown" if expr == auto.ASSESSMENT_SUBMIT_STATE_JS else "")
        )
        with patch.object(auto.solver, "dom_transcript", return_value=""), \
             patch.object(auto.solver, "do_task", return_value="mcq: C"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "st", return_value={"total": "30", "counter": "30"}), \
             patch.object(auto, "click") as click_mock:
            res = auto.handle_test(tab, "Question 30")
        self.assertEqual(res, "test-unanswered: completeness-unknown")
        click_mock.assert_not_called()

    def test_submit_gate_catches_incomplete_task_when_node_ids_are_undefined(self):
        # Regression: undefined !== undefined previously skipped every task lacking NodeId
        app_no_ids = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "_lessonsList": {
                            "SelectedIndex": 0,
                            "Children": [{"Name": "Section 1", "IsDone": False, "Progress": 0}],
                        },
                        "_tasksList": {
                            "SelectedIndex": 1,
                            "Children": [
                                {"IsDone": False, "Progress": 0},  # Q1 unanswered, no NodeId
                                {"IsDone": False, "Progress": 0},  # Q2 current
                            ],
                        },
                    },
                }
            }
        }
        out = run_node_js(auto.ASSESSMENT_SUBMIT_STATE_JS, nodes={"app": app_no_ids})
        self.assertEqual(out["res"], "incomplete")

    def test_section_submission_scopes_to_current_section_and_never_jumps_ahead(self):
        # Section 1 finished while Section 2 & Section 3 are still incomplete -> 'ready', zero selectedChanged calls
        for lessons in [
            [
                {"NodeId": "S1", "Name": "Section 1: Listening", "IsDone": False, "Progress": 0},
                {"NodeId": "S2", "Name": "Section 2: Reading", "IsDone": False, "Progress": 0},
                {"NodeId": "S3", "Name": "Section 3: Grammar", "IsDone": False, "Progress": 0},
            ],
            [
                {"NodeId": "L", "Name": "Listening", "IsDone": False, "Progress": 0},
                {"NodeId": "R", "Name": "Reading", "IsDone": False, "Progress": 0},
            ],
        ]:
            app_sec1 = {
                "__comp": {
                    "componentInstance": {
                        "isTestEnv": True,
                        "navigationService": {
                            "__recordSelectedChanged": True,
                            "_lessonsList": {"SelectedIndex": 0, "Children": lessons},
                            "_tasksList": {
                                "SelectedIndex": 1,
                                "Children": [
                                    {"NodeId": "Q1", "IsDone": True, "Progress": 1},
                                    {"NodeId": "Q2", "IsDone": False, "Progress": 0},
                                ],
                            },
                        },
                    }
                }
            }
            out = run_node_js(auto.ASSESSMENT_SUBMIT_STATE_JS, nodes={"app": app_sec1})
            self.assertEqual(out["res"], "ready")
            self.assertEqual(out["selectedChanged"], [])

    def test_multipart_section_returns_next_part_mid_section_and_blocks_if_earlier_part_incomplete(self):
        # At end of Listening 1 NTE when Listening 2 NTE follows in same section -> 'next-part'
        app_mid = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_lessonsList": {
                            "SelectedIndex": 0,
                            "Children": [
                                {"NodeId": "L1", "Name": "Listening 1 NTE", "IsDone": False, "Progress": 0},
                                {"NodeId": "L2", "Name": "Listening 2 NTE", "IsDone": False, "Progress": 0},
                                {"NodeId": "R1", "Name": "Reading 1 NTE", "IsDone": False, "Progress": 0},
                            ],
                        },
                        "_tasksList": {
                            "SelectedIndex": 0,
                            "Children": [{"NodeId": "Q10", "IsDone": True, "Progress": 1}],
                        },
                    },
                }
            }
        }
        out_mid = run_node_js(auto.ASSESSMENT_SUBMIT_STATE_JS, nodes={"app": app_mid})
        self.assertEqual(out_mid["res"], "next-part")
        self.assertEqual(out_mid["selectedChanged"], [])

        # At Listening 2 NTE (end of Listening section), if Listening 1 NTE was skipped -> 'incomplete'
        app_skipped = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "__recordSelectedChanged": True,
                        "_lessonsList": {
                            "SelectedIndex": 1,
                            "Children": [
                                {"NodeId": "L1", "Name": "Listening 1 NTE", "IsDone": False, "Progress": 0},
                                {"NodeId": "L2", "Name": "Listening 2 NTE", "IsDone": False, "Progress": 0},
                                {"NodeId": "R1", "Name": "Reading 1 NTE", "IsDone": False, "Progress": 0},
                            ],
                        },
                        "_tasksList": {
                            "SelectedIndex": 0,
                            "Children": [{"NodeId": "Q20", "IsDone": True, "Progress": 1}],
                        },
                    },
                }
            }
        }
        out_skipped = run_node_js(auto.ASSESSMENT_SUBMIT_STATE_JS, nodes={"app": app_skipped})
        self.assertEqual(out_skipped["res"], "incomplete")
        self.assertEqual(out_skipped["selectedChanged"], [])

    def test_handle_test_submits_with_testarea_selector_without_manufacturing_progress(self):
        executed_scripts = []

        def fake_js(expr):
            executed_scripts.append(expr)
            if expr == auto.IS_TEST_AREA_JS:
                return True
            if expr == auto.ASSESSMENT_SUBMIT_STATE_JS:
                return "ready"
            if expr == auto.NAV_STATE_SIG_JS:
                return "sig-before"
            if expr == auto.IS_FINAL_ASSESSMENT_COMPLETE_JS:
                return True
            if "document.body?.innerText" in expr:
                return "You have completed the Final Test.\nYour score is 100%."
            return ""

        tab = Mock()
        tab.js.side_effect = fake_js
        with patch.object(auto.solver, "dom_transcript", return_value=""), \
             patch.object(auto.solver, "do_task", return_value="mcq: D"), \
             patch.object(auto, "q", side_effect=lambda _t, expr: 0 if "mcqUnanswered" in expr else 1), \
             patch.object(auto, "st", return_value={"total": "30", "counter": "30"}), \
             patch.object(auto, "click") as click_mock, \
             patch.object(auto.poll, "wait_until", side_effect=[1, "You have completed the Final Test.\nYour score is 100%."]), \
             patch.object(auto.time, "sleep"):
            res = auto.handle_test(tab, "Question 30")

        self.assertTrue(res.startswith("test-submit-final"), res)
        self.assertIn("Your score is 100%.", res)
        clicked_selectors = [c.args[1] for c in click_mock.call_args_list]
        self.assertTrue(any("#learning__tasksNav_submitTest" in s for s in clicked_selectors))
        for script in executed_scripts:
            self.assertNotIn("curStep.Progress = 1", script)
            self.assertNotIn("setProgressAsync", script)


@unittest.skipUnless(NODE_BIN, "node required for JS evaluation tests")
class AssessmentScoreAndSectionTransitionTests(unittest.TestCase):
    def test_failed_submission_stops_immediately_without_repeating_or_forging_progress(self):
        executed = []

        class Tab:
            def js(self, expr):
                executed.append(expr)
                if expr in (auto.IS_TEST_JS, auto.IS_TEST_AREA_JS, auto.IS_LIVE_ASSESSMENT_SESSION_JS):
                    return True
                if expr == auto.ASSESSMENT_SUBMIT_STATE_JS:
                    return "ready"
                if expr == auto.NAV_STATE_SIG_JS:
                    return "stuck-on-q30"  # never changes after submit click!
                if expr == auto.IS_FINAL_ASSESSMENT_COMPLETE_JS:
                    return False
                if "document.body?.innerText" in expr:
                    return "Question 30 of 30"
                return ""

        state = {
            "unit": "",
            "lesson": "",
            "step": "Listening 3:103",
            "counter": "30",
            "total": "30",
            "body": "Question 30 of 30",
        }
        with patch.object(auto.edlib, "tab", return_value=Tab()), \
             patch.object(auto, "st", return_value=state), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto.solver, "source_text", return_value={"resource": "", "body": ""}), \
             patch.object(auto.solver, "dom_transcript", return_value=""), \
             patch.object(auto.solver, "do_task", return_value="mcq: A"), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "click") as click_mock, \
             patch.object(auto.poll, "wait_until", side_effect=[1, 0, ""]), \
             patch.object(auto.time, "sleep"), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                auto.main(max_iter=10)

        # Must exit rc=6 on the first unverified submission, not loop max_iter times
        self.assertEqual(ctx.exception.code, 6)
        self.assertEqual(click_mock.call_count, 1)
        for script in executed:
            self.assertNotIn("curStep.Progress = 1", script)

    def test_course_lesson_unconfirmed_submit_does_not_manufacture_progress(self):
        executed = []
        tab = Mock()
        tab.js.side_effect = lambda expr: (executed.append(expr) or "")
        with patch.object(auto.solver, "dom_transcript", return_value=""), \
             patch.object(auto.solver, "do_task", return_value="mcq: A"), \
             patch.object(auto, "q", return_value=0), \
             patch.object(auto, "st", return_value={"total": "5", "counter": "5"}), \
             patch.object(auto, "click"), \
             patch.object(auto.poll, "wait_until", side_effect=[0, ""]), \
             patch.object(auto.time, "sleep"):
            res = auto.handle_test(tab, "Question 5")

        self.assertEqual(res, "test-submit []")
        for script in executed:
            self.assertNotIn("curStep.Progress = 1", script)

    def test_section_score_and_question_text_are_not_mistaken_for_final_completion(self):
        # 1. Section 1 summary text -> NOT final
        sec_body = "Section 1 Complete.\nYour score is 90%."
        tab_sec = Mock()
        tab_sec.js.return_value = True
        self.assertFalse(auto.is_final_assessment_complete(tab_sec, sec_body))

        # 2. Question prompt containing 'your score is' while MCQ widget or task counter exists -> NOT final
        out_with_widget = run_node_js(
            auto.IS_FINAL_ASSESSMENT_COMPLETE_JS,
            lists={".prMCQ__qaSet": [{}]},
            url="https://ed22.engdis.com/Runtime/TestArea.html",
            body="If your score is below 70%, review the passage.",
        )["res"]
        self.assertFalse(out_with_widget)

        # 3. Remaining incomplete section in _unitsList -> NOT final
        app_remaining = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "_unitsList": {
                            "SelectedIndex": 0,
                            "Children": [
                                {"NodeId": "U1", "IsDone": True, "Progress": 1},
                                {"NodeId": "U2", "IsDone": False, "Progress": 0},
                            ],
                        }
                    },
                }
            }
        }
        out_remaining = run_node_js(
            auto.IS_FINAL_ASSESSMENT_COMPLETE_JS,
            nodes={"app": app_remaining},
            url="https://ed22.engdis.com/Runtime/TestArea.html",
            body="Your score is 90%.",
        )["res"]
        self.assertFalse(out_remaining)

        # 4. Genuine final completion screen (no widgets, no counter, all sections done) -> True
        app_done = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "_unitsList": {
                            "SelectedIndex": 1,
                            "Children": [
                                {"NodeId": "U1", "IsDone": True, "Progress": 1},
                                {"NodeId": "U2", "IsDone": True, "Progress": 1},
                            ],
                        }
                    },
                }
            }
        }
        out_done = run_node_js(
            auto.IS_FINAL_ASSESSMENT_COMPLETE_JS,
            nodes={"app": app_done},
            url="https://ed22.engdis.com/Runtime/TestArea.html",
            body="You have completed the Placement Final Test.\nYour score is 100%.",
        )["res"]
        self.assertTrue(out_done)

    def test_final_completion_predicate_fails_closed_when_nav_or_lists_missing_or_empty(self):
        # 1. Exact review reproduction: TestArea.html + score body + NO app/navigation node -> False
        for body in (
            "Your score is 90%.",
            "You have completed the Placement Final Test.\nYour score is 90%.",
        ):
            out_no_app = run_node_js(
                auto.IS_FINAL_ASSESSMENT_COMPLETE_JS,
                url="https://ed22.engdis.com/Runtime/TestArea.html",
                body=body,
            )["res"]
            self.assertFalse(out_no_app, body)

            tab_no_app = Mock()
            tab_no_app.js.side_effect = lambda expr, _b=body: (
                run_node_js(expr, url="https://ed22.engdis.com/Runtime/TestArea.html", body=_b)["res"]
            )
            self.assertFalse(auto.is_final_assessment_complete(tab_no_app, body))

        # 2. Empty navigationService or empty _unitsList / _lessonsList Children -> False
        for nav in (
            {},
            {"_unitsList": {"Children": []}},
            {"_lessonsList": {"Children": []}},
            {"_unitsList": {"Children": []}, "_lessonsList": {"Children": []}},
            {
                "_unitsList": {"SelectedIndex": 0, "Children": [{"NodeId": "U1", "IsDone": True, "Progress": 1}]},
                "_lessonsList": {"Children": []},
            },
        ):
            app_empty = {"__comp": {"componentInstance": {"isTestEnv": True, "navigationService": nav}}}
            out_empty = run_node_js(
                auto.IS_FINAL_ASSESSMENT_COMPLETE_JS,
                nodes={"app": app_empty},
                url="https://ed22.engdis.com/Runtime/TestArea.html",
                body="You have completed the Final Test.\nYour score is 90%.",
            )["res"]
            self.assertFalse(out_empty, f"expected False for nav={nav}")

        # 3. Single-item list that is incomplete and lacks explicit completion banner -> False
        app_single_inc = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "_unitsList": {
                            "SelectedIndex": 0,
                            "Children": [{"NodeId": "U1", "IsDone": False, "Progress": 0}],
                        }
                    },
                }
            }
        }
        out_single_inc = run_node_js(
            auto.IS_FINAL_ASSESSMENT_COMPLETE_JS,
            nodes={"app": app_single_inc},
            url="https://ed22.engdis.com/Runtime/TestArea.html",
            body="Your score is 90%.",
        )["res"]
        self.assertFalse(out_single_inc)

        # 4. Multi-item list with missing SelectedIndex (-1) and incomplete second unit -> False
        app_unknown_idx = {
            "__comp": {
                "componentInstance": {
                    "isTestEnv": True,
                    "navigationService": {
                        "_unitsList": {
                            "Children": [
                                {"NodeId": "U1", "IsDone": True, "Progress": 1},
                                {"NodeId": "U2", "IsDone": False, "Progress": 0},
                            ]
                        }
                    },
                }
            }
        }
        out_unknown_idx = run_node_js(
            auto.IS_FINAL_ASSESSMENT_COMPLETE_JS,
            nodes={"app": app_unknown_idx},
            url="https://ed22.engdis.com/Runtime/TestArea.html",
            body="You have completed the Final Test.\nYour score is 90%.",
        )["res"]
        self.assertFalse(out_unknown_idx)

    def test_main_fails_closed_on_testarea_score_screen_when_nav_state_is_missing(self):
        body = "Your score is 90%."

        class Tab:
            def js(self, expr):
                if expr == auto.IS_LIVE_ASSESSMENT_SESSION_JS:
                    return True
                return run_node_js(
                    expr,
                    url="https://ed22.engdis.com/Runtime/TestArea.html",
                    body=body,
                )["res"]

        state = {
            "unit": "",
            "lesson": "",
            "step": "",
            "counter": None,
            "total": None,
            "body": body,
        }
        err = io.StringIO()
        with patch.object(auto.edlib, "tab", return_value=Tab()), \
             patch.object(auto, "st", return_value=state), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto.solver, "source_text", return_value={"resource": "", "body": body}), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto, "q", return_value=0), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                auto.main(max_iter=3)

        self.assertEqual(ctx.exception.code, 6)
        self.assertIn("lacks verified final completion state", err.getvalue())

    def test_main_exits_zero_on_verified_final_testarea_score_screen(self):
        class Tab:
            def js(self, expr):
                if expr in (
                    auto.IS_TEST_AREA_JS,
                    auto.IS_LIVE_ASSESSMENT_SESSION_JS,
                    auto.IS_FINAL_ASSESSMENT_COMPLETE_JS,
                ):
                    return True
                return 0

        state = {
            "unit": "",
            "lesson": "",
            "step": "Result",
            "counter": None,
            "total": None,
            "body": "You have completed the Final Test.\nYour score is 100%.",
        }
        buf = io.StringIO()
        with patch.object(auto.edlib, "tab", return_value=Tab()), \
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
        self.assertIn("Your score is 100%.", buf.getvalue())

    def test_main_continues_to_next_section_after_verified_section_submit_and_exits_after_final(self):
        nav_sigs = iter(["sec1-q30", "sec2-q1", "sec2-q20"])
        post_bodies = iter([
            "Section 2: Reading Comprehension",
            "You have completed the Final Test.\nYour score is 100%.",
        ])
        final_flags = iter([False, True])

        class Tab:
            def js(self, expr):
                if expr in (auto.IS_TEST_JS, auto.IS_TEST_AREA_JS, auto.IS_LIVE_ASSESSMENT_SESSION_JS):
                    return True
                if expr == auto.IS_FINAL_ASSESSMENT_COMPLETE_JS:
                    return next(final_flags, True)
                if expr == auto.NAV_STATE_SIG_JS:
                    return next(nav_sigs, "final")
                if "document.body?.innerText" in expr:
                    return next(post_bodies, "")
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
            "test-submit-section",
            "test-submit-final ['Your score is 100%.']",
        ])
        buf = io.StringIO()
        with patch.object(auto.edlib, "tab", return_value=Tab()), \
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
        self.assertIn("Your score is 100%.", buf.getvalue())

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
