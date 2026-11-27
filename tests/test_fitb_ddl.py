"""Offline unit tests for FITB custom `.DDLOptions__selected` dropdown solving."""
import json
import re
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

import auto
import solver


class _FakeFITBTab:
    """Simulates Python orchestration; it does not execute emitted DOM JS."""

    def __init__(
        self,
        questions,
        dropdowns,
        *,
        dom_text="",
        require_scroll=False,
        keep_first_menu_open=False,
        initial_stale_portal=None,
        stale_portal_unclosable=False,
        stale_portal_owner=None,
        fail_pick_attempts=None,
        mutate_before_pick=None,
        on_attempt_open=None,
    ):
        self.questions = questions
        self.dropdowns = dropdowns
        self.dom_text = dom_text
        self.require_scroll = require_scroll
        self.keep_first_menu_open = keep_first_menu_open
        self.stale_portal = list(initial_stale_portal) if initial_stale_portal else None
        self.stale_portal_unclosable = stale_portal_unclosable
        self.stale_portal_owner = stale_portal_owner
        self.stale_portal_was_pre_visible = False
        self.fail_pick_attempts = dict(fail_pick_attempts or {})
        self.mutate_before_pick = mutate_before_pick
        self.on_attempt_open = on_attempt_open
        self.scroll_calls = []
        self.open_clicks = []
        self.pick_clicks = []
        self.stale_portal_clicks = []
        self.mouse_dispatches = []
        self.scripts = []

    def _get_dd(self, idx):
        if 0 <= idx < len(self.dropdowns):
            return self.dropdowns[idx]
        return None

    @staticmethod
    def _filter_selectable(raw_opts):
        out = []
        for item in raw_opts:
            if isinstance(item, dict):
                if item.get("placeholder") or item.get("disabled"):
                    continue
                txt = str(item.get("text") or "").strip()
            else:
                txt = str(item or "").strip()
            if txt:
                out.append(txt)
        return out

    def _visible_options(self, idx):
        dd = self._get_dd(idx)
        if not dd:
            return "nf", "none", []
        mode = dd.get("mode", "container")
        if mode == "container":
            if dd.get("open"):
                raw = dd.get("dom_options", dd.get("options", []))
                return "ok", "container", self._filter_selectable(raw)
            return "ok", "none", []
        if mode in ("document", "portal-linked"):
            if self.stale_portal is not None:
                # Fake orchestration only: these injected results do not prove
                # that the actual JavaScript can associate a document portal.
                if self.stale_portal_owner is not None and self.stale_portal_owner != idx:
                    pass
                elif self.stale_portal_was_pre_visible and not dd.get("bypass_js_before_vis"):
                    pass
                else:
                    return "ok", "document", self._filter_selectable(self.stale_portal)
            if dd.get("open"):
                raw = dd.get("dom_options", dd.get("options", []))
                return "ok", mode, self._filter_selectable(raw)
            return "ok", "none", []
        return "ok", "none", []

    @staticmethod
    def _is_sel_placeholder(dd):
        if not dd:
            return True
        if dd.get("selected_placeholder"):
            return True
        return not str(dd.get("selected") or "").strip()

    def js(self, script):
        self.scripts.append(script)

        # `do_task` readiness & classification support for `auto.handle_test` integration tests
        if "document.querySelector('.DDLOptions__selected')" in script and "practiceData" not in script and "CONTAINER_SEL" not in script:
            if "return 'fitb';" in script:
                return "fitb"
            return 1
        if "openSpeech__btnStart" in script:
            return ""
        if "#textContainer, .seeTextContainer" in script:
            return None
        if "audio,video" in script:
            return ""
        if ".prMCQ__qaSet" in script:
            return 0

        # 1. Extraction (`practiceData` + `domCount` + `domLists`)
        if "practiceData" in script and "answerLists" in script:
            lists = [
                [a["txt"] for a in al.get("answers", [])]
                for q in (self.questions or [])
                for al in q.get("answerLists", [])
            ]
            dom_count = len(self.dropdowns)
            if not lists and not dom_count:
                return None
            text = ""
            if self.questions:
                text = (
                    self.questions[0].get("text", "")
                    if len(self.questions) == 1
                    else "\n".join(q.get("text", "") for q in self.questions if q.get("text"))
                )
            dom_lists = [
                self._filter_selectable(dd.get("pre_dom_options", []))
                for dd in self.dropdowns
            ]
            return {
                "text": text or self.dom_text,
                "domText": self.dom_text or text,
                "lists": lists,
                "domCount": dom_count,
                "domLists": dom_lists,
            }

        # Final rendered-blank count / reconciliation audit
        if "return getTriggers().length;" in script:
            return len(self.dropdowns)
        if "return getTriggers().map(" in script:
            return [
                {
                    "selected": dd.get("selected", ""),
                    "selectedPlaceholder": self._is_sel_placeholder(dd),
                }
                for dd in self.dropdowns
            ]

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
            if callable(self.on_attempt_open):
                self.on_attempt_open(idx, dd, len([x for x in self.open_clicks if x == idx]))
            force_close = "closeOtherMenus(s, true)" in script
            if force_close and not self.stale_portal_unclosable:
                self.stale_portal = None
                for j, other in enumerate(self.dropdowns):
                    if j != idx:
                        other["open"] = False
            else:
                for j, other in enumerate(self.dropdowns):
                    if j != idx and not (j == 0 and self.keep_first_menu_open):
                        other["open"] = False

            # Track whether `stale_portal` was ALREADY visible right before `s.click()`!
            self.stale_portal_was_pre_visible = self.stale_portal is not None

            if "scrollIntoView" in script and "block: 'center'" in script:
                dd["scrolled"] = True
                self.scroll_calls.append(idx)

            if "fireMouse(s)" in script and not re.search(r"if\s*\(\s*0\s*>\s*0\s*\)\s*fireMouse\(s\)", script):
                self.mouse_dispatches.append(("trigger", idx))

            self.open_clicks.append(idx)
            if not dd.get("broken_open") and (not self.require_scroll or dd.get("scrolled")):
                dd["open"] = True
            return {
                "status": "ok",
                "selected": dd.get("selected", ""),
                "selectedPlaceholder": self._is_sel_placeholder(dd),
            }

        # 3. Scoped options query step
        if "options: res.items.map(getOptText)" in script:
            status, scope, opts = self._visible_options(idx)
            if status == "nf":
                return {"status": "nf", "options": [], "scope": "none", "selected": "", "selectedPlaceholder": True}
            return {
                "status": "ok",
                "scope": scope,
                "selected": dd.get("selected", ""),
                "selectedPlaceholder": self._is_sel_placeholder(dd),
                "options": opts,
            }

        # 4. Option pick step (mirrors exact fail-closed & cross-trigger JS logic)
        if "const wantText =" in script:
            if not dd:
                return {"clicked": 0, "selected": "", "selectedPlaceholder": True}
            if callable(self.mutate_before_pick):
                self.mutate_before_pick(idx, dd)
            _status, scope, opts = self._visible_options(idx)
            m_pick = re.search(r"res\.items\[(\d+)\]", script)
            m_want = re.search(r"const wantText = (\".*?\");", script)
            pick_idx = int(m_pick.group(1)) if m_pick else -1
            want_text = json.loads(m_want.group(1)) if m_want else ""

            has_fail_closed = "|| null);" in script and "|| pick;" not in script
            if 0 <= pick_idx < len(opts) and opts[pick_idx] == want_text:
                chosen = opts[pick_idx]
            elif want_text in opts:
                chosen = want_text
            elif not has_fail_closed and 0 <= pick_idx < len(opts):
                chosen = opts[pick_idx]
            else:
                chosen = None

            if chosen is None:
                return {
                    "clicked": 0,
                    "selected": dd.get("selected", ""),
                    "selectedPlaceholder": self._is_sel_placeholder(dd),
                }

            # If click landed on a stale portal belonging to another blank, mutate that owner blank!
            if scope == "document" and self.stale_portal is not None and self.stale_portal_owner is not None and self.stale_portal_owner != idx:
                self.stale_portal_clicks.append((idx, self.stale_portal_owner, chosen))
                owner_dd = self._get_dd(self.stale_portal_owner)
                if owner_dd is not None:
                    prev_val = owner_dd.get("selected", "")
                    owner_dd["selected"] = chosen
                    if "otherMutated" in script and prev_val != chosen:
                        return {
                            "clicked": 0,
                            "otherMutated": 1,
                            "selected": dd.get("selected", ""),
                            "selectedPlaceholder": self._is_sel_placeholder(dd),
                        }
                return {
                    "clicked": 1,
                    "selected": dd.get("selected", ""),
                    "selectedPlaceholder": self._is_sel_placeholder(dd),
                    "rect": None,
                }

            if not re.search(r"if\s*\(\s*0\s*>\s*0\s*\)\s*fireMouse\(pick\)", script):
                self.mouse_dispatches.append(("pick", idx, chosen))
            self.pick_clicks.append((idx, chosen))

            remaining_fails = self.fail_pick_attempts.get(idx, 0)
            if remaining_fails > 0:
                self.fail_pick_attempts[idx] = remaining_fails - 1
                if not (idx == 0 and self.keep_first_menu_open):
                    dd["open"] = False
                return {
                    "clicked": 1,
                    "selected": dd.get("selected", ""),
                    "selectedPlaceholder": self._is_sel_placeholder(dd),
                    "rect": None,
                }

            dd["selected"] = chosen
            dd["selected_placeholder"] = False
            if not (idx == 0 and self.keep_first_menu_open):
                dd["open"] = False
            return {
                "clicked": 1,
                "selected": dd["selected"],
                "selectedPlaceholder": False,
                "rect": None,
            }

        # 5. Standalone selected-text + placeholder state re-read
        if "selectedPlaceholder: isSelectedPlaceholder(s)" in script:
            return {
                "selected": dd.get("selected", "") if dd else "",
                "selectedPlaceholder": self._is_sel_placeholder(dd),
            }

        return None


