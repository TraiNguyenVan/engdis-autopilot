import edlib, json, time

x = edlib.tab()
res = x.js('''(function(){
  var s = angular.element(document.querySelectorAll('.home__unitW')[1]).scope();
  while (s && !s.unitsCtrl) s = s.$parent;
  if (!s) return {err:'no unitsCtrl'};
  var c = s.unitsCtrl;
  var unit = c.units[1];
  var lesson = unit.Children[3];
  var info = {name: lesson.Name, id: lesson.NodeId, progress: lesson.Progress};
  try {
    c.goToLesson(lesson, false, 'Unit');
    return {ok:1, info: info};
  } catch (e) {
    return {err: String(e), info: info};
  }
})()''')
print(json.dumps(res))
time.sleep(10)
print("url:", x.js("location.href"))
print(x.js("({lesson:document.querySelectorAll('ed-la-dropdownlist')[0]?.innerText.split('\\n')[0], step:document.querySelectorAll('ed-la-dropdownlist')[1]?.innerText.split('\\n')[0], counter:document.querySelector('.learning__taskNavPCCurrentTask')?.innerText})"))
