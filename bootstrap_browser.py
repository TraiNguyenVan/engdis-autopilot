import argparse
import glob
import os
import signal
import subprocess
import sys
import time
import urllib.request
import config

def build_chrome_flags(chrome_bin: str, port: int, profile_dir: str) -> list[str]:
    return [
        chrome_bin,
        "--headless=new",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--renderer-process-limit=2",
        "--window-size=1400,1000",
        "--autoplay-policy=no-user-gesture-required",
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        "--js-flags=--max-old-space-size=768",
        "about:blank"
    ]

def clean_profile_locks(profile_dir: str):
    lock_patterns = ["SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort"]
    for pat in lock_patterns:
        for filepath in glob.glob(os.path.join(profile_dir, pat)):
            try:
                os.remove(filepath)
            except OSError:
                pass

def wait_for_cdp(port: int, timeout: float = 15.0) -> bool:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "EngdisBootstrap/1.0"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.getcode() == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False

def main():
    parser = argparse.ArgumentParser(description="Bootstrap headless Chromium with CDP")
    parser.add_argument("--port", type=int, default=config.CDP_PORT)
    parser.add_argument("--profile", default="/data/profile")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    os.makedirs(args.profile, exist_ok=True)
    clean_profile_locks(args.profile)

    cmd = build_chrome_flags(config.CHROME_BIN, args.port, args.profile)
    sys.stderr.write(f"[bootstrap] Launching: {' '.join(cmd)}\n")
    proc = subprocess.Popen(cmd)

    def handle_signal(sig, frame):
        sys.stderr.write("[bootstrap] Terminating Chrome...\n")
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if not wait_for_cdp(args.port, timeout=args.timeout):
        sys.stderr.write(f"[bootstrap] Timeout waiting for CDP on port {args.port}\n")
        proc.terminate()
        sys.exit(1)

    sys.stderr.write(f"[bootstrap] Chromium ready on port {args.port} (PID: {proc.pid})\n")
    try:
        proc.wait()
    except KeyboardInterrupt:
        handle_signal(signal.SIGINT, None)

if __name__ == "__main__":
    main()
