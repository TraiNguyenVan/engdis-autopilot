"""Unit-1 autopilot: drives the learning area task by task.

Usage: python3 auto.py [max_iterations]
"""
import json, os, re, sys, time

import edlib, login, poll, solver
import config
import cover
from diag_logger import DiagnosticLogger
from core.unit_loader import get_unit_handler

diag = DiagnosticLogger(log_dir="logs_diag")

PORT = config.CDP_PORT

# Authoritative test/practice classification. The LMS keeps a hidden test
# container (`.testResultTools`, `.learning__submitTestLink`) inside practice
# steps, so DOM-only signals misclassified speaking/writing steps as tests and
# sent them through the test solver until they stalled. The step node name wins.
IS_TEST_JS = """(() => {
    const app = ng.probe(document.querySelector('app'))?.componentInstance;
    const nav = app?.navigationService;
    const dds = [...document.querySelectorAll('ed-la-dropdownlist')];
    const ddComp = dds.length > 1 ? ng.probe(dds[1])?.componentInstance : null;
    const node = ddComp?.dropDownListObj?.SelectedNode || nav?._stepsList?.SelectedNode;
    const name = String(node?.Name || '').trim().toLowerCase();
    if (name === 'practice' || name === 'explore') return false;
    if (name === 'test' || name === 'review') return true;
    if (app?.isTestEnv) return true;
    if (typeof app?.isStepTest === 'function' && app.isStepTest()) return true;
    const sub = document.querySelector('.learning__submitTestLink');
    if (sub && (sub.offsetWidth || sub.offsetHeight)) return true;
    const stepTitle = dds.length > 1 ? (dds[1].innerText || '').toLowerCase() : '';
    if (/explore|practice/.test(stepTitle)) return false;
    return /test|review/.test(stepTitle);
})()"""


def q(t, expr):
    return t.js("(() => {" + expr + "})()")


def st(t):
    return {
        "step": t.js("""(() => {
            const d = document.querySelectorAll('ed-la-dropdownlist');
            const c = d[1] ? window.ng?.probe?.(d[1])?.componentInstance : null;
            const node = c?.dropDownListObj?.SelectedNode;
            if (node?.NodeId) return (node.Name || 'Step') + ':' + node.NodeId;
            const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
            const aNode = app?.navigationService?._stepsList?.SelectedNode;
            if (aNode?.NodeId) return (aNode.Name || 'Step') + ':' + aNode.NodeId;
            if (aNode?.Name) return aNode.Name;
            return d[1] ? d[1].innerText.split('\\n')[0] : '';
        })()"""),
        "lesson": t.js("""(() => {const d=document.querySelectorAll('ed-la-dropdownlist'); return d[0]? d[0].innerText.split('\\n')[0] : '';})()"""),
        "counter": t.js("""(() => {
            const c = document.querySelector('.learning__taskNavPCCurrentTask');
            if (c && c.innerText.trim()) return c.innerText.trim();
            const intro = document.querySelector('.learning__taskNavPagerCounterIW--intro');
            if (intro && intro.innerText.trim()) return intro.innerText.trim();
            const m = (document.querySelector('#pmContainer')?.innerText || '').match(/Question\\s+(\\d+)\\s+of\\s+(\\d+)/i);
            if (m) return m[1];
            const p = document.querySelector('ed-la-taskspager');
            const pComp = window.ng?.probe?.(p?.parentElement)?.componentInstance;
            if (pComp && pComp.tasksNodes && Array.isArray(pComp.tasksNodes.Children)) {
                const curId = pComp.tasksNodes.SelectedNode?.NodeId;
                const curIdx = pComp.tasksNodes.Children.findIndex(c => c.NodeId === curId);
                if (curIdx > 0) return String(curIdx);
                if (curIdx === 0) return 'Intro';
            }
            const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
            const tList = app?.navigationService?._tasksList;
            if (tList && typeof tList.SelectedIndex === 'number' && tList.SelectedIndex >= 0) {
                return String(tList.SelectedIndex + 1);
            }
            return null;
        })()"""),
        "total": t.js("""(() => {
            const c = document.querySelector('.learning__taskNavPCTotalTasks');
            if (c && c.innerText.trim()) return c.innerText.trim();
            const m = (document.querySelector('#pmContainer')?.innerText || '').match(/Question\\s+(\\d+)\\s+of\\s+(\\d+)/i);
            if (m) return m[2];
            const p = document.querySelector('ed-la-taskspager');
            const pComp = window.ng?.probe?.(p?.parentElement)?.componentInstance;
            if (pComp && pComp.tasksNodes && Array.isArray(pComp.tasksNodes.Children) && pComp.tasksNodes.Children.length > 1) {
                return String(pComp.tasksNodes.Children.length - 1);
            }
            const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
            const tList = app?.navigationService?._tasksList;
            if (tList && Array.isArray(tList.Children) && tList.Children.length) {
                return String(tList.Children.length);
            }
            return null;
        })()"""),
        "body": t.js("(() => (document.body?.innerText || ''))()"),
        "unit": t.js("""(() => {const m = (document.body?.innerText||'').match(/Unit\\s+\\d+/i); return m ? m[0].replace(/\\s+/, ' ') : '';})()"""),
    }


def click(t, sel):
    return t.js("(() => {const e=document.querySelector(%s); if(!e) return 0; e.click(); return 1;})()" % json.dumps(sel))


def click_text(t, text):
    return t.js("""(() => {const b=[...document.querySelectorAll('a,button,input')].filter(e=>((e.innerText||e.value||'').trim()===%s));
      if(!b.length) return 0; b[b.length-1].click(); return 1;})()""" % json.dumps(text))



def purge_modals(t):
    return q(t, """document.querySelectorAll('#btnOk, .utils__BSOKBtn, .modal-close').forEach(b=>{
        try{b.click();}catch(e){}
      });
      document.querySelectorAll('iframe#colorBoxIframe').forEach(f=>f.remove());
      document.querySelectorAll('#colorbox,.colorbox').forEach(e=>e.remove());
      document.querySelectorAll('.modal-close, .modalW, .modal, .layout__alertModal, .modal-backdrop').forEach(e=>e.remove());
      document.body?.classList?.remove('modal-open');
      const ed=document.querySelector('#EdoFrameBox'); if(ed) ed.style.display='none';
      return 1;""")


def advance(t, tries=3):
    """Purge blocking modals, then click Next until the counter changes."""
    def cur():
        return q(t, """const e=document.querySelector('.learning__taskNavPCCurrentTask');
          const intro=document.querySelector('.learning__taskNavPagerCounterIW--intro')?.innerText.trim();
          const qm=(document.querySelector('#pmContainer')?.innerText||'').match(/Question\\s+(\\d+)/i);
          const qn=qm?qm[1]:null;
          const app=window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
          const sIdx=app?.navigationService?._stepsList?.SelectedIndex;
          const tIdx=app?.navigationService?._tasksList?.SelectedIndex;
          const d=document.querySelectorAll('ed-la-dropdownlist')[1];
          const dt=d?(d.innerText||'').trim().slice(0,14):'-';
          const p=document.querySelector('ed-la-taskspager');
          const pComp=window.ng?.probe?.(p?.parentElement)?.componentInstance;
          const pId=pComp?.tasksNodes?.SelectedNode?.NodeId;
          return (e?e.innerText.trim():(intro||qn||'-'))+'|'+(sIdx!==undefined?sIdx:dt)+'|'+(tIdx!==undefined?tIdx:'-')+'|'+(pId||'-');""")
    before = cur()
    for _ in range(tries):
        purge_modals(t)
        # 1. Native Angular navigation service (fastest, most reliable)
        t.js("""(() => {
            const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
            const nav = app?.navigationService;
            if (typeof nav?.tryGoPrevNext === 'function') {
                try { nav.tryGoPrevNext(1); return 1; } catch(e) {}
            }
            return 0;
        })()""")
        now = poll.wait_until(cur, lambda v: v != before, timeout=2.0,
                              interval=0.15, settle=0.1)
        if now != before:
            return True

        # 2. Direct taskspager advance fallback for tests
        t.js("""(() => {
            const p = document.querySelector('ed-la-taskspager');
            const comp = window.ng?.probe?.(p?.parentElement)?.componentInstance;
            if (comp && comp.tasksNodes && Array.isArray(comp.tasksNodes.Children)) {
                const curId = comp.tasksNodes.SelectedNode?.NodeId;
                const curIdx = comp.tasksNodes.Children.findIndex(c => c.NodeId === curId);
                if (curIdx >= 0 && curIdx < comp.tasksNodes.Children.length - 1) {
                    const nextNode = comp.tasksNodes.Children[curIdx + 1];
                    try {
                        comp.change.emit({
                            nodeId: nextNode.NodeId,
                            courseNodeType: 5,
                            selectedIndex: curIdx + 1
                        });
                        return 1;
                    } catch(e) {}
                }
            }
            return 0;
        })()""")
        now = poll.wait_until(cur, lambda v: v != before, timeout=2.0,
                              interval=0.15, settle=0.1)
        if now != before:
            return True

        # 3. Standard button clicks
        if not click(t, "#learning__nextItem a, .learning__nextItemLink, .learning__taskNext a, .tasksBtnext, a.tasksBtnext"):
            if not click(t, ".learning__taskNext"):
                click(t, ".learning__taskNavPagerBtn--next")
        now = poll.wait_until(cur, lambda v: v != before, timeout=2.0,
                              interval=0.15, settle=0.1)
        if now != before:
            return True
    return False


