"""Bounded, read-only snapshots; no browser or harness interaction."""
import json
import math
import os
import re
import stat
import time
from pathlib import Path

MAX_REPORT = 1024 * 1024

def number(value):
    if isinstance(value, list):
        value = value[0] if len(value) == 1 else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        return None
    return value

def safe_read(path, limit, tail=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("not a regular file")
        if not tail and st.st_size > limit:
            raise ValueError("file too large")
        if tail:
            os.lseek(fd, max(0, st.st_size - limit), os.SEEK_SET)
        data = os.read(fd, limit + (0 if tail else 1))
        if len(data) > limit:
            raise ValueError("file too large")
        return data, st.st_mtime
    finally:
        os.close(fd)

def snapshot(root, proc_root=Path('/proc'), now=None):
    root, proc_root = Path(root), Path(proc_root)
    errors = []
    result = dict(generated_at=time.time() if now is None else now, running=False, processes=[], report=None, activity=None, errors=errors)
    try:
        for p in proc_root.iterdir():
            if not p.name.isdigit(): continue
            try:
                parts = (p / 'cmdline').read_bytes()[:8192].split(b'\0')
                if len(parts) < 2: continue
                executable = os.path.basename(os.fsdecode(parts[0]))
                script = os.path.basename(os.fsdecode(parts[1]))
                if re.fullmatch(r'python(?:[0-9.]+)?', executable) and script in ('auto.py', 'cover.py'):
                    result['processes'].append(dict(pid=int(p.name), script=script))
            except (OSError, ValueError): pass
        result['running'] = bool(result['processes'])
    except OSError:
        result['running'] = None; errors.append('Process status unavailable')
    try:
        reports = list(root.glob('cover_report_u*.json'))
        reports.sort(key=lambda p: p.lstat().st_mtime, reverse=True)
        fallback = root / 'cover_report.json'
        if fallback.exists() or fallback.is_symlink(): reports.append(fallback)
        for path in reports:
            try:
                data, mtime = safe_read(path, MAX_REPORT)
                obj = json.loads(data)
                if not isinstance(obj, dict) or not isinstance(obj.get('lessons', {}), dict): raise ValueError()
                lessons = []
                for name, entry in obj.get('lessons', {}).items():
                    if not isinstance(name, str) or not isinstance(entry, dict): continue
                    lessons.append(dict(name=name[:300], progress=number(entry.get('final')), score=None, blocked=entry.get('blocked') is True, rc=entry.get('rc') if type(entry.get('rc')) is int else None))
                result['report'] = dict(source=path.name, observed_at=mtime, unit=str(obj.get('unit') or 'Unknown')[:300], progress=number(obj.get('unit_progress')), lessons=lessons, historical=False)
                break
            except (OSError, ValueError, UnicodeError, RecursionError):
                errors.append('Unable to read a saved report')
    except OSError:
        errors.append('Unable to list saved reports')
    try:
        logs = root / 'logs'
        if logs.is_symlink(): raise OSError()
        if logs.is_dir():
            candidates = list(logs.glob('*.log'))
            candidates.sort(key=lambda p: p.lstat().st_mtime, reverse=True)
            for path in candidates:
                try:
                    data, mtime = safe_read(path, 16384, tail=True)
                    lines = [x for x in data.decode('utf-8', 'replace').splitlines() if x.strip()]
                    if not lines: continue
                    line = lines[-1]
                    kind = 'Speaking blocked' if 'SPEAK-BLOCKED' in line else 'Log updated'
                    result['activity'] = dict(source=path.name, observed_at=mtime, type=kind)
                    break
                except (OSError, ValueError): errors.append('Unable to read an activity log')
    except OSError:
        errors.append('Unable to list activity logs')
    if result['report'] and result['activity']:
        result['report']['historical'] = result['report']['observed_at'] < result['activity']['observed_at']
    return result
