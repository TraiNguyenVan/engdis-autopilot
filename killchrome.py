import os, signal, glob, time

target = "9225"
killed = []
for p in glob.glob("/proc/[0-9]*/cmdline"):
    try:
        with open(p, "rb") as f:
            cmd = f.read().decode("utf-8", "ignore")
    except Exception:
        continue
    if "remote-debugging-port=" + target in cmd and "chrome-linux64" in cmd:
        pid = int(p.split("/")[2])
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(pid)
        except Exception:
            pass
print("killed", killed)
time.sleep(1)
for f in glob.glob("/opt/data/cache/scratch/chrome-ed22c/profile/Singleton*"):
    try:
        os.remove(f)
    except Exception:
        pass
print("locks cleared")
