import edlib, time

x = edlib.tab()

# Login
x.goto("https://ed22.engdis.com/ptithcm")
time.sleep(4)

# Wait for login form
for _ in range(10):
    if x.js("document.querySelector('input[name=username]')"):
        break
    time.sleep(1)

# Fill login
from login import creds
user, pwd = creds()
if user and pwd:
    x.js(f"document.querySelector('input[name=username]').value = '{user}'")
    x.js(f"document.querySelector('input[name=password]').value = '{pwd}'")
    x.js("document.querySelector('button[type=submit]').click()")
else:
    print("No credentials found")
time.sleep(6)

# Check logged in
url = x.js("location.href")
print(f"After login: {url}")

if "home" not in url:
    x.goto("https://ed22.engdis.com/ptithcm#/home")
    time.sleep(4)

# Get Unit 2 structure
u = x.js("angular.element(document.querySelectorAll('.home__unitW')[1]).scope().unit")
print(f"Unit 2: {u['Name']}")
for i, kid in enumerate(u['Children']):
    print(f"  {i}: {kid['Name']} - {kid['Progress']*100:.0f}%")

# Scroll to Unit 2
x.js('document.querySelectorAll(".home__unitW")[1].scrollIntoView()')
time.sleep(2)

# Click Lessons tab
tab_clicked = x.js("""(() => {
    let tab = document.querySelectorAll('.home__unitW')[1].querySelector('.home__units_lessonsTabHandle');
    if (tab) { tab.click(); return 1; }
    return 0;
})()""")
print(f"Tab clicked: {tab_clicked}")
time.sleep(4)

# Get lesson 4 row rect and click
l4 = x.js("""(() => {
    let rows = document.querySelectorAll('.home__unitW')[1].querySelectorAll('.home__units_lessonRow');
    if (rows[3]) {
        let r = rows[3].getBoundingClientRect();
        return {x: r.x + r.width/2, y: r.y + r.height/2, name: rows[3].innerText.slice(0,50)};
    }
    return null;
})()""")
print(f"Lesson 4 row: {l4}")

if l4:
    x.click_xy(l4['x'], l4['y'])
    time.sleep(2)
    
    # Find Start button
    start = x.js("""(() => {
        let u2 = document.querySelectorAll('.home__unitW')[1];
        let btn = u2.querySelector('.home__units_lessonsStart');
        if (btn) {
            let r = btn.getBoundingClientRect();
            return {x: r.x + r.width/2, y: r.y + r.height/2};
        }
        return null;
    })()""")
    print(f"Start button: {start}")
    
    if start:
        x.click_xy(start['x'], start['y'])
        time.sleep(10)
        
        st = x.js("({lesson:document.querySelectorAll('ed-la-dropdownlist')[0]?.innerText.split('\\n')[0], counter:document.querySelector('.learning__taskNavPCCurrentTask')?.innerText})")
        print(f"Opened: {st}")
    else:
        print("No Start button - lesson may need Continue or have prereqs")
else:
    print("Could not find Lesson 4 row")