def _make_practice_question(text, option_lists):
    return {
        "text": text,
        "answerLists": [
            {"answers": [{"txt": opt} for opt in opts]}
            for opts in option_lists
        ],
    }


_NODE_DOM_SHIM = r"""
class ClassList {
  constructor(el) { this.el = el; }
  _set() { return new Set((this.el.className || '').split(/\s+/).filter(Boolean)); }
  contains(c) { return this._set().has(c); }
}
function matchSimple(el, token) {
  if (!el || el.nodeType !== 1) return false;
  if (token.startsWith('[')) {
    const inner = token.slice(1, -1);
    if (inner.includes('*=')) {
      const [attr, rawVal] = inner.split('*=');
      const val = rawVal.replace(/^["']|["']$/g, '');
      const cur = attr === 'class' ? (el.className || '') : (el.getAttribute(attr) || '');
      return cur.toLowerCase().includes(val.toLowerCase());
    }
    if (inner.includes(':not(')) {
      const [baseAttr] = inner.split(':not(');
      return el.hasAttribute(baseAttr) && el.getAttribute(baseAttr) !== 'false';
    }
    if (inner.includes('=')) {
      const [attr, rawVal] = inner.split('=');
      const val = rawVal.replace(/^["']|["']$/g, '');
      return String(el.getAttribute(attr) || '') === val;
    }
    return el.hasAttribute(inner);
  }
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
  constructor(tag, cls = '', text = '', attrs = {}) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.className = cls;
    this.classList = new ClassList(this);
    this.innerText = text;
    this.textContent = text;
    this.id = attrs.id ? String(attrs.id) : '';
    this.style = {};
    this.hidden = false;
    this.disabled = !!attrs.disabled;
    this.attrs = Object.assign({}, attrs);
    this.parentElement = null;
    this.children = [];
    this.onclick = null;
  }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name); }
  getAttribute(name) { return this.hasAttribute(name) ? String(this.attrs[name]) : null; }
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
    const copy = new El(this.tagName, this.className, this.innerText, this.attrs);
    for (const c of this.children) copy.append(c.cloneNode());
    return copy;
  }
  remove() {
    if (this.parentElement) {
      this.parentElement.children = this.parentElement.children.filter(x => x !== this);
      this.parentElement = null;
    }
  }
  click() { if (typeof this.onclick === 'function') this.onclick(); }
  getBoundingClientRect() { return {x: 0, y: 0, width: 0, height: 0}; }
}
"""


