// The full fit report for one candidate and one job: scores, how the fit score is built, requirement by
// requirement comparison, skills, and the AI report. Downloadable as a PDF.
import { CircleCheck, CircleDashed, CircleMinus, CircleX, Download, Printer, Sparkles, Video } from 'lucide-react'
import { Alert, Badge, Button, Card, CardBody, CardHeader, cn } from '../components/ui'
import { BackLink, ErrorBox, PageHeader, PageSkeleton, ScoreRing, useApi } from '../components/kit'
import { when } from '../lib/format'
import { useMe } from '../lib/session'
import { VERDICT } from './labels'

interface Signal { key: string; label: string; weight: number; score: number; points: number }
interface Row { label: string; required: string; candidate: string; note: string; status: 'good' | 'partial' | 'gap' | 'info' }
interface Report {
  job: { id: string; ref: string; title: string; department?: string; status: string }
  candidate: { id: string; ref: string; name: string; headline?: string; email?: string; location?: string; years?: number | null; current_company?: string }
  score: number; knocked_out: string[]; signals: Signal[]; skills: { skill: string; kind: string; status: 'matched' | 'related' | 'missing' }[]
  comparison: Row[]; rank: number | null; ranked: number; ai_score: number | null; ai_at: number | null
  ai: { verdict?: string; summary?: string; strengths?: string[]; gaps?: string[]; risks?: string[]; interview_questions?: string[] } | null
  application: { ref: string; stage: string } | null
}

const STATUS = {
  good: { label: 'Good', cls: 'bg-emerald-50 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200', icon: CircleCheck },
  partial: { label: 'Partial', cls: 'bg-amber-50 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200', icon: CircleMinus },
  gap: { label: 'Gap', cls: 'bg-red-50 text-red-800 dark:bg-red-500/15 dark:text-red-200', icon: CircleX },
  info: { label: 'Not scored', cls: 'bg-slate-100 text-slate-600 dark:bg-ink-800 dark:text-slate-300', icon: CircleDashed },
}
const SKILL = {
  matched: { label: 'Has it', cls: 'bg-emerald-50 text-emerald-800 ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-200 dark:ring-emerald-500/30', icon: CircleCheck },
  related: { label: 'Related', cls: 'bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-500/15 dark:text-amber-200 dark:ring-amber-500/30', icon: CircleMinus },
  missing: { label: 'Missing', cls: 'bg-red-50 text-red-800 ring-red-200 dark:bg-red-500/15 dark:text-red-200 dark:ring-red-500/30', icon: CircleX },
}

