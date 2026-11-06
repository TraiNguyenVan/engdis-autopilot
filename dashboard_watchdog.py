#!/usr/bin/env python3
"""Restart missing dashboard components; report each start."""
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def listening(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(('127.0.0.1', port)) == 0

def ensure(port, script, *args):
    if listening(port):
        return False
    with open(ROOT / 'dashboard-service.log', 'a') as log:
        subprocess.Popen([sys.executable, str(ROOT / script), *args], cwd=ROOT,
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True)
    for _ in range(30):
        if listening(port):
            return True
        time.sleep(0.2)
    raise RuntimeError(f'{script} failed to start on port {port}')

if __name__ == '__main__':
    dashboard = ensure(8796, 'dashboard_server.py', '--port', '8796')
    proxy = ensure(8797, 'dashboard_proxy.py')
    if dashboard or proxy:
        print('Engdis dashboard started: https://engdis.mairapvipproforsure.id.vn/')