class FitbOptionMatcherTests(unittest.TestCase):
    def test_whitespace_case_quotes_and_punctuation_normalization(self):
        opts = ["doesn't", "don't", "didn't"]
        self.assertEqual(solver._match_ddl_option("  Don’t, \n", opts), 1)
        self.assertEqual(solver._match_ddl_option('1. "Don\'t."', opts), 1)

        phrase_opts = ["despite", "in spite of", "although"]
        self.assertEqual(solver._match_ddl_option("  IN   Spite\u00a0Of! ", phrase_opts), 1)

    def test_partial_substring_prefers_word_boundary_and_rejects_inflection_drift(self):
        articles = ["a", "an", "the"]
        self.assertEqual(solver._match_ddl_option("an engineer", articles), 1)
        self.assertEqual(solver._match_ddl_option("a doctor", articles), 0)

        phrases = ["in", "spite", "in spite of"]
        self.assertEqual(solver._match_ddl_option("in spite of the rain", phrases), 2)
        self.assertEqual(solver._match_ddl_option("spite of", ["despite", "in spite of", "although"]), 1)

        # Intra-word substring must NOT drift `choose` -> `chooses` when `choose` is absent!
        self.assertIsNone(solver._match_ddl_option("choose", ["chooses", "chose"]))

    def test_legitimate_choose_and_select_options_are_not_filtered_as_placeholders(self):
        verb_opts = ["choose", "chooses", "chose"]
        self.assertEqual(solver._match_ddl_option("choose", verb_opts), 0)
        self.assertEqual(solver._match_ddl_option("Choose.", verb_opts), 0)
        self.assertEqual(solver._match_ddl_option("chooses", verb_opts), 1)
        self.assertEqual(solver._match_ddl_option("select", ["select", "selects", "selected"]), 0)
        self.assertTrue(solver._ddl_selected_ok("choose", "choose", is_placeholder=False))
        self.assertFalse(solver._ddl_selected_ok("choose", "choose", is_placeholder=True))

        ui_opts = [
            {"text": "choose", "placeholder": True},
            {"text": "choose", "placeholder": False},
            {"text": "chooses", "placeholder": False},
        ]
        self.assertEqual(solver._match_ddl_option("choose", ui_opts), 1)

    def test_selected_verification_rejects_substring_false_positives(self):
        self.assertFalse(solver._ddl_selected_ok("in", "in spite of"))
        self.assertFalse(solver._ddl_selected_ok("in spite of", "in"))
        self.assertFalse(solver._ddl_selected_ok("choose", "chooses"))
        self.assertFalse(solver._ddl_selected_ok("", "ceramic"))
        self.assertFalse(solver._ddl_selected_ok("Select...", "ceramic"))
        self.assertTrue(solver._ddl_selected_ok("in spite of \u25be", "in spite of"))
        self.assertTrue(solver._ddl_selected_ok("ceramic \u25be", "ceramic"))

    def test_empty_items_never_match_unmatched_answer(self):
        opts = ["", "   ", "large", "ceramic", "three"]
        self.assertIsNone(solver._match_ddl_option("however", opts))


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

    def test_choose_disappearing_before_retry_fails_closed_without_selecting_chooses(self):
        """Re-review finding #1: if `choose` disappears before retry, never select `chooses`."""
        option_lists = [["choose", "chooses", "chose"]]

        def _drop_choose_on_retry(_idx, dd, attempt_num):
            if attempt_num >= 1:
                dd["dom_options"] = ["chooses", "chose"]

        tab = _FakeFITBTab(
            questions=[_make_practice_question("They __ wisely.", option_lists)],
            dropdowns=[{
                "options": ["choose", "chooses", "chose"],
                "dom_options": ["choose", "chooses", "chose"],
                "selected": "",
            }],
            fail_pick_attempts={0: 1},
            on_attempt_open=_drop_choose_on_retry,
        )
        with patch.object(solver, "ask_json", return_value={"1": "choose"}), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_fitb(tab, "")

        self.assertEqual(res, "other: fitb: 0=noopt")
        self.assertNotIn((0, "chooses"), tab.pick_clicks)
        self.assertEqual(tab.dropdowns[0]["selected"], "")

        # Multi-word prefix variant: if `in spite of` disappears before retry leaving `in`, fail closed!
        phrase_lists = [["in", "in spite of", "despite"]]

        def _drop_phrase_on_retry(_idx, dd, attempt_num):
            if attempt_num >= 1:
                dd["dom_options"] = ["in", "despite"]

        tab_phrase = _FakeFITBTab(
            questions=[_make_practice_question("We went out __ the storm.", phrase_lists)],
            dropdowns=[{
                "options": ["in", "in spite of", "despite"],
                "dom_options": ["in", "in spite of", "despite"],
                "selected": "",
            }],
            fail_pick_attempts={0: 1},
            on_attempt_open=_drop_phrase_on_retry,
        )
        with patch.object(solver, "ask_json", return_value={"1": "in spite of"}), \
             patch.object(solver.time, "sleep"):
            res_phrase = solver.solve_fitb(tab_phrase, "")

        self.assertEqual(res_phrase, "other: fitb: 0=noopt")
        self.assertNotIn((0, "in"), tab_phrase.pick_clicks)
        self.assertEqual(tab_phrase.dropdowns[0]["selected"], "")

    def test_stale_portal_with_overlapping_option_and_preexisting_value_rejected(self):
        """Re-review finding #2: stale portal sharing `however` + pre-existing `however` on blank 1 must fail closed."""
        option_lists = [
            ["large", "ceramic", "however"],
            ["however", "therefore", "although"],
        ]
        # Blank 0 solved to "large"; Blank 0's portal ["large", "ceramic", "however"] stays stuck open,
        # Blank 1 fails to open its own portal (`broken_open=True`) and ALREADY displays `"however"`!
        tab = _FakeFITBTab(
            questions=[_make_practice_question("1 __ 2 __", option_lists)],
            dropdowns=[
                {"options": option_lists[0], "selected": "", "mode": "portal-linked"},
                {
                    "options": option_lists[1],
                    "selected": "however",
                    "mode": "document",
                    "broken_open": True,
                    "bypass_js_before_vis": True,
                },
            ],
            initial_stale_portal=None,
            stale_portal_unclosable=True,
            stale_portal_owner=0,
        )
        orig_js = tab.js

        def _hook_js(script):
            res = orig_js(script)
            # After Blank 0 finishes, leave Blank 0's portal ["large", "ceramic", "however"] lingering
            if tab.dropdowns[0]["selected"] == "large" and tab.stale_portal is None:
                tab.stale_portal = ["large", "ceramic", "however"]
                tab.stale_portal_owner = None  # Even without explicit owner, option-set mismatch + preVis catches it!
            return res

        tab.js = _hook_js
        with patch.object(solver, "ask_json", return_value={"1": "large", "2": "however"}), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_fitb(tab, "")

        self.assertEqual(res, "other: fitb: 0=ok 1=noopt")
        self.assertEqual(tab.dropdowns[0]["selected"], "large")
        self.assertEqual(tab.stale_portal_clicks, [])
        self.assertNotIn((1, "however"), tab.pick_clicks)

    def test_extra_rendered_blanks_beyond_practice_data_reconciled_and_block_submit(self):
        """Re-review finding #3: extra UI blanks omitted from practiceData block final submission if unverified."""
        # Subcase A: practiceData lists ONLY 1 blank, visible UI renders 2 blanks (second blank left empty)
        tab_incomplete = _FakeFITBTab(
            questions=[_make_practice_question("A __ bowl", [["large", "ceramic", "three"]])],
            dropdowns=[
                {"options": ["large", "ceramic", "three"], "selected": ""},
                {"options": [], "selected": ""},
            ],
        )
        with patch.object(solver, "ask_json", return_value={"1": "ceramic"}), \
             patch.object(solver.time, "sleep"), \
             patch.object(auto.time, "sleep"), \
             patch.object(auto, "st", return_value={"total": "2", "counter": "2"}), \
             patch.object(auto, "click") as mock_click, \
             patch.object(auto.poll, "wait_until"), \
             patch("builtins.print"):
            res = auto.handle_test(tab_incomplete, "")

        self.assertTrue(res.startswith("test-unanswered:"), res)
        self.assertIn("0=ok", res)
        self.assertRegex(res, r"1=(\?|noopt|empty)")
        mock_click.assert_not_called()

        # Subcase B: extra rendered blank WITH discoverable DOM options is solved and verified when LLM answers both!
        tab_both = _FakeFITBTab(
            questions=[_make_practice_question("A __ bowl", [["large", "ceramic"]])],
            dom_text="A [[1]] bowl on a [[2]] table",
            dropdowns=[
                {"options": ["large", "ceramic"], "selected": ""},
                {"options": ["wooden", "glass"], "pre_dom_options": ["wooden", "glass"], "selected": ""},
            ],
        )
        with patch.object(solver, "ask_json", return_value={"1": "ceramic", "2": "wooden"}), \
             patch.object(solver.time, "sleep"):
            res_both = solver.solve_fitb(tab_both, "")

        self.assertEqual(res_both, "fitb: 0=ok 1=ok")
        self.assertEqual([d["selected"] for d in tab_both.dropdowns], ["ceramic", "wooden"])

    def test_existing_in_does_not_pass_as_in_spite_of_after_failed_click(self):
        option_lists = [["in", "in spite of", "despite"]]
        tab_retry = _FakeFITBTab(
            questions=[_make_practice_question("We went out __ the rain.", option_lists)],
            dropdowns=[{"options": option_lists[0], "selected": "in"}],
            fail_pick_attempts={0: 1},
        )
        with patch.object(solver, "ask_json", return_value={"1": "in spite of"}), \
             patch.object(solver.time, "sleep"):
            res_retry = solver.solve_fitb(tab_retry, "")
        self.assertEqual(res_retry, "fitb: 0=ok")
        self.assertEqual(tab_retry.dropdowns[0]["selected"], "in spite of")
        self.assertEqual(len(tab_retry.pick_clicks), 2)

        tab_fail = _FakeFITBTab(
            questions=[_make_practice_question("We went out __ the rain.", option_lists)],
            dropdowns=[{"options": option_lists[0], "selected": "in"}],
            fail_pick_attempts={0: 5},
        )
        with patch.object(solver, "ask_json", return_value={"1": "in spite of"}), \
             patch.object(solver.time, "sleep"):
            res_fail = solver.solve_fitb(tab_fail, "")
        self.assertEqual(res_fail, "other: fitb: 0=empty")
        self.assertEqual(tab_fail.dropdowns[0]["selected"], "in")

    def test_solve_fitb_selects_choose_over_chooses_and_checks_placeholder_ui(self):
        option_lists = [["choose", "chooses", "chose"]]
        tab = _FakeFITBTab(
            questions=[_make_practice_question("They always __ wisely.", option_lists)],
            dropdowns=[{
                "options": option_lists[0],
                "dom_options": [
                    {"text": "choose", "placeholder": True},
                    {"text": "choose", "placeholder": False},
                    {"text": "chooses", "placeholder": False},
                    {"text": "chose", "placeholder": False},
                ],
                "selected": "choose",
                "selected_placeholder": True,
            }],
            fail_pick_attempts={0: 1},
        )
        with patch.object(solver, "ask_json", return_value={"1": "choose"}), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_fitb(tab, "")

        self.assertEqual(res, "fitb: 0=ok")
        self.assertEqual(tab.dropdowns[0]["selected"], "choose")
        self.assertFalse(tab.dropdowns[0]["selected_placeholder"])
        self.assertEqual(tab.pick_clicks, [(0, "choose"), (0, "choose")])

    def test_disappearing_option_between_lookup_and_click_fails_closed(self):
        option_lists = [["alpha", "beta"]]

        def _drop_alpha_before_pick(_idx, dd):
            dd["dom_options"] = ["beta"]

        tab = _FakeFITBTab(
            questions=[_make_practice_question("Pick __", option_lists)],
            dropdowns=[{"options": ["alpha", "beta"], "dom_options": ["alpha", "beta"], "selected": ""}],
            mutate_before_pick=_drop_alpha_before_pick,
        )
        orig_js = tab.js

        def _hook_js(script):
            if "options: res.items.map(getOptText)" in script:
                tab.dropdowns[0]["dom_options"] = ["alpha", "beta"]
            return orig_js(script)

        tab.js = _hook_js
        with patch.object(solver, "ask_json", return_value={"1": "alpha"}), \
             patch.object(solver.time, "sleep"):
            res = solver.solve_fitb(tab, "")

        self.assertEqual(res, "other: fitb: 0=noopt")
        self.assertEqual(tab.pick_clicks, [])
        self.assertEqual(tab.dropdowns[0]["selected"], "")

    def test_handle_test_unanswered_guard_blocks_submit_on_empty_and_noopt(self):
        option_lists = [["large", "ceramic", "three"]]

        tab_empty = _FakeFITBTab(
            questions=[_make_practice_question("A __ bowl", option_lists)],
            dropdowns=[{"options": option_lists[0], "selected": ""}],
            fail_pick_attempts={0: 10},
        )
        with patch.object(solver, "ask_json", return_value={"1": "ceramic"}), \
             patch.object(solver.time, "sleep"), \
             patch.object(auto.time, "sleep"), \
             patch.object(auto, "st", return_value={"total": "2", "counter": "2"}), \
             patch.object(auto, "click") as mock_click, \
             patch.object(auto.poll, "wait_until"), \
             patch("builtins.print"):
            res_empty = auto.handle_test(tab_empty, "")

        self.assertTrue(res_empty.startswith("test-unanswered:"), res_empty)
        self.assertIn("0=empty", res_empty)
        mock_click.assert_not_called()

        tab_noopt = _FakeFITBTab(
            questions=[_make_practice_question("A __ bowl", option_lists)],
            dropdowns=[{"options": [], "selected": ""}],
        )
        with patch.object(solver, "ask_json", return_value={"1": "ceramic"}), \
             patch.object(solver.time, "sleep"), \
             patch.object(auto.time, "sleep"), \
             patch.object(auto, "st", return_value={"total": "2", "counter": "2"}), \
             patch.object(auto, "click") as mock_click, \
             patch.object(auto.poll, "wait_until"), \
             patch("builtins.print"):
            res_noopt = auto.handle_test(tab_noopt, "")

        self.assertTrue(res_noopt.startswith("test-unanswered:"), res_noopt)
        self.assertIn("0=noopt", res_noopt)
        mock_click.assert_not_called()

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

        self.assertEqual(res, "other: fitb: 0=empty")
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

        self.assertEqual(res, "other: fitb: 0=ok 1=? 2=noopt")
        self.assertEqual(tab.dropdowns[0]["selected"], "beta")

    def test_nodata_and_missing_trigger(self):
        empty_tab = Mock()
        empty_tab.js.return_value = None
        self.assertEqual(solver.solve_fitb(empty_tab, ""), "other: fitb: nodata")

        nf_tab = _FakeFITBTab(
            questions=[_make_practice_question("Q1 __", [["alpha", "beta"]])],
            dropdowns=[],
        )
        with patch.object(solver, "ask_json", return_value={"1": "alpha"}), \
             patch.object(solver.time, "sleep"):
            self.assertEqual(solver.solve_fitb(nf_tab, ""), "other: fitb: 0=nf")


