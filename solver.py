"""Automated solver for English Discoveries (ed22.engdis.com) lessons.

Drives own headless Chromium over CDP; answers via a cheap remote LLM.
Prints one terse line per task.
"""
import base64, json, os, subprocess, sys, time, urllib.request

import edlib
import config

LLM_URL = config.LLM_URL
LLM_KEY = os.environ.get("NINEROUTER_API_KEY", "")
LLM_MODELS = [
    "ag/gemini-3.8-flash",
    "ag/claude-sonnet-5-5-low",
    "ag/gpt-oss-120b-medium",
    "ag/gemini-3.7-flash-low",
    "gemini/gemini-3.6-flash",
]
SCRATCH = config.SCRATCH


# ---------- LLM ----------
def ask(prompt, audio_b64=None, max_tokens=800):
    content = [{"type": "text", "text": prompt}]
    if audio_b64:
        content.append({"type": "input_audio", "input_audio": {"data": audio_b64, "format": "mp3"}})
    last = None
    for model in LLM_MODELS:
        payload = {"model": model, "messages": [{"role": "user", "content": content}],
                   "max_tokens": max_tokens, "temperature": 0}
        try:
            req = urllib.request.Request(LLM_URL, data=json.dumps(payload).encode(),
                                        headers={"Content-Type": "application/json",
                                                 "Authorization": "Bearer " + LLM_KEY})
            body = urllib.request.urlopen(req, timeout=180).read().decode()
        except Exception as e:
            last = e
            print("! llm %s: %s" % (model, str(e)[:140]), flush=True)
            time.sleep(1.5)
            continue
        if body.lstrip().startswith("data:"):
            out = []
            for line in body.splitlines():
                if not line.startswith("data: "):
                    continue
                d = line[6:]
                if d == "[DONE]":
                    break
                try:
                    out.append(json.loads(d)["choices"][0]["delta"].get("content") or "")
                except Exception:
                    pass
            return "".join(out)
        try:
            return json.loads(body)["choices"][0]["message"]["content"]
        except Exception as e:
            last = e
            print("! llm %s parse: %s" % (model, str(e)[:140]), flush=True)
    raise last if last else RuntimeError("llm failed")


def ask_json(prompt, audio_b64=None, max_tokens=800):
    txt = ask(prompt + "\n\nReply with JSON only, no prose, no code fences.", audio_b64, max_tokens)
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j < 0:
        return None
    try:
        return json.loads(txt[i:j + 1])
    except Exception as e:
        print("! json: %s | raw=%r" % (str(e)[:80], txt[:120]), flush=True)
        return None



# ---------- blockers ----------
def neutralize(t):
    """Remove modal overlays that eat mouse events (they only block real input, JS clicks pass)."""
    return jso(t, """
      document.querySelectorAll('#colorbox, .colorbox').forEach(e=>e.remove());
      document.querySelectorAll('.utils__siteOverlay').forEach(e=>{e.style.pointerEvents='none';});
      const fb=document.getElementById('EdoFrameBox'); if(fb){fb.style.display='none';}
      return 1;
    """.strip())


def dialog_text(t):
    return t.js("""(() => {
      const out=[];
      document.querySelectorAll('iframe#colorBoxIframe').forEach(f=>{try{const d=f.contentDocument; if(d) out.push(d.body.innerText.trim().slice(0,120));}catch(e){}});
      return out;
    })()""")


def click_label_trusted(t, lbl_for):
    r = t.js("""(() => {const l=document.querySelector('.prMCQ__answerLabel[for=%s]'); if(!l) return null;
      const b=l.getBoundingClientRect(); return {x:Math.round(b.x+b.width/2), y:Math.round(b.y+b.height/2)};})()""" % json.dumps(lbl_for))
    if not r:
        return False
    t.click_xy(r["x"], r["y"])
    time.sleep(0.3)
    return True


def ensure_checked(t, lbl_for, tries=3):
    for _ in range(tries):
        ok = t.js("""(() => {const i=document.querySelector('.prMCQ__answerLabel[for=%s]');
          if(!i) return false; const inp=document.getElementById(i.getAttribute('for')); return !!(inp&&inp.checked);})()""" % json.dumps(lbl_for))
        if ok:
            return True
        click_label_trusted(t, lbl_for)
    return False

