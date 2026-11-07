(function () {
  var tags = {};
  var els = document.querySelectorAll("*");
  for (var i = 0; i < els.length; i++) {
    var n = els[i].tagName.toLowerCase();
    if (n.indexOf("ed-la") === 0 || n.indexOf("ed-") === 0) tags[n] = (tags[n] || 0) + 1;
  }
  return tags;
})()
