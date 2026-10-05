// Which API calls each page makes when it opens, so their data can start loading before the page does:
// when the app starts (in parallel with the sign-in check) and when a link is hovered, focused or touched.
// Keys must match the page's useApi path exactly, or the prefetch simply goes unused (never wrong data).
import { prefetch } from './api'

const ROUTES: [RegExp, (m: RegExpMatchArray, q: URLSearchParams) => string[]][] = [
  [/^\/app\/?$/, () => ['/api/dashboard']],
  [/^\/app\/jobs\/?$/, () => ['/api/jobs']],
  [/^\/app\/jobs\/([^/]+)\/?$/, (m, q) => {
    const id = m[1]!, tab = q.get('tab') || 'matches'
    return [`/api/jobs/${id}`, ...(tab === 'matches' ? [`/api/jobs/${id}/matches?limit=10`] : tab === 'pipeline' ? [`/api/jobs/${id}/pipeline`]
      : tab === 'flow' ? [`/api/jobs/${id}/flow`, '/api/flow-meta'] : tab === 'activity' ? [`/api/jobs/${id}/activity`] : tab === 'overview' ? [`/api/jobs/${id}/jd`] : [])]
  }],
  [/^\/app\/candidates\/?$/, () => ['/api/candidates?q=&skill=&source=&page=1&limit=25']],
  [/^\/app\/candidates\/([^/]+)\/?$/, m => [`/api/candidates/${m[1]}`]],
  [/^\/app\/matches\/?$/, () => ['/api/match/overview']],
  [/^\/app\/interviews\/?$/, () => ['/api/interviews', '/api/calibration']],
  [/^\/app\/my-interviews\/?$/, () => ['/api/my-interviews']],
  [/^\/app\/requests\/?$/, () => ['/api/requests']],
  [/^\/app\/questions\/?$/, () => ['/api/questions?section=&difficulty=&q=&page=1&limit=50', '/api/jobs']],
  [/^\/app\/drives\/?$/, () => ['/api/drives', '/api/jobs']],
  [/^\/app\/outbox\/?$/, () => ['/api/messages?status=&page=1']],
  [/^\/app\/team\/?$/, () => ['/api/team']],
]

export function routeData(href: string): string[] {
  let u: URL
  try { u = new URL(href, location.origin) } catch { return [] }
  if (u.origin !== location.origin) return []
  for (const [re, fn] of ROUTES) { const m = u.pathname.match(re); if (m) return fn(m, u.searchParams) }
  return []
}

export function prefetchRoute(href: string) { for (const p of routeData(href)) prefetch(p) }

/** Hover, keyboard focus or touch on any in-app link starts loading that page's data (~100-300 ms head start). */
export function installPrefetch() {
  const on = (e: Event) => {
    const a = (e.target as Element | null)?.closest?.('a[href^="/app"]') as HTMLAnchorElement | null
    if (a) prefetchRoute(a.getAttribute('href')!)
  }
  document.addEventListener('pointerover', on, { passive: true })
  document.addEventListener('focusin', on)
  document.addEventListener('touchstart', on, { passive: true })
}