# ---------- page helpers ----------
def jso(t, expr):
    return t.js("(() => {" + expr + "})()")


def state(t):
    return t.js("""(() => {
      const dd=[...document.querySelectorAll('ed-la-dropdownlist')].map(d=>d.innerText.split('\\n')[0]);
      const c=document.querySelector('.learning__taskNavPCCurrentTask');
      const tot=document.querySelector('.learning__taskNavPCTotalTasks');
      return {url:location.href, lesson:dd[0]||'', step:dd[1]||'',
              counter:c?c.innerText.trim():null, total:tot?tot.innerText.trim():null};
    })()""")


def source_text(t):
    return t.js("""(() => {
      const r=document.querySelector('ed-la-resourcearea');
      const rt = r ? r.innerText.trim() : '';
      const b = document.body.innerText;
      const i = b.indexOf('Back');
      return {resource: rt, body: b.slice(0, 6000)};
    })()""")


def play_media(t, timeout=90):
    """Click the player's play button and wait until the media finishes."""
    present = t.js("""(() => [...document.querySelectorAll('audio,video')].filter(x=>(x.currentSrc||x.src)).length)()""")
    if not present:
        return False
    t.js("(() => {const b=document.querySelector('.layout__mediaPlayPause'); if(b) b.click(); return 1;})()")
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(2)
        st = t.js("""(() => {const a=[...document.querySelectorAll('audio,video')].filter(x=>(x.currentSrc||x.src));
          if(!a.length) return 'none';
          const el=a.sort((p,q)=>((q.duration||0)-(p.duration||0)))[0];
          if(el.ended) return 'ended';
          if(el.currentTime>0 && el.paused) { const b=document.querySelector('.layout__mediaPlayPause'); if(b) b.click(); }
          return el.currentTime.toFixed(1)+'/'+(el.duration||'?');})()""")
        if st == "ended":
            return True
    return False


def media_url(t):
    return t.js("""(() => {const a=[...document.querySelectorAll('audio,video')].filter(x=>x.src||x.currentSrc)[0];
      return a? (a.currentSrc||a.src): null;})()""")


def transcript_for(url, cache_key):
    path = os.path.join(SCRATCH, f"tr_{cache_key}.txt")
    if os.path.exists(path):
        return open(path).read()
    mp3 = os.path.join(SCRATCH, f"m_{cache_key}.mp3")
    if not os.path.exists(mp3):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", url, "-vn", "-ac", "1", "-ar", "16000", mp3], check=False)
    if not os.path.exists(mp3):
        return ""
    b64 = base64.b64encode(open(mp3, "rb").read()).decode()
    txt = ask("Transcribe this audio exactly. Output only the transcript.", audio_b64=b64, max_tokens=2000)
    open(path, "w").write(txt)
    return txt


# ---------- task solvers ----------
def solve_mcq(t, src):
    sets = edlib.mcq_sets(t)
    picks = []
    for s in sets:
        prompt = (f"SOURCE MATERIAL:\n{src}\n\nQUESTION: {s['q']}\nOPTIONS:\n"
                  + "\n".join(f"- {o['t']}" for o in s["opts"])
                  + '\n\nPick the single correct option. Reply {"answer": "<exact option text>"}.')
        r = ask_json(prompt) or {}
        want = (r.get("answer") or "").strip().lower()
        o = next((x for x in s["opts"] if x["t"].strip().lower() == want), None)
        if not o:
            o = next((x for x in s["opts"] if want and want in x["t"].strip().lower()), None)
        if not o:
            o = s["opts"][0]
        edlib.click_for(t, o["for"])
        ensure_checked(t, o["for"])
        picks.append(o["t"][:40])
    return "mcq: " + " | ".join(picks)


