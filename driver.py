"""Minimal CDP driver over websockets for a locally launched Chromium."""
import json, itertools, time, urllib.request
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed

class Tab:
    def __init__(self, ws_url):
        self.url = ws_url
        self.ws = connect(ws_url, max_size=50_000_000, open_timeout=20, ping_interval=None, close_timeout=5)
        self.ids = itertools.count(1)
        self.dialogs = []

    def send(self, method, timeout=60, **params):
        try:
            return self._send(method, timeout, params)
        except (ConnectionClosed, OSError):
            self.reconnect()
            return self._send(method, timeout, params)
        except TimeoutError:
            # a dead socket looks like a timeout: recv never returns
            self.reconnect()
            return self._send(method, timeout, params)

    def reconnect(self):
        url = self.url
        try:
            self.ws.close()
        except Exception:
            pass
        self.ws = connect(url, max_size=50_000_000, open_timeout=20, ping_interval=None, close_timeout=5)
        for m in ("Page.enable", "Runtime.enable", "Network.enable"):
            try:
                self._send(m, 20, {})
            except Exception:
                pass

    def _send(self, method, timeout, params):
        i = next(self.ids)
        self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        end = time.time() + timeout
        while time.time() < end:
            self.ws.socket.settimeout(max(0.1, end - time.time()))
            try:
                msg = json.loads(self.ws.recv(timeout=max(0.1, end - time.time())))
            except ConnectionClosed:
                raise
            except Exception:
                continue
            if msg.get("method") == "Page.javascriptDialogOpening":
                # a native alert/confirm blocks the renderer until handled:
                # every later evaluate would hang. Always auto-accept.
                self.dialogs.append(msg.get("params", {}).get("message", ""))
                try:
                    j = next(self.ids)
                    self.ws.send(json.dumps({"id": j, "method": "Page.handleJavaScriptDialog",
                                             "params": {"accept": True}}))
                except Exception:
                    pass
                continue
            if msg.get("id") == i:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(method)

    def js(self, expr):
        r = self.send("Runtime.evaluate", expression=expr, returnByValue=True,
                      awaitPromise=True, userGesture=True)
        if "exceptionDetails" in r:
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:500])
        return r.get("result", {}).get("value")

    def goto(self, url, wait=3.0):
        self.send("Page.navigate", url=url)
        time.sleep(wait)

    def mouse(self, etype, x, y, button="none", buttons=0, clickCount=0):
        return self.send("Input.dispatchMouseEvent", type=etype, x=x, y=y,
                         button=button, buttons=buttons, clickCount=clickCount,
                         pointerType="mouse")

    def click_xy(self, x, y):
        self.mouse("mouseMoved", x, y)
        self.mouse("mousePressed", x, y, "left", 1, 1)
        time.sleep(0.05)
        self.mouse("mouseReleased", x, y, "left", 0, 1)

    def drag_xy(self, x1, y1, x2, y2, steps=12, pause=0.06):
        self.mouse("mouseMoved", x1, y1)
        time.sleep(0.1)
        self.mouse("mousePressed", x1, y1, "left", 1, 1)
        time.sleep(0.1)
        for i in range(1, steps + 1):
            self.mouse("mouseMoved", x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps, "left", 1)
            time.sleep(pause)
        time.sleep(0.1)
        self.mouse("mouseReleased", x2, y2, "left", 0, 1)
        time.sleep(0.4)

    def rect(self, selector_or_js):
        expr = selector_or_js if selector_or_js.strip().startswith("(") else \
            f"(() => {{const e=document.querySelector({json.dumps(selector_or_js)}); if(!e) return null; const b=e.getBoundingClientRect(); return {{x:b.x,y:b.y,w:b.width,h:b.height,cx:b.x+b.width/2,cy:b.y+b.height/2}};}})()"
        return self.js(expr)

    def shot(self, path):
        r = self.send("Page.captureScreenshot", format="png")
        import base64
        open(path, "wb").write(base64.b64decode(r["data"]))
        return path


def open_tab(port=9222, url="about:blank"):
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
    pages = [t for t in tabs if t.get("type") == "page"]
    pages.sort(key=lambda t: 0 if "learningArea" in (t.get("url") or "") else 1)
    if pages:
        t = pages[0]
        tab = Tab(t["webSocketDebuggerUrl"])
    else:
        t = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/new?about:blank"))
        tab = Tab(t["webSocketDebuggerUrl"])
    tab.send("Page.enable")
    tab.send("Runtime.enable")
    tab.send("Network.enable")
    if url != "about:blank":
        tab.goto(url)
    return tab


def inject_cookies(tab, cookie_file, domain_filter="engdis.com"):
    cookies = json.load(open(cookie_file))
    n = 0
    for c in cookies:
        if not c.get("name") or domain_filter not in c.get("domain", ""):
            continue
        p = {"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c.get("path", "/"),
             "secure": c.get("secure", False), "httpOnly": c.get("httpOnly", False),
             "sameSite": c.get("sameSite", "Lax")}
        if c.get("expires", -1) and c["expires"] > 0:
            p["expires"] = c["expires"]
        try:
            tab.send("Network.setCookie", **p)
            n += 1
        except Exception as e:
            print("cookie fail", c.get("name"), str(e)[:80])
    return n
