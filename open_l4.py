import edlib, time

x = edlib.tab()
x.goto("https://ed22.engdis.com/Runtime/learningArea.html?v=5")
time.sleep(5)

# Get dropdown rect and click it
dd_rect = x.js("""(() => {
    let dd = document.querySelectorAll('ed-la-dropdownlist')[0];
    let r = dd.getBoundingClientRect();
    return {x: r.x + r.width/2, y: r.y + r.height/2};
})()""")
print(f"Clicking dropdown at ({dd_rect['x']}, {dd_rect['y']})")
x.click_xy(dd_rect['x'], dd_rect['y'])
time.sleep(2)

# Wait for items
items = x.js("""(() => {
    let dd = document.querySelectorAll('ed-la-dropdownlist')[0];
    let items = dd.querySelectorAll('.dropDown__listItem');
    return [...items].map((x,i) => ({i:i, text:x.innerText.slice(0,40), rect:x.getBoundingClientRect()}));
})()""")
print(f"Found {len(items)} items")
for item in items:
    print(f"  {item['i']}: {item['text']}")

if len(items) > 3:
    it = items[3]
    cx = it['rect']['x'] + it['rect']['width']/2
    cy = it['rect']['y'] + it['rect']['height']/2
    print(f"Clicking item 3 at ({cx}, {cy})")
    x.click_xy(cx, cy)
    time.sleep(8)
    
    st = x.js("({lesson:document.querySelectorAll('ed-la-dropdownlist')[0]?.innerText.split('\\n')[0], step:document.querySelectorAll('ed-la-dropdownlist')[1]?.innerText.split('\\n')[0], counter:document.querySelector('.learning__taskNavPCCurrentTask')?.innerText})")
    print("After click:", st)