def solve_multi(t, src):
    items = t.js("""(() => [...document.querySelectorAll('.lessonMultipleAnswer')].map(e=>({id:e.id, t:e.innerText.trim()})))()""")
    q = t.js("""(() => {const e=document.querySelector('.prMCQ__questionText, .learning__practiceQuestionText, .prMULTI__question');
      return e? e.innerText.trim() : '';})()""")
    header = t.js("""(() => {const p=document.querySelector('ed-la-practicearea'); return p? p.innerText.slice(0,200):'';})()""")
    prompt = (f"SOURCE MATERIAL:\n{src}\n\nTASK: {header}\n\nSTATEMENTS:\n"
              + "\n".join(f"{i+1}. {x['t']}" for i, x in enumerate(items))
              + '\n\nWhich statements are TRUE / correct? Reply {"true_indices": [1,3]} using 1-based numbers.')
    r = ask_json(prompt, max_tokens=1500) or {}
    idx = [i for i in r.get("true_indices", []) if isinstance(i, int) and 1 <= i <= len(items)]
    if not idx:
        idx = [1]
    for i in idx:
        el = items[i - 1]
        jso(t, f"const el=document.getElementById('{el['id']}'); if(el){{(el.querySelector('label')||el).click();}} return 1;")
        time.sleep(0.2)
    return "multi: " + ", ".join(items[i - 1]["t"][:30] for i in idx)


def _drag_snapshot(t):
    zones = t.js("""(() => [...document.querySelectorAll('.dndZone')].map(z=>({n:z.getAttribute('dg_name'), items:[...z.querySelectorAll('.dnditem')].map(x=>x.innerText.trim())})))()""")
    bank = t.js("""(() => {const b=[...document.querySelectorAll('.dndZone')].find(z=>z.getAttribute('dg_name')==='TTpTablePlaceHolder');
      return b? [...b.querySelectorAll('.dnditem')].map(x=>x.innerText.trim()):[];})()""")
    return zones, bank


def solve_drag(t, src):
    jso(t, "document.body.style.zoom='0.8'; return 1;")
    time.sleep(1)
    zones, bank = _drag_snapshot(t)
    target_zones = [z for z in zones if z["n"] != "TTpTablePlaceHolder"]
    if target_zones and all(z["items"] for z in target_zones):
        # Filled zones are NOT proof the app recorded the answer: a failed drop,
        # a reload, or a previous run leaves items sitting in the zones while the
        # server still gates progress. Returning early here wedged progress at
        # that task forever (silent STUCK). Clear back to the bank and re-answer.
        print("-- drag: zones pre-filled; clearing and re-dropping")
        for z in target_zones:
            for item_text in z["items"]:
                rr = edlib.rects(t)
                it = next((i for i in rr["items"] if i["t"].strip() == item_text.strip()), None)
                bz = next((zz for zz in rr["zones"] if zz["n"] == "TTpTablePlaceHolder"), None)
                if not it or not bz:
                    continue
                t.drag_xy(it["cx"], it["cy"], bz["cx"], bz["cy"])
                time.sleep(0.5)
        zones, bank = _drag_snapshot(t)
        target_zones = [z for z in zones if z["n"] != "TTpTablePlaceHolder"]
        if target_zones and all(z["items"] for z in target_zones):
            return "drag: already"
    prompt = t.js("""(() => {const p=document.querySelector('ed-la-practicearea'); return p? p.innerText.slice(0,2500):'';})()""")
    a_lines = [f"{i}. [{z['n']}] {z['items'][0] if z['items'] else '(empty)'}" for i, z in enumerate(target_zones)]
    q = (f"SOURCE MATERIAL:\n{src}\n\nEXERCISE TEXT:\n{prompt}\n\n"
         f"Target blanks (id, text):\n" + "\n".join(a_lines) +
         f"\n\nWord bank (to place):\n" + "\n".join(f"- {w}" for w in bank) +
         '\n\nMatch each blank id to the exact bank word that belongs there. '
         'Reply {"map": {"0": "<exact bank word>", "1": "..."}}.')
    r = ask_json(q, max_tokens=2000)
    mapping = (r or {}).get("map", {})
    if not mapping:
        print("-- drag LLM empty; retrying")
        r = ask_json(q, max_tokens=2000)
        mapping = (r or {}).get("map", {})
    if not mapping:
        return "drag: EMPTY-MAP"
    # clear zones whose current item is not the desired one
    bank_zone = "TTpTablePlaceHolder"
    for zid, word in mapping.items():
        cur = t.js(f"""(() => {{const z=document.querySelector('.dndZone[dg_name="{zid}"]'); return z? [...z.querySelectorAll('.dnditem')].map(x=>x.innerText.trim()):[];}})()""")
        for item_text in cur:
            if str(word).strip().lower() in item_text.lower():
                continue
            for _ in range(3):
                rr = edlib.rects(t)
                it = next((i for i in rr["items"] if i["t"].strip() == item_text.strip()), None)
                bz = next((z for z in rr["zones"] if z["n"] == bank_zone), None)
                if not it or not bz:
                    break
                t.drag_xy(it["cx"], it["cy"], bz["cx"], bz["cy"])
                time.sleep(0.7)
                break
    done = []
    for zid, word in mapping.items():
        zid = str(zid)
        ok = False
        for attempt in range(4):
            rects = edlib.rects(t)
            item = next((i for i in rects["items"] if i["t"].strip().lower() == str(word).strip().lower()), None)
            if not item:
                item = next((i for i in rects["items"] if str(word).strip().lower() in i["t"].lower()), None)
            z = next((x for x in rects["zones"] if x["n"] == zid), None)
            if not item or not z:
                break
            t.drag_xy(item["cx"], item["cy"], z["cx"], z["cy"] + (attempt - 1) * 4)
            time.sleep(0.8)
            now = t.js(f"""(() => {{const z=document.querySelector('.dndZone[dg_name="{zid}"]');
              return z? [...z.querySelectorAll('.dnditem')].map(x=>x.innerText.trim()):[];}})()""")
            if any(str(word).strip().lower() in x.lower() for x in now):
                ok = True
                break
        done.append(f"{zid}={'ok' if ok else 'FAIL'}")

    # leftover bank words that clearly belong nowhere: drag out of bank to first free zone as fallback
    return "drag: " + " ".join(done)



