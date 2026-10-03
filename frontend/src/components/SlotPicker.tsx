// Pick an interview time: days as chips (with how many times each has), then that day's times. Shown in the
// viewer's own time zone, labelled, so nobody has to convert.
import { useEffect, useMemo, useState } from 'react'
import { cn } from './ui'

export interface SlotItem { id: string; starts_at: number; note?: string }

const NICE: Record<string, string> = { 'GMT+5:30': 'IST', 'UTC+5:30': 'IST', 'GMT+5:45': 'NPT', 'GMT+4': 'GST', 'GMT+8': 'SGT' }
const nice = (z: string) => NICE[z] || z
export const tzName = () => nice(new Intl.DateTimeFormat([], { timeZoneName: 'short' }).formatToParts(new Date()).find(p => p.type === 'timeZoneName')?.value || '')
export const fullWhen = (ts: number) => {
  const d = new Date(ts * 1000)
  const z = nice(new Intl.DateTimeFormat([], { timeZoneName: 'short' }).formatToParts(d).find(p => p.type === 'timeZoneName')?.value || '')
  return `${d.toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })} ${z}`.trim()
}

export default function SlotPicker({ items, value, onChange, empty }: { items: SlotItem[]; value: string; onChange: (id: string) => void; empty?: string }) {
  const days = useMemo(() => {
    const m = new Map<string, SlotItem[]>()
    for (const s of [...items].sort((a, b) => a.starts_at - b.starts_at)) { const k = new Date(s.starts_at * 1000).toDateString(); m.set(k, [...(m.get(k) || []), s]) }
    return [...m.entries()]
  }, [items])
  const [day, setDay] = useState('')
  useEffect(() => {
    if (!days.length) return
    const sel = items.find(i => i.id === value)
    setDay(d => sel ? new Date(sel.starts_at * 1000).toDateString() : days.some(([k]) => k === d) ? d : days[0]![0])
  }, [days]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!items.length) return <p className="text-sm text-slate-500 dark:text-slate-400">{empty || 'No times are open right now.'}</p>
  const list = days.find(([k]) => k === day)?.[1] || []
  const part = (h: number) => h < 12 ? 'Morning' : h < 17 ? 'Afternoon' : 'Evening'
  const groups = new Map<string, SlotItem[]>()
  for (const s of list) { const k = part(new Date(s.starts_at * 1000).getHours()); groups.set(k, [...(groups.get(k) || []), s]) }
  return (
    <div>
      <div role="tablist" aria-label="Day" className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-2">
        {days.map(([k, l]) => { const d = new Date(l[0]!.starts_at * 1000); return (
          <button key={k} role="tab" type="button" aria-selected={day === k} onClick={() => setDay(k)}
            className={cn('flex min-w-16 shrink-0 flex-col items-center rounded-xl px-3 py-2 text-xs ring-1 ring-inset transition-colors',
              day === k ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white text-slate-700 ring-slate-200 hover:bg-slate-50 dark:bg-ink-850 dark:text-slate-200 dark:ring-ink-700 dark:hover:bg-ink-800')}>
            <span className="font-medium">{d.toLocaleDateString([], { weekday: 'short' })}</span>
            <span className="text-lg font-semibold leading-tight">{d.getDate()}</span>
            <span className={day === k ? 'text-white/80' : 'text-slate-500 dark:text-slate-400'}>{d.toLocaleDateString([], { month: 'short' })} · {l.length}</span>
          </button>)})}
      </div>
      <div className="mt-2 space-y-3">{[...groups.entries()].map(([g, l]) => (
        <div key={g}><div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{g}</div>
          <div className="flex flex-wrap gap-2">{l.map(s => (
            <button key={s.id} type="button" aria-pressed={value === s.id} onClick={() => onChange(s.id)} title={s.note}
              className={cn('tabular rounded-lg px-3 py-2 text-sm font-medium ring-1 ring-inset transition-colors',
                value === s.id ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white text-slate-800 ring-slate-200 hover:bg-brand-50 dark:bg-ink-850 dark:text-slate-100 dark:ring-ink-700 dark:hover:bg-brand-500/15')}>
              {new Date(s.starts_at * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}{s.note ? <span className="ml-1 text-xs opacity-75">· {s.note}</span> : null}</button>))}</div></div>))}</div>
      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">Times are in your time zone ({tzName()}).</p>
    </div>
  )
}
