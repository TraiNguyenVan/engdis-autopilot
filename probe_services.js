(function () {
  var inj = angular.element(document.body).injector();
  var names = ["activityService", "lessonService", "taskService", "learningService", "practiceService", "courseService", "apiService", "dataService", "sessionService", "userService", "authenticationService"];
  var res = {};
  for (var i = 0; i < names.length; i++) {
    var n = names[i];
    try {
      var s = inj.get(n);
      var keys = [];
      for (var k in s) {
        try { if (typeof s[k] === "function") keys.push(k); } catch (e2) {}
      }
      res[n] = keys.slice(0, 30);
    } catch (e) {
      res[n] = null;
    }
  }
  return res;
})()
