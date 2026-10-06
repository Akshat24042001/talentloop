// Match display shared by the job page, the match center and the candidate page.
import { ChevronDown, CircleCheck, CircleX, ExternalLink, Globe, ShieldAlert, Sparkles, TriangleAlert } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Badge, Button, cn, toast } from '../components/ui'
import { api } from '../lib/api'
import { VERDICT } from './labels'

export interface Breakdown {
  skills: { score: number; must_matched: string[]; must_missing: string[]; nice_matched: string[] }
  experience: { score: number; years: number | null; note: string }
  relevance: { score: number; title: number }
  location: { score: number; note: string; candidate?: string }
  logistics: { score: number; notice?: string; salary?: string }
  applied?: boolean; knocked_out?: string[]
}
export interface WebItem { id: string; kind: string; status: 'confirmed' | 'possible'; url: string; evidence: string[]; about?: string; dead?: boolean; source?: string }
export interface Quoted { point?: string; what?: string; flag?: string; quote: string }
export interface AIReport {
  source?: string; why_no_ai?: string; schema?: number
  score: number | null; verdict: string | null; confidence?: string; confidence_why?: string; prescreen_score?: number
  summary: string; recommendation?: { action: string; why: string }
  must_haves?: { skill: string; status: 'proven' | 'claimed' | 'related' | 'missing'; where: string; quote: string }[]
  strengths: string[]; gaps: string[]; risks: string[]; interview_questions: string[]
  strengths_detail?: Quoted[]; gaps_detail?: Quoted[]; risks_detail?: Quoted[]
  career?: { total_years: number | null; jobs: number | null; avg_tenure_months: number | null; trajectory: string; notes: string }
  achievements?: Quoted[]; red_flags?: Quoted[]
  online?: { consistency: string; notes: string[]; evidence_ids: string[] }
  interview_focus?: { topic: string; why: string; question: string }[]; verify_next?: string[]
  web?: { items: WebItem[]; notes: string[]; queries: string[] }
  based_on?: { resume_chars: number; web_items: number; search: string | null; lookup: string }
}

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

const REC = { interview: { label: 'Interview', cls: 'bg-emerald-50 text-emerald-800 ring-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-200 dark:ring-emerald-500/30' },
  hold: { label: 'Hold', cls: 'bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-200 dark:ring-amber-500/30' },
  decline: { label: 'Decline', cls: 'bg-red-50 text-red-800 ring-red-200 dark:bg-red-500/10 dark:text-red-200 dark:ring-red-500/30' } } as const
