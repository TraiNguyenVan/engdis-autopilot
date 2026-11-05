import edlib, time, json

t = edlib.tab()
t.js("(() => { document.body.style.zoom='0.8'; return 1; })()")
time.sleep(1)

MAP = {"0": "would you rather", "1": "'d rather"}
BANK = "TTpTablePlaceHolder"

def zone_items(zid):
    return t.js(f"""(() => {{const z=document.querySelector('.dndZone[dg_name="{zid}"]');
      return z? [...z.querySelectorAll('.dnditem')].map(x=>x.innerText.trim()):[];}})()""")

# clear any wrong items back to bank
for zid in MAP:
    for txt in zone_items(zid):
        if MAP[zid].lower() in txt.lower():
            continue
        for _ in range(3):
            rr = edlib.rects(t)
            it = next((i for i in rr["items"] if i["t"].strip().lower() == txt.strip().lower()), None)
            bz = next((z for z in rr["zones"] if z["n"] == BANK), None)
            if not it or not bz:
                break
            t.drag_xy(it["cx"], it["cy"], bz["cx"], bz["cy"])
            time.sleep(0.8)
            break
print("after clear", {z: zone_items(z) for z in MAP})

for zid, word in MAP.items():
    if any(word.lower() in x.lower() for x in zone_items(zid)):
        print(zid, "already")
        continue
    ok = False
    for attempt in range(4):
        rr = edlib.rects(t)
        item = next((i for i in rr["items"] if i["t"].strip().lower() == word.lower()), None)
        if not item:
            item = next((i for i in rr["items"] if word.lower() in i["t"].lower()), None)
        z = next((x for x in rr["zones"] if x["n"] == zid), None)
        if not item or not z:
            print(zid, "norect", bool(item), bool(z))
            break
        t.drag_xy(item["cx"], item["cy"], z["cx"], z["cy"] + (attempt - 1) * 4)
        time.sleep(0.9)
        if any(word.lower() in x.lower() for x in zone_items(zid)):
            ok = True
            break
    print(zid, "ok" if ok else "FAIL", zone_items(zid))