export default function MatchReport({ jobId, candId }: { jobId: string; candId: string }) {
  const me = useMe()
  const { data: d, error, reload } = useApi<Report>(`/api/jobs/${jobId}/match/${candId}`)
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!d) return <PageSkeleton />
  const v = d.ai?.verdict ? VERDICT[d.ai.verdict] : null
  const must = d.skills.filter(s => s.kind === 'Must-have'), nice = d.skills.filter(s => s.kind !== 'Must-have')
  const mustHit = must.filter(s => s.status === 'matched').length
  const pdf = `/api/jobs/${jobId}/match/${candId}?format=pdf`
  return (
    <>
      <PageHeader back={<BackLink href={`/app/jobs/${d.job.ref}`}>{d.job.title}</BackLink>}
        title={<span>{d.candidate.name} <span className="font-normal text-slate-500 dark:text-slate-400">for</span> {d.job.title}</span>}
        description={[d.candidate.headline, d.candidate.current_company, d.candidate.location, d.candidate.years != null ? `${d.candidate.years} years` : ''].filter(Boolean).join(' · ')}
        actions={<>
          <Button icon={<Printer />} onClick={() => print()}>Print</Button>
          <Button variant="primary" icon={<Download />} href={pdf} download>Download PDF</Button>
        </>} />

      {d.knocked_out.length > 0 && <Alert tone="danger" className="mb-5" title="Screened out by the job's rules">{d.knocked_out.join('; ')}</Alert>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="flex items-center gap-4 p-4"><ScoreRing value={d.score} size={64} label="Fit score" /><div><div className="text-xs text-slate-500 dark:text-slate-400">Fit score</div><div className="text-sm font-semibold">Skills, experience, location, notice</div></div></Card>
        <Card className="flex items-center gap-4 p-4"><ScoreRing value={d.ai_score} size={64} label="AI score" /><div><div className="text-xs text-slate-500 dark:text-slate-400">AI score</div><div className="text-sm font-semibold">{d.ai_score != null ? 'Reads the whole resume' : 'Not run yet'}</div></div></Card>
        <Card className="p-4"><div className="text-xs text-slate-500 dark:text-slate-400">Shortlist rank</div><div className="mt-1 text-2xl font-semibold tabular">{d.rank ? `#${d.rank}` : '-'}<span className="text-sm font-normal text-slate-500 dark:text-slate-400">{d.rank ? ` of ${d.ranked}` : ' not ranked'}</span></div></Card>
        <Card className="p-4"><div className="text-xs text-slate-500 dark:text-slate-400">Verdict</div><div className="mt-1.5">{v ? <Badge tone={v.tone}>{v.label}</Badge> : <span className="text-sm text-slate-500 dark:text-slate-400">After the AI report</span>}</div>
          <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">Must-haves: <b className="text-slate-800 dark:text-slate-100">{mustHit}/{must.length}</b>{d.application ? <> · <a className="font-medium text-brand-600 hover:underline dark:text-brand-400" href={`/app/jobs/${d.job.ref}?tab=pipeline&app=${d.application.ref}`}>in pipeline</a></> : ''}</div></Card>
      </div>

      {d.ai?.summary && (
        <Card className="mt-5 bg-gradient-to-br from-brand-50/80 to-violet-50/60 p-5 ring-brand-100 dark:from-brand-500/10 dark:to-violet-500/10 dark:ring-brand-500/20">
          <div className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="size-4 text-brand-600 dark:text-brand-300" />AI summary{d.ai_at && <span className="font-normal text-slate-500 dark:text-slate-400">· {when(d.ai_at)}</span>}</div>
          <p className="mt-2 leading-relaxed text-slate-700 dark:text-slate-200">{d.ai.summary}</p>
        </Card>)}

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <Card><CardHeader title="How the fit score is built" description="Each signal's score, times its weight (set in Settings, Matching), adds up to the fit score." />
          <CardBody>
            <div className="flex h-4 overflow-hidden rounded-full bg-[var(--track)]" role="img" aria-label={`Fit score ${Math.round(d.score)} of 100`}>
              {d.signals.map((s, i) => <span key={s.key} title={`${s.label}: ${s.points} points`} style={{ width: `${s.points}%`, opacity: 1 - i * 0.15 }} className="h-full bg-[var(--series-1)] first:rounded-l-full [&+span]:border-l [&+span]:border-white/70 dark:[&+span]:border-ink-900/70" />)}
            </div>
            <div className="mt-1 flex justify-between text-[11px] text-slate-500 dark:text-slate-400"><span>0</span><span className="font-semibold text-slate-700 dark:text-slate-200">{Math.round(d.score)} of 100</span><span>100</span></div>
            <table className="mt-4 w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-500 dark:text-slate-400"><th className="pb-2 font-medium">Signal</th><th className="pb-2 font-medium">Score</th><th className="pb-2 text-right font-medium">Weight</th><th className="pb-2 text-right font-medium">Points</th></tr></thead>
              <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{d.signals.map((s, i) => (
                <tr key={s.key}>
                  <td className="py-2.5 pr-3"><span className="flex items-center gap-2"><i className="size-2.5 rounded-sm bg-[var(--series-1)]" style={{ opacity: 1 - i * 0.15 }} />{s.label}</span></td>
                  <td className="w-2/5 py-2.5 pr-3"><span className="flex items-center gap-2"><span className="relative h-2 flex-1 rounded-full bg-[var(--track)]"><i className="absolute inset-y-0 left-0 rounded-full bg-[var(--series-1)]" style={{ width: `${s.score}%` }} /></span><span className="tabular w-9 text-right text-xs">{s.score}%</span></span></td>
                  <td className="tabular py-2.5 text-right text-slate-500 dark:text-slate-400">{s.weight}%</td>
                  <td className="tabular py-2.5 text-right font-semibold">{s.points}</td>
                </tr>))}</tbody>
            </table>
          </CardBody></Card>

        <Card><CardHeader title="Skills" description={`${mustHit} of ${must.length} must-haves, ${nice.filter(s => s.status === 'matched').length} of ${nice.length} nice-to-haves`} />
          <CardBody className="space-y-4">
            {[['Must-have', must], ['Nice-to-have', nice]].map(([title, list]) => (list as Report['skills']).length > 0 && (
              <div key={title as string}>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{title as string}</div>
                <div className="flex flex-wrap gap-1.5">{(list as Report['skills']).map(s => { const k = SKILL[s.status]; return (
                  <span key={s.skill} title={k.label} className={cn('inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium ring-1 ring-inset', k.cls)}><k.icon className="size-3.5" />{s.skill}</span>) })}</div>
              </div>))}
            <div className="flex flex-wrap gap-3 border-t border-slate-100 pt-3 text-[11px] text-slate-500 dark:border-ink-800 dark:text-slate-400">
              {Object.values(SKILL).map(k => <span key={k.label} className="flex items-center gap-1"><k.icon className="size-3" />{k.label}</span>)}</div>
          </CardBody></Card>
      </div>

      <Card className="mt-5 overflow-x-auto"><CardHeader title="Requirements vs candidate" description="What the job asks for, next to what the candidate has." />
        <table className="w-full min-w-[560px] text-sm">
          <thead><tr className="border-y border-slate-100 bg-slate-50/70 text-left text-xs text-slate-500 dark:border-ink-800 dark:bg-ink-850 dark:text-slate-400">
            <th className="px-5 py-2.5 font-medium">Requirement</th><th className="px-3 py-2.5 font-medium">Job asks for</th><th className="px-3 py-2.5 font-medium">Candidate</th><th className="px-5 py-2.5 text-right font-medium">Fit</th></tr></thead>
          <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{d.comparison.map(r => { const s = STATUS[r.status]; return (
            <tr key={r.label}>
              <td className="px-5 py-3 font-medium">{r.label}</td>
              <td className="px-3 py-3 text-slate-600 dark:text-slate-300">{r.required}</td>
              <td className="px-3 py-3">{r.candidate}{r.note && !r.candidate.includes(r.note) && <span className="block text-xs text-slate-500 dark:text-slate-400">{r.note}</span>}</td>
              <td className="px-5 py-3 text-right"><span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold', s.cls)}><s.icon className="size-3.5" />{s.label}</span></td>
            </tr>) })}</tbody>
        </table></Card>

      {d.ai ? (
        <div className="mt-5 grid gap-5 md:grid-cols-2">
          <Points title="Strengths" items={d.ai.strengths} tone="emerald" />
          <Points title="Gaps" items={d.ai.gaps} tone="amber" />
          {!!d.ai.risks?.length && <Points title="Risks" items={d.ai.risks} tone="red" />}
          <Card><CardHeader title="Ask in the interview" description="Questions that test the gaps." /><CardBody>
            <ol className="space-y-2">{(d.ai.interview_questions || []).map((q, i) => <li key={i} className="flex gap-3 text-sm"><span className="grid size-6 shrink-0 place-items-center rounded-full bg-brand-50 text-xs font-bold text-brand-700 dark:bg-brand-500/15 dark:text-brand-200">{i + 1}</span>{q}</li>)}</ol>
            {me.can.manage_jobs && <Button className="mt-4" size="sm" icon={<Video />} href={`/app/interviews/new?job=${d.job.ref}&candidate=${d.candidate.ref}${d.application ? `&application=${d.application.ref}` : ''}`}>Send an AI interview</Button>}
          </CardBody></Card>
        </div>
      ) : <Card className="mt-5"><CardBody><p className="text-sm text-slate-600 dark:text-slate-300">No AI report yet. AI reports are written for each job's shortlist from the Match center; the fit score above is always available.</p></CardBody></Card>}
    </>
  )
}

function Points({ title, items, tone }: { title: string; items?: string[]; tone: 'emerald' | 'amber' | 'red' }) {
  if (!items?.length) return null
  const dot = { emerald: 'bg-emerald-500', amber: 'bg-amber-500', red: 'bg-red-500' }[tone]
  return (
    <Card><CardHeader title={title} /><CardBody>
      <ul className="space-y-2">{items.map((x, i) => <li key={i} className="flex gap-2.5 text-sm leading-relaxed"><span className={cn('mt-2 size-1.5 shrink-0 rounded-full', dot)} />{x}</li>)}</ul>
    </CardBody></Card>
  )
}
