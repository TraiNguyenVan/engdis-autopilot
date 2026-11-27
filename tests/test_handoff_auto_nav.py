"""Behavioural pins for the navigation / test-flow changes merged from the
upstream handoff: explore-aware classification, the taskspager counter
fallback, the reordered advance() ladder, the 8s question-widget wait and the
Send-to-Teacher speaking completion path.

The tab is always a Mock. Where the new behaviour lives inside a JS expression
(counter fallback, taskspager emit payload, classification guards) the exact
expression captured from auto.py is executed by node against a stub DOM, so the
assertions are about behaviour rather than string formatting.
"""
import json
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

import auto


NODE_BIN = shutil.which("node")

BEFORE = "1|0|0|n1"
AFTER = "1|0|0|n2"

PRELUDE = r"""
globalThis.__payloads = [];
const RAW = __DATA__;
function mk(p) {
  const o = Object.assign({innerText: '', offsetWidth: 0, offsetHeight: 0, innerHTML: '', parentElement: null}, p);
  o.classList = {contains: (c) => Array.isArray(o.__classes) && o.__classes.indexOf(c) >= 0};
  o.click = () => {};
  o.remove = () => {};
  o.style = {};
  return o;
}
const NODES = {};
Object.keys(RAW.nodes || {}).forEach((k) => { NODES[k] = mk(RAW.nodes[k]); });
const LISTS = {};
Object.keys(RAW.lists || {}).forEach((k) => { LISTS[k] = (RAW.lists[k] || []).map(mk); });
const PROBE = new Map();
Object.keys(RAW.nodes || {}).forEach((k) => {
  const raw = RAW.nodes[k];
  if (raw && raw.__comp !== undefined) PROBE.set(NODES[k], raw.__comp);
});
Object.keys(RAW.lists || {}).forEach((k) => {
  (RAW.lists[k] || []).forEach((raw, i) => {
    if (raw && raw.__comp !== undefined) PROBE.set(LISTS[k][i], raw.__comp);
  });
});
const ng = {probe: (e) => PROBE.get(e) || null};
const document = {
  querySelector: (s) => NODES[s] || null,
  querySelectorAll: (s) => LISTS[s] || [],
  body: {innerText: ''}
};
const window = {ng: ng};
"""


