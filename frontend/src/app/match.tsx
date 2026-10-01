// Match display shared by the job page, the match center and the candidate page.
import { ChevronDown, CircleCheck, CircleX, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Badge, cn } from '../components/ui'
import { VERDICT } from './labels'

export interface Breakdown {
  skills: { score: number; must_matched: string[]; must_missing: string[]; nice_matched: string[] }
  experience: { score: number; years: number | null; note: string }
  relevance: { score: number; title: number }
  location: { score: number; note: string; candidate?: string }
  logistics: { score: number; notice?: string; salary?: string }
  applied?: boolean; knocked_out?: string[]
}
export interface AIReport { score: number | null; verdict: string; summary: string; strengths: string[]; gaps: string[]; risks: string[]; interview_questions: string[] }

export function BreakdownBars({ b }: { b: Breakdown }) {
  const rows: [string, number, string][] = [
    ['Skills', b.skills.score, `${b.skills.must_matched.length}/${b.skills.must_matched.length + b.skills.must_missing.length} must-haves`],
    ['Experience', b.experience.score, b.experience.years != null ? `${b.experience.years} yrs · ${b.experience.note}` : b.experience.note],
    ['Relevance', b.relevance.score, 'resume vs job text'],
    ['Location', b.location.score, b.location.note],
    ['Notice & pay', b.logistics.score, [b.logistics.notice && `notice ${b.logistics.notice}`, b.logistics.salary].filter(Boolean).join(' · ') || 'no limits set'],
  ]
  return (
    <div className="space-y-2">
      {rows.map(([k, v, sub]) => (
        <div key={k} className="grid grid-cols-[88px_1fr_minmax(0,140px)] items-center gap-3 text-xs">
          <span className="font-medium text-slate-600 dark:text-slate-300">{k}</span>
          <span className="relative h-2 rounded-full bg-[var(--track)]"><i className="absolute inset-y-0 left-0 rounded-full bg-[var(--series-1)]" style={{ width: `${Math.round(v * 100)}%` }} /></span>
          <span className="truncate text-slate-500 dark:text-slate-400" title={sub}>{sub}</span>
        </div>
      ))}
    </div>
  )
}

export function SkillChips({ b }: { b: Breakdown }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {b.skills.must_matched.map(s => <span key={s} className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"><CircleCheck className="size-3" />{s}</span>)}
      {b.skills.must_missing.map(s => <span key={s} className="inline-flex items-center gap-1 rounded-md bg-red-50 px-1.5 py-0.5 text-xs font-medium text-red-700 dark:bg-red-500/15 dark:text-red-300"><CircleX className="size-3" />{s}</span>)}
      {b.skills.nice_matched.map(s => <span key={s} className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-600 dark:bg-ink-800 dark:text-slate-300">+ {s}</span>)}
    </div>
  )
}

export function ReportView({ r, compact }: { r: AIReport; compact?: boolean }) {
  const [open, setOpen] = useState(!compact)
  const v = VERDICT[r.verdict]
  return (
    <div className="rounded-xl bg-gradient-to-br from-brand-50/80 to-violet-50/60 p-4 ring-1 ring-brand-100 dark:from-brand-500/10 dark:to-violet-500/10 dark:ring-brand-500/20">
      <button className="flex w-full items-center justify-between gap-2 text-left" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        <span className="flex flex-wrap items-center gap-2 text-sm font-semibold"><Sparkles className="size-4 text-brand-600 dark:text-brand-300" />AI match report
          {v && <Badge tone={v.tone}>{v.label}</Badge>}{r.score != null && <span className="tabular text-slate-500">{r.score}/100</span>}</span>
        <ChevronDown className={cn('size-4 text-slate-400 transition-transform', open && 'rotate-180')} />
      </button>
      <p className="mt-2 text-sm leading-relaxed text-slate-700 dark:text-slate-200">{r.summary}</p>
      {open && (
        <div className="mt-3 grid gap-4 text-sm sm:grid-cols-2">
          <List title="Strengths" items={r.strengths} tone="text-emerald-700 dark:text-emerald-300" />
          <List title="Gaps" items={r.gaps} tone="text-amber-700 dark:text-amber-300" />
          {r.risks.length > 0 && <List title="Risks" items={r.risks} tone="text-red-700 dark:text-red-300" />}
          <List title="Ask in the interview" items={r.interview_questions} tone="text-brand-700 dark:text-brand-300" />
        </div>
      )}
    </div>
  )
}
function List({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  if (!items?.length) return null
  return <div><div className={cn('mb-1 text-xs font-semibold uppercase tracking-wide', tone)}>{title}</div><ul className="space-y-1 text-slate-700 dark:text-slate-200">{items.map((x, i) => <li key={i} className="flex gap-2"><span className="mt-2 size-1 shrink-0 rounded-full bg-current opacity-50" />{x}</li>)}</ul></div>
}
