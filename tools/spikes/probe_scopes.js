(function () {
  var el = document.querySelectorAll("ed-la-dropdownlist")[0];
  var s = angular.element(el).scope();
  var out = [];
  var depth = 0;
  while (s && depth < 15) {
    var keys = Object.keys(s).filter(function (k) { return k.indexOf("$") !== 0; });
    var fns = keys.filter(function (k) {
      try { return typeof s[k] === "function" && /lesson|node|activ|task|load|chang|select|next/i.test(k); } catch (e) { return false; }
    });
    var ctrl = s.__ctrl || null;
    out.push({ depth: depth, ctrlName: s && s.constructor ? null : null, fns: fns.slice(0, 40), keyCount: keys.length });
    s = s.$parent;
    depth++;
  }
  return out;
})()
