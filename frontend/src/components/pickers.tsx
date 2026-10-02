// Styled date, time and number pickers that replace the browser's native widgets.
// Values keep the native formats ('YYYY-MM-DD', 'HH:MM', 'YYYY-MM-DDTHH:MM') so forms and the API don't change.
import * as Popover from '@radix-ui/react-popover'
import { CalendarDays, ChevronLeft, ChevronRight, Minus, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Select, cn } from './ui'

const pad = (n: number) => String(n).padStart(2, '0')
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const parse = (v: string) => { const [y, m, d] = (v || '').split('-').map(Number); return y && m && d ? new Date(y, m - 1, d) : null }
const DOW = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
const TRIGGER = 'group flex h-10 w-full items-center gap-2 rounded-xl bg-white px-3.5 text-left text-sm text-slate-900 shadow-sm ring-1 ring-inset ring-slate-200 hover:ring-slate-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 data-[state=open]:ring-2 data-[state=open]:ring-brand-500 disabled:opacity-60 dark:bg-ink-850 dark:text-slate-100 dark:ring-ink-700 dark:hover:ring-ink-600'

export function DatePicker({ id, value, onChange, min, max, placeholder = 'Pick a date', disabled, 'aria-label': ariaLabel }:
  { id?: string; value: string; onChange: (v: string) => void; min?: string; max?: string; placeholder?: string; disabled?: boolean; 'aria-label'?: string }) {
  const sel = parse(value)
  const [open, setOpen] = useState(false)
  const [view, setView] = useState(() => { const d = sel || parse(min || '') || new Date(); return new Date(d.getFullYear(), d.getMonth(), 1) })
  const lo = parse(min || ''), hi = parse(max || '')
  const days = useMemo(() => {
    const first = (view.getDay() + 6) % 7            // Monday first
    const n = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate()
    return [...Array(first).fill(null), ...Array.from({ length: n }, (_, i) => new Date(view.getFullYear(), view.getMonth(), i + 1))]
  }, [view])
  const today = iso(new Date())
  const off = (d: Date) => (!!lo && d < lo) || (!!hi && d > hi)
  const label = sel ? sel.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : ''
  return (
    <Popover.Root open={open} onOpenChange={o => { setOpen(o); if (o) { const d = sel || lo || new Date(); setView(new Date(d.getFullYear(), d.getMonth(), 1)) } }}>
      <Popover.Trigger id={id} type="button" disabled={disabled} aria-label={ariaLabel} className={TRIGGER}>
        <CalendarDays className="size-4 shrink-0 text-slate-400" />
        <span className={cn('min-w-0 flex-1 truncate', !label && 'text-slate-400 dark:text-slate-500')}>{label || placeholder}</span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content sideOffset={6} collisionPadding={12} align="start"
          className="z-[70] w-72 rounded-xl bg-white p-3 text-sm text-slate-800 shadow-xl shadow-slate-900/10 ring-1 ring-slate-200 animate-rise dark:bg-ink-850 dark:text-slate-100 dark:shadow-black/40 dark:ring-ink-700">
          <div className="mb-2 flex items-center justify-between">
            <button type="button" aria-label="Previous month" onClick={() => setView(new Date(view.getFullYear(), view.getMonth() - 1, 1))} className="rounded-lg p-1.5 hover:bg-slate-100 dark:hover:bg-ink-800"><ChevronLeft className="size-4" /></button>
            <span className="font-semibold">{view.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}</span>
            <button type="button" aria-label="Next month" onClick={() => setView(new Date(view.getFullYear(), view.getMonth() + 1, 1))} className="rounded-lg p-1.5 hover:bg-slate-100 dark:hover:bg-ink-800"><ChevronRight className="size-4" /></button>
          </div>
          <div className="grid grid-cols-7 gap-0.5 text-center">
            {DOW.map(d => <span key={d} className="py-1 text-[11px] font-semibold text-slate-400">{d}</span>)}
            {days.map((d, i) => d ? (
              <button key={i} type="button" disabled={off(d)} aria-label={d.toDateString()} aria-pressed={iso(d) === value}
                onClick={() => { onChange(iso(d)); setOpen(false) }}
                className={cn('tabular h-9 rounded-lg text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-30',
                  iso(d) === value ? 'bg-brand-600 font-semibold text-white' : 'hover:bg-brand-50 dark:hover:bg-brand-500/20',
                  iso(d) === today && iso(d) !== value && 'font-semibold text-brand-700 ring-1 ring-inset ring-brand-200 dark:text-brand-300 dark:ring-brand-500/40')}>{d.getDate()}</button>
            ) : <span key={i} />)}
          </div>
          <div className="mt-2 flex justify-between border-t border-slate-100 pt-2 text-xs dark:border-ink-700">
            <button type="button" className="font-medium text-brand-600 hover:underline disabled:opacity-40 dark:text-brand-400" disabled={!!lo && new Date() < lo && iso(new Date()) !== min}
              onClick={() => { onChange(today); setOpen(false) }}>Today</button>
            {value && <button type="button" className="text-slate-500 hover:underline dark:text-slate-400" onClick={() => { onChange(''); setOpen(false) }}>Clear</button>}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

export function TimePicker({ id, value, onChange, step = 15, from = 6, to = 23, 'aria-label': ariaLabel }:
  { id?: string; value: string; onChange: (v: string) => void; step?: number; from?: number; to?: number; 'aria-label'?: string }) {
  const opts = useMemo(() => {
    const out: string[] = []
    for (let m = from * 60; m <= to * 60 + 45; m += step) out.push(`${pad(Math.floor(m / 60))}:${pad(m % 60)}`)
    if (value && !out.includes(value)) out.push(value), out.sort()
    return out
  }, [step, from, to, value])
  const show = (t: string) => { const [h, m] = t.split(':').map(Number); return new Date(2000, 0, 1, h, m).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) }
  return (
    <Select id={id} aria-label={ariaLabel} value={value} onChange={e => onChange(e.target.value)}>
      <option value="">Pick a time…</option>{opts.map(t => <option key={t} value={t}>{show(t)}</option>)}
    </Select>
  )
}

export function DateTimePicker({ id, value, onChange, min, 'aria-label': ariaLabel }: { id?: string; value: string; onChange: (v: string) => void; min?: string; 'aria-label'?: string }) {
  const [d, t] = (value || '').split('T')
  const set = (nd: string, nt: string) => onChange(nd ? `${nd}T${nt || '09:00'}` : '')
  return (
    <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] gap-2">
      <DatePicker id={id} aria-label={ariaLabel ? `${ariaLabel} date` : undefined} value={d || ''} min={min} onChange={nd => set(nd, t)} />
      <TimePicker aria-label={ariaLabel ? `${ariaLabel} time` : 'Time'} from={0} to={23} value={t ? t.slice(0, 5) : ''} onChange={nt => set(d || iso(new Date()), nt)} />
    </div>
  )
}

