// API client. Sessions are an httpOnly cookie; a 401 sends the person to the sign-in page.
export class ApiError extends Error { status: number; constructor(msg: string, status: number) { super(msg); this.status = status } }

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn }

/** Page data seen in this tab, shown instantly on revisits (and after a browser refresh) while fresh data loads:
 * stale-while-revalidate. Every page refetches when it opens, so cached data is only ever shown for the moment the
 * fresh copy takes to arrive. Kept in sessionStorage (this tab only, gone when it closes) and cleared on sign-out,
 * on a 401 and when a different person or company signs in. */
export const pageCache = new Map<string, unknown>()
const fetchedAt = new Map<string, number>()
const inflight = new Map<string, Promise<unknown>>()
const STORE = 'tl-page-cache-v1', OWNER = 'tl-page-cache-owner', MAX_BYTES = 1_500_000
try { const raw = sessionStorage.getItem(STORE); if (raw) for (const [k, v] of JSON.parse(raw) as [string, unknown][]) pageCache.set(k, v) } catch { /* storage off or full */ }
let saveTimer: ReturnType<typeof setTimeout> | undefined
function persist() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    try {
      let rows = [...pageCache.entries()], txt = JSON.stringify(rows)
      while (txt.length > MAX_BYTES && rows.length > 1) { rows = rows.slice(Math.ceil(rows.length / 4)); txt = JSON.stringify(rows) }   // drop the oldest
      sessionStorage.setItem(STORE, txt)
    } catch { /* storage off or full: memory cache still works */ }
  }, 300)
}
export function remember(path: string, data: unknown) { pageCache.delete(path); pageCache.set(path, data); fetchedAt.set(path, Date.now()); persist() }
export function clearCache() { pageCache.clear(); fetchedAt.clear(); try { sessionStorage.removeItem(STORE) } catch { /* ignore */ } }
/** The cache belongs to one person in one company: switching either empties it. */
export function cacheOwner(owner: string) {
  try { if (sessionStorage.getItem(OWNER) !== owner) { clearCache(); sessionStorage.setItem(OWNER, owner) } } catch { /* ignore */ }
}
/** GET with the cache and in-flight sharing: a request already on its way (a prefetch, another component) is reused. */
export function getData<T = any>(path: string, opts: { quiet401?: boolean } = {}): Promise<T> {
  const cur = inflight.get(path)
  if (cur) return cur as Promise<T>
  const p = api<T>(path, opts).then(d => { remember(path, d); return d }).finally(() => inflight.delete(path))
  inflight.set(path, p)
  return p
}
/** Start loading data a page will need (link hovered, app starting). Skipped if it was fetched in the last 15 seconds. */
export function prefetch(path: string) {
  if (inflight.has(path) || Date.now() - (fetchedAt.get(path) || 0) < 15000) return
  getData(path, { quiet401: true }).catch(() => { /* the page shows the error when it opens */ })
}

export async function api<T = any>(path: string, opts: { method?: string; json?: unknown; body?: BodyInit; quiet401?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  let body = opts.body
  if (opts.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.json) }
  const method = opts.method || (body ? 'POST' : 'GET')
  if (method !== 'GET') { fetchedAt.clear(); inflight.clear() }   // after a change nothing reuses a read started before it
  const r = await fetch(path, { method, headers, body, credentials: 'same-origin' })
  const txt = await r.text()
  let data: any
  try { data = JSON.parse(txt) } catch { data = txt }
  if (r.status === 401) { clearCache(); if (!opts.quiet401) onUnauthorized?.() }
  if (!r.ok) {
    const d = data && data.detail
    throw new ApiError(typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: any) => x.msg).join('; ') : txt || r.statusText, r.status)
  }
  return data as T
}

/** Links the browser opens itself (downloads, media) carry the session cookie, so no key is needed. */
export function withKey(path: string): string { return path }
export function mediaUrl(iid: string, file: string, download = false): string {
  return `/media/${iid}/${encodeURIComponent(file)}${download ? '?download=1' : ''}`
}

/** Candidate-side calls (no sign-in). */
export async function post<T = any>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) })
  if (!r.ok) {
    let d: string | undefined
    try { d = (await r.json()).detail } catch { /* not JSON */ }
    throw new ApiError(d || r.statusText, r.status)
  }
  return r.json()
}
