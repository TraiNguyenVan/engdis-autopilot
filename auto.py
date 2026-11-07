"""Unit-1 autopilot: drives the learning area task by task.

Usage: python3 auto.py [max_iterations]
"""
import json, os, sys, time

import edlib, login, poll, solver
import config
from diag_logger import DiagnosticLogger

diag = DiagnosticLogger(log_dir="logs_diag")

PORT = config.CDP_PORT


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
            return d[1] ? d[1].innerText.split('\\n')[0] : '';
        })()"""),
        "lesson": t.js("""(() => {const d=document.querySelectorAll('ed-la-dropdownlist'); return d[0]? d[0].innerText.split('\\n')[0] : '';})()"""),
        "counter": t.js("""(() => {const c=document.querySelector('.learning__taskNavPCCurrentTask'); return c? c.innerText.trim(): null;})()"""),
        "total": t.js("""(() => {const c=document.querySelector('.learning__taskNavPCTotalTasks'); return c? c.innerText.trim(): null;})()"""),
        "body": t.js("(() => (document.body?.innerText || '').slice(0,600))()"),
        "unit": t.js("""(() => {const m = (document.body?.innerText||'').match(/Unit\\s+\\d+/i); return m ? m[0].replace(/\\s+/, ' ') : '';})()"""),
    }


def click(t, sel):
    return t.js("(() => {const e=document.querySelector(%s); if(!e) return 0; e.click(); return 1;})()" % json.dumps(sel))


def click_text(t, text):
    return t.js("""(() => {const b=[...document.querySelectorAll('a,button,input')].filter(e=>((e.innerText||e.value||'').trim()===%s));
      if(!b.length) return 0; b[b.length-1].click(); return 1;})()""" % json.dumps(text))



def purge_modals(t):
    return q(t, """document.querySelectorAll('iframe#colorBoxIframe').forEach(f=>f.remove());
      document.querySelectorAll('#colorbox,.colorbox').forEach(e=>e.remove());
      document.querySelectorAll('.modal-close, .modalW, .modal, .layout__alertModal, .modal-backdrop').forEach(e=>e.remove());
      document.body.classList.remove('modal-open');
      const ed=document.querySelector('#EdoFrameBox'); if(ed) ed.style.display='none';
      return 1;""")


def advance(t, tries=3):
    """Purge blocking modals, then click Next until the counter changes."""
    def cur():
        return q(t, """const e=document.querySelector('.learning__taskNavPCCurrentTask');
          const app=window.ng?.probe?.(document.querySelector('app'))?.componentInstance;
          const sIdx=app?.navigationService?._stepsList?.SelectedIndex;
          const d=document.querySelectorAll('ed-la-dropdownlist')[1];
          const dt=d?(d.innerText||'').trim().slice(0,14):'-';
          return (e?e.innerText.trim():'-')+'|'+(sIdx!==undefined?sIdx:dt);""")
    before = cur()
    for _ in range(tries):
        purge_modals(t)
        click(t, ".learning__taskNext")
        now = poll.wait_until(cur, lambda v: v != before, timeout=4.0,
                              interval=0.2, settle=0.2)
        if now != before:
            return True
    return False

def wait_text(t, needles, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        body = t.js("""(() => {const p=document.querySelector('ed-la-practicearea')||document.body; return p.innerText;})()""")
        if any(n.lower() in body.lower() for n in needles):
            return body
        time.sleep(1.5)
    return ""


def handle_speaking(t, src):
    """Speaking / interact recording: click Start, let it record, stop if needed."""
    # Speech already rejected by the server: don't re-record, let the try counter trip SPEAK-BLOCKED
    if q(t, "/Try again|record your answer again/i.test(document.body.innerText) ? 1 : 0;"):
        return "speak: blocked"
    
    if q(t, "return document.querySelectorAll('a.chooseCaracterArrow').length;"):
        t.js("(() => {const a=document.querySelectorAll('a.chooseCaracterArrow'); if(a.length) a[0].click(); return 1;})()")
        time.sleep(2)
    clicked = click_text(t, "Start") or t.js("(() => {const b=document.querySelector('.openSpeech__btnStart, .openSpeech__btn'); if(b){b.click(); return 1;} return 0;})()")
    if not clicked:
        return "speak: blocked"
    time.sleep(3.5)
    return "speak: clicked"


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


def handle_test(t, src):
    """Answer a test question set, submit on the last one."""
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
    out = solver.do_task(t, src)
    # Require a checked answer in every MCQ set, including after retry.
    def unanswered(result):
        return result.startswith("other:") or bool(q(t, """return [...document.querySelectorAll('.prMCQ__qaSet')].some(e=>!e.querySelector('.prMCQ__answers--checked'))?1:0;"""))

    if unanswered(out):
        time.sleep(1.5)
        retry = solver.do_task(t, src)
        out = retry
        print("test retry", str(retry)[:60], flush=True)
    if unanswered(out):
        return "test-unanswered: " + out
    poll.wait_until(
        lambda: q(t, "return [...document.querySelectorAll('a,button,input')].some(e=>/^Check answer$/i.test((e.innerText||e.value||'').trim()))?1:0;"),
        lambda v: v == 1, timeout=3.0, interval=0.12)
    total = st(t)["total"]
    counter = st(t)["counter"]
    sub = q(t, "return document.querySelector('.learning__submitTestLink')?1:0;")
    if sub and total and counter == total:
        click(t, ".learning__submitTestLink")
        t.js("(() => {const a=document.querySelector('.learning__submitTestLink'); if(a) angular.element(a).triggerHandler('click');})()")
        poll.wait_until(
            lambda: q(t, "return (document.querySelector('iframe#colorBoxIframe') || document.querySelector('#colorbox') || document.querySelector('.modal'))?1:0;"),
            lambda v: v == 1, timeout=8.0, interval=0.2)
        t.js("""(() => {const f=[...document.querySelectorAll('iframe#colorBoxIframe')].pop();
          if(f && f.contentDocument) {
            const d=f.contentDocument;
            const b=[...d.querySelectorAll('input[type=button],input[type=submit],button,a')]
              .filter(e=>/ok|continue|submit|yes|confirm/i.test((e.value||e.innerText||'').trim()));
            if(b.length) { b[b.length-1].click(); return 1; }
          }
          const b2=[...document.querySelectorAll('#colorbox input, #colorbox button, #colorbox a, .modal button')]
            .filter(e=>/ok|continue|submit|yes|confirm/i.test((e.value||e.innerText||'').trim()));
          if(b2.length) { b2[b2.length-1].click(); return 2; }
          return 0;})()""")
        body = poll.wait_until(
            lambda: t.js("(() => document.body.innerText.slice(0,500))()"),
            lambda b: bool(b) and "%" in b, timeout=12.0, interval=0.3) or ""
        score = [ln for ln in body.split("\n") if "%" in ln][:2]
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

def require_lesson_complete(t):
    """Exit successfully only when every step has verified progress."""
    progress = t.js("""(() => {
      const d = document.querySelectorAll('ed-la-dropdownlist')[1];
      const children = window.ng?.probe?.(d)?.componentInstance?.dropDownListObj?.Children;
      if (!Array.isArray(children) || !children.length) return null;
      return children.map(node => node?.Progress ?? null);
    })()""")
    if (isinstance(progress, list) and progress and all(
        not isinstance(p, bool) and isinstance(p, (int, float)) and p >= 0.999
        for p in progress
    )):
        print("All steps done — lesson complete")
        sys.exit(0)
    print(f"LESSON-INCOMPLETE or progress unavailable: {progress}")
    sys.exit(2)


def main(max_iter=120):
    t = edlib.tab()
    if not login.ensure_login(t):
        print("LOGIN-FAIL")
        sys.exit(4)
    src = ""
    lesson = None
    prev = None
    stuck = 0
    speak_tries = {}
    adv_tries = {}
    media_done = set()
    unit_lock = ""
    lesson_lock = ""
    for _ in range(max_iter):
        s = st(t)
        if "Member Login" in (s.get("body") or ""):
            print("session dropped, relogging")
            if not login.ensure_login(t):
                print("LOGIN-FAIL")
                sys.exit(4)
            unit_lock = lesson_lock = ""
            prev = None
            continue
        if not unit_lock:
            unit_lock = s.get("unit") or ""
        elif s.get("unit") and s["unit"] != unit_lock:
            print("UNIT-CHANGED", unit_lock, "->", s["unit"])
            sys.exit(4)
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
            print("STUCK", sig, "|", s["body"][:120].replace("\n", " "))
            return
        if s["lesson"] != lesson:
            lesson = s["lesson"]
            d = solver.source_text(t)
            src = (d["resource"] or "") + "\n" + d["body"]
            print(f"== {lesson} / {s['step']}")

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
                print(f"STEP-SWITCH-STUCK ({s['lesson']}) — returning to home to clear lock")
                t.goto("https://ed22.engdis.com/ptithcm#/home", wait=4)
                adv_tries.clear()
            prev = None
            continue

        # test entry screen
        if q(t, "return document.querySelector('.btnStartTest')?1:0;"):
            click(t, ".btnStartTest")
            print("test started")
            poll.wait_until(
                lambda: q(t, "const e=document.querySelector('.learning__taskNavPCCurrentTask'); return e?e.innerText.trim():null;"),
                lambda v: v is not None, timeout=12.0, interval=0.25)
            prev = None
            continue

        # intro / reading / interact intro on pages without counter
        if s["counter"] is None or ("arrow next to the character" in s["body"].lower() and q(t, "return document.querySelectorAll('a.chooseCaracterArrow').length ? 1 : 0;")):
            # Check if choose speaker exists for interact
            if q(t, "return document.querySelectorAll('a.chooseCaracterArrow').length ? 1 : 0;"):
                print("-- interact speaker selection")
                t.js("(() => {const a=document.querySelectorAll('a.chooseCaracterArrow'); if(a.length) a[0].click(); return 1;})()")
                time.sleep(2.0)
                prev = None
                continue

            poll.wait_until(
                lambda: q(t, "return [...document.querySelectorAll('audio,video')].some(x=>(x.currentSrc||x.src))?1:0;"),
                lambda v: v == 1, timeout=3.0, interval=0.25)
            played = solver.play_media(t, timeout=45, quick=True)
            print(f"-- intro (media={'y' if played else 'n'})", flush=True)
            if not advance(t):
                nxt = solver.set_next_step(t)
                print(f"-- fallback next step: {nxt}", flush=True)
                if nxt == 'last step':
                    require_lesson_complete(t)
            prev = None
            time.sleep(1.0)
            continue

        is_test = t.js("""(() => {
            const app = ng.probe(document.querySelector('app'))?.componentInstance;
            if (app?.isTestEnv) return true;
            if (typeof app?.isStepTest === 'function' && app.isStepTest()) return true;
            if (document.querySelector('.learning__submitTestLink')) return true;
            const nav = app?.navigationService;
            const name = (nav?._stepsList?.SelectedNode?.Name || '').toLowerCase();
            if (name === 'test' || name === 'review') return true;
            const dds = [...document.querySelectorAll('ed-la-dropdownlist')];
            const stepTitle = dds.length > 1 ? (dds[1].innerText || '').toLowerCase() : '';
            return /test|review/.test(stepTitle);
        })()""")

        if q(t, "return document.querySelectorAll('a.chooseCaracterArrow').length ? 1 : 0;"):
            is_test = False
        if is_test:
            out = handle_test(t, src)
        else:
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
                  const a=[...document.querySelectorAll('a.button.continue,button.button.continue,input.button.continue,button,input[type=button]')]
                    .map(e=>(e.innerText||e.value||'').trim());
                  if(a.includes('Start') || document.querySelector('.openSpeech__btnStart, .openSpeech__btn')) return 'speak';
                  return 'other';
                })()""")
                if kind == "speak":
                    out = handle_speaking(t, src)
                    sk = ("speak", s["lesson"], s["step"], s["counter"])
                    speak_tries[sk] = speak_tries.get(sk, 0) + 1
                    if speak_tries[sk] >= 3:
                        print("SPEAK-BLOCKED", sk, flush=True)
                        sys.exit(3)
                elif kind in ("mcq", "multi", "drag", "write"):
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
        if not advance(t):
            if s.get("counter") and s.get("total") and s["counter"] == s["total"]:
                solver.set_next_step(t)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
