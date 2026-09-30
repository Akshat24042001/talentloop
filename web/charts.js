// Small dependency-free chart helpers (HTML bars + a timeline strip), used by the dashboard and the report.
// Colors come from CSS tokens (--series-1/2, --status-*) defined in style.css for light and dark mode.

function chartTipInit(){
  if (window.__chartTip) return;
  const tip = document.createElement('div'); tip.className = 'chart-tip hidden'; document.body.appendChild(tip);
  window.__chartTip = tip;
  const place = e => { const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + w > innerWidth - 8) x = e.clientX - w - pad; if (y + h > innerHeight - 8) y = e.clientY - h - pad;
    tip.style.left = Math.max(8, x) + 'px'; tip.style.top = Math.max(8, y) + 'px'; };
  document.addEventListener('mouseover', e => { const t = e.target.closest('[data-ctip]'); if (!t) return;
    tip.innerHTML = t.dataset.ctip; tip.classList.remove('hidden'); place(e); });
  document.addEventListener('mousemove', e => { if (!tip.classList.contains('hidden')) place(e); });
  document.addEventListener('mouseout', e => { const t = e.target.closest('[data-ctip]'); if (t && !t.contains(e.relatedTarget)) tip.classList.add('hidden'); });
}

// rows: [{label, sub?, value (number|null), display?, marker? (number|null), tip?, onclick?}]
// opts: {max, markerLabel, valueLabel, empty}
function hbarChart(rows, opts = {}){
  chartTipInit();
  const max = opts.max || Math.max(1, ...rows.map(r => Math.max(r.value || 0, r.marker || 0)));
  const legend = opts.markerLabel ? `<div class="chart-legend"><span><i class="sw s1"></i>${esc(opts.valueLabel || 'Value')}</span><span><i class="sw mk"></i>${esc(opts.markerLabel)}</span></div>` : '';
  if (!rows.length) return `<p class="small muted">${esc(opts.empty || 'No data yet.')}</p>`;
  return legend + `<div class="hbars">${rows.map(r => {
    const pct = r.value == null ? 0 : Math.max(0, Math.min(100, r.value / max * 100));
    const mk = r.marker == null ? '' : `<i class="mk" style="left:calc(${Math.min(100, r.marker / max * 100)}% - 2px)"></i>`;
    // r.tip is HTML (callers escape their data); the default is built from escaped text.
    const tip = esc(r.tip || `${esc(r.label)}: <b>${esc(r.display ?? r.value ?? '-')}</b>`);
    return `<div class="hbar" data-ctip="${tip}">
      <div class="hb-label" title="${esc(r.sub || r.label)}"><b>${esc(r.label)}</b>${r.sub ? `<span>${esc(r.sub)}</span>` : ''}</div>
      <div class="hb-track">${r.value == null ? '<span class="hb-na">not scored</span>' : `<i class="hb-fill" style="width:${pct}%"></i>`}${mk}</div>
      <div class="hb-val">${esc(r.display ?? (r.value ?? '-'))}</div></div>`; }).join('')}</div>`;
}

// events: [{t (seconds from start), severity: 'high'|'medium', label, q?, detail?}], markers: [{t, label, kind}] (e.g. warnings)
function timelineChart(events, duration, markers = []){
  chartTipInit();
  const D = Math.max(60, duration || 0, ...events.map(e => e.t || 0), ...markers.map(m => m.t || 0));
  const mm = t => { t = Math.max(0, Math.round(t)); return String(Math.floor(t / 60)).padStart(2, '0') + ':' + String(t % 60).padStart(2, '0'); };
  const ticks = []; const step = D > 1800 ? 600 : D > 600 ? 300 : D > 240 ? 60 : 30;
  for (let t = 0; t <= D; t += step) ticks.push(t);
  // Labels and details can come from the candidate's browser: escape them inside the tooltip HTML too.
  const dot = e => `<i class="tl-dot ${e.severity === 'high' ? 'high' : 'medium'}" style="left:${(e.t / D * 100).toFixed(2)}%" data-ctip="${esc(`<b>${mm(e.t)}</b> ${esc(e.label)}${e.q ? `<br><span>${esc(e.q)}</span>` : ''}${e.detail ? `<br><span>${esc(e.detail)}</span>` : ''}`)}"></i>`;
  const mk = m => `<i class="tl-mark" style="left:${(m.t / D * 100).toFixed(2)}%" data-ctip="${esc(`<b>${mm(m.t)}</b> ${esc(m.label)}`)}"></i>`;
  const hi = events.filter(e => e.severity === 'high'), med = events.filter(e => e.severity !== 'high');
  return `<div class="chart-legend"><span><i class="sw st-high"></i>High-risk signal</span><span><i class="sw st-med"></i>Medium signal</span>${markers.length ? '<span><i class="sw st-mark"></i>Interviewer warning</span>' : ''}</div>
    <div class="tl"><div class="tl-row"><span class="tl-name">High</span><div class="tl-lane">${hi.map(dot).join('')}${markers.map(mk).join('')}</div></div>
      <div class="tl-row"><span class="tl-name">Medium</span><div class="tl-lane">${med.map(dot).join('')}</div></div>
      <div class="tl-row axis"><span class="tl-name"></span><div class="tl-lane">${ticks.map(t => `<span class="tl-tick" style="left:${t / D * 100}%">${mm(t)}</span>`).join('')}</div></div></div>`;
}

// Proportion bar for categories, e.g. recommendations. parts: [{label, n, cls}]
function splitBar(parts){
  chartTipInit();
  const total = parts.reduce((a, p) => a + p.n, 0);
  if (!total) return '<p class="small muted">No data yet.</p>';
  return `<div class="split">${parts.filter(p => p.n).map(p => `<i class="${p.cls}" style="flex:${p.n}" data-ctip="${esc(`${esc(p.label)}: <b>${p.n}</b> (${Math.round(p.n / total * 100)}%)`)}"></i>`).join('')}</div>
    <div class="chart-legend">${parts.map(p => `<span><i class="sw ${p.cls}"></i>${esc(p.label)} <b>${p.n}</b></span>`).join('')}</div>`;
}
