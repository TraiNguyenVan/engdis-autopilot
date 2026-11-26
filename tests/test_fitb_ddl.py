"""Offline unit tests for FITB custom `.DDLOptions__selected` dropdown solving."""
import json
import re
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

import solver


class _FakeFITBTab:
    """Offline stateful simulation of multi-dropdown `.DDLOptions__selected` pages.

    Models:
    - Multiple `.DDLOptions__selected` widgets with configurable wrapper classes
      (`.DDLOptionsW`, `.prFITB__DDLOptionsW`, `.prFITB__qaItem`, `.prDDL__qaItem`, `.fitb-ddl`)
      or document-level portal menus (`scope="document"`).
    - Requiring `scrollIntoView({block: 'center'})` before clicking off-viewport
      dropdown triggers (`require_scroll=True`).
    - Stale open dropdown menus from earlier blanks staying in the DOM
      (`keep_first_menu_open=True` or `initial_stale_portal`).
    - Flaky option clicks that fail to update `.DDLOptions__selected` on attempt 0
      (`fail_pick_attempts`).
    """

    def __init__(
        self,
        questions,
        dropdowns,
        *,
        require_scroll=False,
        keep_first_menu_open=False,
        initial_stale_portal=None,
        fail_pick_attempts=None,
    ):
        self.questions = questions
        self.dropdowns = dropdowns
        self.require_scroll = require_scroll
        self.keep_first_menu_open = keep_first_menu_open
        self.stale_portal = list(initial_stale_portal) if initial_stale_portal else None
        self.fail_pick_attempts = dict(fail_pick_attempts or {})
        self.scroll_calls = []
        self.open_clicks = []
        self.pick_clicks = []
        self.mouse_dispatches = []
        self.scripts = []

    def _get_dd(self, idx):
        if 0 <= idx < len(self.dropdowns):
            return self.dropdowns[idx]
        return None

    def _visible_options(self, idx):
        dd = self._get_dd(idx)
        if not dd:
            return "nf", "none", []
        mode = dd.get("mode", "container")
        if mode == "container":
            if dd.get("open"):
                return "ok", "container", list(dd.get("dom_options", dd.get("options", [])))
            # Even if dropdown 0 still has visible items inside dropdown 0's container,
            # container scoping + owner exclusion prevents leaking dropdown 0's items here.
            return "ok", "none", []
        if mode == "document":
            if self.stale_portal is not None:
                return "ok", "document", list(self.stale_portal)
            if dd.get("open"):
                return "ok", "document", list(dd.get("dom_options", dd.get("options", [])))
            return "ok", "none", []
        return "ok", "none", []

    def js(self, script):
        self.scripts.append(script)

        # 1. practiceData extraction
        if "practiceData" in script and "answerLists" in script:
            if not self.questions:
                return None
            text = (
                self.questions[0].get("text", "")
                if len(self.questions) == 1
                else "\n".join(q.get("text", "") for q in self.questions if q.get("text"))
            )
            lists = [
                [a["txt"] for a in al.get("answers", [])]
                for q in self.questions
                for al in q.get("answerLists", [])
            ]
            return {"text": text, "lists": lists}

        # Extract target blank index from getTrigger(i)
        m_idx = re.search(r"getTrigger\((\d+)\)", script)
        if not m_idx:
            return None
        idx = int(m_idx.group(1))
        dd = self._get_dd(idx)

        # 2. Open trigger step
        if "closeOtherMenus(s," in script:
            if not dd:
                return {"status": "nf"}
            force_close = "closeOtherMenus(s, true)" in script
            if force_close:
                self.stale_portal = None
                for j, other in enumerate(self.dropdowns):
                    if j != idx:
                        other["open"] = False
            else:
                for j, other in enumerate(self.dropdowns):
                    if j != idx and not (j == 0 and self.keep_first_menu_open):
                        other["open"] = False

            if "scrollIntoView" in script and "block: 'center'" in script:
                dd["scrolled"] = True
                self.scroll_calls.append(idx)

            if "fireMouse(s)" in script and not re.search(r"if\s*\(\s*0\s*>\s*0\s*\)\s*fireMouse\(s\)", script):
                self.mouse_dispatches.append(("trigger", idx))

            self.open_clicks.append(idx)
            if not self.require_scroll or dd.get("scrolled"):
                dd["open"] = True
            return {"status": "ok", "selected": dd.get("selected", "")}

        # 3. Scoped options query step
        if "options: res.items.map(getOptText)" in script:
            status, scope, opts = self._visible_options(idx)
            if status == "nf":
                return {"status": "nf", "options": [], "scope": "none", "selected": ""}
            return {
                "status": "ok",
                "scope": scope,
                "selected": dd.get("selected", ""),
                "options": opts,
            }

        # 4. Option pick step
        if "const wantText =" in script:
            if not dd:
                return {"clicked": 0, "selected": ""}
            _status, _scope, opts = self._visible_options(idx)
            m_pick = re.search(r"res\.items\[(\d+)\]", script)
            m_want = re.search(r"const wantText = (\".*?\");", script)
            pick_idx = int(m_pick.group(1)) if m_pick else -1
            want_text = json.loads(m_want.group(1)) if m_want else ""
            chosen = None
            if 0 <= pick_idx < len(opts) and opts[pick_idx] == want_text:
                chosen = opts[pick_idx]
            elif want_text in opts:
                chosen = want_text
            elif 0 <= pick_idx < len(opts):
                chosen = opts[pick_idx]
            if chosen is None:
                return {"clicked": 0, "selected": dd.get("selected", "")}

            if not re.search(r"if\s*\(\s*0\s*>\s*0\s*\)\s*fireMouse\(pick\)", script):
                self.mouse_dispatches.append(("pick", idx, chosen))
            self.pick_clicks.append((idx, chosen))

            remaining_fails = self.fail_pick_attempts.get(idx, 0)
            if remaining_fails > 0:
                self.fail_pick_attempts[idx] = remaining_fails - 1
                if not (idx == 0 and self.keep_first_menu_open):
                    dd["open"] = False
                return {"clicked": 1, "selected": dd.get("selected", ""), "rect": None}

            dd["selected"] = chosen
            if not (idx == 0 and self.keep_first_menu_open):
                dd["open"] = False
            return {"clicked": 1, "selected": dd["selected"], "rect": None}

        # 5. Standalone selected-text re-read
        if "return getSelectedText(s);" in script:
            return dd.get("selected", "") if dd else ""

        return None