def solve_cloze(t, src):
    """Legacy cloze: .draggable.wordBankTile -> .TTpanswerDiv droptargets."""
    jso(t, "document.body.style.zoom='0.85'; return 1;")
    time.sleep(0.8)
    data = t.js("""(() => {
      const targets=[...document.querySelectorAll('.TTpanswerDiv')].map((el,i)=>{
        let p=el.closest('.TextDiv')||el.parentElement;
        return {i:i, sentence:(p? p.innerText:'').trim().slice(0,300)};
      });
      const items=[...document.querySelectorAll('.draggable.wordBankTile')].map(el=>el.innerText.trim()).filter(Boolean);
      return {targets, items};
    })()""")
    targets = data["targets"] or []
    items = data["items"] or []
    if not targets or not items:
        return "cloze: no-targets"
    lines = "\n".join(f'{x["i"]}. "{x["sentence"]}"' for x in targets)
    r = ask_json(f"SOURCE MATERIAL:\n{src}\n\nGapped sentences (the gap is where a word must go):\n{lines}\n\n"
                 f"Word bank:\n" + "\n".join(f"- {w}" for w in items) +
                 '\n\nFor each sentence index pick the exact bank word. Reply {"map": {"0": "<word>", ...}}.', max_tokens=1500) or {}
    mapping = r.get("map", {})
    done = []
    for k, word in mapping.items():
        i = int(k)
        ok = False
        for _ in range(3):
            rects = t.js("""(() => {
              const el=document.querySelectorAll('.TTpanswerDiv')[%d];
              if(!el) return null; const b=el.getBoundingClientRect();
              return {x:b.x+b.width/2, y:b.y+b.height/2};
            })()""" % i)
            tile = t.js("""(() => {const els=[...document.querySelectorAll('.draggable.wordBankTile')];
              const el=els.find(e=>e.innerText.trim().toLowerCase()===%s.toLowerCase()) || null;
              if(!el) return null; const b=el.getBoundingClientRect();
              return {x:b.x+b.width/2, y:b.y+b.height/2};})()""" % json.dumps(word))
            if not rects or not tile:
                break
            t.drag_xy(tile["x"], tile["y"], rects["x"], rects["y"])
            time.sleep(0.6)
            txt = t.js("""(() => {const el=document.querySelectorAll('.TTpanswerDiv')[%d]; return el? el.innerText.trim():'';})()""" % i)
            if txt and txt.strip().lower().startswith(str(word).strip().lower()[:4]):
                ok = True
                break
        done.append(f"{i}={'ok' if ok else 'FAIL'}")
    return "cloze: " + " ".join(done)