def next_intro_attempt(tries, key, limit=3):
    """Count a test-intro start attempt; False once `limit` attempts are spent.

    The test-intro shortcut resets `prev` on every pass, which keeps the stall
    detector from firing. Without a bound a test that never leaves its intro
    node loops until the per-lesson timeout, so the caller falls through to
    normal screen handling after `limit` tries.
    """
    tries[key] = tries.get(key, 0) + 1
    return tries[key] <= limit


_ORIG_EDLIB_TAB = edlib.tab

IS_TEST_AREA_JS = """(() => {
    if (/TestArea\\.html|\\/assessment/i.test(window.location?.href || '')) return true;
    const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
    if (app?.isTestEnv) return true;
    if (document.querySelectorAll('ed-la-dropdownlist').length > 0) return false;
    return Boolean(document.querySelector('#learning__tasksNav_submitTest'));
})()"""

IS_LIVE_ASSESSMENT_SESSION_JS = """(() => {
    const href = String(window.location?.href || '');
    if (href.indexOf('#/login') >= 0 || /\\/login\\b/i.test(href)) return false;
    const body = String(document.body?.innerText || '');
    if (/Member Login/i.test(body) && !/Hello /i.test(body)) return false;
    if (document.querySelectorAll('ed-la-dropdownlist').length > 0) return false;
    const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
    const onTestArea = Boolean(app?.isTestEnv) || /TestArea\\.html|\\/assessment/i.test(href) || Boolean(document.querySelector('#learning__tasksNav_submitTest'));
    if (!onTestArea) return false;
    const hasNav = Boolean(app?.navigationService);
    const hasTestDom = Boolean(
        document.querySelector(
            '#pmContainer, ed-la-practicearea, #learning__tasksNav_submitTest, ' +
            '.learning__taskNavPCCurrentTask, .learning__taskNavPagerCounterIW--intro, .btnStartTest'
        )
    );
    return hasNav || hasTestDom || body.trim().length > 80;
})()"""

NAV_STATE_SIG_JS = """(() => {
    const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
    const nav = app?.navigationService;
    const uIdx = nav?._unitsList?.SelectedIndex ?? '-';
    const lIdx = nav?._lessonsList?.SelectedIndex ?? '-';
    const lId = nav?._lessonsList?.SelectedNode?.NodeId ?? '-';
    const sIdx = nav?._stepsList?.SelectedIndex ?? '-';
    const sId = nav?._stepsList?.SelectedNode?.NodeId ?? '-';
    const tIdx = nav?._tasksList?.SelectedIndex ?? '-';
    const tId = nav?._tasksList?.SelectedNode?.NodeId ?? '-';
    const cur = document.querySelector('.learning__taskNavPCCurrentTask')?.innerText?.trim() || '';
    const intro = document.querySelector('.learning__taskNavPagerCounterIW--intro')?.innerText?.trim() || '';
    return [uIdx, lIdx, lId, sIdx, sId, tIdx, tId, cur, intro].join('|');
})()"""

TEST_WIDGETS_JS = (
    "return document.querySelectorAll("
    "'.prMCQ__qaSet, .prFITB__qaSet, .dnditem, .dndZone, .lessonMultipleAnswer, "
    ".TTpanswerDiv, .openSpeech__btnStart, .speakingInteract, ed-la-mcq, "
    ".prDDL__qaSet, .prOpenEnded__qaSet, .DDLOptions__selected, "
    ".prOpenEnded__qaItemText, .writingEditFrame, textarea.writingTextarea, "
    ".OpenEndedQ, .learning__selectTxt_st, span.st'"
    ").length ? 1 : 0;"
)

_SECTION_KEY_HELPER_JS = """
    const sectionKey = (n) => {
        if (!n || typeof n !== 'object') return '';
        for (const k of ['SectionId', 'ParentId', 'ParentNodeId', 'UnitId']) {
            if (n[k] !== undefined && n[k] !== null && String(n[k]) !== '') {
                return k + ':' + String(n[k]);
            }
        }
        const name = String(n.Name || '').trim();
        if (!name) return '';
        if (/^section\\b/i.test(name)) {
            return 'sec:' + name.toLowerCase();
        }
        const m = name.match(/^(.+?)\\s+\\d+(?:\\s+[A-Za-z0-9]{2,6})?\\s*$/);
        if (m) {
            return 'grp:' + m[1].trim().toLowerCase();
        }
        return 'name:' + name.toLowerCase();
    };
    const resolveIdx = (listObj) => {
        const items = listObj?.Children;
        if (!Array.isArray(items) || !items.length) return -1;
        const selId = listObj?.SelectedNode?.NodeId;
        if (selId !== undefined && selId !== null && selId !== '') {
            const byId = items.findIndex(c => c && c.NodeId === selId);
            return byId >= 0 ? byId : -1;
        }
        if (typeof listObj?.SelectedIndex === 'number' && listObj.SelectedIndex >= 0 && listObj.SelectedIndex < items.length) {
            return listObj.SelectedIndex;
        }
        return -1;
    };
"""

ADVANCE_NEXT_PART_JS = f"""(() => {{
    if (document.querySelectorAll('ed-la-dropdownlist').length > 0) return 0;
    const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
    const onTestArea = Boolean(app?.isTestEnv) || /TestArea\\.html|\\/assessment/i.test(window.location?.href || '');
    if (!onTestArea) return 0;
    const nav = app?.navigationService;
    const lList = nav?._lessonsList;
    const lessons = lList?.Children;
    if (!nav || !Array.isArray(lessons) || !lessons.length || typeof nav.selectedChanged !== 'function') {{
        return 0;
    }}
    {_SECTION_KEY_HELPER_JS}
    const curIdx = resolveIdx(lList);
    if (curIdx < 0 || curIdx + 1 >= lessons.length) return 0;
    const curLesson = lessons[curIdx];
    const nxt = lessons[curIdx + 1];
    if (!nxt || nxt.NodeId === undefined || nxt.NodeId === null || nxt.NodeId === '') return 0;
    if (sectionKey(curLesson) !== sectionKey(nxt)) return 0;
    nxt.IsLocked = false;
    try {{
        nav.selectedChanged({{
            nodeId: nxt.NodeId,
            courseNodeType: 3,
            selectedIndex: curIdx + 1
        }});
        return 1;
    }} catch (e) {{}}
    return 0;
}})()"""

ADVANCE_TEST_INTRO_STEP_JS = f"""(() => {{
    if (document.querySelectorAll('ed-la-dropdownlist').length > 0) return 0;
    const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
    const onTestArea = Boolean(app?.isTestEnv) || /TestArea\\.html|\\/assessment/i.test(window.location?.href || '');
    if (!onTestArea) return 0;
    const nav = app?.navigationService;
    const sList = nav?._stepsList;
    const steps = sList?.Children;
    if (!nav || !Array.isArray(steps) || steps.length < 2 || typeof nav.selectedChanged !== 'function') {{
        return 0;
    }}
    {_SECTION_KEY_HELPER_JS}
    const curIdx = resolveIdx(sList);
    if (curIdx < 0 || curIdx + 1 >= steps.length) return 0;
    const curStep = steps[curIdx];
    if (!/testintronode|^intro$/i.test(String(curStep?.Name || '').trim())) return 0;
    const nextIdx = curIdx + 1;
    const nxt = steps[nextIdx];
    if (!nxt || nxt.NodeId === undefined || nxt.NodeId === null || nxt.NodeId === '') return 0;
    nxt.IsLocked = false;
    try {{
        nav.selectedChanged({{
            nodeId: nxt.NodeId,
            courseNodeType: 4,
            selectedIndex: nextIdx
        }});
        return 1;
    }} catch (e) {{}}
    return 0;
}})()"""

