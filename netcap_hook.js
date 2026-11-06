(function () {
  if (window.__netlog) return "already";
  window.__netlog = [];
  var push = function (rec) { try { window.__netlog.push(rec); } catch (e) {} };

  var oOpen = XMLHttpRequest.prototype.open;
  var oSend = XMLHttpRequest.prototype.send;
  var oSetH = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.open = function (m, u) { this.__m = m; this.__u = String(u); this.__h = {}; return oOpen.apply(this, arguments); };
  XMLHttpRequest.prototype.setRequestHeader = function (k, v) { try { this.__h[k] = v; } catch (e) {} return oSetH.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (body) {
    var self = this;
    var rec = { kind: "xhr", m: this.__m, u: this.__u, body: typeof body === "string" ? body.slice(0, 6000) : "",
                h: this.__h, t: Math.round(performance.now()) };
    this.addEventListener("load", function () {
      rec.status = self.status;
      try { rec.resp = String(self.responseText).slice(0, 6000); } catch (e) {}
      push(rec);
    });
    this.addEventListener("error", function () { rec.status = self.status; rec.err = "network-error"; push(rec); });
    this.addEventListener("abort", function () { rec.status = self.status; rec.err = "abort"; push(rec); });
    this.addEventListener("timeout", function () { rec.status = self.status; rec.err = "timeout"; push(rec); });
    return oSend.apply(this, arguments);
  };

  if (window.fetch) {
    var oFetch = window.fetch;
    window.fetch = function (input, init) {
      var url = String(input && input.url ? input.url : input);
      var rec = { kind: "fetch", m: (init && init.method) || "GET", u: url,
                  body: init && init.body ? String(init.body).slice(0, 6000) : "",
                  h: (init && init.headers) || {}, t: Math.round(performance.now()) };
      return oFetch.apply(this, arguments).then(function (r) {
        rec.status = r.status;
        try { r.clone().text().then(function (txt) { rec.resp = txt.slice(0, 6000); push(rec); }); }
        catch (e) { push(rec); }
        return r;
      }, function (e) { rec.err = String(e).slice(0, 200); push(rec); throw e; });
    };
  }

  if (window.WebSocket) {
    var oWS = window.WebSocket;
    window.WebSocket = function (url, protos) {
      var ws = protos ? new oWS(url, protos) : new oWS(url);
      var rec = { kind: "ws", u: String(url), frames: [] };
      push(rec);
      var oSendWS = ws.send;
      ws.send = function (data) {
        try { rec.frames.push({ dir: "out", data: String(data).slice(0, 2000) }); } catch (e) {}
        return oSendWS.apply(ws, arguments);
      };
      ws.addEventListener("message", function (ev) {
        try { rec.frames.push({ dir: "in", data: String(ev.data).slice(0, 2000) }); } catch (e) {}
      });
      return ws;
    };
    window.WebSocket.prototype = oWS.prototype;
  }
  return "hooked";
})();
