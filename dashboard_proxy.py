#!/usr/bin/env python3
"""Authenticated loopback reverse proxy for the read-only dashboard."""
import base64
import hmac
import http.client
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PASSWORD = Path('/opt/data/.config/engdis/dashboard-password').read_text().strip()
EXPECTED = 'Basic ' + base64.b64encode(('trai:' + PASSWORD).encode()).decode()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not hmac.compare_digest(self.headers.get('Authorization', ''), EXPECTED):
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="Engdis dashboard", charset="UTF-8"')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        conn = http.client.HTTPConnection('127.0.0.1', 8796, timeout=5)
        try:
            conn.request('GET', self.path, headers={'Host': 'localhost:8796'})
            resp = conn.getresponse()
            data = resp.read()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in ('connection', 'transfer-encoding', 'content-length', 'server', 'date'):
                    self.send_header(k, v)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
        except (OSError, http.client.HTTPException):
            self.send_error(502)
        finally:
            conn.close()
    def log_message(self, fmt, *args):
        pass

if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8797), Handler).serve_forever()
