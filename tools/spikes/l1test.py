import json, sys, time
import edlib, solver

TRANS = open('t_a2labue.txt').read().strip()

def dump():
    return edlib.tab()

def click_opt(t, label_for):
    ok = t.js("""(() => {
      const l = document.querySelector('.prMCQ__answerLabel[for="%s"]');
      if(!l) return 'nf';
      l.click();
      const inp = document.getElementById('%s');
      if(inp && !inp.checked){ l.click(); }
      return (inp && inp.checked) ? 'ok' : 'unchecked';
    })()""" % (label_for, label_for))
    return ok

def main():
    t = edlib.tab()
    for i in range(1, 6):
        solver.neutralize(t)
        sets = edlib.mcq_sets(t)
        if not sets:
            print(f"Q{i}: no mcq", flush=True)
            break
        s = sets[0]
        prompt = (f"LISTENING TRANSCRIPT:\n{TRANS}\n\nQUESTION: {s['q']}\nOPTIONS:\n"
                  + "\n".join(f"- {o['t']}" for o in s["opts"])
                  + '\n\nPick the single correct option. Reply {"answer": "<exact option text>"}.')
        r = solver.ask_json(prompt) or {}
        want = (r.get("answer") or "").strip()
        opt = next((o for o in s["opts"] if o["t"].strip().lower() == want.lower()), None)
        if opt is None:
            opt = next((o for o in s["opts"] if want.lower() in o["t"].lower()), s["opts"][0])
        st = click_opt(t, opt["for"])
        print(f"Q{i}: {s['q'][:90]} -> {opt['t'][:60]} [{st}]", flush=True)
        time.sleep(1)
        t.js("(() => {const b=document.querySelector('.learning__taskNext'); if(b) b.click(); return 1;})()")
        time.sleep(4)

    solver.neutralize(t)
    print("SUBMIT", t.js("(() => {const b=document.querySelector('.learning__submitTestLink'); if(!b) return 'nf'; b.click(); return 'clicked';})()"), flush=True)
    time.sleep(4)
    print("DIALOG", solver.dialog_text(t)[:2], flush=True)
    t.js("""(() => {
      const f=document.querySelector('iframe#colorBoxIframe');
      if(!f) return 'no-iframe';
      const d=f.contentDocument;
      const b=[...d.querySelectorAll('input,button,a')].find(x=>/^(submit|ok|continue|yes)$/i.test((x.value||x.innerText||'').trim()));
      if(b){ b.click(); return 'clicked ' + ((b.value||b.innerText)||'').trim(); }
      return 'no-btn';
    })()""")
    time.sleep(8)
    print("BODY", t.js("(() => document.body.innerText.slice(0,400))()"), flush=True)

main()