def solve_cloze_legacy(t, src):
    """Old TTp cloze: jQuery 'drop' trigger with a bank tile element."""
    data = t.js("""(() => ({
      targets:[...document.querySelectorAll('.TTpanswerDiv')].map(e=>({id:e.getAttribute('data-id'),
        ctx:((e.closest('.TextDiv')||e.parentElement||e).innerText||'').replace(/\\s+/g,' ').trim().slice(0,300)})),
      bank:[...document.querySelectorAll('.draggable.wordBankTile')].map(e=>({id:jQuery(e.closest('.draggable')).data('id'), t:e.innerText.trim()}))
    }))()""")
    targets, bank = data["targets"], data["bank"]
    if not targets or not bank:
        return "lcloze: none"
    lines = "\n".join(f'- [{x["id"]}] "..."{x["ctx"][-160:]}' for x in targets)
    r = ask_json(f"SOURCE MATERIAL:\n{src}\n\nSentences with one gap (gap shown as blank):\n{lines}\n\n"
                 f"Word bank:\n" + "\n".join(f"- {w['t']}" for w in bank) +
                 '\n\nChoose the word for each sentence. Reply {"map": {"<target id>": "<exact bank word>"}}.', max_tokens=1200) or {}
    mapping = r.get("map", {})
    done = []
    for tid, word in mapping.items():
        w = next((b for b in bank if b["t"].strip().lower() == str(word).strip().lower()), None)
        if not w:
            done.append(f"{tid}=nw")
            continue
        ok = t.js("""(() => {const tgt=document.querySelector('.TTpanswerDiv[data-id="%s"]');
          const el=jQuery('.draggable[data-id=%s]')[0];
          if(!tgt||!el) return false; jQuery(tgt).triggerHandler('drop', [el]);
          return tgt.getAttribute('ans')==='%s';})()""" % (tid, w["id"], str(w["id"])))
        done.append(f"{tid}={'ok' if ok else 'FAIL'}")
    return "lcloze: " + " ".join(done)


def solve_writing(t, src, task_text):
    r = ask_json(f"SOURCE MATERIAL:\n{src}\n\nTASK:\n{task_text}\n\n"
                 'Write a natural 100-140 word response in the required role. Reply {"text": "..."}.')
    text = (r or {}).get("text") or ""
    if len(text.split()) < 10:
        return "write: FAIL(short)"
    jso(t, """const ed=window.tinymce&&tinymce.activeEditor; if(ed){ed.setContent(%s); ed.save();
      ['keyup','input','change'].forEach(ev=>{try{ed.fireEvent(ev,{});}catch(e){}
        const b=ed.getBody(); b.dispatchEvent(ev==='input'? new InputEvent('input',{bubbles:true}) : new KeyboardEvent(ev,{bubbles:true}));});
      try{ed.nodeChanged();}catch(e){} return 1;} return 0;""" % json.dumps(text))
    time.sleep(0.8)
    jso(t, """const b=[...document.querySelectorAll('a,button,div,span')].filter(e=>(e.innerText||'').trim()==='Done');
      if(b.length){b[b.length-1].click(); return 1;} return 0;""")
    time.sleep(1.5)
    words = jso(t, "const m=document.body.innerText.match(/Words: \\\\d+/); return m?m[0]:'';")
    return f"write: {words}"


def task_text(t):
    return t.js("""(() => {const p=document.querySelector('ed-la-practicearea');
      return p? p.innerText.slice(0,1200):'';})()""")



def solve_openended(t, src=""):
    """Vocabulary open-ended items: type the model answer into each textarea.

    Must go through Input.insertText (real typing) after focus(): assigning
    .value directly leaves the Angular model untouched, so the activity never
    registers and the step stays blocked.
    """
    data = t.js("""(() => {const el=document.querySelector('.learning__angPracticeW ng-component');
      if(!el) return null; const c=ng.probe(el).componentInstance; const qa=c.questionAnswers||{};
      const out=[]; Object.keys(qa).forEach(q=>{Object.keys(qa[q]).forEach(a=>{
        const box=qa[q][a]; out.push({id:'#prOpenEnded__qaItemText--qId_'+q+'_alId_'+a,
          txt:(box.answers&&box.answers[0]&&box.answers[0].txt)||''}); });});
      return out;})()""")
    if not data:
        return "open: nodata"
    ok = 0
    for item in data:
        if not item["txt"]:
            continue
        focused = jso(t, f"const ta=document.querySelector({json.dumps(item['id'])}); if(!ta) return 0; ta.focus(); return 1;")
        if not focused:
            continue
        t.send("Input.insertText", text=item["txt"])
        time.sleep(0.2)
        # Angular's open-ended component only marks the activity done from its
        # (keyup) handler, so fire one after the model has the text.
        jso(t, "const ta=document.querySelector(" + json.dumps(item["id"]) +
            "); if(ta) ta.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true})); return 1;")
        time.sleep(0.2)
        ok += 1
    jso(t, "document.body.focus(); if(document.activeElement) document.activeElement.blur(); return 1;")
    return f"open: {ok}"


