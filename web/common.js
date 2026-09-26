// Shared helpers for HR pages.
const K = 'tl_admin_key';
function adminKey(){ return sessionStorage.getItem(K) || ''; }
async function api(path, opts = {}){
  const headers = Object.assign({}, opts.headers || {});
  if (opts.json !== undefined){ headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(opts.json); }
  if (adminKey()) headers['X-Admin-Key'] = adminKey();
  const r = await fetch(path, Object.assign({}, opts, {headers}));
  if (r.status === 401){
    const k = prompt('Admin key (ADMIN_KEY from your .env):');
    if (k){ sessionStorage.setItem(K, k); return api(path, opts); }
  }
  const txt = await r.text();
  let data; try { data = JSON.parse(txt); } catch { data = txt; }
  if (!r.ok) throw new Error((data && data.detail) || txt || r.statusText);
  return data;
}
function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function $(id){ return document.getElementById(id); }
function mediaUrl(iid, f){ return `/media/${iid}/${encodeURIComponent(f)}` + (adminKey() ? `?key=${encodeURIComponent(adminKey())}` : ''); }
const REC_LABEL = {strong_yes:'Strong yes', yes:'Yes', maybe:'Maybe', no:'No'};
const REC_CLASS = {strong_yes:'ok', yes:'ok', maybe:'warn', no:'bad'};