// Minutes (or any number): - and + in steps, with one-tap presets.
export function Stepper({ id, value, onChange, min = 5, max = 90, step = 5, unit = 'min', presets, 'aria-label': ariaLabel }:
  { id?: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; unit?: string; presets?: number[]; 'aria-label'?: string }) {
  const clamp = (v: number) => Math.max(min, Math.min(max, Math.round(v / step) * step || min))
  const v = clamp(Number(value) || min)
  const btn = 'grid size-10 shrink-0 place-items-center rounded-xl bg-white text-slate-700 shadow-sm ring-1 ring-inset ring-slate-200 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-ink-850 dark:text-slate-200 dark:ring-ink-700 dark:hover:bg-ink-800'
  return (
    <div>
      <div className="flex items-center gap-2">
        <button type="button" className={btn} aria-label={`Decrease by ${step} ${unit}`} disabled={v <= min} onClick={() => onChange(clamp(v - step))}><Minus className="size-4" /></button>
        <div id={id} role="spinbutton" tabIndex={0} aria-label={ariaLabel} aria-valuenow={v} aria-valuemin={min} aria-valuemax={max}
          onKeyDown={e => { if (e.key === 'ArrowUp' || e.key === 'ArrowRight') { e.preventDefault(); onChange(clamp(v + step)) } if (e.key === 'ArrowDown' || e.key === 'ArrowLeft') { e.preventDefault(); onChange(clamp(v - step)) } }}
          className="tabular flex h-10 min-w-24 flex-1 items-center justify-center rounded-xl bg-white px-3 text-sm font-semibold text-slate-900 shadow-sm ring-1 ring-inset ring-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 dark:bg-ink-850 dark:text-slate-100 dark:ring-ink-700">
          {v} {unit}</div>
        <button type="button" className={btn} aria-label={`Increase by ${step} ${unit}`} disabled={v >= max} onClick={() => onChange(clamp(v + step))}><Plus className="size-4" /></button>
      </div>
      {presets && <div className="mt-2 flex flex-wrap gap-1.5">{presets.filter(p => p >= min && p <= max).map(p => (
        <button key={p} type="button" aria-pressed={v === p} onClick={() => onChange(p)}
          className={cn('rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition-colors',
            v === p ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white text-slate-600 ring-slate-200 hover:bg-slate-50 dark:bg-ink-850 dark:text-slate-300 dark:ring-ink-700 dark:hover:bg-ink-800')}>{p} {unit}</button>))}</div>}
    </div>
  )
}
export const MINUTE_PRESETS = [10, 15, 20, 30, 45, 60, 90]
