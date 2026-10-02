// First-run guided tour: a spotlight on each part of the sidebar with a short, plain explanation. Adapts to the
// person's role, can be skipped, and can be restarted from Your account. Remembered per browser and user.
import { ArrowLeft, ArrowRight, Sparkles, X } from 'lucide-react'
import { useEffect, useLayoutEffect, useState } from 'react'
import { Button, cn } from './ui'

export interface TourStep { target?: string; title: string; body: string }
const KEY = (uid: string) => `tl.tour.${uid}`
const listeners = new Set<() => void>()
export function startTour() { listeners.forEach(f => f()) }
export function tourDone(uid: string) { try { return localStorage.getItem(KEY(uid)) === 'done' } catch { return true } }

export function Tour({ uid, steps, auto }: { uid: string; steps: TourStep[]; auto: boolean }) {
  const [i, setI] = useState<number | null>(null)
  const [rect, setRect] = useState<DOMRect | null>(null)
  useEffect(() => { const f = () => setI(0); listeners.add(f); return () => { listeners.delete(f) } }, [])
  useEffect(() => { if (auto && !tourDone(uid)) { const t = setTimeout(() => setI(0), 600); return () => clearTimeout(t) } }, [auto, uid])
  const step = i == null ? null : steps[i]
  useLayoutEffect(() => {
    if (!step) return
    const find = () => {
      const el = step.target ? document.querySelector(`[data-tour="${step.target}"]`) as HTMLElement | null : null
      const r = el && el.offsetParent !== null ? el.getBoundingClientRect() : null
      setRect(r && r.width ? r : null)
    }
    find(); window.addEventListener('resize', find); window.addEventListener('scroll', find, true)
    return () => { window.removeEventListener('resize', find); window.removeEventListener('scroll', find, true) }
  }, [step])
  useEffect(() => {
    if (i == null) return
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); if (e.key === 'ArrowRight') next(); if (e.key === 'ArrowLeft' && i > 0) setI(i - 1) }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  })
  if (!step || i == null) return null
  function close() { try { localStorage.setItem(KEY(uid), 'done') } catch { /* private mode */ } setI(null) }
  function next() { if (i! < steps.length - 1) setI(i! + 1); else close() }
  const pad = 6
  const card = rect
    ? { top: Math.min(Math.max(12, rect.top - 8), window.innerHeight - 260), left: Math.min(rect.right + 18, window.innerWidth - 360) }
    : { top: Math.max(24, window.innerHeight / 2 - 140), left: Math.max(16, window.innerWidth / 2 - 170) }
  return (
    <div className="fixed inset-0 z-[80]" role="dialog" aria-modal="true" aria-label={`Tour: ${step.title}`}>
      {rect ? <div className="pointer-events-none fixed rounded-xl ring-2 ring-brand-400 transition-all duration-300"
        style={{ top: rect.top - pad, left: rect.left - pad, width: rect.width + pad * 2, height: rect.height + pad * 2, boxShadow: '0 0 0 9999px rgba(10,12,17,.62)' }} />
        : <div className="fixed inset-0 bg-ink-950/60" />}
      <div className="fixed w-[min(340px,calc(100vw-32px))] rounded-2xl bg-white p-5 text-slate-800 shadow-2xl ring-1 ring-slate-200 animate-rise dark:bg-ink-850 dark:text-slate-100 dark:ring-ink-700" style={card}>
        <button type="button" aria-label="Skip the tour" onClick={close} className="absolute right-3 top-3 rounded-lg p-1 text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-ink-800"><X className="size-4" /></button>
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-brand-600 dark:text-brand-300"><Sparkles className="size-3.5" />Quick tour · {i + 1} of {steps.length}</div>
        <h2 className="mt-2 text-base font-semibold">{step.title}</h2>
        <p className="mt-1.5 text-sm leading-relaxed text-slate-600 dark:text-slate-300">{step.body}</p>
        <div className="mt-4 flex items-center justify-between gap-2">
          <div className="flex gap-1">{steps.map((_, k) => <span key={k} className={cn('h-1.5 rounded-full transition-all', k === i ? 'w-5 bg-brand-600' : 'w-1.5 bg-slate-300 dark:bg-ink-600')} />)}</div>
          <div className="flex gap-2">
            {i > 0 ? <Button size="sm" variant="ghost" icon={<ArrowLeft />} onClick={() => setI(i - 1)}>Back</Button> : <Button size="sm" variant="ghost" onClick={close}>Skip</Button>}
            <Button size="sm" variant="primary" onClick={next}>{i === steps.length - 1 ? 'Finish' : <>Next<ArrowRight className="size-3.5" /></>}</Button>
          </div>
        </div>
      </div>
    </div>
  )
}