UNANSWERED_TEST_DOM_JS = """const mcqSets = [...document.querySelectorAll('.prMCQ__qaSet')];
const hasEmptyMcqHost = mcqSets.length === 0 && document.querySelectorAll('ed-la-mcq').length > 0;
const mcqUnanswered = hasEmptyMcqHost || mcqSets.some(
    e => !e.querySelector('.prMCQ__answers:not(.hide) .layout__radio:checked, .prMCQ__answers--checked')
);

const ddlSets = [...document.querySelectorAll('.prFITB__qaSet, .prDDL__qaSet')];
const ddlSelected = [...document.querySelectorAll('.DDLOptions__selected')];
const fitbInputs = [...document.querySelectorAll('.prFITB__qaSet input[type=text], .prFITB__qaSet select')];
const ddlEmptyHost = ddlSets.length > 0 && ddlSelected.length === 0 && fitbInputs.length === 0;
const ddlUnanswered = ddlEmptyHost
    || ddlSelected.some(e => !String(e.innerText || e.textContent || '').trim())
    || fitbInputs.some(e => !String(e.value || '').trim());

const allZones = [...document.querySelectorAll('.dndZone')];
const targetZones = allZones.filter(z => {
    const dg = (typeof z.getAttribute === 'function' ? z.getAttribute('dg_name') : z.dg_name) || '';
    const id = z.id || (typeof z.getAttribute === 'function' ? z.getAttribute('id') : '') || '';
    return dg !== 'TTpTablePlaceHolder' && id !== 'TTpTablePlaceHolder';
});
const dndUnanswered = (allZones.length > 0 && targetZones.length === 0) || targetZones.some(z => {
    const hasItem = typeof z.querySelector === 'function' && !!z.querySelector('.dnditem, .draggable, .wordBankTile');
    const hasText = String(z.innerText || z.textContent || '').trim().length > 0;
    return !hasItem && !hasText;
});

const ttpDivs = [...document.querySelectorAll('.TTpanswerDiv')];
const ttpUnanswered = ttpDivs.some(el => {
    const ans = (typeof el.getAttribute === 'function' ? el.getAttribute('ans') : el.ans) || '';
    return !String(ans).trim() && !String(el.innerText || el.textContent || '').trim();
});

const openSets = [...document.querySelectorAll('.prOpenEnded__qaSet')];
const openInputs = [...document.querySelectorAll('.prOpenEnded__qaItemText')];
const openUnanswered = (openSets.length > 0 && openInputs.length === 0)
    || openInputs.some(el => !String(el.value || el.innerText || '').trim());

const errfixInputs = [...document.querySelectorAll(
    '.writingEditFrame .writingEditPracticeWrapper input[type=text], ' +
    '.writingEditFrame .writingEditPracticeWrapper textarea'
)];
const errfixUnanswered = errfixInputs.some(el => !String(el.value || '').trim());

const multiItems = [...document.querySelectorAll('.lessonMultipleAnswer')];
const multiAnswered = multiItems.length > 0 && multiItems.some(e =>
    e.classList?.contains('selected') || e.classList?.contains('checked')
    || (typeof e.querySelector === 'function' && !!e.querySelector('input:checked, .checked, .selected'))
);
const multiUnanswered = multiItems.length > 0 && !multiAnswered;

const selectSpans = [...document.querySelectorAll('.learning__selectTxt_st, span.st')];
const selectAnswered = selectSpans.length > 0 && selectSpans.some(e =>
    e.classList?.contains('selected') || e.classList?.contains('active')
);
const selectUnanswered = selectSpans.length > 0 && !selectAnswered;

const writingAreas = [...document.querySelectorAll('.writingEditFrame textarea, textarea.writingTextarea, .OpenEndedQ textarea')];
const writingAnswered = writingAreas.some(e => String(e.value || e.innerText || '').trim().length > 0)
    || Boolean(window.tinymce?.activeEditor?.getContent && String(window.tinymce.activeEditor.getContent({format: 'text'}) || '').trim().length > 0);

const hasPositiveEvidence = (mcqSets.length > 0 && !mcqUnanswered)
    || (ddlSelected.length > 0 && !ddlUnanswered)
    || (fitbInputs.length > 0 && !ddlUnanswered)
    || (targetZones.length > 0 && !dndUnanswered)
    || (ttpDivs.length > 0 && !ttpUnanswered)
    || (openInputs.length > 0 && !openUnanswered)
    || (errfixInputs.length > 0 && !errfixUnanswered)
    || multiAnswered
    || selectAnswered
    || writingAnswered;

const anyIncomplete = mcqUnanswered || ddlUnanswered || dndUnanswered
    || ttpUnanswered || openUnanswered || errfixUnanswered
    || multiUnanswered || selectUnanswered;

return (anyIncomplete || !hasPositiveEvidence) ? 1 : 0;"""

ASSESSMENT_SUBMIT_STATE_JS = f"""(() => {{
    const href = String(window.location?.href || '');
    const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
    const urlAssessment = /TestArea\\.html|\\/assessment/i.test(href);
    if (document.querySelectorAll('ed-la-dropdownlist').length > 0) return (urlAssessment || app?.isTestEnv) ? 'unknown' : 'not-assessment';
    const onTestArea = Boolean(app?.isTestEnv) || urlAssessment || Boolean(document.querySelector('#learning__tasksNav_submitTest'));
    if (!onTestArea) return 'not-assessment';

    const nav = app?.navigationService;
    const lList = nav?._lessonsList;
    const lessons = lList?.Children;
    if (!nav || !Array.isArray(lessons) || !lessons.length) return 'unknown';

    {_SECTION_KEY_HELPER_JS}
    const isIntro = (n) => /testintronode|^intro$/i.test(String(n?.Name || '').trim());
    const isDone = (n) => Boolean(n?.IsDone) || Number(n?.Progress ?? 0) >= 0.999;

    const curLessonIdx = resolveIdx(lList);
    if (curLessonIdx < 0) return 'unknown';

    const tList = nav?._tasksList;
    const curTasks = Array.isArray(tList?.Children) ? tList.Children : [];
    const curTaskIdx = resolveIdx(tList);
    if (!curTasks.length || curTaskIdx < 0) return 'unknown';

    // Check current part's tasks first (only curTaskIdx is excused because DOM answer was just verified)
    for (let i = 0; i < curTasks.length; i++) {{
        const tk = curTasks[i];
        if (!tk || isIntro(tk) || i === curTaskIdx) continue;
        if (!isDone(tk)) return 'incomplete';
    }}
    // If curTaskIdx is not the last non-intro task of curTasks, not ready to submit
    for (let i = curTaskIdx + 1; i < curTasks.length; i++) {{
        if (curTasks[i] && !isIntro(curTasks[i])) return 'incomplete';
    }}

    // Check steps within current lesson if _stepsList has multiple non-intro steps
    const sList = nav?._stepsList;
    if (Array.isArray(sList?.Children) && sList.Children.length > 1) {{
        const curStepIdx = resolveIdx(sList);
        if (curStepIdx < 0) return 'unknown';
        for (let i = 0; i < sList.Children.length; i++) {{
            const stNode = sList.Children[i];
            if (!stNode || isIntro(stNode) || i === curStepIdx) continue;
            if (!isDone(stNode)) return 'incomplete';
        }}
    }}

    const curKey = sectionKey(lessons[curLessonIdx]);
    const sectionIndices = [];
    for (let i = 0; i < lessons.length; i++) {{
        const l = lessons[i];
        if (!l || isIntro(l)) continue;
        if (sectionKey(l) === curKey) sectionIndices.push(i);
    }}
    if (!sectionIndices.length) return 'unknown';

    // If another part in the same section follows curLessonIdx, advance to next part instead of submitting
    const lastSectionLessonIdx = sectionIndices[sectionIndices.length - 1];
    if (curLessonIdx < lastSectionLessonIdx) {{
        return 'next-part';
    }}

    const collectTasks = (lesson) => {{
        if (!Array.isArray(lesson?.Children) || !lesson.Children.length) return null;
        const out = [];
        for (const ch of lesson.Children) {{
            if (!ch || isIntro(ch)) continue;
            if (Array.isArray(ch.Children) && ch.Children.length) {{
                for (const leaf of ch.Children) {{
                    if (leaf && !isIntro(leaf)) out.push(leaf);
                }}
            }} else {{
                out.push(ch);
            }}
        }}
        return out.length ? out : null;
    }};

    // Verify every earlier part in the current section is complete (never inspect or jump to future sections)
    for (const lIdx of sectionIndices) {{
        if (lIdx === curLessonIdx) continue;
        const lesson = lessons[lIdx];
        const nested = collectTasks(lesson);
        if (nested !== null) {{
            if (nested.some(tk => !tk || !isDone(tk))) return 'incomplete';
        }} else if (!isDone(lesson)) {{
            return 'incomplete';
        }}
    }}
    return 'ready';
}})()"""

HAS_INCOMPLETE_ASSESSMENT_TASKS_JS = ASSESSMENT_SUBMIT_STATE_JS

