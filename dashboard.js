'use strict';
const el = id => document.getElementById(id);
function stamp(value) { return typeof value === 'number' ? new Date(value * 1000).toLocaleString() : 'Unknown'; }
function pct(value) { return typeof value === 'number' ? (value * 100).toFixed(1) + '%' : 'Unknown'; }

let isRunning = false;

function render(s) {
  isRunning = !!s.running;
  el('harness').textContent = s.running === null ? 'Unknown' : s.running ? 'Running' : 'Stopped';
  el('processes').textContent = s.processes && s.processes.length ? s.processes.map(p => p.script + ' (PID ' + p.pid + ')').join(', ') : 'No harness processes detected';

  // Live status
  if (s.live && s.live.lesson) {
    const l = s.live;
    el('live-summary').textContent = (l.unit ? l.unit + ' · ' : '') + l.lesson + ' · ' + l.step;
    el('live-detail').textContent = 'Task ' + (l.task || '?') + '/' + (l.total_tasks || '?') +
      (l.progress !== null && l.progress !== undefined ? ' (' + pct(l.progress) + ')' : '') +
      (l.last_action ? ' · Action: ' + l.last_action : '') +
      ' · ' + stamp(l.updated_at);
  } else {
    el('live-summary').textContent = isRunning ? 'Runner active (waiting for next task update...)' : 'No active real-time task data';
    el('live-detail').textContent = '';
  }

  // Diagnostic events
  const evList = el('events-list');
  evList.replaceChildren();
  if (s.recent_events && s.recent_events.length > 0) {
    for (const ev of s.recent_events.slice().reverse()) {
      const item = document.createElement('li');
      item.textContent = '[' + (ev.time ? ev.time.slice(11, 19) : '??') + '] ' +
        ev.lesson + ' · ' + ev.step + ' (Task ' + ev.task + ') · ' +
        ev.type + ' -> ' + ev.result +
        (ev.duration_s ? ' (' + ev.duration_s + 's)' : '');
      evList.append(item);
    }
  } else {
    const item = document.createElement('li');
    item.textContent = 'No recent diagnostic events';
    evList.append(item);
  }

  // Report snapshot
  const r = s.report;
  el('unit').textContent = r ? r.unit + ' · ' + pct(r.progress) : 'Unknown';
  el('source').textContent = r ? 'Source: ' + r.source + ' · ' + stamp(r.observed_at) + (r.historical ? ' · older than activity' : '') : 'Source: Unknown';
  el('lessons').replaceChildren();
  if (r && r.lessons) for (const lesson of r.lessons) {
    const item = document.createElement('li');
    item.textContent = lesson.name + ' · ' + pct(lesson.progress) + ' · score: ' + pct(lesson.score) + (lesson.blocked ? ' · blocked' : '') + (lesson.rc !== null ? ' · return code ' + lesson.rc : '');
    el('lessons').append(item);
  }

  el('updated').textContent = 'Last updated: ' + stamp(s.generated_at);
  el('errors').textContent = (s.errors || []).join(' · ');
}

async function poll() {
  try {
    const response = await fetch('/api/status', {cache: 'no-store'});
    if (!response.ok) throw Error();
    render(await response.json());
  } catch (_) {
    el('harness').textContent = 'Unknown';
    el('errors').textContent = 'Dashboard connection failed; displayed data may be stale.';
  } finally {
    setTimeout(poll, 4000);
  }
}
poll();

let imageUrl = null;
async function captureScreenshot() {
  const btn = el('capture');
  btn.disabled = true;
  el('capture-status').textContent = 'Capturing…';
  try {
    const response = await fetch('/api/screenshot', {cache: 'no-store'});
    if (!response.ok) throw new Error('Browser screenshot unavailable');
    const blob = await response.blob();
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    imageUrl = URL.createObjectURL(blob);
    el('screenshot').src = imageUrl;
    el('screenshot').hidden = false;
    el('capture-status').textContent = 'Captured: ' + new Date().toLocaleTimeString();
  } catch (_) {
    el('capture-status').textContent = 'Screenshot unavailable (Chrome tab closed or unresponsive).';
  } finally {
    btn.disabled = false;
  }
}

el('capture').addEventListener('click', captureScreenshot);

// Auto-screenshot timer (every 15s if checked)
setInterval(() => {
  const chk = el('auto-screenshot');
  if (chk && chk.checked) {
    captureScreenshot();
  }
}, 15000);
