"""Loopback-only, read-only dashboard server."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from dashboard_data import snapshot

HERE = Path(__file__).resolve().parent
ASSETS = {'/': ('dashboard.html', 'text/html; charset=utf-8'), '/dashboard.js': ('dashboard.js', 'text/javascript; charset=utf-8'), '/dashboard.css': ('dashboard.css', 'text/css; charset=utf-8')}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send_data(self, code, data, content_type):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        try:
            if self.path == '/api/status':
                data = json.dumps(snapshot(self.server.data_root, self.server.proc_root), allow_nan=False).encode()
                self.send_data(200, data, 'application/json; charset=utf-8')
            elif self.path in ASSETS:
                name, content_type = ASSETS[self.path]
                self.send_data(200, (HERE / name).read_bytes(), content_type)
            else: self.send_data(404, b'Not found', 'text/plain; charset=utf-8')
        except (OSError, ValueError, TypeError):
            self.send_data(500, b'Internal error', 'text/plain; charset=utf-8')
    def do_POST(self): self.send_data(405, b'Method not allowed', 'text/plain; charset=utf-8')

def make_server(port=8765, host='127.0.0.1', data_root=HERE, proc_root=Path('/proc')):
    if host != '127.0.0.1': raise ValueError('Only 127.0.0.1 is allowed')
    if not isinstance(port, int) or not 0 <= port <= 65535: raise ValueError('Invalid port')
    server = ThreadingHTTPServer((host, port), Handler)
    server.data_root, server.proc_root = Path(data_root), Path(proc_root)
    return server

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    try: server = make_server(args.port)
    except ValueError as exc: parser.error(str(exc))
    print('Dashboard: http://127.0.0.1:%s/' % server.server_port, flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__ == '__main__': main()