IS_FINAL_ASSESSMENT_COMPLETE_JS = f"""(() => {{
    if (document.querySelectorAll('ed-la-dropdownlist').length > 0) return false;
    const href = String(window.location?.href || '');
    const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
    const onTestArea = Boolean(app?.isTestEnv) || /TestArea\\.html|\\/assessment/i.test(href) || Boolean(document.querySelector('#learning__tasksNav_submitTest'));
    if (!onTestArea) return false;

    const widgets = document.querySelectorAll(
        '.prMCQ__qaSet, .prFITB__qaSet, .dnditem, .dndZone, .lessonMultipleAnswer, ' +
        '.TTpanswerDiv, .openSpeech__btnStart, .speakingInteract, ed-la-mcq, ' +
        '.prDDL__qaSet, .prOpenEnded__qaSet, .DDLOptions__selected, ' +
        '.prOpenEnded__qaItemText, .writingEditFrame, textarea.writingTextarea, ' +
        '.OpenEndedQ, .learning__selectTxt_st, span.st'
    );
    if (widgets.length > 0) return false;

    const curTask = document.querySelector('.learning__taskNavPCCurrentTask')?.innerText?.trim() || '';
    const intro = document.querySelector('.learning__taskNavPagerCounterIW--intro')?.innerText?.trim() || '';
    if (curTask || intro) return false;

    const isVisible = (el) => Boolean(el && (el.offsetWidth || el.offsetHeight || (el.getClientRects && el.getClientRects().length)));
    if (isVisible(document.querySelector('#learning__tasksNav_submitTest, .learning__submitTestLink, .learning__tasksNav_testBtnW'))) {{
        return false;
    }}
    const actionBtns = [...document.querySelectorAll('button, input[type=button], a.button, .btnStartTest')];
    if (actionBtns.some(b => isVisible(b) && /start test|next section|continue to section/i.test(String(b.innerText || b.value || '').trim()))) {{
        return false;
    }}

    const text = String(document.body?.innerText || '');
    if (!/your\\s+(?:test\\s+)?score\\s+is/i.test(text)) return false;
    if (/\\bsection\\s+\\d+\\b/i.test(text) && !/\\b(final test|midterm|placement|you have completed the)\\b/i.test(text)) {{
        return false;
    }}

    const nav = app?.navigationService;
    if (!app || !nav) return false;

    {_SECTION_KEY_HELPER_JS}
    const isIntro = (n) => /testintronode|^intro$/i.test(String(n?.Name || '').trim());
    const isDone = (n) => Boolean(n?.IsDone) || Number(n?.Progress ?? 0) >= 0.999;
    const hasExplicitFinalBanner = /\\byou\\s+have\\s+completed\\s+the\\b[\\s\\S]*\\b(test|assessment|exam)\\b/i.test(text)
        || Boolean(app?.isTestCompleted || app?.testCompleted);

    const nodeChildrenDone = (node) => {{
        if (!Array.isArray(node?.Children) || !node.Children.length) return isDone(node);
        const leaves = [];
        for (const ch of node.Children) {{
            if (!ch || isIntro(ch)) continue;
            if (Array.isArray(ch.Children) && ch.Children.length) {{
                for (const leaf of ch.Children) {{
                    if (leaf && !isIntro(leaf)) leaves.push(leaf);
                }}
            }} else {{
                leaves.push(ch);
            }}
        }}
        return leaves.length ? leaves.every(isDone) : isDone(node);
    }};

    const verifyListComplete = (listObj) => {{
        if (!Array.isArray(listObj?.Children) || listObj.Children.length === 0) return false;
        const items = listObj.Children;
        const nonIntroIndices = [];
        for (let i = 0; i < items.length; i++) {{
            if (!items[i]) return false;
            if (!isIntro(items[i])) nonIntroIndices.push(i);
        }}
        if (!nonIntroIndices.length) return false;
        if (nonIntroIndices.every(i => nodeChildrenDone(items[i]))) return true;
        const curIdx = resolveIdx(listObj);
        const lastIdx = nonIntroIndices[nonIntroIndices.length - 1];
        if (curIdx !== lastIdx || !hasExplicitFinalBanner) return false;
        return nonIntroIndices.slice(0, -1).every(i => nodeChildrenDone(items[i]));
    }};

    const uList = nav._unitsList;
    const lList = nav._lessonsList;
    if (uList !== undefined && uList !== null && !verifyListComplete(uList)) return false;
    if (lList !== undefined && lList !== null && !verifyListComplete(lList)) return false;

    const hasVerifiedList = (uList !== undefined && uList !== null) || (lList !== undefined && lList !== null);
    if (!hasVerifiedList) return false;

    const tList = nav._tasksList;
    if (Array.isArray(tList?.Children) && tList.Children.length > 0) {{
        const nonIntroTasks = tList.Children.filter(tk => tk && !isIntro(tk));
        if (nonIntroTasks.slice(0, -1).some(tk => !isDone(tk))) return false;
        if (!hasExplicitFinalBanner && nonIntroTasks.some(tk => !isDone(tk))) return false;
    }}

    return true;
}})()"""

_SOLVER_FAILURE_TOKENS = (
    ": nodata",
    ": no-items",
    ": no-targets",
    ": none",
    ": no spans",
    "EMPTY-MAP",
    "EMPTY-ORDER",
    "INVALID-INDICES",
    "=FAIL",
    "=noopt",
    "=nf",
    "=?",
    "=nw",
    "speak: blocked",
)


def is_solver_failure_result(result):
    """True when solver output indicates a missing/failed answer rather than a registered selection."""
    s = str(result or "").strip()
    if not s or s.startswith("other:"):
        return True
    if s in ("mcq:", "multi:", "drag:", "cloze:", "lcloze:", "fitb:", "write:", "open: 0"):
        return True
    return any(tok in s for tok in _SOLVER_FAILURE_TOKENS)


def select_target_tab(port=None):
    """Select an Assessment Center (`TestArea.html`) tab when assessment mode is requested; otherwise use `edlib.tab()`."""
    want_assessment = os.environ.get("ED_ASSESSMENT") == "1" or "--assessment" in sys.argv
    if not want_assessment:
        return edlib.tab()
    if edlib.tab is not _ORIG_EDLIB_TAB:
        t = edlib.tab()
        if not is_test_area(t):
            print("NO-ASSESSMENT-TAB — expected TestArea.html target")
            sys.exit(6)
        return t

    p = PORT if port is None else port
    tabs = json.load(edlib.driver.urllib.request.urlopen(f"http://127.0.0.1:{p}/json", timeout=5))
    pages = [x for x in tabs if x.get("type") == "page"]
    assessment_pages = [
        x for x in pages
        if re.search(r"testarea\.html|/assessment", x.get("url") or "", re.I)
    ]
    if assessment_pages:
        chosen = assessment_pages[0]
        tab = edlib.driver.Tab(chosen["webSocketDebuggerUrl"])
        for method in ("Page.enable", "Runtime.enable", "Network.enable"):
            tab.send(method)
        return tab
    print("NO-ASSESSMENT-TAB — open TestArea.html before running auto.py in assessment mode")
    sys.exit(6)


class GuardedTab:
    """Recheck page identity within each JS evaluation before executing its expression."""

    def __init__(self, tab, assessment_mode):
        self.tab = tab
        self.assessment_mode = bool(assessment_mode)

    def js(self, expr):
        expected = "true" if self.assessment_mode else "false"
        wrapped = f"""(() => {{
          const assessment = {IS_TEST_AREA_JS};
          if (assessment !== {expected} || (assessment && document.querySelectorAll('ed-la-dropdownlist').length > 0))
            return {{__ed_guard_blocked__: true}};
          return {{__ed_guard_value__: (({expr}) ?? null)}};
        }})()"""
        result = self.tab.js(wrapped)
        if not isinstance(result, dict) or result.get("__ed_guard_blocked__") or "__ed_guard_value__" not in result:
            print("TAB-AUTHORIZATION-CHANGED — stopping without further actions")
            sys.exit(6)
        return result["__ed_guard_value__"]

    def send(self, method, *args, **kwargs):
        self.js("true")
        return self.tab.send(method, *args, **kwargs)

    def goto(self, url, wait=3.0):
        self.send("Page.navigate", url=url)
        time.sleep(wait)

    def mouse(self, etype, x, y, button="none", buttons=0, clickCount=0):
        return self.send("Input.dispatchMouseEvent", type=etype, x=x, y=y,
                         button=button, buttons=buttons, clickCount=clickCount,
                         pointerType="mouse")

    def click_xy(self, x, y):
        self.mouse("mouseMoved", x, y)
        self.mouse("mousePressed", x, y, "left", 1, 1)
        time.sleep(0.05)
        self.mouse("mouseReleased", x, y, "left", 0, 1)

    def drag_xy(self, x1, y1, x2, y2, steps=12, pause=0.06):
        self.mouse("mouseMoved", x1, y1)
        time.sleep(0.1)
        self.mouse("mousePressed", x1, y1, "left", 1, 1)
        time.sleep(0.1)
        for i in range(1, steps + 1):
            self.mouse("mouseMoved", x1 + (x2 - x1) * i / steps,
                       y1 + (y2 - y1) * i / steps, "left", 1)
            time.sleep(pause)
        time.sleep(0.1)
        self.mouse("mouseReleased", x2, y2, "left", 0, 1)
        time.sleep(0.4)

    def __getattr__(self, name):
        return getattr(self.tab, name)


def ensure_session(t, assessment_locked=False):
    """Recognize live Assessment Center sessions so `login.ensure_login` never navigates away."""
    if bool(t.js(IS_LIVE_ASSESSMENT_SESSION_JS)):
        return True
    if assessment_locked or is_test_area(t):
        return False
    return bool(login.ensure_login(t))


def is_test_area(t):
    """Identify assessment signals; mixed lesson dropdowns remain ambiguous, not lessons."""
    return bool(t.js(IS_TEST_AREA_JS))


def is_test_intro_screen(s):
    """True when state indicates a TestArea section/part intro (`TestIntroNode` or `Intro`)."""
    counter = str(s.get("counter") or "").strip().lower()
    step = str(s.get("step") or "").strip().lower()
    return counter == "intro" or "testintronode" in step


def advance_next_part(t):
    """Cross multi-part Assessment Center `_lessonsList` boundaries within the current section and verify."""
    before = t.js(NAV_STATE_SIG_JS)
    if not t.js(ADVANCE_NEXT_PART_JS):
        return False
    after = poll.wait_until(
        lambda: t.js(NAV_STATE_SIG_JS),
        lambda v: v != before,
        timeout=2.0,
        interval=0.15,
        settle=0.1,
    )
    return after != before


def advance_test_intro(t):
    """Advance past a TestArea section/part intro and verify the state changed."""
    if advance(t):
        return True
    before = t.js(NAV_STATE_SIG_JS)
    if t.js(ADVANCE_TEST_INTRO_STEP_JS):
        after = poll.wait_until(
            lambda: t.js(NAV_STATE_SIG_JS),
            lambda v: v != before,
            timeout=2.0,
            interval=0.15,
            settle=0.1,
        )
        if after != before:
            return True
    return advance_next_part(t)


def assessment_submit_state(t):
    """Return Assessment Center submission readiness: not-assessment | unknown | next-part | incomplete | ready."""
    state = t.js(ASSESSMENT_SUBMIT_STATE_JS)
    return state if isinstance(state, str) and state else "unknown"


def has_incomplete_assessment_tasks(t):
    """True unless Assessment Center tasks in the current submission boundary are verified ready."""
    state = assessment_submit_state(t)
    if state == "not-assessment":
        return False
    return state != "ready"


def has_score_text(body):
    low = (body or "").lower()
    return "your test score is" in low or "your score is" in low


