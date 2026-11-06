"""Capture the existing Engdis Chrome tab without navigating or controlling it."""
import base64
import json
import urllib.request
from urllib.parse import urlsplit
from websockets.sync.client import connect


def capture():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:9225/json', timeout=3) as response:
        targets = json.load(response)
    pages = [t for t in targets if t.get('type') == 'page' and
             urlsplit(t.get('url', '')).hostname == 'ed22.engdis.com']
    pages.sort(key=lambda t: 'learningArea' not in t.get('url', ''))
    if not pages:
        raise RuntimeError('No Engdis browser tab available')
    ws_url = pages[0].get('webSocketDebuggerUrl', '')
    parsed = urlsplit(ws_url)
    if parsed.scheme != 'ws' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.port != 9225:
        raise RuntimeError('Invalid browser endpoint')
    with connect(ws_url, open_timeout=3, close_timeout=1, max_size=20_000_000, proxy=None) as ws:
        ws.send(json.dumps({'id': 1, 'method': 'Page.captureScreenshot', 'params': {'format': 'png'}}))
        while True:
            msg = json.loads(ws.recv(timeout=5))
            if msg.get('id') == 1:
                if 'error' in msg:
                    raise RuntimeError('Screenshot capture failed')
                return base64.b64decode(msg['result']['data'], validate=True)
