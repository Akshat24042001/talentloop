// Shared helpers for HR pages.
const K = 'tl_admin_key';
function adminKey(){ try{ return sessionStorage.getItem(K) || ''; }catch{ return ''; } }
async function api(path, opts = {}){
  const headers = Object.assign({}, opts.headers || {});
  if (opts.json !== undefined){ headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(opts.json); }
  if (adminKey()) headers['X-Admin-Key'] = adminKey();
  const r = await fetch(path, Object.assign({}, opts, {headers}));
  if (r.status === 401){
    const k = prompt('Admin key (ADMIN_KEY from your .env):');
    if (k){ try{ sessionStorage.setItem(K, k); }catch{} return api(path, opts); }
  }
  const txt = await r.text();
  let data; try { data = JSON.parse(txt); } catch { data = txt; }
  if (!r.ok) throw new Error((data && data.detail) || txt || r.statusText);
  return data;
}
function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function $(id){ return document.getElementById(id); }
function mediaUrl(iid, f){ return `/media/${iid}/${encodeURIComponent(f)}` + (adminKey() ? `?key=${encodeURIComponent(adminKey())}` : ''); }
function withKey(path){ return path + (adminKey() ? (path.includes('?') ? '&' : '?') + 'key=' + encodeURIComponent(adminKey()) : ''); }
const REC_LABEL = {strong_yes:'Strong yes', yes:'Yes', maybe:'Maybe', no:'No'};
const REC_CLASS = {strong_yes:'ok', yes:'ok', maybe:'warn', no:'bad'};
const STATUS_LABEL = {created:'Not started', in_progress:'In progress', completed:'Completed', incomplete:'Ended early',
                      scored:'Scored', cancelled:'Cancelled'};
const STATUS_CLASS = {created:'gray', in_progress:'', completed:'ok', incomplete:'warn', scored:'ok', cancelled:'gray'};

const ICONS = {
  logo: '<path d="M17 3a4 4 0 0 1 0 8H7a4 4 0 0 0 0 8h10"/><path d="m14 16 3 3-3 3"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5M12 15V3"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.2L3 16M3 21v-5h5"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4M12 17h.01"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
  sparkle: '<path d="M12 3l1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2z"/>',
};
function icon(name, size = 18){ return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`; }

function renderNav(active){
  const el = document.createElement('header');
  el.className = 'topnav';
  el.innerHTML = `<div class="in">
    <a class="brand" href="/dashboard.html"><span class="logo">${icon('logo')}</span><span class="name">TalentLoop <small class="muted" style="font-weight:500">AI Interviews</small></span></a>
    <nav>
      <a href="/dashboard.html" class="${active === 'dashboard' ? 'on' : ''}">${icon('grid', 17)}<span>Interviews</span></a>
      <a href="/hr.html" class="${active === 'new' ? 'on' : ''}">${icon('plus', 17)}<span>New interview</span></a>
    </nav></div>`;
  document.body.prepend(el);
}
let _toastT = null;
function toast(msg){ let t = document.querySelector('.toast'); if (!t){ t = document.createElement('div'); t.className = 'toast'; document.body.appendChild(t); }
  t.textContent = msg; t.classList.remove('hidden'); clearTimeout(_toastT); _toastT = setTimeout(() => t.classList.add('hidden'), 2800); }
function copyText(text, msg = 'Copied'){ (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(() => toast(msg), () => prompt('Copy this:', text)); }
function when(ts){ return ts ? new Date(ts * 1000).toLocaleString([], {day:'numeric', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'}) : '-'; }
function ago(ts){ if (!ts) return '-'; const s = Date.now() / 1000 - ts; if (s < 60) return 'just now'; if (s < 3600) return Math.floor(s / 60) + ' min ago';
  if (s < 86400) return Math.floor(s / 3600) + ' h ago'; if (s < 7 * 86400) return Math.floor(s / 86400) + ' d ago'; return new Date(ts * 1000).toLocaleDateString([], {day:'numeric', month:'short'}); }