def eval_js(expr, nodes=None, lists=None, extra_js=""):
    """Run one JS expression from auto.py in node against a stub DOM."""
    assert NODE_BIN
    script = (
        PRELUDE.replace("__DATA__", json.dumps({"nodes": nodes or {}, "lists": lists or {}}))
        + "\n" + extra_js
        + "\nconst __v = (" + expr + ");"
        + "\nprocess.stdout.write(JSON.stringify({v: __v === undefined ? null : __v, payloads: globalThis.__payloads}));"
    )
    proc = subprocess.run(
        [NODE_BIN, "-e", script], capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        raise AssertionError("node eval failed:\n" + (proc.stderr or proc.stdout))
    return json.loads(proc.stdout)


def pager_js(selected_node_id, children=("i0", "n2", "n3")):
    """Stub the ed-la-taskspager component, recording change.emit payloads."""
    child_js = ", ".join("{NodeId: %s}" % json.dumps(c) for c in children)
    return """
const __pager = NODES['ed-la-taskspager'];
const __parent = {};
__pager.parentElement = __parent;
PROBE.set(__parent, {componentInstance: {
  tasksNodes: {Children: [%s], SelectedNode: {NodeId: %s}},
  change: {emit: (p) => { globalThis.__payloads.push(p); }}
}});
""" % (child_js, json.dumps(selected_node_id))


def st_exprs():
    """Capture the six js expressions st() sends, in dictionary order."""
    tab = Mock()
    tab.js.return_value = None
    auto.st(tab)
    return [call.args[0] for call in tab.js.call_args_list]


@unittest.skipUnless(NODE_BIN, "node not available for JS behaviour checks")
class ClassificationTests(unittest.TestCase):
    def _classify(self, node_name, dropdown_text):
        dds = [
            {"innerText": "Unit 1\nLesson"},
            {"innerText": dropdown_text, "__comp": {"componentInstance": {
                "dropDownListObj": {"SelectedNode": {"Name": node_name}}}}},
        ]
        return eval_js(auto.IS_TEST_JS, lists={"ed-la-dropdownlist": dds})["v"]

    def test_selected_explore_node_is_not_a_test(self):
        self.assertFalse(self._classify("Explore", "Explore"))

    def test_explore_title_without_test_node_name_is_not_a_test(self):
        self.assertFalse(self._classify("Step 1", "Explore the scene\nPlay the audio"))

    def test_practice_title_wins_over_test_keyword_in_title(self):
        # The dropdown title contains both words; the explore/practice guard is
        # evaluated before the trailing /test|review/ test, so it must win.
        self.assertFalse(self._classify("Step 3", "Practice Test"))

    def test_test_and_review_nodes_are_tests(self):
        self.assertTrue(self._classify("Test", "Unit 1 Test"))
        self.assertTrue(self._classify("Review", "Review"))

    def test_is_test_js_still_carries_both_explore_guards(self):
        self.assertIn("'explore'", auto.IS_TEST_JS)
        guard = auto.IS_TEST_JS.index("/explore|practice/")
        final = auto.IS_TEST_JS.index("return /test|review/")
        self.assertLess(guard, final)


@unittest.skipUnless(NODE_BIN, "node not available for JS behaviour checks")
class CounterFallbackTests(unittest.TestCase):
    def setUp(self):
        self.exprs = st_exprs()
        self.assertEqual(len(self.exprs), 6, "st() js call order changed")
        self.counter_js, self.total_js = self.exprs[2], self.exprs[3]
        self.assertIn("ed-la-taskspager", self.counter_js)
        self.assertIn("_tasksList", self.counter_js)

    def test_intro_node_reports_intro_and_total_is_children_minus_one(self):
        out = eval_js(
            self.counter_js,
            nodes={"ed-la-taskspager": {}},
            extra_js=pager_js("i0", ("i0", "n2", "n3", "n4")),
        )
        self.assertEqual(out["v"], "Intro")
        total = eval_js(
            self.total_js,
            nodes={"ed-la-taskspager": {}},
            extra_js=pager_js("i0", ("i0", "n2", "n3", "n4")),
        )["v"]
        self.assertEqual(total, "3")

    def test_selected_child_reports_its_index(self):
        out = eval_js(
            self.counter_js,
            nodes={"ed-la-taskspager": {}},
            extra_js=pager_js("n3", ("i0", "n2", "n3")),
        )
        self.assertEqual(out["v"], "2")

    def test_dom_counter_still_wins_when_present(self):
        counter = eval_js(
            self.counter_js,
            nodes={
                ".learning__taskNavPCCurrentTask": {"innerText": "2"},
                "ed-la-taskspager": {},
            },
            extra_js=pager_js("i0"),
        )["v"]
        self.assertEqual(counter, "2")
        total = eval_js(
            self.total_js,
            nodes={
                ".learning__taskNavPCTotalTasks": {"innerText": "5"},
                "ed-la-taskspager": {},
            },
            extra_js=pager_js("i0"),
        )["v"]
        self.assertEqual(total, "5")

    def test_navigation_tasks_list_is_the_last_counter_fallback(self):
        app = {"__comp": {"componentInstance": {"navigationService": {"_tasksList": {
            "SelectedIndex": 2,
            "Children": [{"NodeId": "a"}, {"NodeId": "b"}, {"NodeId": "c"}],
        }}}}}
        counter = eval_js(self.counter_js, nodes={"app": app})["v"]
        total = eval_js(self.total_js, nodes={"app": app})["v"]
        self.assertEqual(counter, "3")
        self.assertEqual(total, "3")


class AdvanceOrderTests(unittest.TestCase):
    def _run(self, waits, clicks=(1,)):
        tab = Mock()
        q_mock = Mock(return_value=BEFORE)
        click_mock = Mock(side_effect=list(clicks))
        with patch.object(auto, "q", q_mock), \
             patch.object(auto, "click", click_mock), \
             patch.object(auto, "poll") as poll_mock:
            poll_mock.wait_until.side_effect = list(waits)
            result = auto.advance(tab, tries=3)
        return result, tab, q_mock, click_mock, poll_mock

    def test_native_nav_runs_before_the_taskspager_emit(self):
        result, tab, _, click_mock, _ = self._run([BEFORE, AFTER])
        self.assertTrue(result)
        exprs = [call.args[0] for call in tab.js.call_args_list]
        self.assertEqual(len(exprs), 2)
        self.assertIn("tryGoPrevNext(1)", exprs[0])
        self.assertIn("comp.change.emit", exprs[1])
        self.assertLess(exprs.index(exprs[0]), exprs.index(exprs[1]))
        click_mock.assert_not_called()

    def test_each_nav_attempt_polls_for_two_seconds(self):
        _, _, _, _, poll_mock = self._run([BEFORE, AFTER])
        self.assertGreaterEqual(poll_mock.wait_until.call_count, 1)
        for call in poll_mock.wait_until.call_args_list:
            self.assertEqual(call.kwargs.get("timeout"), 2.0)

    def test_advance_stops_polling_once_the_native_nav_moved(self):
        result, tab, _, _, poll_mock = self._run([AFTER])
        self.assertTrue(result)
        self.assertEqual(poll_mock.wait_until.call_count, 1)
        self.assertEqual(len(tab.js.call_args_list), 1)  # no taskspager emit needed

    def test_falls_back_to_standard_next_buttons(self):
        result, _, _, click_mock, poll_mock = self._run(
            [BEFORE, BEFORE, AFTER], clicks=(0, 0, 1)
        )
        self.assertTrue(result)
        self.assertEqual(poll_mock.wait_until.call_count, 3)
        selectors = [call.args[1] for call in click_mock.call_args_list]
        self.assertEqual(
            selectors,
            [
                "#learning__nextItem a, .learning__nextItemLink, .learning__taskNext a, "
                ".tasksBtnext, a.tasksBtnext",
                ".learning__taskNext",
                ".learning__taskNavPagerBtn--next",
            ],
        )
        self.assertIn("a.tasksBtnext", selectors[0])

    def test_gives_up_after_the_retry_budget(self):
        result, _, _, click_mock, poll_mock = self._run(
            [BEFORE] * 9, clicks=(1, 1, 1)
        )
        self.assertFalse(result)
        # three attempts, each probing the counter after nav, emit and click
        self.assertEqual(poll_mock.wait_until.call_count, 9)
        self.assertEqual(click_mock.call_count, 3)

    @unittest.skipUnless(NODE_BIN, "node not available for JS behaviour checks")
    def test_taskspager_emit_advances_to_the_next_child_of_type_five(self):
        _, tab, _, _, _ = self._run([BEFORE, AFTER])
        emit_js = tab.js.call_args_list[1].args[0]
        out = eval_js(
            emit_js,
            nodes={"ed-la-taskspager": {}},
            extra_js=pager_js("i0", ("i0", "n2", "n3")),
        )
        self.assertEqual(out["v"], 1)
        self.assertEqual(
            out["payloads"],
            [{"nodeId": "n2", "courseNodeType": 5, "selectedIndex": 1}],
        )

        last = eval_js(
            emit_js,
            nodes={"ed-la-taskspager": {}},
            extra_js=pager_js("n3", ("i0", "n2", "n3")),
        )
        self.assertEqual(last["v"], 0)
        self.assertEqual(last["payloads"], [])

    @unittest.skipUnless(NODE_BIN, "node not available for JS behaviour checks")
    def test_change_signature_includes_the_taskspager_selected_node(self):
        _, _, q_mock, _, _ = self._run([BEFORE, AFTER])
        cur_js = q_mock.call_args_list[0].args[1]
        self.assertIn("tasksNodes", cur_js)
        self.assertIn("SelectedNode", cur_js)
        out = eval_js(
            "(() => {" + cur_js + "})()",
            nodes={"ed-la-taskspager": {}},
            extra_js=pager_js("n2", ("i0", "n2", "n3")),
        )
        self.assertTrue(out["v"].endswith("|n2"), out["v"])


class SpeakingSendTests(unittest.TestCase):
    def test_send_to_teacher_click_reports_sent_without_forging_progress(self):
        tab = Mock()
        tab.js.return_value = 1  # Send-to-Teacher clicked
        with patch.object(auto, "q", return_value=0), \
             patch.object(auto, "click_text", return_value=0) as click_text_mock, \
             patch.object(auto.time, "sleep"):
            result = auto.handle_speaking(tab, "")

        self.assertEqual(result, "speak: sent")
        sent_js = tab.js.call_args_list[0].args[0]
        for selector in (".openSpeech__SentTTBtn", ".openSpeech__btnSend", "[class*=\"SentTTBtn\"]"):
            self.assertIn(selector, sent_js)
        self.assertIn("disabled", sent_js)
        self.assertEqual(len(tab.js.call_args_list), 1)  # no Start / bridge attempt
        click_text_mock.assert_not_called()
        for call in tab.js.call_args_list:
            self.assertNotIn("setProgress", call.args[0])

    def test_disabled_send_button_falls_through_to_recording(self):
        tab = Mock()
        tab.js.side_effect = [0, 1]  # send button disabled, then Start clicked
        with patch.object(auto, "q", return_value=0), \
             patch.object(auto, "click_text", return_value=0), \
             patch.object(auto.time, "sleep"):
            result = auto.handle_speaking(tab, "")

        self.assertEqual(result, "speak: clicked")
        for call in tab.js.call_args_list:
            self.assertNotIn("setProgress", call.args[0])


class MainTestFlowTests(unittest.TestCase):
    """main(): wait for a real question widget, and auto-start the test intro."""

    def _run_one_iteration(self, tab, events):
        status = {"step": "Step 4: Test", "lesson": None, "counter": "1",
                  "total": "2", "body": "Question 1 of 2", "unit": ""}

        def wait_until(read, pred, **kwargs):
            events.append(("wait", kwargs.get("timeout")))
            read()  # let the read expression reach the mocked q()
            return 1

        def source_text(_t):
            events.append("source")
            return {"resource": "", "body": "Question 1 of 2"}

        def handle_test(*_a, **_k):
            events.append("test")
            return "test-submit"

        with patch.object(auto, "GuardedTab", new=lambda tab, assessment_mode: tab), \
             patch.object(auto, "edlib") as edlib_mock, \
             patch.object(auto, "login") as login_mock, \
             patch.object(auto, "st", return_value=status), \
             patch.object(auto, "update_live_status"), \
             patch.object(auto, "require_lesson_complete"), \
             patch.object(auto, "q", return_value=0) as q_mock, \
             patch.object(auto, "poll") as poll_mock, \
             patch.object(auto, "handle_test", side_effect=handle_test), \
             patch.object(auto.solver, "source_text", side_effect=source_text), \
             patch.object(auto.solver, "neutralize"), \
             patch.object(auto.solver, "set_next_step", return_value="next"), \
             patch.object(auto.time, "sleep"), \
             patch.dict("os.environ", {"ED_TARGET_STEP": "", "ED_UNATTENDED": "",
                                       "ED_LESSON_LOCK": ""}):
            edlib_mock.tab.return_value = tab
            login_mock.ensure_login.return_value = True
            poll_mock.wait_until.side_effect = wait_until
            auto.main(max_iter=1)
        return q_mock, poll_mock

    def test_main_waits_for_question_widget_before_solving(self):
        class Tab:
            def js(self, expr):
                if expr == auto.IS_TEST_JS:
                    return 1
                if "const idx = children.findIndex" in expr:
                    return None
                return 0

        events = []
        q_mock, _ = self._run_one_iteration(Tab(), events)

        self.assertIn("source", events)
        self.assertIn("test", events)
        self.assertLess(events.index(("wait", 8.0)), events.index("source"))
        self.assertLess(events.index("source"), events.index("test"))
        widget_js = [c.args[1] for c in q_mock.call_args_list]
        self.assertTrue(any("ed-la-mcq" in expr and ".prMCQ__qaSet" in expr for expr in widget_js))

    def test_main_autostarts_test_from_the_intro_node(self):
        class Tab:
            def __init__(self):
                self.exprs = []

            def js(self, expr):
                self.exprs.append(expr)
                if "comp.isStepTest" in expr:
                    return 1  # test intro node selected
                return 0

        tab = Tab()
        events = []
        _, poll_mock = self._run_one_iteration(tab, events)

        self.assertNotIn("test", events)
        self.assertNotIn("source", events)
        intro_js = [expr for expr in tab.exprs if "comp.isStepTest" in expr]
        self.assertEqual(len(intro_js), 1)
        self.assertIn("onTaskClick", intro_js[0])
        self.assertIn("Children[1]", intro_js[0])
        self.assertEqual(poll_mock.wait_until.call_count, 0)


if __name__ == "__main__":
    unittest.main()
