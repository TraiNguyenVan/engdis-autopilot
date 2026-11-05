"""One-line status for the Engdis autopilot. Keeps agent context tiny."""
import subprocess, sys

JS = """(() => {
  const dd = [...document.querySelectorAll('ed-la-dropdownlist')].map(d=>((d.innerText||'').split(String.fromCharCode(10))[0]||'').trim());
  const c = document.querySelector('.learning__taskNavPCCurrentTask');
  const tot = document.querySelector('.learning__taskNavPCTotalTasks');
  const test = !!document.querySelector('.learning__submitTestLink');
  const start = !!document.querySelector('.btnStartTest');
  return [dd[0]||'-', dd[1]||'-', c?(c.innerText||'').trim():'-', tot?(tot.innerText||'').trim():'-', test?'submit':'', start?'start':''].join('|');
})()"""

def main():
    sys.path.insert(0, '/opt/data/cache/scratch/ed22u1')
    import edlib
    try:
        t = edlib.tab()
        line = t.js(JS)
    except Exception as e:
        print(f"ERR|{type(e).__name__}: {str(e)[:80]}")
        return
    proc = subprocess.run(['pgrep', '-c', '-f', 'python3 auto.py'], capture_output=True, text=True)
    running = proc.stdout.strip() or '0'
    log = subprocess.run(['tail', '-n', '1', '/opt/data/cache/scratch/ed22u1/auto_l4.log'],
                         capture_output=True, text=True).stdout.strip()[:90]
    print(f"{line}|auto={running}|{log}")

main()
