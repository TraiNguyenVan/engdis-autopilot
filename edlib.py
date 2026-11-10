"""Helpers for the English Discoveries learning area (ed22.engdis.com)."""
import json, time
import driver
import config

PORT = config.CDP_PORT

def tab():
    t = driver.open_tab(port=PORT)
    return t

def home(t):
    t.goto("https://ed22.engdis.com/ptithcm#/home", wait=6)

def open_lesson(t, unit_idx=0, lesson_idx=0):
    """From dashboard: expand unit N, click the lesson's Continue."""
    home(t)
    t.js(f"""(() => {{const tabs=[...document.querySelectorAll('.home__units_lessonsTabHandle')]; if(tabs[{unit_idx}]) tabs[{unit_idx}].click(); return 1;}})()""")
    time.sleep(1.5)
    t.js(f"""(() => {{
      const w=document.querySelectorAll('.home__unitW')[{unit_idx}];
      const items=[...w.querySelectorAll('[ng-click*=statusClick], .home__unit, .home__unitNameW, .home__units_lesson, li')];
      return w.innerText;}})()""")

def state(t):
    return t.js("""(() => {
      const txt=s=>{const e=document.querySelector(s); return e? e.innerText.trim(): null;};
      const counter=txt('.learning__taskNavPCCurrentTask');
      const total=txt('.learning__taskNavPCTotalTasks');
      const instr=txt('.learning__tasksNav_instructionsW');
      const title=(document.querySelector('ed-la-dropdownlist')||{}).innerText||'';
      return {url:location.href, step:(document.querySelectorAll('ed-la-dropdownlist')[1]||{}).innerText, instr, counter, total,
              finished: !!document.querySelector('.learning__tasksNav_pager_intro')};
    })()""")

def next_task(t):
    return t.js("""(() => {
      const el=document.querySelector('.learning__taskNext');
      if(el){el.click(); return 'next';}
      return 'not-found';
    })()""")

def rects(t):
    return t.js("""(() => ({
      items:[...document.querySelectorAll('.dnditem')].map(e=>({t:e.innerText.trim(), cx:e.getBoundingClientRect().x+e.getBoundingClientRect().width/2, cy:e.getBoundingClientRect().y+e.getBoundingClientRect().height/2})),
      zones:[...document.querySelectorAll('.dndZone')].map(e=>({n:e.getAttribute('dg_name'), cx:e.getBoundingClientRect().x+e.getBoundingClientRect().width/2, cy:e.getBoundingClientRect().y+e.getBoundingClientRect().height/2, count:e.querySelectorAll('.dnditem').length}))
    }))()""")

def drag_match(t, pairs):
    """pairs: list of (item_text_prefix, zone_name)"""
    out = []
    for text, zone in pairs:
        r = rects(t)
        item = next((i for i in r["items"] if i["t"].startswith(text)), None)
        z = next((x for x in r["zones"] if x["n"] == zone), None)
        if not item or not z:
            out.append(("MISS", text[:25], zone)); continue
        t.drag_xy(item["cx"], item["cy"], z["cx"], z["cy"])
        out.append(("ok", text[:25], zone))
        time.sleep(0.6)
    return out

def click_answer(t, text):
    """Click an MCQ/multi-select answer whose text matches (prefix, case-insensitive)."""
    return t.js("""(() => {
      const want=%s.toLowerCase();
      const cands=[...document.querySelectorAll('.prMCQ__answerLabel, .lessonMultipleAnswer, .prMCQ__answers')];
      const el=cands.find(e=>e.innerText.trim().toLowerCase().startsWith(want));
      if(!el) return 'nf: '+cands.map(e=>e.innerText.trim().slice(0,20)).join('|');
      (el.querySelector('label')||el).click();
      return 'clicked';
    })()""" % __import__("json").dumps(text))

def visible_task(t):
    """Return instruction + question + option texts of the current task."""
    return t.js("""(() => {
      const pa=document.querySelector('ed-la-practicearea');
      const instr=(document.querySelector('.learning__tasksNav_instructionsW')||{}).innerText||'';
      const q=(document.querySelector('.qText, .prMCQ__question, .practice__question')||{}).innerText||'';
      const opts=[...document.querySelectorAll('.prMCQ__answerLabel, .lessonMultipleAnswer, .dnditem, .prMT_T2T__answersText')].map(e=>e.innerText.trim()).filter(Boolean);
      const counter=(document.querySelector('.learning__taskNavPCCurrentTask')||{}).innerText;
      return {counter, instr:instr.trim().slice(0,300), q:q.trim().slice(0,300), opts, html_len:(pa&&pa.innerHTML.length)||0};
    })()""")

def mcq_sets(t):
    return t.js("""(() => [...document.querySelectorAll('.prMCQ__qaSet')].map((s,i)=>({
      q:(s.querySelector('.prMCQ__questionText')||{}).innerText||'',
      opts:[...s.querySelectorAll('.prMCQ__answers:not(.hide) .prMCQ__answerLabel')].map(l=>({t:l.innerText.trim(), for:l.getAttribute('for')}))
    })))()""")

def click_for(t, lbl_for):
    return t.js("""(() => {
      const l = document.querySelector('.prMCQ__answerLabel[for=%s]');
      if (!l) return 'nf';
      const inp = document.getElementById(l.getAttribute('for'));
      if (inp) {
        inp.checked = true;
        inp.dispatchEvent(new Event('change', { bubbles: true }));
      }
      const parent = l.closest('.prMCQ__answers');
      if (parent) {
        parent.classList.add('prMCQ__answers--checked');
      }
      l.click();
      return 'ok';
    })()""" % __import__("json").dumps(lbl_for))

def answer_sets(t, picks):
    """picks: list of (question_substring, option_substring)"""
    sets = mcq_sets(t)
    out = []
    for qsub, osub in picks:
        s = next((x for x in sets if qsub.lower() in x["q"].lower()), None)
        if not s:
            out.append(("MISSq", qsub)); continue
        o = next((x for x in s["opts"] if x["t"].lower().startswith(osub.lower())), None)
        if not o:
            out.append(("MISSo", osub, [x["t"][:25] for x in s["opts"]])); continue
        click_for(t, o["for"])
        out.append(("ok", s["q"][:30], o["t"][:25]))
        time.sleep(0.3)
    return out