def _make_practice_question(text, option_lists):
    return {
        "text": text,
        "answerLists": [
            {"answers": [{"txt": opt} for opt in opts]}
            for opts in option_lists
        ],
    }


class FitbOptionMatcherTests(unittest.TestCase):
    def test_whitespace_case_quotes_and_punctuation_normalization(self):
        opts = ["doesn't", "don't", "didn't"]
        self.assertEqual(solver._match_ddl_option("  Don’t, \n", opts), 1)
        self.assertEqual(solver._match_ddl_option('1. "Don\'t."', opts), 1)

        phrase_opts = ["despite", "in spite of", "although"]
        self.assertEqual(solver._match_ddl_option("  IN   Spite\u00a0Of! ", phrase_opts), 1)

    def test_partial_substring_prefers_word_boundary_and_longest_option(self):
        articles = ["a", "an", "the"]
        self.assertEqual(solver._match_ddl_option("an engineer", articles), 1)
        self.assertEqual(solver._match_ddl_option("a doctor", articles), 0)

        phrases = ["in", "spite", "in spite of"]
        self.assertEqual(solver._match_ddl_option("in spite of the rain", phrases), 2)
        self.assertEqual(solver._match_ddl_option("spite of", ["despite", "in spite of", "although"]), 1)

    def test_empty_and_placeholder_items_never_match_unmatched_answer(self):
        opts = ["", "   ", "Select...", "Choose...", "large", "ceramic", "three"]
        self.assertIsNone(solver._match_ddl_option("however", opts))
        self.assertFalse(solver._ddl_selected_ok("", "ceramic"))
        self.assertFalse(solver._ddl_selected_ok("Select...", "ceramic"))
        self.assertTrue(solver._ddl_selected_ok("ceramic \u25be", "ceramic"))