def solve_fitb(t, src=""):
    """Sentence with numbered blanks, each a dropdown of options."""
    data = jso(t, """
      const el=document.querySelector('.learning__angPracticeW ng-component');
      if(!el) return null; const c=ng.probe(el).componentInstance;
      const q=(c.practiceData&&c.practiceData.questions&&c.practiceData.questions[0]);
      if(!q) return null;
      return {text:q.text, lists:(q.answerLists||[]).map(l=>(l.answers||[]).map(a=>a.txt))};
    """)
    if not data:
        return "fitb: nodata"
    lines = "\n".join(f"{i+1}. {o}" for i, o in
                      [(i, " | ".join(opts)) for i, opts in enumerate(data["lists"])])
    prompt = ("Sentence with blanks (numbered):\n" + data["text"] +
              "\n\nOptions per blank:\n" + lines +
              '\n\nPick the best option for each blank. Reply ONLY JSON:'
              ' {"1": "<exact option text>", "2": "..."}')
    picks = ask_json(prompt, max_tokens=300) or {}
    out = []
    for i, opts in enumerate(data["lists"]):
        want = picks.get(str(i + 1)) or picks.get(i + 1) or ""
        if not want:
            out.append(f"{i}=?")
            continue
        sel = jso(t, f"""
          const w=document.querySelectorAll('.prFITB__DDLOptionsW')[{i}];
          if(!w) return 0; const s=w.querySelector('.DDLOptions__selected');
          if(s) s.click(); return 1;
        """)
        time.sleep(0.4)
        st = jso(t, f"""
          const w=document.querySelectorAll('.prFITB__DDLOptionsW')[{i}];
          if(!w) return 'nf'; const W={json.dumps(str(want).lower())};
          const items=[...w.querySelectorAll('.DDLOptions__listItem')];
          const pick=items.find(x=>(x.innerText||'').trim()=== {json.dumps(str(want))})
            || items.find(x=>(x.innerText||'').trim().toLowerCase()===W)
            || items.find(x=>(x.innerText||'').toLowerCase().includes(W))
            || items.find(x=>W.includes((x.innerText||'').trim().toLowerCase()));
          if(!pick) return 'noopt'; pick.click(); return 'ok';
        """)
        time.sleep(0.3)
        out.append(f"{i}={st}")
    return "fitb: " + " ".join(out)


def do_task(t, src):
    # A test question renders a beat after the counter updates; classifying too
    # early returns 'other', and the caller then advances to the next question
    # with this one unanswered (scores ~0% and the submit dialog complains).
    for _ in range(40):
        ready = t.js("""(() => (document.querySelector('.prMCQ__qaSet')
          || document.querySelector('.prOpenEnded__qaItemText')
          || document.querySelector('.DDLOptions__selected')
          || document.querySelector('.lessonMultipleAnswer')
          || document.querySelector('.dnditem')
          || document.querySelector('.TTpanswerDiv')
          || (window.tinymce && tinymce.activeEditor && tinymce.activeEditor.initialized))
          ? 1 : 0)()""")
        if ready:
            break
        time.sleep(0.25)
    kind = t.js("""(() => {
      if(window.tinymce && tinymce.activeEditor && tinymce.activeEditor.initialized && document.querySelector('.mce-edit-area, iframe[id$=_ifr]')) return 'writing';
      if(document.querySelector('.prOpenEnded__qaItemText')) return 'open';
      if(document.querySelector('.DDLOptions__selected')) return 'fitb';
      if(document.querySelectorAll('.prMCQ__qaSet').length) return 'mcq';
      if(document.querySelectorAll('.lessonMultipleAnswer').length) return 'multi';
      if(document.querySelectorAll('.dnditem').length && document.querySelectorAll('.dndZone').length) return 'drag';
      if(document.querySelectorAll('.TTpanswerDiv').length && document.querySelectorAll('.draggable').length) return 'lcloze';
      if(document.querySelectorAll('.draggable.wordBankTile').length && document.querySelectorAll('.dndZone').length) return 'cloze';
      return 'other';
    })()""")
    if kind == "mcq":
        return solve_mcq(t, src)
    if kind == "multi":
        return solve_multi(t, src)
    if kind == "drag":
        return solve_drag(t, src)
    if kind == "cloze":
        return solve_cloze(t, src)
    if kind == "lcloze":
        return solve_cloze_legacy(t, src)
    if kind == "fitb":
        return solve_fitb(t, src)
    if kind == "open":
        return solve_openended(t, src)
    if kind == "writing":
        return solve_writing(t, src, task_text(t))
    return "other: " + (task_text(t)[:60].replace("\n", " "))


