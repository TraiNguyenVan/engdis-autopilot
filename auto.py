"""Unit-1 autopilot: drives the learning area task by task.

Usage: python3 auto.py [max_iterations]
"""
import json, os, sys, time

import edlib, solver

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
        time.sleep(2.5)
        if cur() != before:
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
    # Check for Try again (speaking failed)
    if click_text(t, "Try again"):
        time.sleep(3.5)
        return "speak: try-again-clicked"
    
    if q(t, "return document.querySelectorAll('a.chooseCaracterArrow').length;"):
        t.js("(() => {const a=document.querySelectorAll('a.chooseCaracterArrow'); if(a.length) a[0].click(); return 1;})()")
        time.sleep(2)
    if not click_text(t, "Start"):
        return "speak: no-start"
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
    time.sleep(1)
    total = st(t)["total"]
    counter = st(t)["counter"]
    sub = q(t, "return document.querySelector('.learning__submitTestLink')?1:0;")
    if sub and total and counter == total:
        click(t, ".learning__submitTestLink")
        time.sleep(3)
        t.js("""(() => {const f=[...document.querySelectorAll('iframe#colorBoxIframe')].pop(); if(!f) return 1;
          const d=f.contentDocument; const b=[...d.querySelectorAll('input[type=button],button,a')]
            .filter(e=>/^(OK|Ok|Continue|Submit)$/i.test((e.value||e.innerText||'').trim()));
          if(b.length) b[b.length-1].click(); return 1;})()""")
        time.sleep(5)
        body = t.js("(() => document.body.innerText.slice(0,500))()")
        score = [ln for ln in body.split("\n") if "%" in ln][:2]
        return f"test-submit {score}"
    return out


def main(max_iter=120):
    t = edlib.tab()
    src = ""
    lesson = None
    prev = None
    stuck = 0
    speak_tries = {}
    unit_lock = ""
    for _ in range(max_iter):
        s = st(t)
        if not unit_lock:
            unit_lock = s.get("unit") or ""
        elif s.get("unit") and s["unit"] != unit_lock:
            print("UNIT-CHANGED", unit_lock, "->", s["unit"])
            sys.exit(4)
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

        # test entry screen
        if s["step"].startswith("Step 3") and s["counter"] is None and q(t, "return document.querySelector('.btnStartTest')?1:0;"):
            click(t, ".btnStartTest")
            print("test started")
            time.sleep(6)
            prev = None
            continue

        # a task is loaded?
        if s["counter"] is None:
            # intro / reading / interact intro: play media then advance
            for _w in range(8):
                if q(t, "return [...document.querySelectorAll('audio,video')].some(x=>(x.currentSrc||x.src));"):
                    break
                time.sleep(2)
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
                for _w in range(6):
                    ready = q(t, """const p=document.querySelector('ed-la-practicearea');
                      const tasks=document.querySelectorAll('.prMCQ__qaSet,.lessonMultipleAnswer,.dnditem,.TTpanswerDiv,.draggable,.dndZone').length;
                      return (p && (p.innerText||'').trim().length>25) || tasks ? 1 : 0;""")
                    if ready:
                        break
                    time.sleep(1.5)
                media = q(t, """return [...document.querySelectorAll('audio,video')].filter(x=>(x.currentSrc||x.src)).length;""")
                if media:
                    solver.play_media(t, timeout=70)
                kind = t.js("""(() => {
                  if(document.querySelectorAll('a.chooseCaracterArrow').length) return 'speak';
                  if(document.querySelector('.prMCQ__qaSet')) return 'mcq';
                  if(document.querySelectorAll('.lessonMultipleAnswer').length) return 'multi';
                  if(document.querySelectorAll('.dnditem').length && document.querySelectorAll('.dndZone').length) return 'drag';
                  if(window.tinymce && tinymce.activeEditor) return 'write';
                  const a=[...document.querySelectorAll('a.button.continue')].map(e=>(e.innerText||'').trim());
                  if(a.includes('Start')) return 'speak';
                  return 'other';
                })()""")
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
                    time.sleep(1)
                    if click_text(t, "Check answer") or click_text(t, "Check Answer"):
                        time.sleep(1.5)
                else:
                    out = solver.do_task(t, src)
                    if out.startswith("other:"):
                        out = "other: " + s["body"][:80].replace("\n", " ")

        print(f"[{s['counter']}/{s['total']}] {str(out)[:100]}")
        advance(t)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