class FitbMultiDropdownSolverTests(unittest.TestCase):
    def test_multi_dropdown_scrolls_into_view_and_ignores_earlier_open_menu(self):
        """Reproduces Advanced 2 Final Test Use of English multi-DDL `noopt` bug."""
        option_lists = [
            ["large", "ceramic", "three"],
            ["which", "who", "whose"],
            ["had left", "has left", "leaves"],
            ["however", "although", "despite"],
        ]
        tab = _FakeFITBTab(
            questions=[_make_practice_question("1 __ 2 __ 3 __ 4 __", option_lists)],
            dropdowns=[{"options": opts, "selected": ""} for opts in option_lists],
            require_scroll=True,
            keep_first_menu_open=True,
        )
        llm_answers = {"1": "large", "2": "which", "3": "had left", "4": "however"}
        with patch.object(solver, "ask_json", return_value=llm_answers), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_fitb(tab, "context passage")

        self.assertEqual(res, "fitb: 0=ok 1=ok 2=ok 3=ok")
        self.assertEqual(tab.scroll_calls, [0, 1, 2, 3])
        self.assertEqual(
            [d["selected"] for d in tab.dropdowns],
            ["large", "which", "had left", "however"],
        )

    def test_document_portal_rejects_stale_earlier_menu_and_retries(self):
        option_lists = [
            ["large", "ceramic", "three"],
            ["however", "therefore", "although"],
        ]
        tab = _FakeFITBTab(
            questions=[_make_practice_question("Blank 1 __ Blank 2 __", option_lists)],
            dropdowns=[
                {"options": option_lists[0], "selected": "large", "mode": "document"},
                {"options": option_lists[1], "selected": "", "mode": "document"},
            ],
            initial_stale_portal=None,
        )
        # Solve blank 0 normally, then inject blank 0's stale portal before blank 1's first read.
        orig_js = tab.js
        injected = {"done": False}

        def _hook_js(script):
            if not injected["done"] and "getTrigger(1)" in script and "closeOtherMenus(s, false)" in script:
                res = orig_js(script)
                tab.stale_portal = ["large", "ceramic", "three"]
                injected["done"] = True
                return res
            return orig_js(script)

        tab.js = _hook_js
        with patch.object(solver, "ask_json", return_value={"1": "large", "2": "However,"}), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_fitb(tab, "")

        self.assertEqual(res, "fitb: 0=ok 1=ok")
        self.assertEqual(tab.dropdowns[0]["selected"], "large")
        self.assertEqual(tab.dropdowns[1]["selected"], "however")
        # Blank 1 never clicked an option from blank 0's stale portal.
        self.assertNotIn((1, "large"), tab.pick_clicks)

    def test_retries_when_option_click_does_not_update_selected_text(self):
        option_lists = [["large", "ceramic", "three"]]
        tab = _FakeFITBTab(
            questions=[_make_practice_question("A __ bowl", option_lists)],
            dropdowns=[{"options": option_lists[0], "selected": "Select..."}],
            fail_pick_attempts={0: 1},
        )
        with patch.object(solver, "ask_json", return_value={"1": "1. Ceramic."}), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_fitb(tab, "")

        self.assertEqual(res, "fitb: 0=ok")
        self.assertEqual(tab.dropdowns[0]["selected"], "ceramic")
        self.assertEqual(len(tab.pick_clicks), 2)
        self.assertIn(("pick", 0, "ceramic"), tab.mouse_dispatches)

    def test_reports_empty_instead_of_false_ok_when_selected_never_updates(self):
        option_lists = [["large", "ceramic", "three"]]
        tab = _FakeFITBTab(
            questions=[_make_practice_question("A __ bowl", option_lists)],
            dropdowns=[{"options": option_lists[0], "selected": ""}],
            fail_pick_attempts={0: 5},
        )
        with patch.object(solver, "ask_json", return_value={"1": "ceramic"}), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_fitb(tab, "")

        self.assertEqual(res, "fitb: 0=empty")
        self.assertEqual(tab.dropdowns[0]["selected"], "")

    def test_multi_question_practice_data_and_missing_states(self):
        questions = [
            _make_practice_question("Q1 __", [["alpha", "beta"]]),
            _make_practice_question("Q2 __ and __", [["gamma", "delta"], []]),
        ]
        tab = _FakeFITBTab(
            questions=questions,
            dropdowns=[
                {"options": ["alpha", "beta"], "selected": ""},
                {"options": ["gamma", "delta"], "selected": ""},
                {"options": [], "selected": ""},
            ],
        )
        with patch.object(solver, "ask_json", return_value={"1": "beta", "3": "anything"}), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_fitb(tab, "")

        self.assertEqual(res, "fitb: 0=ok 1=? 2=noopt")
        self.assertEqual(tab.dropdowns[0]["selected"], "beta")

    def test_nodata_and_missing_trigger(self):
        empty_tab = Mock()
        empty_tab.js.return_value = None
        self.assertEqual(solver.solve_fitb(empty_tab, ""), "fitb: nodata")

        nf_tab = _FakeFITBTab(
            questions=[_make_practice_question("Q1 __", [["alpha", "beta"]])],
            dropdowns=[],
        )
        with patch.object(solver, "ask_json", return_value={"1": "alpha"}), \
             patch.object(solver.time, "sleep"):
            self.assertEqual(solver.solve_fitb(nf_tab, ""), "fitb: 0=nf")


