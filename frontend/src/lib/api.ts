// HR API client. The admin key lives in sessionStorage; a 401 opens the sign-in dialog (see AdminKeyDialog).
const KEY = 'tl_admin_key'

export function adminKey(): string {
  try { return sessionStorage.getItem(KEY) || '' } catch { return '' }
}
export function setAdminKey(k: string) {
  try { sessionStorage.setItem(KEY, k) } catch { /* private mode: key lives for this page only */ }
  memoryKey = k
}
let memoryKey = ''
const currentKey = () => adminKey() || memoryKey

type KeyWaiter = (key: string | null) => void
let waiters: KeyWaiter[] = []
const keyListeners = new Set<() => void>()
export const keyRequest = {
  pending: () => waiters.length > 0,
  subscribe(fn: () => void) { keyListeners.add(fn); return () => { keyListeners.delete(fn) } },
  resolve(key: string | null) { const w = waiters; waiters = []; w.forEach(f => f(key)); keyListeners.forEach(f => f()) },
}
function askForKey(): Promise<string | null> {
  return new Promise(res => { waiters.push(res); keyListeners.forEach(f => f()) })
}

export class ApiError extends Error { status: number; constructor(msg: string, status: number) { super(msg); this.status = status } }

export async function api<T = any>(path: string, opts: { method?: string; json?: unknown; body?: BodyInit } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  let body = opts.body
  if (opts.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.json) }
  if (currentKey()) headers['X-Admin-Key'] = currentKey()
  const r = await fetch(path, { method: opts.method || (body ? 'POST' : 'GET'), headers, body })
  if (r.status === 401) {
    const k = await askForKey()
    if (k) { setAdminKey(k); return api<T>(path, opts) }
  }
  const txt = await r.text()
  let data: any
  try { data = JSON.parse(txt) } catch { data = txt }
  if (!r.ok) throw new ApiError((data && data.detail) || txt || r.statusText, r.status)
  return data as T
}

/** For links the browser opens itself (downloads, media): the key goes in the query string. */
export function withKey(path: string): string {
  const k = currentKey()
  return k ? `${path}${path.includes('?') ? '&' : '?'}key=${encodeURIComponent(k)}` : path
}
export function mediaUrl(iid: string, file: string, download = false): string {
  return withKey(`/media/${iid}/${encodeURIComponent(file)}${download ? '?download=1' : ''}`)
}

/** Candidate-side calls (no admin key). */
export async function post<T = any>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) })
  if (!r.ok) {
    let d: string | undefined
    try { d = (await r.json()).detail } catch { /* not JSON */ }
    throw new ApiError(d || r.statusText, r.status)
  }
  return r.json()
}