class FitbDomJsExecutionTests(unittest.TestCase):
    """Validates `_FITB_DOM_JS` scoping, portal trigger association, UI placeholders, and fail-closed click in JS."""

    def test_dom_js_declares_required_containers_options_and_portal_owner(self):
        for token in (
            ".DDLOptionsW",
            ".prFITB__qaItem",
            ".prDDL__qaItem",
            ".fitb-ddl",
            ".DDLOptions__listItem",
            ".DDLOptions__list li",
            ".DDLOptions__option",
            "isOptionPlaceholder",
            "isSelectedPlaceholder",
            "getPortalOwner",
        ):
            self.assertIn(token, solver._FITB_DOM_JS)

    def test_dom_js_scopes_wrappers_and_associated_portals_in_node(self):
        node_bin = shutil.which("node")
        if not node_bin:
            return
        harness = _NODE_DOM_SHIM + r"""
const body = new El('body');
const documentElement = new El('html').append(body);
const practice = new El('div', 'learning__angPracticeW');
body.append(practice);

// Blank 0 (.DDLOptionsW): includes UI-placeholder item "choose" + legitimate options ["choose", "chooses", "chose"]
const sel0 = new El('div', 'DDLOptions__selected DDLOptions__selected--placeholder', 'choose', {id: 'trig-0', 'aria-controls': 'portal-0'});
const phOpt = new El('li', 'DDLOptions__listItem DDLOptions__listItem--placeholder', 'choose', {'aria-disabled': 'true'});
const realChoose = new El('li', 'DDLOptions__listItem', 'choose');
const realChooses = new El('li', 'DDLOptions__listItem', 'chooses');
const realChose = new El('li', 'DDLOptions__listItem', 'chose');
const b0 = new El('div', 'DDLOptionsW').append(
  sel0,
  new El('ul', 'DDLOptions__list').append(phOpt, realChoose, realChooses, realChose)
);
// Blank 1 (.prFITB__qaItem with sibling .DDLOptions__list > li)
const b1 = new El('div', 'prFITB__qaItem').append(
  new El('div', 'DDLOptionsW').append(new El('div', 'DDLOptions__selected', 'which')),
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
// Blank 3 (.fitb-ddl linked via aria-controls="portal-3" to its body-level portal)
const b3 = new El('div', 'fitb-ddl').append(
  new El('div', 'DDLOptions__selected', '', {id: 'trig-3', 'aria-controls': 'portal-3'})
);
// Stale portal explicitly owned by Blank 0 AND an unlinked stale option already sitting on body:
const stalePortal0 = new El('div', 'cdk-overlay-pane', '', {id: 'portal-0'}).append(
  new El('div', 'DDLOptions__option', 'however')
);
const unlinkedStale = new El('div', 'DDLOptions__option', 'unlinked-stale');
// Portal explicitly linked to Blank 3:
const portal3 = new El('div', 'cdk-overlay-pane', '', {id: 'portal-3'}).append(
  new El('div', 'DDLOptions__option disabled', 'Choose...', {disabled: 'true'}),
  new El('div', 'DDLOptions__option', 'however')
);
practice.append(b0, b1, b2, b3);
body.append(stalePortal0, unlinkedStale, portal3);

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
  return {
    scope: r.scope,
    selPh: isSelectedPlaceholder(s),
    opts: r.items.map(getOptText),
    firstIsRealChoose: i === 0 ? r.items[0] === realChoose : null,
  };
});
console.log(JSON.stringify(out));
"""
        proc = subprocess.run([node_bin, "-e", harness], check=True, capture_output=True, text=True)
        parsed = json.loads(proc.stdout.strip())
        self.assertEqual(parsed, [
            {"scope": "container", "selPh": True, "opts": ["choose", "chooses", "chose"], "firstIsRealChoose": True},
            {"scope": "container", "selPh": False, "opts": ["which", "whose"], "firstIsRealChoose": None},
            {"scope": "container", "selPh": True, "opts": ["had left", "leaves"], "firstIsRealChoose": None},
            {"scope": "portal-linked", "selPh": True, "opts": ["however"], "firstIsRealChoose": None},
        ])

    def test_portal_open_provenance_rejects_preexisting_stale_menu_in_node(self):
        """A stale unlinked menu is rejected; an explicitly owned fresh menu works."""
        node_bin = shutil.which("node")
        if not node_bin:
            return
        harness = _NODE_DOM_SHIM + r"""
const body = new El('body');
const documentElement = new El('html').append(body);
const practice = new El('div', 'learning__angPracticeW');
body.append(practice);

const s0 = new El('div', 'DDLOptions__selected', 'large');
const s1 = new El('div', 'DDLOptions__selected', 'however', {id: 'target', 'aria-controls': 'fresh-menu'});
practice.append(new El('div', 'DDLOptionsW').append(s0), new El('div', 'DDLOptionsW').append(s1));

// Stale unlinked menu from Blank 0 already visible on body before s1 is clicked:
const staleOpt = new El('li', 'DDLOptions__listItem', 'however');
const staleMenu = new El('ul', 'DDLOptions__list').append(staleOpt);
body.append(staleMenu);

const document = {
  body,
  documentElement,
  querySelectorAll: (s) => documentElement.querySelectorAll(s),
  querySelector: (s) => documentElement.querySelector(s),
};
const window = { getComputedStyle: (el) => el.style };
""" + solver._FITB_DOM_JS + r"""
// 1. Simulate open_res for s1 when s1 fails to open a new menu (staleMenu was already visible!):
const preVis1 = selectableOptions(document.querySelectorAll(OPT_SEL)).filter(isVisible);
window._edFitbPortalState = { trigger: s1, beforeVis: new WeakSet(preVis1) };
s1.click();
const afterBrokenOpen = getScopedOptions(s1);

// 2. Now simulate s1.click() mounting a portal explicitly associated with s1:
const freshOpt = new El('li', 'DDLOptions__listItem', 'however');
s1.onclick = () => { body.append(new El('ul', 'DDLOptions__list', '', {id: 'fresh-menu'}).append(freshOpt)); };
const preVis2 = selectableOptions(document.querySelectorAll(OPT_SEL)).filter(isVisible);
window._edFitbPortalState = { trigger: s1, beforeVis: new WeakSet(preVis2) };
s1.click();
const afterRealOpen = getScopedOptions(s1);

console.log(JSON.stringify({
  brokenScope: afterBrokenOpen.scope,
  brokenCount: afterBrokenOpen.items.length,
  realScope: afterRealOpen.scope,
  realIsFresh: afterRealOpen.items.length === 1 && afterRealOpen.items[0] === freshOpt,
}));
"""
        proc = subprocess.run([node_bin, "-e", harness], check=True, capture_output=True, text=True)
        parsed = json.loads(proc.stdout.strip())
        self.assertEqual(parsed, {
            "brokenScope": "none",
            "brokenCount": 0,
            "realScope": "portal-linked",
            "realIsFresh": True,
        })

    def test_unlinked_stale_portal_created_after_click_is_not_owned(self):
        """Timing and identical option text do not prove a portal belongs to a trigger."""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node is required to execute the production DOM helper")
        harness = _NODE_DOM_SHIM + r"""
const body = new El('body');
const documentElement = new El('html').append(body);
const practice = new El('div', 'learning__angPracticeW');
body.append(practice);
const s0 = new El('div', 'DDLOptions__selected', 'large');
const s1 = new El('div', 'DDLOptions__selected', 'however');
practice.append(new El('div', 'DDLOptionsW').append(s0), new El('div', 'DDLOptionsW').append(s1));
const document = {
  body, documentElement,
  querySelectorAll: (s) => documentElement.querySelectorAll(s),
  querySelector: (s) => documentElement.querySelector(s),
};
const window = { getComputedStyle: (el) => el.style };
""" + solver._FITB_DOM_JS + r"""
const before = selectableOptions(document.querySelectorAll(OPT_SEL)).filter(isVisible);
window._edFitbPortalState = { trigger: s1, beforeVis: new WeakSet(before) };
// A stale menu for s0 is remounted while s1 fails to open; its complete option
// set is identical to s1's expected options and s1 already displays however.
s1.onclick = () => body.append(new El('ul', 'DDLOptions__list').append(
  new El('li', 'DDLOptions__listItem', 'however'),
  new El('li', 'DDLOptions__listItem', 'therefore')));
s1.click();
const res = getScopedOptions(s1);
console.log(JSON.stringify({scope: res.scope, count: res.items.length}));
"""
        proc = subprocess.run([node_bin, "-e", harness], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(proc.stdout), {"scope": "none", "count": 0})

    def test_portal_with_multiple_claiming_triggers_is_rejected(self):
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node is required to execute the production DOM helper")
        harness = _NODE_DOM_SHIM + r"""
const body = new El('body');
const documentElement = new El('html').append(body);
const practice = new El('div', 'learning__angPracticeW');
body.append(practice);
const s0 = new El('div', 'DDLOptions__selected', 'large', {'aria-controls': 'shared'});
const s1 = new El('div', 'DDLOptions__selected', 'however', {'aria-controls': 'shared'});
practice.append(new El('div', 'DDLOptionsW').append(s0), new El('div', 'DDLOptionsW').append(s1));
body.append(new El('ul', 'DDLOptions__list', '', {id: 'shared'}).append(
  new El('li', 'DDLOptions__listItem', 'however')));
const document = {
  body, documentElement,
  querySelectorAll: (s) => documentElement.querySelectorAll(s),
  querySelector: (s) => documentElement.querySelector(s),
};
const window = { getComputedStyle: (el) => el.style };
""" + solver._FITB_DOM_JS + r"""
console.log(JSON.stringify({scope: getScopedOptions(s0).scope, count: getScopedOptions(s0).items.length}));
"""
        proc = subprocess.run([node_bin, "-e", harness], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(proc.stdout), {"scope": "none", "count": 0})

    def test_active_descendant_identifies_unlinked_menu_via_emitted_js(self):
        """A unique ARIA active option can identify its list without a menu ID."""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node is required to execute the emitted JS")
        scripts = []

        class CaptureTab:
            def js(self, script):
                scripts.append(script)
                return {"status": "ok", "options": [], "scope": "none"}

        with patch.object(solver.time, "sleep"):
            solver._open_and_read_ddl(CaptureTab(), 1)
        open_js, read_js = scripts
        harness = _NODE_DOM_SHIM + r"""
const body = new El('body');
const documentElement = new El('html').append(body);
const practice = new El('div', 'learning__angPracticeW');
body.append(practice);
const s0 = new El('div', 'DDLOptions__selected', 'large');
const s1 = new El('div', 'DDLOptions__selected', '');
practice.append(new El('div', 'DDLOptionsW').append(s0), new El('div', 'DDLOptionsW').append(s1));
const document = {body, documentElement,
  querySelectorAll: s => documentElement.querySelectorAll(s),
  querySelector: s => documentElement.querySelector(s)};
const window = {getComputedStyle: el => el.style};
s1.onclick = () => {
  s1.attrs['aria-activedescendant'] = 'option-1';
  body.append(new El('ul', 'DDLOptions__list').append(
    new El('li', 'DDLOptions__listItem', 'however', {id: 'option-1'}),
    new El('li', 'DDLOptions__listItem', 'therefore')));
};
const opened = """ + open_js + ";\nconst result = " + read_js + r""";
console.log(JSON.stringify(result));
"""
        proc = subprocess.run([node_bin, "-e", harness], check=True, capture_output=True, text=True)
        result = json.loads(proc.stdout)
        self.assertEqual(result["scope"], "portal-linked")
        self.assertEqual(result["options"], ["however", "therefore"])

    def test_active_descendant_is_not_borrowed_from_another_option_list(self):
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node is required to execute the emitted JS")
        scripts = []

        class CaptureTab:
            def js(self, script):
                scripts.append(script)
                return {"status": "ok", "options": [], "scope": "none"}

        with patch.object(solver.time, "sleep"):
            solver._open_and_read_ddl(CaptureTab(), 0)
        read_js = scripts[1]
        harness = _NODE_DOM_SHIM + r"""
const body = new El('body');
const documentElement = new El('html').append(body);
const practice = new El('div', 'learning__angPracticeW');
body.append(practice);
const s0 = new El('div', 'DDLOptions__selected', '', {'aria-activedescendant': 'active'});
practice.append(new El('div', 'DDLOptionsW').append(s0));
// A broad listbox contains a menu and an unrelated outside option. The
// active item within that menu cannot establish ownership of the outside option.
body.append(new El('div', '', '', {role: 'listbox'}).append(
  new El('ul', 'DDLOptions__list').append(new El('li', 'DDLOptions__listItem', 'right', {id: 'active'})),
  new El('div', 'DDLOptions__option', 'stale')));
const document = {body, documentElement,
  querySelectorAll: s => documentElement.querySelectorAll(s),
  querySelector: s => documentElement.querySelector(s)};
const window = {getComputedStyle: el => el.style};
const result = """ + read_js + r""";
console.log(JSON.stringify(result));
"""
        proc = subprocess.run([node_bin, "-e", harness], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(proc.stdout)["options"], ["right"])

    def test_duplicate_menu_id_is_ambiguous_via_emitted_js(self):
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node is required to execute the emitted JS")
        scripts = []

        class CaptureTab:
            def js(self, script):
                scripts.append(script)
                return {"status": "ok", "options": [], "scope": "none"}

        with patch.object(solver.time, "sleep"):
            solver._open_and_read_ddl(CaptureTab(), 0)
        harness = _NODE_DOM_SHIM + r"""
const body = new El('body');
const documentElement = new El('html').append(body);
const practice = new El('div', 'learning__angPracticeW');
body.append(practice);
const s0 = new El('div', 'DDLOptions__selected', '', {'aria-controls': 'duplicate'});
practice.append(new El('div', 'DDLOptionsW').append(s0));
body.append(new El('ul', 'DDLOptions__list', '', {id: 'duplicate'}).append(
  new El('li', 'DDLOptions__listItem', 'right')),
  new El('ul', 'DDLOptions__list', '', {id: 'duplicate'}).append(
  new El('li', 'DDLOptions__listItem', 'stale')));
const document = {body, documentElement,
  querySelectorAll: s => documentElement.querySelectorAll(s),
  querySelector: s => documentElement.querySelector(s)};
const window = {getComputedStyle: el => el.style};
const result = """ + scripts[1] + r""";
console.log(JSON.stringify(result));
"""
        proc = subprocess.run([node_bin, "-e", harness], check=True, capture_output=True, text=True)
        result = json.loads(proc.stdout)
        self.assertEqual((result["scope"], result["options"]), ("none", []))

    def test_active_descendant_change_during_pick_does_not_click_stale_menu(self):
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node is required to execute the emitted JS")
        captured = []

        class CaptureTab:
            def js(self, script):
                captured.append(script)
                if "practiceData" in script and "answerLists" in script:
                    return {"text": "Pick __", "lists": [["alpha", "beta"]],
                            "domCount": 1, "domLists": [[]]}
                if "closeOtherMenus(s," in script:
                    return {"status": "ok", "selected": "", "selectedPlaceholder": True}
                if "options: res.items.map(getOptText)" in script:
                    return {"status": "ok", "scope": "portal-linked", "selected": "",
                            "selectedPlaceholder": True, "options": ["alpha", "beta"]}
                if "const wantText =" in script:
                    return {"clicked": 0, "selected": "", "selectedPlaceholder": True}
                if "return getTriggers().map(" in script:
                    return [{"selected": "", "selectedPlaceholder": True}]
                return None

        with patch.object(solver, "ask_json", return_value={"1": "alpha"}), \
             patch.object(solver.time, "sleep"):
            solver.solve_fitb(CaptureTab(), "")
        pick_js = next(s for s in captured if "const wantText =" in s)
        harness = _NODE_DOM_SHIM + r"""
const body = new El('body');
const documentElement = new El('html').append(body);
const practice = new El('div', 'learning__angPracticeW');
body.append(practice);
const s0 = new El('div', 'DDLOptions__selected', '', {'aria-activedescendant': 'other-active'});
practice.append(new El('div', 'DDLOptionsW').append(s0));
let clicked = false;
const stale = new El('li', 'DDLOptions__listItem', 'alpha', {id: 'old-active'});
stale.onclick = () => { clicked = true; };
body.append(new El('ul', 'DDLOptions__list').append(stale, new El('li', 'DDLOptions__listItem', 'beta')),
  new El('ul', 'DDLOptions__list').append(new El('li', 'DDLOptions__listItem', 'gamma', {id: 'other-active'})));
const document = {body, documentElement,
  querySelectorAll: s => documentElement.querySelectorAll(s),
  querySelector: s => documentElement.querySelector(s)};
const window = {getComputedStyle: el => el.style};
const result = """ + pick_js + r""";
console.log(JSON.stringify({clicked, result}));
"""
        proc = subprocess.run([node_bin, "-e", harness], check=True, capture_output=True, text=True)
        result = json.loads(proc.stdout)
        self.assertFalse(result["clicked"])
        self.assertEqual(result["result"]["clicked"], 0)

    def test_active_descendant_menu_option_is_clicked_by_emitted_pick_js(self):
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node is required to execute the emitted JS")
        captured = []

        class CaptureTab:
            def js(self, script):
                captured.append(script)
                if "practiceData" in script and "answerLists" in script:
                    return {"text": "Pick __", "lists": [["alpha", "beta"]],
                            "domCount": 1, "domLists": [[]]}
                if "closeOtherMenus(s," in script:
                    return {"status": "ok", "selected": "", "selectedPlaceholder": True}
                if "options: res.items.map(getOptText)" in script:
                    return {"status": "ok", "scope": "portal-linked", "selected": "",
                            "selectedPlaceholder": True, "options": ["alpha", "beta"]}
                if "const wantText =" in script:
                    return {"clicked": 0, "selected": "", "selectedPlaceholder": True}
                if "return getTriggers().map(" in script:
                    return [{"selected": "", "selectedPlaceholder": True}]
                return None

        with patch.object(solver, "ask_json", return_value={"1": "alpha"}), \
             patch.object(solver.time, "sleep"):
            solver.solve_fitb(CaptureTab(), "")
        pick_js = next(s for s in captured if "const wantText =" in s)
        harness = _NODE_DOM_SHIM + r"""
const body = new El('body');
const documentElement = new El('html').append(body);
const practice = new El('div', 'learning__angPracticeW');
body.append(practice);
const s0 = new El('div', 'DDLOptions__selected', '', {'aria-activedescendant': 'active'});
practice.append(new El('div', 'DDLOptionsW').append(s0));
let clicked = false;
const option = new El('li', 'DDLOptions__listItem', 'alpha', {id: 'active'});
option.onclick = () => { clicked = true; s0.innerText = s0.textContent = 'alpha'; };
body.append(new El('ul', 'DDLOptions__list').append(option, new El('li', 'DDLOptions__listItem', 'beta')));
const document = {body, documentElement,
  querySelectorAll: s => documentElement.querySelectorAll(s),
  querySelector: s => documentElement.querySelector(s)};
const window = {getComputedStyle: el => el.style};
const result = """ + pick_js + r""";
console.log(JSON.stringify({clicked, result}));
"""
        proc = subprocess.run([node_bin, "-e", harness], check=True, capture_output=True, text=True)
        result = json.loads(proc.stdout)
        self.assertTrue(result["clicked"])
        self.assertEqual(result["result"]["selected"], "alpha")
        self.assertEqual(result["result"]["scope"], "portal-linked")

    def test_pick_js_fails_closed_in_node_when_target_option_disappears(self):
        node_bin = shutil.which("node")
        if not node_bin:
            return
        captured = []

        class _CaptureTab:
            def js(self, script):
                captured.append(script)
                if "practiceData" in script and "answerLists" in script:
                    return {
                        "text": "Pick __",
                        "domText": "Pick [[1]]",
                        "lists": [["alpha", "beta"]],
                        "domCount": 1,
                        "domLists": [["alpha", "beta"]],
                    }
                if "closeOtherMenus(s," in script:
                    return {"status": "ok", "selected": "", "selectedPlaceholder": True}
                if "options: res.items.map(getOptText)" in script:
                    return {
                        "status": "ok",
                        "scope": "container",
                        "selected": "",
                        "selectedPlaceholder": True,
                        "options": ["alpha", "beta"],
                    }
                if "const wantText =" in script:
                    return {"clicked": 0, "selected": "", "selectedPlaceholder": True}
                if "return getTriggers().map(" in script:
                    return [{"selected": "", "selectedPlaceholder": True}]
                return None

        with patch.object(solver, "ask_json", return_value={"1": "alpha"}), \
             patch.object(solver.time, "sleep"):
            solver.solve_fitb(_CaptureTab(), "")

        pick_iife = next(s for s in captured if "const wantText =" in s)
        harness = _NODE_DOM_SHIM + r"""
const body = new El('body');
const documentElement = new El('html').append(body);
const practice = new El('div', 'learning__angPracticeW');
body.append(practice);

let betaClicked = false;
const beta = new El('li', 'DDLOptions__listItem', 'beta');
beta.onclick = () => { betaClicked = true; };
const b0 = new El('div', 'DDLOptionsW').append(
  new El('div', 'DDLOptions__selected', ''),
  new El('ul', 'DDLOptions__list').append(beta)
);
practice.append(b0);
const document = {
  body,
  documentElement,
  querySelectorAll: (s) => documentElement.querySelectorAll(s),
  querySelector: (s) => documentElement.querySelector(s),
};
const window = { getComputedStyle: (el) => el.style };
const res = """ + pick_iife + r""";
console.log(JSON.stringify({res, betaClicked}));
"""
        proc = subprocess.run([node_bin, "-e", harness], check=True, capture_output=True, text=True)
        parsed = json.loads(proc.stdout.strip())
        self.assertEqual(parsed["res"]["clicked"], 0)
        self.assertFalse(parsed["betaClicked"])


if __name__ == "__main__":
    unittest.main()
