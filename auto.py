"""Unit-1 autopilot: drives the learning area task by task.

Usage: python3 auto.py [max_iterations]
"""
import json, os, sys, time

import edlib, login, poll, solver

PORT = 9225


def q(t, expr):
    return t.js("(() => {" + expr + "})()")


def st(t):
    return {
        "step": t.js("""(() => {const d=document.querySelectorAll('ed-la-dropdownlist'); return d[1]? d[1].innerText.split('\\n')[0] : '';})()"""),
        "lesson": t.js("""(() => {const d=document.querySelectorAll('ed-la-dropdownlist'); return d[0]? d[0].innerText.split('\\n')[0] : '';})()"""),
        "counter": t.js("""(() => {const c=document.querySelector('.learning__taskNavPCCurrentTask'); return c? c.innerText.trim(): null;})()"""),
        "total": t.js("""(() => {const c=document.querySelector('.learning__taskNavPCTotalTasks'); return c? c.innerText.trim(): null;})()"""),
        "body": t.js("(() => document.body.innerText.slice(0,600))()"),
        "unit": t.js("""(() => {const ls=(document.body.innerText||'').split(String.fromCharCode(10)); const m=ls.find(x=>x.trim().startsWith('Unit ')); return m?m.trim():'';})()"""),
    }


def click(t, sel):
    return t.js("(() => {const e=document.querySelector(%s); if(!e) return 0; e.click(); return 1;})()" % json.dumps(sel))


def click_text(t, text):
    return t.js("""(() => {const b=[...document.querySelectorAll('a,button,input')].filter(e=>((e.innerText||e.value||'').trim()===%s));
      if(!b.length) return 0; b[b.length-1].click(); return 1;})()""" % json.dumps(text))



def purge_modals(t):
    return q(t, """document.querySelectorAll('iframe#colorBoxIframe').forEach(f=>f.remove());
      document.querySelectorAll('#colorbox,.colorbox').forEach(e=>e.remove());
      const ed=document.querySelector('#EdoFrameBox'); if(ed) ed.style.display='none';
      return 1;""")


def advance(t, tries=3):
    """Purge blocking modals, then click Next until the counter changes."""
    def cur():
        return q(t, """const e=document.querySelector('.learning__taskNavPCCurrentTask');
          const d=document.querySelectorAll('ed-la-dropdownlist')[1];
          const dt=d?(d.innerText||'').trim().slice(0,14):'-';
          return (e?e.innerText.trim():'-')+'|'+dt;""")
    before = cur()
    for _ in range(tries):
        purge_modals(t)
        click(t, ".learning__taskNext")
        now = poll.wait_until(cur, lambda v: v != before, timeout=6.0,
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
    if not click_text(t, "Start"):
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
    # unanswered question (render race or a failed click) would silently score 0:
    # retry once before the caller advances to the next question
    if out.startswith("other:") or (
        q(t, "return document.querySelector('.prMCQ__qaSet')?1:0;")
        and not q(t, "return document.querySelectorAll('.prMCQ__answers--checked').length;")
    ):
        time.sleep(1.5)
        retry = solver.do_task(t, src)
        if not retry.startswith("other:"):
            out = retry
        print("test retry", str(retry)[:60], flush=True)
    poll.wait_until(
        lambda: q(t, "return [...document.querySelectorAll('a,button,input')].some(e=>/^Check answer$/i.test((e.innerText||e.value||'').trim()))?1:0;"),
        lambda v: v == 1, timeout=3.0, interval=0.12)
    total = st(t)["total"]
    counter = st(t)["counter"]
    sub = q(t, "return document.querySelector('.learning__submitTestLink')?1:0;")
    if sub and total and counter == total:
        click(t, ".learning__submitTestLink")
        poll.wait_until(
            lambda: q(t, "return document.querySelector('iframe#colorBoxIframe')?1:0;"),
            lambda v: v == 1, timeout=8.0, interval=0.2)
        t.js("""(() => {const f=[...document.querySelectorAll('iframe#colorBoxIframe')].pop(); if(!f) return 1;
          const d=f.contentDocument; const b=[...d.querySelectorAll('input[type=button],button,a')]
            .filter(e=>/^(OK|Ok|Continue|Submit)$/i.test((e.value||e.innerText||'').trim()));
          if(b.length) b[b.length-1].click(); return 1;})()""")
        body = poll.wait_until(
            lambda: t.js("(() => document.body.innerText.slice(0,500))()"),
            lambda b: bool(b) and "%" in b, timeout=12.0, interval=0.3) or ""
        score = [ln for ln in body.split("\n") if "%" in ln][:2]
        return f"test-submit {score}"
    return out


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
        STEP_PROGRESS_JS = """(() => {const d=document.querySelectorAll('ed-la-dropdownlist')[1];
              if(!d) return null; const c=ng.probe(d).componentInstance;
              const o=c && c.dropDownListObj; const n=o && (o.SelectedNode || (o.Children||[])[o.SelectedIndex]);
              return n ? Number(n.Progress) : null;})()"""
        if s["step"].startswith("Step 2"):
            if q(t, EMPTY_PRACTICE_JS):
                poll.wait_until(lambda: q(t, WIDGETS_JS), lambda v: v == 1,
                                timeout=6.0, interval=0.25)
            sp = t.js(STEP_PROGRESS_JS)
            skipped = (not isinstance(sp, bool)) and isinstance(sp, (int, float)) and sp >= 0.999
            if skipped:
                key = (s["lesson"], s["step"], s["counter"])
                adv = adv_tries.get(key, 0) + 1
                adv_tries[key] = adv
                print(f"-- practice done (progress={sp}); advancing [{adv}/3]")
                if adv > 3:
                    print("STEP-BLOCKED", key)
                    sys.exit(7)
                advance(t)
                prev = None
                continue

        # test entry screen
        if s["step"].startswith("Step 3") and s["counter"] is None and q(t, "return document.querySelector('.btnStartTest')?1:0;"):
            click(t, ".btnStartTest")
            print("test started")
            poll.wait_until(
                lambda: q(t, "const e=document.querySelector('.learning__taskNavPCCurrentTask'); return e?e.innerText.trim():null;"),
                lambda v: v is not None, timeout=15.0, interval=0.25)
            prev = None
            continue

        # a task is loaded?
        if s["counter"] is None:
            # intro / reading / interact intro: play media then advance
            poll.wait_until(
                lambda: q(t, "return [...document.querySelectorAll('audio,video')].some(x=>(x.currentSrc||x.src))?1:0;"),
                lambda v: v == 1, timeout=16.0, interval=0.25)
            played = solver.play_media(t, timeout=45)
            advance(t)
            print(f"-- intro (media={'y' if played else 'n'})")
            prev = None
            continue

        if s["step"].startswith("Step 3"):
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
                  if(a.includes('Start')) return 'speak';
                  return 'other';
                })()""")
                if sig not in media_done and q(t, """return [...document.querySelectorAll('audio,video')].filter(x=>(x.currentSrc||x.src)).length;"""):
                    media_done.add(sig)
                    solver.play_media(t, timeout=70)
                if kind == "speak":
                    out = handle_speaking(t, src)
                    sk = ("speak", s["lesson"], s["step"], s["counter"])
                    speak_tries[sk] = speak_tries.get(sk, 0) + 1
                    if speak_tries[sk] >= 3:
                        print("SPEAK-BLOCKED", sk)
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

        print(f"[{s['counter']}/{s['total']}] {str(out)[:100]}")
        advance(t)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
