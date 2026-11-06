"""Grep the app bundles for API path literals (Track B recon helper).

The bundles build URLs from `localStorage.api.host`, so plain '/api/' literals do
not appear — this matches '<Controller>/<Method>' fragments instead.

Usage: python3 netprobe.py
"""
import edlib

JS = r"""
(async () => {
  const files = ['https://ed22.engdis.com/appNG/LearningArea/dist/learningAreaApp.js',
                 'https://ed22.engdis.com/appNG/LearningArea/dist/LAScripts.min.js',
                 'https://ed22.engdis.com/appNG/LearningArea/dist/reqFunc.min.js'];
  const hits = {};
  const words = ['Progress', 'CourseTree', 'practiceManager', 'Test', 'Activity', 'Answer',
                 'Item', 'Lesson', 'Media', 'Ping'];
  for (const f of files) {
    const txt = await (await fetch(f, {credentials: 'include'})).text();
    for (const w of words) {
      let i = -1, n = 0;
      while ((i = txt.indexOf(w + '/', i + 1)) >= 0 && n < 40) {
        const m = txt.slice(i, i + 60).match(/^[A-Za-z]+\/[A-Za-z0-9_\-\/]+/);
        if (m) { hits[m[0]] = (hits[m[0]] || 0) + 1; n++; }
      }
    }
  }
  return Object.keys(hits).sort();
})()
"""

t = edlib.tab()
res = t.js(JS) or []
print("paths:", len(res))
for r in res:
    print(r)
