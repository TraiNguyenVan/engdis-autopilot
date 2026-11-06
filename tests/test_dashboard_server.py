import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from dashboard_server import make_server

class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        (self.root / 'secret').write_text('sensitive-credential')
        (self.root / 'proc').mkdir()
        (self.root / 'cover_report_u3.json').write_text(json.dumps({'unit':'<img src=x onerror=alert(1)>','lessons':{}}))
        self.server = make_server(0, data_root=self.root, proc_root=self.root / 'proc')
        self.thread = threading.Thread(target=self.server.serve_forever); self.thread.start()
        self.url = 'http://127.0.0.1:%d' % self.server.server_port
    def tearDown(self):
        self.server.shutdown(); self.thread.join(); self.server.server_close(); self.tmp.cleanup()
    def test_routes_and_headers(self):
        with urlopen(self.url + '/api/status') as r:
            self.assertEqual(r.headers['Cache-Control'], 'no-store'); self.assertTrue(r.headers['Content-Type'].startswith('application/json'))
            body = r.read().decode(); self.assertNotIn('sensitive-credential', body); self.assertEqual(json.loads(body)['report']['unit'], '<img src=x onerror=alert(1)>')
        for path in ('/', '/dashboard.js', '/dashboard.css'):
            with urlopen(self.url + path) as r: self.assertEqual(r.status, 200)
        with urlopen(self.url + '/') as r:
            html = r.read().decode()
            for label in ('Harness', 'Latest activity', 'Saved unit snapshot', 'Lessons', 'Source', 'Last updated'): self.assertIn(label, html)
            self.assertNotIn('<img src=x', html); self.assertNotIn('https://', html)
        with urlopen(self.url + '/dashboard.js') as r:
            script = r.read().decode(); self.assertNotIn('innerHTML', script); self.assertIn('textContent', script)
    def test_rejections(self):
        with self.assertRaises(ValueError): make_server(0, host='0.0.0.0')
        for path in ('/secret', '/?../secret', '/api/status?x=1'):
            with self.assertRaises(HTTPError) as e: urlopen(self.url + path)
            self.assertEqual(e.exception.code, 404)
        with self.assertRaises(HTTPError) as e: urlopen(Request(self.url + '/api/status', method='POST'))
        self.assertEqual(e.exception.code, 405)

if __name__ == '__main__': unittest.main()