const MH: Record<string, { label: string; cls: string }> = {
  proven: { label: 'Proven', cls: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200' },
  claimed: { label: 'Only listed', cls: 'bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200' },
  related: { label: 'Related', cls: 'bg-sky-100 text-sky-800 dark:bg-sky-500/20 dark:text-sky-200' },
  missing: { label: 'Missing', cls: 'bg-red-100 text-red-800 dark:bg-red-500/20 dark:text-red-200' } }
const TRAJ: Record<string, string> = { rising: 'Rising: growing responsibility', steady: 'Steady', mixed: 'Mixed', unclear: 'Unclear from the resume' }
const CONS: Record<string, { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral' }> = {
  consistent: { label: 'Online matches the resume', tone: 'success' }, some_differences: { label: 'Some differences online', tone: 'warning' },
  conflicts: { label: 'Online conflicts with the resume', tone: 'danger' }, not_checked: { label: 'Not checked online', tone: 'neutral' } }
const pretty = (u: string) => { try { const x = new URL(u); return x.host.replace(/^www\./, '') + (x.pathname === '/' ? '' : x.pathname.replace(/\/$/, '')) } catch { return u } }

export function ReportView({ r, compact, retry }: { r: AIReport; compact?: boolean; retry?: ReactNode }) {
  const [open, setOpen] = useState(!compact)
  const v = r.verdict ? VERDICT[r.verdict] : null
  const auto = r.source === 'rules'
  const rec = r.recommendation && REC[r.recommendation.action as keyof typeof REC]
  return (
    <div className="rounded-xl bg-gradient-to-br from-brand-50/80 to-violet-50/60 p-4 ring-1 ring-brand-100 dark:from-brand-500/10 dark:to-violet-500/10 dark:ring-brand-500/20">
      <button className="flex w-full items-center justify-between gap-2 text-left" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        <span className="flex flex-wrap items-center gap-2 text-sm font-semibold"><Sparkles className="size-4 text-brand-600 dark:text-brand-300" />{auto ? 'Automatic summary' : 'AI match report'}
          {auto && <Badge tone="warning">No AI yet</Badge>}{v && <Badge tone={v.tone}>{v.label}</Badge>}
          {!auto && r.score != null && <span className="tabular text-slate-600 dark:text-slate-300" title="The AI's own judgement after reading the resume and what is public about the candidate. Different from the keyword match score.">AI score {r.score}/100</span>}
          {!auto && r.confidence && <span className="text-xs font-normal text-slate-500 dark:text-slate-400" title={r.confidence_why}>{r.confidence} confidence</span>}</span>
        <ChevronDown className={cn('size-4 text-slate-500 dark:text-slate-400 transition-transform', open && 'rotate-180')} />
      </button>
      {auto && r.why_no_ai && <p className="mt-2 flex gap-2 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900 ring-1 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-200 dark:ring-amber-500/30"><TriangleAlert className="mt-0.5 size-3.5 shrink-0" /><span><b>Why the AI didn't write this:</b> {r.why_no_ai}</span></p>}
      <p className="mt-2 text-sm leading-relaxed text-slate-700 dark:text-slate-200">{r.summary}</p>
      {!auto && r.prescreen_score != null && r.score != null && Math.abs(r.score - r.prescreen_score) >= 10 &&
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Keyword match {r.prescreen_score}, AI score {r.score}: the AI read the whole resume and what is public about the candidate, so the two can differ.</p>}
      {rec && <div className={cn('mt-3 rounded-lg p-2.5 text-sm ring-1', rec.cls)}><b>Suggested next step: {rec.label}.</b> {r.recommendation?.why} <span className="opacity-70">A person decides.</span></div>}
      {retry && <div className="mt-2">{retry}</div>}
      {open && (
        <div className="mt-4 space-y-4 text-sm">
          {!!r.must_haves?.length && <div><Head>Must-have skills</Head>
            <ul className="space-y-1.5">{r.must_haves.map((m, i) => <li key={i} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-semibold', MH[m.status]?.cls)}>{MH[m.status]?.label}</span><b>{m.skill}</b>
              {m.where && <span className="text-slate-500 dark:text-slate-400">at {m.where}</span>}{m.quote && <Quote q={m.quote} />}</li>)}</ul></div>}
          <div className="grid gap-4 sm:grid-cols-2">
            <Points title="Strengths" tone="text-emerald-700 dark:text-emerald-300" items={r.strengths_detail} flat={r.strengths} />
            <Points title="Gaps" tone="text-amber-700 dark:text-amber-300" items={r.gaps_detail} flat={r.gaps} />
            <Points title="Risks" tone="text-red-700 dark:text-red-300" items={r.risks_detail} flat={r.risks} />
            {!!r.achievements?.length && <Points title="Achievements (with numbers)" tone="text-brand-700 dark:text-brand-300" items={r.achievements} flat={[]} />}
          </div>
          {!!r.red_flags?.length && <div className="rounded-lg bg-red-50 p-3 ring-1 ring-red-200 dark:bg-red-500/10 dark:ring-red-500/30"><Head tone="text-red-700 dark:text-red-300"><ShieldAlert className="mr-1 inline size-3.5" />Red flags to look into</Head>
            <ul className="space-y-1.5">{r.red_flags.map((x, i) => <li key={i}>{x.flag}{x.quote && <Quote q={x.quote} />}</li>)}</ul></div>}
          {r.career && (r.career.total_years != null || r.career.jobs != null || r.career.notes) && <div><Head>Career</Head>
            <div className="flex flex-wrap gap-1.5 text-xs">{r.career.total_years != null && <Chip>{r.career.total_years} years in total</Chip>}{r.career.jobs != null && <Chip>{r.career.jobs} jobs</Chip>}
              {r.career.avg_tenure_months != null && <Chip>about {r.career.avg_tenure_months} months per job</Chip>}<Chip>{TRAJ[r.career.trajectory] || r.career.trajectory}</Chip></div>
            {r.career.notes && <p className="mt-1.5 text-slate-600 dark:text-slate-300">{r.career.notes}</p>}</div>}
          <Online r={r} />
          {!!r.interview_focus?.length ? <div><Head>What to ask in the interview</Head>
            <ul className="space-y-2">{r.interview_focus.map((f, i) => <li key={i}><b>{f.topic}</b>{f.why && <span className="text-slate-500 dark:text-slate-400"> · {f.why}</span>}<div className="mt-0.5 text-slate-800 dark:text-slate-100">"{f.question}"</div></li>)}</ul></div>
            : <Points title="Ask in the interview" tone="text-brand-700 dark:text-brand-300" flat={r.interview_questions} />}
          {!!r.verify_next?.length && <div><Head>Check outside the interview</Head><ul className="list-disc space-y-0.5 pl-5">{r.verify_next.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
          {r.based_on && <p className="border-t border-brand-100 pt-2 text-xs text-slate-500 dark:border-brand-500/20 dark:text-slate-400">Based on the resume ({r.based_on.resume_chars.toLocaleString()} characters)
            {r.based_on.web_items ? ` and ${r.based_on.web_items} public source${r.based_on.web_items > 1 ? 's' : ''}` : r.based_on.lookup ? `. ${r.based_on.lookup}` : ', with nothing public found'}. Quotes are copied from the resume and checked by the system. Items marked Possible may be someone with the same name.</p>}
        </div>
      )}
    </div>
  )
}
const Head = ({ children, tone }: { children: ReactNode; tone?: string }) => <div className={cn('mb-1 text-xs font-semibold uppercase tracking-wide', tone || 'text-slate-500 dark:text-slate-400')}>{children}</div>
const Chip = ({ children }: { children: ReactNode }) => <span className="rounded-md bg-white/70 px-2 py-0.5 ring-1 ring-brand-100 dark:bg-white/5 dark:ring-white/10">{children}</span>
const Quote = ({ q }: { q: string }) => <span className="block w-full text-xs italic text-slate-500 dark:text-slate-400">"{q}"</span>

function Points({ title, tone, items, flat }: { title: string; tone: string; items?: Quoted[]; flat: string[] }) {
  const rows = items?.length ? items.map(x => ({ t: x.point || x.what || x.flag || '', q: x.quote })) : (flat || []).map(t => ({ t, q: '' }))
  if (!rows.length) return null
  return <div><Head tone={tone}>{title}</Head><ul className="space-y-1.5 text-slate-700 dark:text-slate-200">{rows.map((x, i) => <li key={i} className="flex gap-2"><span className="mt-2 size-1 shrink-0 rounded-full bg-current opacity-50" /><span>{x.t}{x.q && <Quote q={x.q} />}</span></li>)}</ul></div>
}

function Online({ r }: { r: AIReport }) {
  const w = r.web, items = w?.items || []
  const cons = r.online && CONS[r.online.consistency]
  const sure = items.filter(i => i.status === 'confirmed'), maybe = items.filter(i => i.status === 'possible')
  const row = (i: WebItem) => (
    <li key={i.id} className="flex flex-wrap items-baseline gap-x-2">
      <Badge tone={i.status === 'confirmed' ? 'success' : 'warning'}>{i.status === 'confirmed' ? 'Confirmed' : 'Possible'}</Badge>
      <a href={i.url} target="_blank" rel="noopener noreferrer nofollow" className={cn('inline-flex items-center gap-1 font-medium text-brand-700 hover:underline dark:text-brand-300', i.dead && 'line-through opacity-70')}>{i.kind}: {pretty(i.url)}<ExternalLink className="size-3" /></a>
      <span className="w-full text-xs text-slate-500 dark:text-slate-400">{i.dead ? 'Does not load. ' : ''}{i.evidence.join('; ')}{i.about ? ` · ${i.about}` : ''}</span></li>)
  return (
    <div><Head><Globe className="mr-1 inline size-3.5" />Found online</Head>
      {cons && <div className="mb-1.5"><Badge tone={cons.tone}>{cons.label}</Badge></div>}
      {r.online?.notes?.length ? <ul className="mb-2 list-disc space-y-0.5 pl-5 text-slate-700 dark:text-slate-200">{r.online.notes.map((n, i) => <li key={i}>{n}</li>)}</ul> : null}
      {items.length ? <ul className="space-y-1.5">{[...sure, ...maybe].map(row)}</ul> : <p className="text-slate-500 dark:text-slate-400">Nothing public found beyond the resume.</p>}
      {!!w?.notes?.length && <details className="mt-2 text-xs text-slate-500 dark:text-slate-400"><summary className="cursor-pointer">What was and wasn't checked</summary>
        <ul className="mt-1 list-disc space-y-0.5 pl-5">{w.notes.map((n, i) => <li key={i}>{n}</li>)}{!!w.queries?.length && <li>Searches run: {w.queries.join(' · ')}</li>}</ul></details>}
    </div>
  )
}

/** Write (or rewrite) the AI report for one candidate on one job. Always leaves something useful: if every AI provider
 * refuses, the server keeps an automatic summary from the match data and says why. Returns true when it changed anything. */
export async function writeAiReport(jobRef: string, candRef: string, refresh = false): Promise<boolean> {
  try {
    const r = await api<{ generated: number; score?: number | null; model?: string; error?: string; fallback?: boolean }>(`/api/jobs/${jobRef}/match/${candRef}/ai-report${refresh ? '?refresh=1' : ''}`, { method: 'POST' })
    if (r.generated) { toast(r.score != null ? `AI report written. AI score ${r.score}.` : 'AI report written.'); return true }
    toast(`${r.error || 'The AI did not answer.'}${r.fallback ? ' An automatic summary from the match data was saved meanwhile.' : ''}`)
    return !!r.fallback
  } catch (e: any) { toast(e.message); return false }
}

export function WriteReportButton({ jobRef, candRef, has, auto, onDone, size = 'sm', variant }: { jobRef: string; candRef: string; has: boolean; auto?: boolean; onDone: () => void; size?: 'sm' | 'md'; variant?: 'primary' | 'secondary' | 'subtle' | 'ghost' }) {
  const [busy, setBusy] = useState(false)
  return <Button size={size} variant={variant || (has && !auto ? 'ghost' : 'subtle')} icon={<Sparkles />} loading={busy}
    onClick={async () => { setBusy(true); const changed = await writeAiReport(jobRef, candRef, has && !auto); setBusy(false); if (changed) onDone() }}>
    {has && !auto ? 'Rewrite AI report' : auto ? 'Try the AI again' : 'Write AI report'}</Button>
}
