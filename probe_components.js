(function () {
  var res = {};
  var els = document.querySelectorAll("[class*=learning], ed-la-dropdownlist, ed-la-tasksnav, ed-la-practicearea, app-root, .learningArea, ed-la-tasksmenu, body > *");
  var seen = {};
  for (var i = 0; i < els.length; i++) {
    var el = els[i];
    var tag = el.tagName.toLowerCase();
    if (seen[tag]) continue;
    try {
      var probe = ng.probe(el);
      if (!probe || !probe.componentInstance) continue;
      var c = probe.componentInstance;
      var keys = Object.keys(c);
      var fns = keys.filter(function (k) { try { return typeof c[k] === "function"; } catch (e) { return false; } });
      res[tag] = fns.slice(0, 40);
      seen[tag] = 1;
    } catch (e) {}
  }
  return res;
})()
