// A small history router: enough for this app's routes, no dependency.
import { useSyncExternalStore, type AnchorHTMLAttributes } from 'react'

const listeners = new Set<() => void>()
const emit = () => listeners.forEach(f => f())
if (typeof window !== 'undefined') window.addEventListener('popstate', emit)

/** A page with unsaved changes registers a guard; in-app navigation asks before leaving it. */
let leaveGuard: (() => boolean) | null = null
export function setLeaveGuard(fn: (() => boolean) | null) { leaveGuard = fn }
export function canLeave(): boolean { return !leaveGuard || leaveGuard() }

export function navigate(to: string, opts: { replace?: boolean; keepScroll?: boolean; force?: boolean } = {}) {
  if (to === location.pathname + location.search) return
  if (!opts.force && !canLeave()) return
  leaveGuard = null
  history[opts.replace ? 'replaceState' : 'pushState'](null, '', to)
  emit()
  if (!opts.keepScroll) window.scrollTo(0, 0)
}

const subscribe = (f: () => void) => { listeners.add(f); return () => { listeners.delete(f) } }
export function useLocation(): { path: string; search: string; query: URLSearchParams } {
  const href = useSyncExternalStore(subscribe, () => location.pathname + location.search)
  const i = href.indexOf('?')
  const search = i >= 0 ? href.slice(i) : ''
  return { path: i >= 0 ? href.slice(0, i) : href, search, query: new URLSearchParams(search) }
}

/** match('/app/jobs/:id', '/app/jobs/abc') -> { id: 'abc' } */
export function match(pattern: string, path: string): Record<string, string> | null {
  const p = pattern.split('/').filter(Boolean), a = path.replace(/\/+$/, '').split('/').filter(Boolean)
  if (p.length !== a.length) return null
  const out: Record<string, string> = {}
  for (let i = 0; i < p.length; i++) {
    if (p[i]!.startsWith(':')) out[p[i]!.slice(1)] = decodeURIComponent(a[i]!)
    else if (p[i] !== a[i]) return null
  }
  return out
}

/** Same-origin links inside the app are handled without a page load. */
export function isAppPath(href: string): boolean {
  return /^\/(app|admin|careers|login|signup|invite|forgot)?(\/|$|\?)/.test(href) && !/\.(html|pdf|csv|zip|json|txt)(\?|$)/.test(href)
}
export function installLinkInterceptor() {
  document.addEventListener('click', e => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    const a = (e.target as HTMLElement).closest('a')
    if (!a || a.target || a.hasAttribute('download') || a.origin !== location.origin) return
    const href = a.pathname + a.search
    if (a.hash && href === location.pathname + location.search) {      // a link to a section of this page
      const el = document.getElementById(decodeURIComponent(a.hash.slice(1)))
      if (el) { e.preventDefault(); el.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
      return
    }
    if (!isAppPath(href)) return
    e.preventDefault()
    navigate(href + (a.hash || ''))
  })
}

export function Link({ to, ...rest }: { to: string } & AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <a href={to} {...rest} />
}
