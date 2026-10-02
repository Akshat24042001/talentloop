// Building blocks shared by the workspace pages.
import { TriangleAlert, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { api, pageCache } from '../lib/api'
import { ago, initials, when } from '../lib/format'
import { Alert, Button, Spinner, cn } from './ui'

export function PageHeader({ title, description, actions, back }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; back?: ReactNode }) {
  return (
    <div className="mb-6">
      {back}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white sm:text-[28px]">{title}</h1>
          {description && <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  )
}

export function BackLink({ href, children }: { href: string; children: ReactNode }) {
  return <a href={href} className="no-print mb-3 inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white">← {children}</a>
}

export function Avatar({ name, size = 'md', className }: { name?: string | null; size?: 'sm' | 'md' | 'lg'; className?: string }) {
  const s = { sm: 'size-7 text-[10px]', md: 'size-9 text-xs', lg: 'size-14 text-lg' }[size]
  return <span className={cn('grid shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-100 to-violet-100 font-bold text-brand-700 dark:from-brand-500/25 dark:to-violet-500/25 dark:text-brand-200', s, className)}>{initials(name)}</span>
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="px-6 py-14 text-center">
      {icon && <div className="mx-auto grid size-12 place-items-center rounded-2xl bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300 [&_svg]:size-6">{icon}</div>}
      <h3 className="mt-4 text-base font-semibold text-slate-900 dark:text-white">{title}</h3>
      {children && <p className="mx-auto mt-1 max-w-md text-sm text-slate-500 dark:text-slate-400">{children}</p>}
      {action && <div className="mt-5 flex justify-center gap-2">{action}</div>}
    </div>
  )
}

export function Loading({ className }: { className?: string }) {
  return <div className={cn('grid place-items-center p-16', className)}><Spinner className="size-6 text-brand-500" /></div>
}
// Skeletons: the page's shape while data loads, so the layout doesn't jump when it arrives.
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('animate-pulse rounded-lg bg-slate-200/70 dark:bg-ink-800', className)} />
}
export function ListSkeleton({ rows = 6, avatar = true }: { rows?: number; avatar?: boolean }) {
  return (
    <div role="status" aria-label="Loading" className="divide-y divide-slate-100 rounded-2xl bg-white ring-1 ring-slate-200/70 dark:divide-ink-800 dark:bg-ink-900 dark:ring-ink-800">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3 px-5 py-4">
          {avatar && <Skeleton className="size-9 shrink-0 rounded-full" />}
          <div className="min-w-0 flex-1 space-y-2"><Skeleton className="h-3.5 w-2/5" /><Skeleton className="h-3 w-3/5" /></div>
          <Skeleton className="hidden h-6 w-20 rounded-full sm:block" />
        </div>))}
    </div>
  )
}
export function CardsSkeleton({ n = 4, className }: { n?: number; className?: string }) {
  return <div role="status" aria-label="Loading" className={cn('grid grid-cols-2 gap-3 lg:grid-cols-4', className)}>{Array.from({ length: n }, (_, i) => (
    <div key={i} className="space-y-3 rounded-2xl bg-white p-5 ring-1 ring-slate-200/70 dark:bg-ink-900 dark:ring-ink-800"><Skeleton className="h-3 w-1/2" /><Skeleton className="h-7 w-1/3" /><Skeleton className="h-3 w-2/3" /></div>))}</div>
}
export function BoardSkeleton({ cols = 4 }: { cols?: number }) {
  return <div role="status" aria-label="Loading" className="flex gap-3 overflow-hidden">{Array.from({ length: cols }, (_, i) => (
    <div key={i} className="w-72 shrink-0 space-y-2.5 rounded-2xl bg-slate-100/70 p-3 dark:bg-ink-900"><Skeleton className="h-4 w-1/2" />
      {Array.from({ length: 3 - (i % 2) }, (_, j) => <div key={j} className="space-y-2 rounded-xl bg-white p-3 dark:bg-ink-850"><Skeleton className="h-3.5 w-3/4" /><Skeleton className="h-3 w-1/2" /></div>)}</div>))}</div>
}
export function PageSkeleton() {
  return <div role="status" aria-label="Loading" className="space-y-5"><div className="space-y-2"><Skeleton className="h-7 w-56" /><Skeleton className="h-4 w-80 max-w-full" /></div><CardsSkeleton /><ListSkeleton rows={5} /></div>
}
export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return <Alert tone="danger" icon={<TriangleAlert />} title="Something went wrong">{error}{retry && <> <button className="font-semibold underline" onClick={retry}>Try again</button></>}</Alert>
}