def next_task(t):
    return jso(t, "const n=document.querySelector('.learning__taskNext'); if(n){n.click(); return 1;} return 0;")


def set_step(t, index):
    """Switch step via the dropdown component API (index 0-based)."""
    return jso(t, f"""const c=ng.probe(document.querySelectorAll('ed-la-dropdownlist')[1]).componentInstance;
      const k=c.dropDownListObj.Children[{index}];
      c.selectListItem({{preventDefault(){{}}}}, k.NodeId, false, {index + 1});
      return k.Name;""")


def start_test(t):
    return jso(t, "const a=document.querySelector('.btnStartTest'); if(a){a.click(); return 1;} return 0;")


def submit_test(t):
    return jso(t, "const a=document.querySelector('.learning__submitTestLink'); if(a){a.click(); return 1;} return 0;")


def main(max_tasks=200):
    t = edlib.tab()
    last_lesson = None
    src = ""
    stuck = 0
    prev_sig = None
    for i in range(max_tasks):
        st = state(t)
        if "login" in st["url"]:
            print("LOGIN LOST")
            return
        sig = (st["lesson"], st["step"], st["counter"])
        if sig == prev_sig:
            stuck += 1
        else:
            stuck = 0
        prev_sig = sig

        if st["lesson"] != last_lesson:
            last_lesson = st["lesson"]
            s = source_text(t)
            src = (s["resource"] or "") + "\n" + s["body"]
            print(f"== {st['lesson']} / {st['step']}")

        # step intro / test entry screens
        if st["step"].startswith("Step 3") and st["counter"] is None:
            if start_test(t):
                print("test started")
                time.sleep(6)
                prev_sig = None
                continue

        if st["counter"] is None and "Start Test" not in t.js("(() => document.body.innerText)()"):
            # no task loaded (intro/reading screen): play media if any, then Next
            played = play_media(t)
            next_task(t)
            time.sleep(3)
            print(f"-- passthrough (media={'y' if played else 'n'})")
            prev_sig = None
            continue

        # test finished? submit button present on last question
        sub = jso(t, "return document.querySelector('.learning__submitTestLink')?1:0;")
        total = st["total"]
        if sub and total and st["counter"] == total and st["step"].startswith("Step 3"):
            submit_test(t)
            time.sleep(4)
            body = t.js("(() => document.body.innerText.slice(0,400))()")
            m = [ln for ln in body.split("\n") if "test score" in ln.lower() or "%" in ln]
            print("TEST SUBMITTED", m[:2])
            prev_sig = None
            continue

        # audio/video comprehension task: make sure we have a transcript
        u = media_url(t)
        if u and "transcript" not in src.lower():
            key = u.rsplit("/", 1)[-1].split("?")[0]
            tr = transcript_for(u, key)
            if tr:
                src += "\n\nAUDIO TRANSCRIPT:\n" + tr
                print(f"-- transcript {key} ({len(tr)} chars)")

        if stuck >= 3:
            # try switching step, then give up
            print("STUCK at", sig)
            return

        neutralize(t)
        out = do_task(t, src)
        print(f"[{st['counter']}/{st['total']}] {out[:110]}")
        next_task(t)
        time.sleep(2.5)
        neutralize(t)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
