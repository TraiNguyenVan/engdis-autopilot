(function () {
  if (window.__netlog) return "already";
  window.__netlog = [];
  var origOpen = XMLHttpRequest.prototype.open;
  var origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) {
    this.__m = m; this.__u = u;
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function (body) {
    var rec = { m: this.__m, u: this.__u, body: typeof body === "string" ? body.slice(0, 4000) : String(body).slice(0, 300), t: Date.now() };
    var self = this;
    this.addEventListener("load", function () {
      rec.status = self.status;
      try { rec.resp = String(self.responseText).slice(0, 1500); } catch (e) {}
      window.__netlog.push(rec);
    });
    return origSend.apply(this, arguments);
  };
  if (window.fetch) {
    var of = window.fetch;
    window.fetch = function (input, init) {
      var rec = { m: (init && init.method) || "GET", u: String(input && input.url ? input.url : input), body: init && init.body ? String(init.body).slice(0, 4000) : "", t: Date.now(), f: 1 };
      window.__netlog.push(rec);
      return of.apply(this, arguments).then(function (r) {
        try { r.clone().text().then(function (txt) { rec.status = r.status; rec.resp = txt.slice(0, 1500); }); } catch (e) {}
        return r;
      });
    };
  }
  return "hooked";
})()