/** Load JSON from the API; `reload` refetches. Shows the last copy of the same page instantly, then refreshes it. */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const cached = path ? (pageCache.get(path) as T | undefined) : undefined
  const [data, setData] = useState<T | null>(cached ?? null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(!!path && cached === undefined)
  const seq = useRef(0)
  const reload = useCallback(async () => {
    if (!path) return
    const n = ++seq.current
    if (!pageCache.has(path)) setLoading(true)
    else setData(pageCache.get(path) as T)
    try { const d = await api<T>(path); pageCache.set(path, d); if (n === seq.current) { setData(d); setError('') } }
    catch (e: any) { if (n === seq.current) setError(e.message) }
    if (n === seq.current) setLoading(false)
  }, [path, ...deps])                          // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { reload() }, [reload])
  return { data, error, loading, reload, setData }
}

export function Tabs<T extends string>({ tabs, value, onChange, className }: { tabs: { id: T; label: ReactNode; count?: number | null }[]; value: T; onChange: (v: T) => void; className?: string }) {
  return (
    <div role="tablist" className={cn('no-print -mx-1 flex gap-1 overflow-x-auto border-b border-slate-200 px-1 dark:border-ink-700', className)}>
      {tabs.map(t => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cn('-mb-px flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
            value === t.id ? 'border-brand-600 text-brand-700 dark:border-brand-400 dark:text-brand-200' : 'border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-white')}>
          {t.label}{t.count != null && <span className="tabular rounded-full bg-slate-100 px-1.5 text-xs text-slate-600 dark:bg-ink-800 dark:text-slate-300">{t.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function scoreTone(s: number | null | undefined): string {
  if (s == null) return 'text-slate-500 dark:text-slate-400'
  return s >= 75 ? 'text-emerald-600 dark:text-emerald-400' : s >= 55 ? 'text-brand-600 dark:text-brand-300' : s >= 40 ? 'text-amber-600 dark:text-amber-400' : 'text-slate-500'
}
export function ScoreBar({ value, max = 100, className }: { value: number | null | undefined; max?: number; className?: string }) {
  return (
    <span className={cn('flex items-center gap-2', className)}>
      <span className={cn('tabular w-8 text-right text-sm font-semibold', scoreTone(value != null ? (value / max) * 100 : null))}>{value == null ? '-' : Math.round(value)}</span>
      <span className="relative h-1.5 w-16 rounded-full bg-[var(--track)]"><i className="absolute inset-y-0 left-0 rounded-full bg-[var(--series-1)]" style={{ width: `${Math.max(0, Math.min(100, ((value || 0) / max) * 100))}%` }} /></span>
    </span>
  )
}
export function ScoreRing({ value, size = 56, label }: { value: number | null | undefined; size?: number; label?: string }) {
  const r = size / 2 - 5, c = 2 * Math.PI * r, v = Math.max(0, Math.min(100, value || 0))
  return (
    <span className="relative inline-grid shrink-0 place-items-center" style={{ width: size, height: size }} aria-label={label ? `${label}: ${value ?? 'not scored'}` : undefined}>
      <svg width={size} height={size} className="-rotate-90"><circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--track)" strokeWidth="5" />
        {value != null && <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--series-1)" strokeWidth="5" strokeLinecap="round" strokeDasharray={`${(v / 100) * c} ${c}`} />}</svg>
      <span className={cn('tabular absolute text-sm font-bold', scoreTone(value))}>{value == null ? '-' : Math.round(value)}</span>
    </span>
  )
}

/** Tags with Enter/comma to add, optional suggestions. */
export function TagInput({ value, onChange, placeholder, suggestions, id }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; suggestions?: string[]; id?: string }) {
  const [text, setText] = useState('')
  const add = (raw: string) => {
    const items = raw.split(',').map(s => s.trim()).filter(Boolean)
    if (items.length) onChange([...new Set([...value, ...items])])
    setText('')
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(text) }
    if (e.key === 'Backspace' && !text && value.length) onChange(value.slice(0, -1))
  }
  const listId = id ? `${id}-list` : undefined
  const sugg = suggestions && text.length >= 1 ? suggestions.filter(s => s.toLowerCase().includes(text.toLowerCase()) && !value.includes(s)).slice(0, 8) : []
  return (
    <div className="relative">
      <div className="flex min-h-[42px] flex-wrap items-center gap-1.5 rounded-xl bg-white px-2 py-1.5 shadow-sm ring-1 ring-inset ring-slate-200 focus-within:ring-2 focus-within:ring-brand-500 dark:bg-ink-850 dark:ring-ink-700">
        {value.map(v => (
          <span key={v} className="inline-flex items-center gap-1 rounded-lg bg-brand-50 py-0.5 pl-2 pr-1 text-[13px] font-medium text-brand-700 dark:bg-brand-500/15 dark:text-brand-200">
            {v}<button type="button" aria-label={`Remove ${v}`} className="rounded p-0.5 hover:bg-brand-100 dark:hover:bg-brand-500/25" onClick={() => onChange(value.filter(x => x !== v))}><X className="size-3" /></button>
          </span>
        ))}
        <input id={id} list={listId} value={text} onChange={e => setText(e.target.value)} onKeyDown={onKey} onBlur={() => text && add(text)}
          placeholder={value.length ? '' : placeholder} className="min-w-[120px] flex-1 bg-transparent px-1.5 py-1 text-sm outline-none placeholder:text-slate-400" />
      </div>
      {sugg.length > 0 && (
        <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-xl bg-white py-1 shadow-lg ring-1 ring-slate-200 dark:bg-ink-850 dark:ring-ink-700">
          {sugg.map(s => <button type="button" key={s} onMouseDown={e => { e.preventDefault(); onChange([...value, s]); setText('') }} className="block w-full px-3 py-1.5 text-left text-sm hover:bg-slate-50 dark:hover:bg-ink-800">{s}</button>)}
        </div>
      )}
    </div>
  )
}

/** Editable list of lines (responsibilities etc.). */
export function ListInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const rows = value.length ? value : ['']
  return (
    <div className="space-y-2">
      {rows.map((v, i) => (
        <div key={i} className="flex gap-2">
          <span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-slate-300 dark:bg-ink-600" />
          <input value={v} placeholder={i === 0 ? placeholder : ''} onChange={e => { const n = [...rows]; n[i] = e.target.value; onChange(n) }}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); const n = [...rows]; n.splice(i + 1, 0, ''); onChange(n); setTimeout(() => (e.target as HTMLInputElement).parentElement?.nextElementSibling?.querySelector('input')?.focus(), 0) } }}
            className="block w-full rounded-lg border-0 bg-white px-3 py-2 text-sm shadow-sm ring-1 ring-inset ring-slate-200 focus:outline-none focus:ring-2 focus:ring-brand-500 dark:bg-ink-850 dark:ring-ink-700" />
          <button type="button" aria-label="Remove line" onClick={() => onChange(rows.filter((_, j) => j !== i))} className="rounded-lg px-2 text-slate-500 dark:text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-ink-800"><X className="size-4" /></button>
        </div>
      ))}
      <Button type="button" size="sm" variant="ghost" onClick={() => onChange([...rows, ''])}>+ Add line</Button>
    </div>
  )
}