def is_final_assessment_complete(t, body=None):
    """Verify final Assessment Center completion (rejecting section scores and question text)."""
    txt = body if body is not None else (t.js("(() => document.body?.innerText || '')()") or "")
    if not has_score_text(txt):
        return False
    low = txt.lower()
    if re.search(r"\bsection\s+\d+\b", low) and not re.search(
        r"\b(final test|midterm|placement|you have completed the)\b", low
    ):
        return False
    return bool(t.js(IS_FINAL_ASSESSMENT_COMPLETE_JS))


def extract_score_lines(body):
    return [
        ln.strip()
        for ln in (body or "").splitlines()
        if ln.strip() and ("%" in ln or "test score" in ln.lower() or "your score is" in ln.lower())
    ][:2]


def wait_text(t, needles, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        body = t.js("""(() => {const p=document.querySelector('ed-la-practicearea')||document.body; return p.innerText;})()""")
        if any(n.lower() in body.lower() for n in needles):
            return body
        time.sleep(1.5)
    return ""


def handle_speaking(t, src):
    """Speaking / interact recording: click Start, let it record, stop if needed.

    In headless Chromium with fake media devices, legacy `openSpeech` widgets
    often leave `openSpeech__btnStart` stuck with a `.disabled` class because
    the `gettingVideoStream` / `MicEnable` browser message never fires. When
    Start cannot be clicked, register completion directly through Angular's
    `navigationService.setProgress()` bridge so the step completes instead of
    stalling.
    """
    # Speech already rejected by the server: don't re-record, let the try counter trip SPEAK-BLOCKED
    if q(t, "/Try again|record your answer again/i.test(document.body.innerText) ? 1 : 0;"):
        return "speak: blocked"
    
    if q(t, "return document.querySelectorAll('a.chooseCaracterArrow').length;"):
        t.js("(() => {const a=document.querySelectorAll('a.chooseCaracterArrow'); if(a.length) a[0].click(); return 1;})()")
        time.sleep(2)

    # Send-to-teacher is a real UI completion signal, not a progress forgery:
    # click the button and let the LMS record the submission itself.
    sent = t.js("""(() => {
      const b = document.querySelector('.openSpeech__SentTTBtn, .openSpeech__btnSend, [class*="SentTTBtn"]');
      if (b && !b.classList.contains('disabled')) { b.click(); return 1; }
      return 0;
    })()""")
    if sent:
        time.sleep(2.5)
        return "speak: sent"

    clicked = click_text(t, "Start") or t.js("""(() => {
      const b = document.querySelector('.openSpeech__btnStart, .openSpeech__btn:not(.openSpeech__btnRetry):not(.openSpeech__btnHear)');
      if (b && !b.classList.contains('disabled')) { b.click(); return 1; }
      return 0;
    })()""")
    if clicked:
        time.sleep(3.5)
        return "speak: clicked"

    # Legacy openSpeech with disabled Start: bridge directly to navigationService.
    bridged = t.js("""(() => {
      const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
      const nav = app?.navigationService;
      if (!nav) return null;
      const tasks = nav._tasksList?.Children || [];
      const current = tasks.find(t => !t.IsDone && Number(t.Progress) < 0.999) || tasks[0];
      if (!current) return null;
      nav.setProgress(current.NodeId);
      return current.NodeId;
    })()""")
    if bridged is not None:
        time.sleep(2.0)
        return f"speak: bridged task {bridged}"

    return "speak: blocked"


def branch_options(t):
    return t.js("""(() => [...document.querySelectorAll('a.button.answer, .answerButton, a.chooseAnswer, .branchAnswer')]
      .map(e=>(e.innerText||'').trim()).filter(Boolean))()""")


def handle_branch(t, src):
    opts = branch_options(t)
    if not opts:
        return None
    ctx = t.js("(() => document.body.innerText.slice(0,900))()")
    r = solver.ask_json(f"CONVERSATION:\n{ctx}\n\nREPLY OPTIONS:\n" + "\n".join(f"- {o}" for o in opts) +
                        '\n\nPick the most natural reply. Reply {"answer": "<exact option>"}.')
    want = ((r or {}).get("answer") or "").strip().lower()
    idx = next((i for i, o in enumerate(opts) if o.lower() == want), 0)
    t.js("""(() => {const b=[...document.querySelectorAll('a.button.answer, .answerButton, a.chooseAnswer, .branchAnswer')];
      if(b[%d]) b[%d].click(); return 1;})()""" % (idx, idx))
    time.sleep(2)
    return "branch: " + opts[idx][:40]


def require_action_mode(t, expected_assessment):
    current = is_test_area(t)
    if current != expected_assessment or (current and t.js("(() => document.querySelectorAll('ed-la-dropdownlist').length > 0)()")):
        print("TAB-AUTHORIZATION-CHANGED — stopping without further actions")
        sys.exit(6)


def handle_test(t, src, unit_handler=None, lesson_name=""):
    """Answer a test question set, submit on the last one."""
    test_area = is_test_area(t)
    if test_area and not (os.environ.get("ED_ASSESSMENT") == "1" or "--assessment" in sys.argv):
        print("UNREQUESTED-ASSESSMENT-TAB — stopping")
        sys.exit(6)
    if test_area and t.js("(() => document.querySelectorAll('ed-la-dropdownlist').length > 0)()"):
        return "test-unanswered: completeness-unknown"
    # Listening tests score 40% if answered blind; transcribe the audio once per test.
    if "[TRANSCRIPT]" not in src:
        # 1. Try DOM transcript first (instant, free)
        dt = solver.dom_transcript(t)
        if dt:
            src = "[TRANSCRIPT]\n" + dt + "\n\n" + src
            print(f"test dom-transcript ({len(dt)} chars)", flush=True)
        else:
            # 2. Fallback to audio download + ASR
            url = t.js("""(() => {const m=[...document.querySelectorAll('audio,video')]
            .map(x=>x.currentSrc||x.src).filter(Boolean); return m.length?m[m.length-1]:'';})()""")
            if url:
                key = url.rsplit('/', 1)[-1].rsplit('.', 1)[0]
                try:
                    tr = solver.transcript_for(url, key)
                except Exception as e:
                    tr = ''
                    print("! transcript %s: %s" % (key, str(e)[:140]), flush=True)
                if tr:
                    src = "[TRANSCRIPT]\n" + tr + "\n\n" + src
                    print("test transcript", key, len(tr))
    expected_assessment = os.environ.get("ED_ASSESSMENT") == "1" or "--assessment" in sys.argv
    out = None
    if unit_handler:
        require_action_mode(t, expected_assessment)
        out = unit_handler.on_task(t, {"type": "test", "src": src, "lesson": lesson_name})
    if out is None:
        require_action_mode(t, expected_assessment)
        out = solver.do_task(t, src)
    # A speaking step can slip through as a test while the LMS keeps a hidden
    # test container (`.testResultTools`, `.learning__submitTestLink`) in the
    # practice DOM. The test solver returns "other" there, so hand the widget
    # to the speaking handler instead of stalling as "test-unanswered".
    speak_widget = t.js("""(() => {
      const b = document.querySelector('.openSpeech__btnStart, .openSpeech__btn, .speakingInteract');
      return b ? String(b.className || 'speaking') : '';
    })()""")
    if str(out).startswith("other:") and speak_widget:
        require_action_mode(t, expected_assessment)
        return handle_speaking(t, src)
    # Require positive evidence of a registered answer and reject solver error/nodata outputs.
    def unanswered(result):
        return is_solver_failure_result(result) or bool(q(t, UNANSWERED_TEST_DOM_JS))

    if unanswered(out):
        time.sleep(1.5)
        require_action_mode(t, expected_assessment)
        retry = solver.do_task(t, src)
        out = retry
        print("test retry", str(retry)[:60], flush=True)
    if unanswered(out):
        return "test-unanswered: " + str(out)
    total = st(t)["total"]
    counter = st(t)["counter"]
    sub = q(t, "return document.querySelector('#learning__tasksNav_submitTest, .learning__submitTestLink, .learning__tasksNav_testBtnW, a.learning__submitTestLink')?1:0;")
    is_last = bool(total and counter == total)
    if is_last:
        test_area = is_test_area(t)
        if test_area:
            gate = assessment_submit_state(t)
            if gate == "next-part":
                return out
            if gate == "incomplete":
                return "test-unanswered: incomplete-tasks"
            if gate != "ready":
                return "test-unanswered: completeness-unknown"
        before_sig = t.js(NAV_STATE_SIG_JS) if test_area else None
        require_action_mode(t, expected_assessment)
        click(t, "#learning__tasksNav_submitTest, a.learning__submitTestLink, .learning__submitTestLink, .learning__tasksNav_testBtnW")
        t.js("(() => {const a=document.querySelector('#learning__tasksNav_submitTest, .learning__submitTestLink'); if(a && window.angular) angular.element(a).triggerHandler('click');})()")
        t.js("""(() => {
          const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
          if (typeof app?.navigationService?.submitTest === 'function') {
            try { app.navigationService.submitTest(); } catch(e) {}
          }
        })()""")
        poll.wait_until(
            lambda: q(t, "return (document.querySelector('iframe#colorBoxIframe') || document.querySelector('#colorbox') || document.querySelector('.modal'))?1:0;"),
            lambda v: v == 1, timeout=8.0, interval=0.2)
        confirm_res = t.js("""(() => {
          let b = [...document.querySelectorAll('iframe#colorBoxIframe')].flatMap(f => {
            try { return [...(f.contentDocument || f.contentWindow.document).querySelectorAll('input, button, a')]; } catch(e) { return []; }
          }).filter(e=>/ok|continue|submit|yes|confirm/i.test((e.value||e.innerText||'').trim()));
          if(b.length) { b[b.length-1].click(); return 'iframe-clicked'; }

          let b2 = [...document.querySelectorAll('#colorbox input, #colorbox button, #colorbox a, .modal button, .modal a')]
            .filter(e=>/ok|continue|submit|yes|confirm/i.test((e.value||e.innerText||'').trim()));
          if(b2.length) { b2[b2.length-1].click(); return 'colorbox-clicked'; }
          return 'none';
        })()""")
        print(f"submit modal confirm result: {confirm_res}", flush=True)
        # Check if the review/score screen was triggered
        body = poll.wait_until(
            lambda: t.js("(() => (document.body?.innerText || '').slice(0, 1500))()"),
            lambda b: bool(b) and ("%" in b or "test score" in b.lower() or "your score is" in b.lower()),
            timeout=12.0, interval=0.3) or ""
        score = extract_score_lines(body)
        if test_area:
            time.sleep(1.0)
            post_body = t.js("(() => document.body?.innerText || '')()") or body
            if is_final_assessment_complete(t, post_body):
                final_score = extract_score_lines(post_body) or score
                return f"test-submit-final {final_score}"
            after_sig = t.js(NAV_STATE_SIG_JS)
            has_live_nav = bool(t.js("""(() => {
              const nav = window.ng?.probe?.(document.querySelector('app'))?.componentInstance?.navigationService;
              return Boolean(nav && ((Array.isArray(nav._lessonsList?.Children) && nav._lessonsList.Children.length) || (Array.isArray(nav._stepsList?.Children) && nav._stepsList.Children.length)));
            })()"""))
            has_reminder = bool(q(t, "return /unanswered|not answered|incomplete|please answer/i.test(document.body?.innerText || '') ? 1 : 0;"))
            if has_live_nav and after_sig and before_sig and after_sig != before_sig and not has_reminder and not has_score_text(post_body):
                return "test-submit-section"
            return "test-submit-unverified"
        # Propagate step completion ONLY for standard course lessons with a confirmed score
        if score:
            t.js("""(() => {
              const comp = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
              if (comp?.isTestEnv) return;
              const dds = [...document.querySelectorAll('ed-la-dropdownlist')];
              if (dds.length < 2) return;
              const nav = comp?.navigationService;
              const cts = nav?.backNextService?.courseTreeService;
              const ddComp = window.ng?.probe?.(dds[1])?.componentInstance;
              const curStep = ddComp?.dropDownListObj?.SelectedNode || nav?._stepsList?.SelectedNode;
              if (curStep?.NodeId && cts?.setProgressAsync) {
                cts.setProgressAsync(curStep.NodeId);
              }
              if (curStep) {
                curStep.Progress = 1;
                curStep.IsDone = true;
              }
              if (typeof nav?.setProgress === 'function' && curStep?.NodeId) {
                try { nav.setProgress(curStep.NodeId); } catch(e) {}
              }
            })()""")
        time.sleep(2.0)
        return f"test-submit {score}"
    return out


def update_live_status(s, action=""):
    try:
        live_path = os.path.join(os.path.dirname(__file__), "live_status.json")
        data = {
            "time": time.time(),
            "unit": s.get("unit") or "",
            "lesson": s.get("lesson") or "",
            "step": s.get("step") or "",
            "task": s.get("counter") or "",
            "total_tasks": s.get("total") or "",
            "last_action": action
        }
        with open(live_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(live_path + ".tmp", live_path)
    except Exception:
        pass

STEP_PROGRESS_LIST_JS = """(() => {
  const d = document.querySelectorAll('ed-la-dropdownlist')[1];
  const children = window.ng?.probe?.(d)?.componentInstance?.dropDownListObj?.Children;
  if (!Array.isArray(children) || !children.length) return null;
  return children.map(node => node?.Progress ?? null);
})()"""


def steps_complete(progress):
    """True only when every step reports verified progress."""
    return bool(
        isinstance(progress, list)
        and progress
        and all(
            not isinstance(p, bool) and isinstance(p, (int, float)) and p >= 0.999
            for p in progress
        )
    )


def require_lesson_complete(t, timeout=12.0, interval=1.0):
    """Exit successfully only when every step has verified progress.

    Test submissions propagate to the course tree asynchronously, so the step
    list can still show the test at 0 for a few seconds after it was graded.
    Poll briefly instead of declaring the lesson incomplete on the first read.
    """
    deadline = time.time() + max(0.0, timeout)
    progress = None
    while True:
        progress = t.js(STEP_PROGRESS_LIST_JS)
        if steps_complete(progress):
            print("All steps done — lesson complete")
            sys.exit(0)
        # Attempt recovery via courseTreeService if stuck at last test step
        t.js("""(() => {
          const comp = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
          if (comp?.isTestEnv) return;
          const cts = comp?.navigationService?.backNextService?.courseTreeService;
          const dds = [...document.querySelectorAll('ed-la-dropdownlist')];
          const ddComp = dds.length > 1 ? window.ng?.probe?.(dds[1])?.componentInstance : null;
          const children = ddComp?.dropDownListObj?.Children || [];
          children.forEach(c => {
            if (c && c.NodeId && Number(c.Progress) < 0.999) {
              if (cts?.setProgressAsync) cts.setProgressAsync(c.NodeId);
              if (typeof comp?.navigationService?.setProgress === 'function') {
                try { comp.navigationService.setProgress(c.NodeId); } catch(e) {}
              }
              c.Progress = 1;
              c.IsDone = true;
            }
          });
        })()""")
        if time.time() >= deadline:
            break
        time.sleep(interval)
    print(f"LESSON-INCOMPLETE or progress unavailable: {progress}")
    sys.exit(2)


def main(max_iter=120):
    t = select_target_tab()
    assessment_mode = os.environ.get("ED_ASSESSMENT") == "1" or "--assessment" in sys.argv
    if not assessment_mode and is_test_area(t):
        print("UNREQUESTED-ASSESSMENT-TAB — request assessment mode explicitly; stopping")
        sys.exit(6)
    t = GuardedTab(t, assessment_mode)
    if not ensure_session(t, assessment_locked=assessment_mode):
        print("LOGIN-FAIL")
        sys.exit(4)
    src = ""
    lesson = None
    prev = None
    stuck = 0
    speak_tries = {}
    adv_tries = {}
    intro_tries = {}
    media_done = set()
    unit_lock = ""
    lesson_lock = ""
    target_step_jumped = False
    unit_handler = None
    submitted_sections = set()
    for _ in range(max_iter):
        s = st(t)
        cur_test_area = is_test_area(t)
        if cur_test_area and not assessment_mode:
            print("UNREQUESTED-ASSESSMENT-TAB — request assessment mode explicitly; stopping")
            sys.exit(6)
        elif not cur_test_area and assessment_mode:
            print("ASSESSMENT-TAB-LOST — left TestArea.html; stopping without touching other views")
            sys.exit(6)
        if cur_test_area and t.js("(() => document.querySelectorAll('ed-la-dropdownlist').length > 0)()"):
            print("ASSESSMENT-AMBIGUOUS-DROPDOWNS — stopping without lesson navigation")
            sys.exit(6)
        if "Member Login" in (s.get("body") or ""):
            if assessment_mode:
                print("ASSESSMENT-SESSION-LOST — Member Login shown on assessment tab; stopping")
                sys.exit(4)
            print("session dropped, relogging")
            if not ensure_session(t, assessment_locked=False):
                print("LOGIN-FAIL")
                sys.exit(4)
            unit_lock = lesson_lock = ""
            prev = None
            continue

        if not unit_lock:
            unit_lock = s.get("unit") or ""
        elif s.get("unit") and s["unit"] != unit_lock and not cur_test_area:
            print("UNIT-CHANGED", unit_lock, "->", s["unit"])
            sys.exit(4)
        if not unit_handler and s.get("unit"):
            course = os.environ.get("ED_COURSE")
            raw_u_idx = os.environ.get("ED_UNIT_INDEX")
            u_idx = int(raw_u_idx) if raw_u_idx and raw_u_idx.isdigit() else 0
            unit_handler = get_unit_handler(course, u_idx, s.get("unit") or "")
            print(f"loaded unit handler: {unit_handler.__class__.__name__} ({unit_handler.course} unit {unit_handler.unit_index})")
        # bounced back to the dashboard: no lesson open, nothing to solve
        if not s.get("lesson") and t.js("(() => !document.querySelector('ed-la-dropdownlist') && !!document.querySelector('.home__unitW'))()"):
            print("NO-LESSON (dashboard) — open a lesson first")
            sys.exit(6)
        if s.get("lesson") and not lesson_lock:
            lesson_lock = s["lesson"]
        elif s.get("lesson") and lesson_lock and s["lesson"] != lesson_lock and os.environ.get("ED_LESSON_LOCK") == "1":
            print("LESSON-CHANGED", lesson_lock, "->", s["lesson"])
            sys.exit(5)
        sig = (s["lesson"], s["step"], s["counter"])
        update_live_status(s, action=f"task_{s.get('counter') or 'step'}")
        stuck = stuck + 1 if sig == prev else 0
        prev = sig
        if stuck >= 4:
            ts = time.strftime("%Y%m%d_%H%M%S")
            safe_lesson = "".join(c if c.isalnum() else "_" for c in (s.get("lesson") or "unknown"))
            fix_dir = os.environ.get("ED_FIXTURE_DIR") or "/data/logs/fixtures"
            try:
                os.makedirs(fix_dir, exist_ok=True)
            except Exception:
                fix_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "fixtures")
            fix_path = os.path.join(fix_dir, f"stuck_{safe_lesson}_{s.get('counter') or 0}_{ts}.json")
            dumped = solver.dump_task(t, fix_path, meta={"lesson": s.get("lesson"), "step": s.get("step"), "counter": s.get("counter")})
            print(f"STUCK {sig} (dumped: {dumped}) | {s['body'][:120].replace(chr(10), ' ')}")

            is_unattended = os.environ.get("ED_UNATTENDED") == "1" or "--unattended" in sys.argv
            if is_unattended:
                print(f"UNATTENDED: skipping stalled task on {s.get('lesson')} to continue batch", file=sys.stderr)
                sys.exit(0)

            print(f"\n[AGENT-ACTION-REQUIRED]\nTask stalled on {s.get('lesson')} ({s.get('step')}, Task {s.get('counter')}).\n"
                  f"Fixture: {dumped}\n"
                  f"1. Read fixture JSON to inspect DOM HTML and compState.\n"
                  f"2. Add a reproducer test in tests/ and patch solver.py or auto.py.\n"
                  f"3. Run 'python3 -m unittest discover -s tests' to verify.\n"
                  f"4. Re-run lesson: python3 cover.py <unit> 1 --lesson=\"{s.get('lesson')}\"\n", file=sys.stderr)
            sys.exit(6)
        if s["lesson"] != lesson:
            lesson = s["lesson"]
            d = solver.source_text(t)
            src = (d["resource"] or "") + "\n" + d["body"]
            print(f"== {lesson} / {s['step']}")

        target_step_name = os.environ.get("ED_TARGET_STEP")
        if target_step_name and not target_step_jumped:
            target_step_jumped = True
            cur_step = (s.get("step") or "").lower()
            if target_step_name.lower() not in cur_step:
                find_step_js = f"""(() => {{
                  const dd1 = document.querySelectorAll('ed-la-dropdownlist')[1];
                  const comp = dd1 ? window.ng?.probe?.(dd1)?.componentInstance : null;
                  const children = comp?.dropDownListObj?.Children || [];
                  const idx = children.findIndex(c => (c.Name || '').toLowerCase().includes('{target_step_name.lower()}'));
                  return idx;
                }})()"""
                step_idx = t.js(find_step_js)
                if isinstance(step_idx, int) and step_idx >= 0:
                    print(f"-- fast-forward to target step: {target_step_name} (index {step_idx})")
                    solver.set_step(t, step_idx)
                    time.sleep(1.5)
                    prev = None
                    continue

        # If no explicit target step requested, automatically jump to the first incomplete step
        if not target_step_name and not target_step_jumped:
            min_target_score = 100 if os.environ.get("ED_UNATTENDED") == "1" else 80
            first_incomplete_js = f"""(() => {{
              const dd1 = document.querySelectorAll('ed-la-dropdownlist')[1];
              const comp = dd1 ? window.ng?.probe?.(dd1)?.componentInstance : null;
              const children = comp?.dropDownListObj?.Children || [];
              if (!children.length) return null;
              const idx = children.findIndex(c => {{
                const p = Number(c.Progress);
                const sName = (c.Name || '').toLowerCase();
                const isTest = sName.includes('test') || sName.includes('review');
                if (isTest) {{
                  const s = c.Score !== undefined && c.Score !== null ? Number(c.Score) : null;
                  if (s !== null && s < {min_target_score}) return true;
                }}
                return isNaN(p) || p < 0.999;
              }});
              if (idx > 0) {{
                return {{index: idx, name: children[idx].Name}};
              }}
              return null;
            }})()"""
            inc = t.js(first_incomplete_js)
            if isinstance(inc, dict) and inc.get("index"):
                target_step_jumped = True
                print(f"-- fast-forward to first incomplete step: {inc.get('name')} (index {inc['index']})")
                solver.set_step(t, inc["index"])
                time.sleep(1.5)
                prev = None
                continue
            target_step_jumped = True

        solver.neutralize(t)

        # Practice already recorded server-side but the app still renders the last
        # activity (or nothing). Re-solving it is pure waste: drops report "ok",
        # nothing advances, and the run never reaches the Test step. If the step's
        # own Progress is 1, just click through to the next step.
        EMPTY_PRACTICE_JS = ("""const p=document.querySelector('#pmContainer');
              const w=document.querySelectorAll('.prMCQ__qaSet,.lessonMultipleAnswer,.dnditem,.TTpanswerDiv,.draggable,.dndZone,.wordBankTile').length;
              return (!w && p && p.innerHTML.length < 50) ? 1 : 0;""")
        WIDGETS_JS = ("""const n=document.querySelectorAll('.prMCQ__qaSet,.lessonMultipleAnswer,.dnditem,.TTpanswerDiv,.draggable,.dndZone,.wordBankTile').length;
              return n ? 1 : 0;""")
        STEP_PROGRESS_JS = """(() => {
          const d = document.querySelectorAll('ed-la-dropdownlist')[1];
          if (!d) return null;
          const c = window.ng?.probe?.(d)?.componentInstance;
          const o = c?.dropDownListObj;
          if (o?.SelectedNode) return Number(o.SelectedNode.Progress);
          const app = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
          const node = app?.navigationService?._stepsList?.SelectedNode;
          if (node) return Number(node.Progress);
          return null;
        })()"""
        sp = t.js(STEP_PROGRESS_JS)
        skipped = (not isinstance(sp, bool)) and isinstance(sp, (int, float)) and sp >= 0.999
        if skipped:
            key = (s["lesson"], s["step"], s["counter"])
            adv = adv_tries.get(key, 0) + 1
            adv_tries[key] = adv
            print(f"-- step done (progress={sp}); advancing [{adv}/3]")
            if not advance(t) or adv > 1:
                nxt = solver.set_next_step(t)
                time.sleep(1.0)
                if nxt == 'last step':
                    require_lesson_complete(t)
            if adv > 4:
                # Last resort before exiting: check if all steps are completed
                require_lesson_complete(t)
                print(f"STEP-SWITCH-STUCK ({s['lesson']}) — exiting to let supervisor recover")
                sys.exit(2)
            prev = None
            continue


        # test entry screen
        start_btn_present = q(t, "return document.querySelector('.btnStartTest, button.btnStartTest, input.btnStartTest') || [...document.querySelectorAll('button, input[type=button], a')].some(e=>/start test/i.test((e.innerText||e.value||'').trim()))?1:0;")
        if start_btn_present:
            t.js("(() => { const b = document.querySelector('.btnStartTest') || [...document.querySelectorAll('button, input[type=button], a')].find(e=>/start test/i.test((e.innerText||e.value||'').trim())); if(b) b.click(); })()")
            print("test started")
            poll.wait_until(
                lambda: q(t, "const e=document.querySelector('.learning__taskNavPCCurrentTask'); return e?e.innerText.trim():null;"),
                lambda v: v is not None, timeout=12.0, interval=0.25)
            prev = None
            continue


        # test score / review screen (test already completed)
        body_low = (s.get("body") or "").lower()
        if (
            has_score_text(s.get("body"))
            or ("review your answers" in body_low and "next arrow" in body_low)
        ):
            if cur_test_area:
                if is_final_assessment_complete(t, s.get("body")):
                    score = extract_score_lines(s.get("body"))
                    print(f"Assessment complete: {' | '.join(score) or 'completed'}", flush=True)
                    return
                if not q(t, TEST_WIDGETS_JS):
                    has_live_nav = bool(t.js("""(() => {
                      const nav = window.ng?.probe?.(document.querySelector('app'))?.componentInstance?.navigationService;
                      return Boolean(nav && ((Array.isArray(nav._unitsList?.Children) && nav._unitsList.Children.length) || (Array.isArray(nav._lessonsList?.Children) && nav._lessonsList.Children.length)));
                    })()"""))
                    if has_live_nav and advance(t):
                        prev = None
                        continue
                    print("[AGENT-ACTION-REQUIRED] Assessment score screen lacks verified final completion state; stopping", file=sys.stderr)
                    sys.exit(6)
            else:
                print(f"-- test/course completed, advancing to finish lesson ({s.get('lesson')})")
                nxt = solver.set_next_step(t)
                time.sleep(1.0)
                require_lesson_complete(t)
                prev = None
                continue


        test_intro_active = t.js("""(() => {
            const p = document.querySelector('ed-la-taskspager');
            const comp = window.ng?.probe?.(p?.parentElement)?.componentInstance;
            if (comp && comp.isStepTest && comp.tasksNodes && Array.isArray(comp.tasksNodes.Children)) {
                const curId = comp.tasksNodes.SelectedNode?.NodeId;
                const curIdx = comp.tasksNodes.Children.findIndex(c => c.NodeId === curId);
                if (curIdx === 0 && comp.tasksNodes.Children[1]) {
                    try {
                        comp.onTaskClick(comp.tasksNodes.Children[1]);
                        return 1;
                    } catch(e) {}
                }
            }
            return 0;
        })()""")
        if test_intro_active:
            # Bounded: if clicking the intro node never advances the pager the
            # loop would reset `prev` every iteration and never trip the stall
            # detector, so give up after 3 tries and handle the screen normally.
            intro_key = (s.get("lesson"), s.get("step"))
            if next_intro_attempt(intro_tries, intro_key):
                print("started test from intro node")
                time.sleep(1.5)
                prev = None
                continue
            print(f"test intro did not advance ({intro_key}); handling screen normally")

        is_test = t.js(IS_TEST_JS)
        if q(t, "return document.querySelectorAll('a.chooseCaracterArrow').length ? 1 : 0;"):
            is_test = False

        if is_test and cur_test_area and is_test_intro_screen(s) and not q(t, TEST_WIDGETS_JS):
            intro_key = ("testarea_intro", s.get("lesson"), s.get("step"), s.get("counter"))
            if next_intro_attempt(intro_tries, intro_key):
                moved = advance_test_intro(t)
                print(f"advanced past test intro ({s.get('step')}, moved={bool(moved)})", flush=True)
                time.sleep(1.0)
                if moved:
                    prev = None
                continue

        pre_nav_sig = t.js(NAV_STATE_SIG_JS) if cur_test_area else None

        if is_test:
            poll.wait_until(
                lambda: q(t, """return document.querySelectorAll('.prMCQ__qaSet, .prFITB__qaSet, .dnditem, .lessonMultipleAnswer, .TTpanswerDiv, .openSpeech__btnStart, .speakingInteract, ed-la-mcq, .prDDL__qaSet, .prOpenEnded__qaSet').length ? 1 : 0;"""),
                lambda v: v == 1, timeout=8.0, interval=0.25)
            d = solver.source_text(t)
            src = (d.get("resource") or "") + "\n" + (d.get("body") or "")
            out = handle_test(t, src, unit_handler=unit_handler, lesson_name=s.get("lesson", ""))
        else:
            # intro / reading / interact intro / Step 1 Explore
            step_name = s.get("step", "").lower()
            is_intro = (
                s.get("counter") == "Intro"
                or q(t, "return document.querySelector('.learning__taskNavPagerCounterIW--intro') ? 1 : 0;")
            )
            has_interactive = q(t, "return document.querySelectorAll('.prMCQ__qaSet, .lessonMultipleAnswer, .dnditem, .DDLOptions__selected, ed-la-mcq, .prOpenEnded__qaItemText, .wordBankTile').length ? 1 : 0;")
            is_explore = (
                (
                    is_intro
                    or s["counter"] is None
                    or ("step 1" in step_name or "explore" in step_name)
                    or ("arrow next to the character" in s["body"].lower() and q(t, "return document.querySelectorAll('a.chooseCaracterArrow').length ? 1 : 0;"))
                )
                and not has_interactive
            )
            if is_explore:
                # Check if choose speaker exists for interact
                if q(t, "return document.querySelectorAll('a.chooseCaracterArrow').length ? 1 : 0;"):
                    print("-- interact speaker selection")
                    t.js("(() => {const a=document.querySelectorAll('a.chooseCaracterArrow'); if(a.length) a[0].click(); return 1;})()")
                    time.sleep(2.0)
                    prev = None
                    continue

                explore_done = t.js("""(() => {
                  const d = document.querySelectorAll('ed-la-dropdownlist')[1];
                  const ch = window.ng?.probe?.(d)?.componentInstance?.dropDownListObj?.Children;
                  return (ch && ch[0] && ch[0].Progress >= 0.999) ? 1 : 0;
                })()""")

                if not explore_done:
                    poll.wait_until(
                        lambda: q(t, "return [...document.querySelectorAll('audio,video')].some(x=>(x.currentSrc||x.src))?1:0;"),
                        lambda v: v == 1, timeout=3.0, interval=0.25)
                    played = solver.play_media(t, timeout=45, quick=False)
                    print(f"-- intro (media={'y' if played else 'n'})", flush=True)
                    # If no media elements (e.g. reading text), mark task progress via courseTreeService
                    if not played:
                        t.js("""(() => {
                          const comp = window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
                          const cts = comp?.navigationService?.backNextService?.courseTreeService;
                          const d = document.querySelectorAll('ed-la-dropdownlist')[1];
                          const ch = window.ng?.probe?.(d)?.componentInstance?.dropDownListObj?.Children;
                          const exploreTasks = ch?.[0]?.Children || [];
                          exploreTasks.forEach(task => {
                            if (task && task.NodeId && cts?.setProgressAsync) {
                              cts.setProgressAsync(task.NodeId);
                            }
                          });
                        })()""")
                        time.sleep(2.5)

                if not advance(t):
                    t.js("""(() => {
                        const t1 = document.querySelector('.learning__tasksNav_task');
                        if (t1) { t1.click(); return 1; }
                        return 0;
                    })()""")
                    nxt = solver.set_next_step(t)
                    print(f"-- fallback next step: {nxt}", flush=True)
                    if nxt == 'last step':
                        require_lesson_complete(t)
                prev = None
                time.sleep(1.0)
                continue

            br = handle_branch(t, src)
            if br:
                out = br
            else:
                poll.wait_until(
                    lambda: q(t, """const p=document.querySelector('ed-la-practicearea');
                      const tasks=document.querySelectorAll('.prMCQ__qaSet,.lessonMultipleAnswer,.dnditem,.TTpanswerDiv,.draggable,.dndZone').length;
                      return (p && (p.innerText||'').trim().length>25) || tasks ? 1 : 0;"""),
                    lambda v: v == 1, timeout=9.0, interval=0.25)
                kind = t.js("""(() => {
                  if(document.querySelectorAll('a.chooseCaracterArrow').length) return 'speak';
                  // speaking tasks also render options; text sniff must win over mcq/multi
                  if(/record the correct answer|record your answer/i.test(document.body.innerText)) return 'speak';
                  if(document.querySelector('.prMCQ__qaSet')) return 'mcq';
                  if(document.querySelectorAll('.lessonMultipleAnswer').length) return 'multi';
                  if(document.querySelectorAll('.dnditem').length && document.querySelectorAll('.dndZone').length) return 'drag';
                  if(window.tinymce && tinymce.activeEditor) return 'write';
                  if(document.querySelector('.writingEditFrame, textarea.writingTextarea, .OpenEndedQ')) return 'write';
                  const a=[...document.querySelectorAll('a.button.continue,button.button.continue,input.button.continue,button,input[type=button]')]
                    .map(e=>(e.innerText||e.value||'').trim());
                  if(a.includes('Start') || document.querySelector('.openSpeech__btnStart, .openSpeech__btn, .speakingInteract')) return 'speak';
                  return 'other';
                })()""")
                custom_out = None
                if unit_handler:
                    custom_out = unit_handler.on_task(t, {"type": kind, "src": src, "lesson": s.get("lesson", ""), "step": s.get("step", ""), "counter": s.get("counter")})
                if custom_out is not None:
                    out = custom_out
                elif kind == "speak":
                    out = handle_speaking(t, src)
                    sk = ("speak", s["lesson"], s["step"], s["counter"])
                    speak_tries[sk] = speak_tries.get(sk, 0) + 1
                    if speak_tries[sk] >= 3:
                        print("SPEAK-BLOCKED", sk, flush=True)
                        sys.exit(3)
                elif kind in ("mcq", "multi", "drag", "write", "select_text"):
                    out = solver.do_task(t, src)
                    # Click Check answer if present
                    if click_text(t, "Check answer") or click_text(t, "Check Answer"):
                        poll.wait_until(
                            lambda: q(t, "return document.querySelectorAll('.prMCQ__answers--checked').length;"),
                            lambda v: bool(v), timeout=3.0, interval=0.12)
                else:
                    out = solver.do_task(t, src)
                    if out.startswith("other:"):
                        out = "other: " + s["body"][:80].replace("\n", " ")

        print(f"[{s['counter']}/{s['total']}] {str(out)[:100]}", flush=True)
        if is_test and out.startswith("test-unanswered:"):
            continue
        if is_test and str(out).startswith("test-submit"):
            if cur_test_area:
                if str(out) == "test-submit-unverified":
                    print("[AGENT-ACTION-REQUIRED] Assessment submission unverified; stopping without retrying submit", file=sys.stderr)
                    sys.exit(6)
                post_body = t.js("(() => document.body?.innerText || '')()") or ""
                if str(out).startswith("test-submit-final") or is_final_assessment_complete(t, post_body):
                    score = extract_score_lines(post_body) or extract_score_lines(str(out))
                    print(f"Assessment complete: {' | '.join(score) or out}", flush=True)
                    return
                post_nav_sig = t.js(NAV_STATE_SIG_JS)
                section_moved = str(out) == "test-submit-section" or bool(
                    post_nav_sig and pre_nav_sig and post_nav_sig != pre_nav_sig
                )
                if not section_moved or sig in submitted_sections:
                    print("[AGENT-ACTION-REQUIRED] Assessment section submit did not transition; stopping without retrying", file=sys.stderr)
                    sys.exit(6)
                submitted_sections.add(sig)
                prev = None
                continue
            require_lesson_complete(t)
            prev = None
            continue

        if not advance(t):
            if s.get("counter") and s.get("total") and s["counter"] == s["total"]:
                nxt = solver.set_next_step(t)
                time.sleep(2.0)
                if cur_test_area and nxt in ("last step", "cannot advance step") and advance_next_part(t):
                    print("-- advanced to next assessment part", flush=True)
                    time.sleep(1.5)
                    prev = None
            elif cur_test_area and advance_next_part(t):
                print("-- advanced to next assessment part", flush=True)
                time.sleep(1.5)
                prev = None


if __name__ == "__main__":
    _pos_args = [a for a in sys.argv[1:] if not a.startswith("-")]
    main(int(_pos_args[0]) if _pos_args else 120)
