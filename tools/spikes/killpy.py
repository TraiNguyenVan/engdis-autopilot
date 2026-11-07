import os, signal, glob, sys

needle = sys.argv[1]
killed = []
me = os.getpid()
for p in glob.glob("/proc/[0-9]*/cmdline"):
    try:
        cmd = open(p, "rb").read().decode("utf-8", "ignore").replace("\x00", " ")
    except Exception:
        continue
    pid = int(p.split("/")[2])
    if pid == me:
        continue
    if needle in cmd and "killpy" not in cmd:
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append((pid, cmd[:80]))
        except Exception:
            pass
print(killed)