/** Client-side paging for lists already in memory: `const { rows, pager } = usePaged(filtered, 25, [filters...])`. */
export function usePaged<T>(items: T[], size = 25, resetOn: unknown[] = []) {
  const [page, setPage] = useState(1)
  useEffect(() => { setPage(1) }, resetOn)            // eslint-disable-line react-hooks/exhaustive-deps
  const pages = Math.max(1, Math.ceil(items.length / size)), cur = Math.min(page, pages)
  return { rows: items.slice((cur - 1) * size, cur * size), pager: <Pager page={cur} total={items.length} limit={size} onPage={p => { setPage(p); window.scrollTo({ top: 0, behavior: 'smooth' }) }} /> }
}
export function Pager({ page, total, limit, onPage }: { page: number; total: number; limit: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / limit))
  if (pages <= 1) return null
  return (
    <div className="flex items-center justify-between gap-2 border-t border-slate-100 px-4 py-3 text-sm text-slate-500 dark:border-ink-800">
      <span>{(page - 1) * limit + 1}-{Math.min(total, page * limit)} of {total}</span>
      <div className="flex items-center gap-1"><Button size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        {Array.from({ length: pages }, (_, i) => i + 1).filter(n => n === 1 || n === pages || Math.abs(n - page) <= 1).map((n, i, a) => (
          <span key={n} className="flex items-center">{i > 0 && n - a[i - 1]! > 1 && <span className="px-1 text-slate-400">…</span>}
            <button type="button" aria-current={n === page ? 'page' : undefined} onClick={() => onPage(n)}
              className={cn('tabular hidden size-8 rounded-lg text-sm font-medium sm:inline-block', n === page ? 'bg-brand-600 text-white' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-ink-800')}>{n}</button></span>))}
        <Button size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button></div>
    </div>
  )
}

export function KV({ k, children }: { k: ReactNode; children: ReactNode }) {
  return <div className="flex justify-between gap-4 py-2 text-sm"><dt className="text-slate-500 dark:text-slate-400">{k}</dt><dd className="text-right font-medium text-slate-800 dark:text-slate-100">{children || '-'}</dd></div>
}

/** "3 weeks ago", with the exact date and time on hover. */
export function Ago({ ts, prefix = '' }: { ts?: number | null; prefix?: string }) {
  if (!ts) return <>-</>
  return <time dateTime={new Date(ts * 1000).toISOString()} title={when(ts)}>{prefix}{ago(ts)}</time>
}
