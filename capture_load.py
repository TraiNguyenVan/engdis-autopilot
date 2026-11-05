import edlib, json, time

x = edlib.tab()
hook = open('/opt/data/cache/scratch/ed22u1/hook_net.js').read()
x.send("Page.addScriptToEvaluateOnNewDocument", source=hook)
x.goto("https://ed22.engdis.com/Runtime/learningArea.html?v=5", wait=2)
for _ in range(20):
    time.sleep(1.5)
    try:
        n = x.js("window.__netlog ? window.__netlog.length : 0")
    except Exception:
        n = 0
    if n and n > 15:
        break
time.sleep(3)
log = x.js("window.__netlog") or []
print("entries", len(log))
keep = []
for e in log:
    u = e.get("u", "")
    if "mixpanel" in u or "google" in u:
        continue
    rec = {k: e.get(k) for k in ("m", "u", "status") if e.get(k) is not None}
    if e.get("body") and e["body"] not in ("null", ""):
        rec["body"] = e["body"][:600]
    keep.append(rec)
open('/opt/data/cache/scratch/ed22u1/net_dump.json', 'w').write(json.dumps(keep, indent=1))
for r in keep[:40]:
    print(r.get("m"), r.get("status"), r.get("u")[:110])
