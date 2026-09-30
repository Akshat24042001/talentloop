// Charts: horizontal bars, a time strip and a proportion bar. Colors come from CSS tokens (see styles.css):
// --series-1/2 are colorblind-validated categorical slots; status colors are fixed and always paired with a label.
import { type ReactNode } from 'react'
import { mmss } from '../lib/format'
import { Tip, cn } from './ui'

export interface BarRow { key: string; label: string; sub?: string; value: number | null; display?: string; marker?: number | null; tip?: ReactNode }

export function HBarChart({ rows, max, valueLabel = 'Value', markerLabel, empty = 'No data yet.' }: { rows: BarRow[]; max?: number; valueLabel?: string; markerLabel?: string | null; empty?: string }) {
  if (!rows.length) return <p className="text-sm text-slate-500 dark:text-slate-400">{empty}</p>
  const m = max || Math.max(1, ...rows.map(r => Math.max(r.value || 0, r.marker || 0)))
  return (
    <div>
      {markerLabel && (
        <div className="mb-3 flex flex-wrap gap-4 text-xs text-slate-500 dark:text-slate-400">
          <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-[3px] bg-[var(--series-1)]" />{valueLabel}</span>
          <span className="inline-flex items-center gap-1.5"><i className="h-3 w-1 rounded-full bg-[var(--series-2)]" />{markerLabel}</span>
        </div>
      )}
      <div className="space-y-2.5">
        {rows.map(r => (
          <Tip key={r.key} label={r.tip ?? <>{r.label}: <b>{r.display ?? r.value ?? '-'}</b></>}>
            <div className="hbar grid cursor-default grid-cols-[minmax(0,1fr)_44px] items-center gap-x-3 gap-y-1 rounded-lg px-1 py-0.5 hover:bg-slate-50 dark:hover:bg-ink-850 sm:grid-cols-[minmax(110px,38%)_minmax(0,1fr)_48px]">
              <div className="col-span-2 min-w-0 text-[13px] leading-tight sm:col-span-1">
                <div className="truncate font-semibold text-slate-800 dark:text-slate-100">{r.label}</div>
                {r.sub && <div className="truncate text-xs text-slate-500 dark:text-slate-400">{r.sub}</div>}
              </div>
              <div className="relative h-3 rounded-r-[4px] bg-[var(--track)]">
                {r.value == null ? <span className="absolute -top-0.5 left-2 text-[10px] leading-4 text-slate-400">not scored</span>
                  : <i className="absolute inset-y-0 left-0 min-w-[2px] rounded-r-[4px] bg-[var(--series-1)]" style={{ width: `${Math.min(100, Math.max(0, (r.value / m) * 100))}%` }} />}
                {r.marker != null && <i className="absolute -inset-y-1 w-1 rounded-full bg-[var(--series-2)] ring-2 ring-white dark:ring-ink-900" style={{ left: `calc(${Math.min(100, (r.marker / m) * 100)}% - 2px)` }} />}
              </div>
              <div className="tabular text-right text-[13px] font-semibold text-slate-800 dark:text-slate-100">{r.display ?? r.value ?? '-'}</div>
            </div>
          </Tip>
        ))}
      </div>
    </div>
  )
}

export interface TimelineEvent { t: number; severity: 'high' | 'medium'; label: string; q?: string; detail?: string }
export function TimelineChart({ events, duration, markers = [] }: { events: TimelineEvent[]; duration: number; markers?: { t: number; label: string }[] }) {
  const D = Math.max(60, duration || 0, ...events.map(e => e.t || 0), ...markers.map(m => m.t || 0))
  const step = D > 1800 ? 600 : D > 600 ? 300 : D > 240 ? 60 : 30
  const ticks: number[] = []
  for (let t = 0; t <= D; t += step) ticks.push(t)
  const pct = (t: number) => `${((t / D) * 100).toFixed(2)}%`
  const Lane = ({ name, list, withMarkers }: { name: string; list: TimelineEvent[]; withMarkers?: boolean }) => (
    <div className="grid grid-cols-[64px_1fr] items-center gap-2">
      <span className="text-xs font-medium text-slate-500 dark:text-slate-400">{name}</span>
      <div className="relative h-8 border-b border-dashed border-slate-200 dark:border-ink-700">
        {withMarkers && markers.map((m, i) => (
          <Tip key={`m${i}`} label={<><b>{mmss(m.t)}</b> {m.label}</>}>
            <i className="absolute inset-y-1 w-1 -translate-x-1/2 cursor-default rounded-full bg-slate-900 dark:bg-white" style={{ left: pct(m.t) }} />
          </Tip>
        ))}
        {list.map((e, i) => (
          <Tip key={i} label={<><b>{mmss(e.t)}</b> {e.label}{e.q && <div className="mt-0.5 text-slate-300">{e.q}</div>}{e.detail && <div className="text-slate-400">{e.detail}</div>}</>}>
            <i className={cn('absolute top-2.5 size-3 -translate-x-1/2 cursor-default rounded-full ring-2 ring-white dark:ring-ink-900', e.severity === 'high' ? 'bg-[var(--status-critical)]' : 'bg-[var(--status-serious)]')} style={{ left: pct(e.t) }} />
          </Tip>
        ))}
      </div>
    </div>
  )
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-4 text-xs text-slate-500 dark:text-slate-400">
        <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-full bg-[var(--status-critical)]" />High-risk signal</span>
        <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-full bg-[var(--status-serious)]" />Medium signal</span>
        {markers.length > 0 && <span className="inline-flex items-center gap-1.5"><i className="h-3 w-1 rounded-full bg-slate-900 dark:bg-white" />Interviewer warning</span>}
      </div>
      <Lane name="High" list={events.filter(e => e.severity === 'high')} withMarkers />
      <Lane name="Medium" list={events.filter(e => e.severity !== 'high')} />
      <div className="grid grid-cols-[64px_1fr] gap-2">
        <span />
        <div className="relative h-6">{ticks.map(t => <span key={t} className="tabular absolute top-1 -translate-x-1/2 text-[11px] text-slate-400" style={{ left: pct(t) }}>{mmss(t)}</span>)}</div>
      </div>
    </div>
  )
}

export function SplitBar({ parts }: { parts: { label: string; n: number; color: string }[] }) {
  const total = parts.reduce((a, p) => a + p.n, 0)
  if (!total) return <p className="text-sm text-slate-500 dark:text-slate-400">No data yet.</p>
  return (
    <div>
      <div className="flex h-3 gap-[2px] overflow-hidden rounded-[4px]">
        {parts.filter(p => p.n).map(p => (
          <Tip key={p.label} label={<>{p.label}: <b>{p.n}</b> ({Math.round((p.n / total) * 100)}%)</>}>
            <i className="block min-w-1 cursor-default" style={{ flex: p.n, background: p.color }} />
          </Tip>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-slate-500 dark:text-slate-400">
        {parts.map(p => <span key={p.label} className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-[3px]" style={{ background: p.color }} />{p.label} <b className="text-slate-800 dark:text-slate-100">{p.n}</b></span>)}
      </div>
    </div>
  )
}