class FitbDomJsExecutionTests(unittest.TestCase):
    """Validates `_FITB_DOM_JS` container scoping & visible fallback in JS."""

    def test_dom_js_declares_required_containers_options_and_scroll(self):
        for token in (
            ".DDLOptionsW",
            ".prFITB__qaItem",
            ".prDDL__qaItem",
            ".fitb-ddl",
            ".DDLOptions__listItem",
            ".DDLOptions__list li",
            ".DDLOptions__option",
        ):
            self.assertIn(token, solver._FITB_DOM_JS)

    def test_dom_js_scopes_all_wrapper_variants_and_visible_fallback_in_node(self):
        node_bin = shutil.which("node")
        if not node_bin:
            return
        harness = r"""
class ClassList {
  constructor(el) { this.el = el; }
  _set() { return new Set((this.el.className || '').split(/\s+/).filter(Boolean)); }
  contains(c) { return this._set().has(c); }
}
function matchSimple(el, token) {
  if (!el || el.nodeType !== 1) return false;
  let tag = null;
  const classes = [];
  const parts = token.split('.');
  if (parts[0]) tag = parts[0].toLowerCase();
  for (let i = 1; i < parts.length; i++) if (parts[i]) classes.push(parts[i]);
  if (tag && el.tagName.toLowerCase() !== tag) return false;
  for (const c of classes) if (!el.classList.contains(c)) return false;
  return !!(tag || classes.length);
}
function matchChain(el, chain) {
  if (!matchSimple(el, chain[chain.length - 1])) return false;
  let cur = el.parentElement;
  for (let i = chain.length - 2; i >= 0; i--) {
    while (cur && !matchSimple(cur, chain[i])) cur = cur.parentElement;
    if (!cur) return false;
    cur = cur.parentElement;
  }
  return true;
}
class El {
  constructor(tag, cls = '', text = '') {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.className = cls;
    this.classList = new ClassList(this);
    this.innerText = text;
    this.textContent = text;
    this.style = {};
    this.hidden = false;
    this.parentElement = null;
    this.children = [];
  }
  hasAttribute() { return false; }
  append(...kids) {
    for (const k of kids) { k.parentElement = this; this.children.push(k); }
    return this;
  }
  contains(other) {
    if (this === other) return true;
    return this.children.some(c => c.contains(other));
  }
  matches(sel) {
    return sel.split(',').some(s => matchChain(this, s.trim().split(/\s+/)));
  }
  closest(sel) {
    let cur = this;
    while (cur && cur.nodeType === 1) {
      if (cur.matches(sel)) return cur;
      cur = cur.parentElement;
    }
    return null;
  }
  querySelectorAll(sel) {
    const out = [];
    const walk = (n) => {
      for (const c of n.children) {
        if (c.matches(sel)) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  cloneNode() {
    const copy = new El(this.tagName, this.className, this.innerText);
    for (const c of this.children) copy.append(c.cloneNode());
    return copy;
  }
  remove() {
    if (this.parentElement) {
      this.parentElement.children = this.parentElement.children.filter(x => x !== this);
      this.parentElement = null;
    }
  }
  getBoundingClientRect() { return {x: 0, y: 0, width: 0, height: 0}; }
}
const body = new El('body');
const documentElement = new El('html').append(body);
const practice = new El('div', 'learning__angPracticeW');
body.append(practice);

// Blank 0 (.DDLOptionsW) with its menu STILL visible in DOM: ['large', 'ceramic', 'three']
const b0 = new El('div', 'DDLOptionsW').append(
  new El('div', 'DDLOptions__selected', 'large'),
  new El('ul', 'DDLOptions__list').append(
    new El('li', 'DDLOptions__listItem', 'large'),
    new El('li', 'DDLOptions__listItem', 'ceramic'),
    new El('li', 'DDLOptions__listItem', 'three')
  )
);
// Blank 1 (.prFITB__qaItem with sibling .DDLOptions__list > li)
const b1 = new El('div', 'prFITB__qaItem').append(
  new El('div', 'DDLOptionsW').append(new El('div', 'DDLOptions__selected', '')),
  new El('ul', 'DDLOptions__list').append(
    new El('li', '', 'which'),
    new El('li', '', 'whose')
  )
);
// Blank 2 (.prDDL__qaItem with .DDLOptions__option)
const b2 = new El('div', 'prDDL__qaItem').append(
  new El('div', 'DDLOptions__selected', ''),
  new El('div', 'DDLOptions__option', 'had left'),
  new El('div', 'DDLOptions__option', 'leaves')
);
// Blank 3 (.fitb-ddl with NO container options yet -> uses visible body portal, ignoring b0..b2!)
const b3 = new El('div', 'fitb-ddl').append(new El('div', 'DDLOptions__selected', ''));
const hiddenPortal = new El('div', 'DDLOptions__option', 'stale-hidden');
hiddenPortal.style.display = 'none';
const visPortal = new El('div', 'DDLOptions__option', 'however');
practice.append(b0, b1, b2, b3);
body.append(hiddenPortal, visPortal);

const document = {
  body,
  documentElement,
  querySelectorAll: (s) => documentElement.querySelectorAll(s),
  querySelector: (s) => documentElement.querySelector(s),
};
const window = { getComputedStyle: (el) => el.style };
""" + solver._FITB_DOM_JS + r"""
const out = [0, 1, 2, 3].map(i => {
  const s = getTrigger(i);
  const r = getScopedOptions(s);
  return {scope: r.scope, opts: r.items.map(getOptText)};
});
console.log(JSON.stringify(out));
"""
        proc = subprocess.run([node_bin, "-e", harness], check=True, capture_output=True, text=True)
        parsed = json.loads(proc.stdout.strip())
        self.assertEqual(parsed, [
            {"scope": "container", "opts": ["large", "ceramic", "three"]},
            {"scope": "container", "opts": ["which", "whose"]},
            {"scope": "container", "opts": ["had left", "leaves"]},
            {"scope": "document", "opts": ["however"]},
        ])


if __name__ == "__main__":
    unittest.main()
