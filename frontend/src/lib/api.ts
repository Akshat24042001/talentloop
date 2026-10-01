// API client. Sessions are an httpOnly cookie; a 401 sends the person to the sign-in page.
export class ApiError extends Error { status: number; constructor(msg: string, status: number) { super(msg); this.status = status } }

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn }

export async function api<T = any>(path: string, opts: { method?: string; json?: unknown; body?: BodyInit; quiet401?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  let body = opts.body
  if (opts.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.json) }
  const r = await fetch(path, { method: opts.method || (body ? 'POST' : 'GET'), headers, body, credentials: 'same-origin' })
  const txt = await r.text()
  let data: any
  try { data = JSON.parse(txt) } catch { data = txt }
  if (r.status === 401 && !opts.quiet401) onUnauthorized?.()
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
