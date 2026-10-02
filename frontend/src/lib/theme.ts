// Light, dark or follow the device. Saved per browser; the inline script in index.html applies it before paint.
import { useEffect, useState } from 'react'

export type Theme = 'system' | 'light' | 'dark'
const KEY = 'tl.theme'
const media = () => window.matchMedia('(prefers-color-scheme: dark)')

export function getTheme(): Theme {
  try { const t = localStorage.getItem(KEY); return t === 'light' || t === 'dark' ? t : 'system' } catch { return 'system' }
}
function apply(t: Theme) {
  document.documentElement.classList.toggle('dark', t === 'dark' || (t === 'system' && media().matches))
}
const subs = new Set<(t: Theme) => void>()
export function setTheme(t: Theme) {
  try { localStorage.setItem(KEY, t) } catch { /* private mode: still applies for this visit */ }
  apply(t); subs.forEach(f => f(t))
}
// Follow the device while on "System".
media().addEventListener?.('change', () => { if (getTheme() === 'system') apply('system') })

export function useTheme(): [Theme, (t: Theme) => void] {
  const [t, set] = useState<Theme>(getTheme)
  useEffect(() => { subs.add(set); return () => { subs.delete(set) } }, [])
  return [t, setTheme]
}
