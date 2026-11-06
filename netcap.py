"""Record every XHR/fetch/WebSocket the learning area makes while one task cycle runs.

Read-only observation: it clicks Next and Check answer, never submits.
Writes net_calls.json next to this file.

Usage: python3 netcap.py [cycles]
"""
import json
import os
import sys
import time

import edlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "net_calls.json")
HOOK = open(os.path.join(HERE, "netcap_hook.js"), encoding="utf-8").read()

NOISE = ("mixpanel", "google-analytics", "googletagmanager", "facebook", "doubleclick",
         "hotjar", "sentry", "clarity")

LEARN = "https://ed22.engdis.com/Runtime/learningArea.html?v=5"


def main(cycles=2):
    t = edlib.tab()
    t.send("Page.enable")
    t.send("Runtime.enable")
    t.send("Page.addScriptToEvaluateOnNewDocument", source=HOOK)
    t.goto(LEARN, wait=6)
    if not t.js("!!window.__netlog"):
        print("HOOK-MISSING")
        return 1
    t.js("window.__netlog = []")
    for i in range(cycles):
        t.js("(() => {const b=document.querySelector('.learning__taskNext'); if(b) b.click(); return 1;})()")
        time.sleep(3)
        t.js("""(() => {const b=[...document.querySelectorAll('a,button,input')]
            .filter(e=>/^(Check answer|Check Answer)$/i.test((e.innerText||e.value||'').trim()));
            if(b.length) b[0].click(); return 1;})()""")
        time.sleep(3)
        print("cycle", i + 1, "done")
    log = t.js("window.__netlog") or []
    keep = [r for r in log if not any(n in (r.get("u") or "").lower() for n in NOISE)]
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(keep, f, indent=1)
    print("calls", len(keep), "->", OUT)
    for r in keep:
        if (r.get("m") or "GET").upper() != "GET" or r.get("kind") == "ws":
            print(r.get("kind"), r.get("m"), r.get("status"), (r.get("u") or "")[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 2))
