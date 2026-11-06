'use strict';
const el = id => document.getElementById(id);
function stamp(value) { return typeof value === 'number' ? new Date(value * 1000).toLocaleString() : 'Unknown'; }
function pct(value) { return typeof value === 'number' ? (value * 100).toFixed(1) + '%' : 'Unknown'; }
function render(s) {
  el('harness').textContent = s.running === null ? 'Unknown' : s.running ? 'Running' : 'Stopped';
  el('processes').textContent = s.processes.length ? s.processes.map(p => p.script + ' (PID ' + p.pid + ')').join(', ') : 'No harness processes detected';
  el('activity').textContent = s.activity ? s.activity.type + ' · ' + s.activity.source + ' · ' + stamp(s.activity.observed_at) : 'Unknown';
  const r = s.report;
  el('unit').textContent = r ? r.unit + ' · ' + pct(r.progress) : 'Unknown';
  el('source').textContent = r ? 'Source: ' + r.source + ' · ' + stamp(r.observed_at) + (r.historical ? ' · older than activity' : '') : 'Source: Unknown';
  el('lessons').replaceChildren();
  if (r) for (const lesson of r.lessons) {
    const item = document.createElement('li');
    item.textContent = lesson.name + ' · ' + pct(lesson.progress) + ' · score: ' + pct(lesson.score) + (lesson.blocked ? ' · blocked' : '') + (lesson.rc !== null ? ' · return code ' + lesson.rc : '');
    el('lessons').append(item);
  }
  el('updated').textContent = 'Last updated: ' + stamp(s.generated_at);
  el('errors').textContent = s.errors.join(' · ');
}
async function poll() {
  try { const response = await fetch('/api/status', {cache: 'no-store'}); if (!response.ok) throw Error(); render(await response.json()); }
  catch (_) { el('harness').textContent = 'Unknown'; el('errors').textContent = 'Dashboard connection failed; displayed data may be stale.'; }
  finally { setTimeout(poll, 5000); }
}
poll();
let imageUrl = null;
el('capture').addEventListener('click', async () => {
  el('capture').disabled = true;
  el('capture-status').textContent = 'Capturing…';
  try {
    const response = await fetch('/api/screenshot', {cache: 'no-store'});
    if (!response.ok) throw new Error('Browser screenshot unavailable');
    const blob = await response.blob();
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    imageUrl = URL.createObjectURL(blob);
    el('screenshot').src = imageUrl;
    el('screenshot').hidden = false;
    el('capture-status').textContent = 'Captured: ' + new Date().toLocaleString();
  } catch (_) {
    el('capture-status').textContent = 'Screenshot unavailable. Is the Engdis browser running?';
  } finally { el('capture').disabled = false; }
});
