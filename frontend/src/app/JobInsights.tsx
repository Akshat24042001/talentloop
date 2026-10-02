// A job's insights: does the AI agree with your team (calibration), and do any candidates' answers look copied
// from each other (cross-candidate integrity scan). Both are evidence for a person to read, never automatic decisions.
import { Copy, Scale } from 'lucide-react'
import { Alert, Badge, Card, CardBody, CardHeader } from '../components/ui'
import { Empty, Loading, useApi } from '../components/kit'
import { SHORT_LABEL, type RoundType } from './flow/types'

interface Person { application_id: string; name: string; email: string; stage: string }
interface Pair { a: Person; b: Person; kind: 'interview' | 'live_task' | 'test' | 'contact'; round: string; score: number; detail: string; sample: string }
interface Scan { pairs: Pair[]; compared: Record<string, number>; applications: number }
interface Dis { application_id: string; name: string; score: number | null; ai: string; decision: string; by: string; reason: string }
interface CalRound {
  round_id: string; name: string; type: RoundType; mark: number; mark_source: string; decided: number; compared: number; unsure: number; agree: number
  agreement: number | null; avg_score_passed: number | null; avg_score_rejected: number | null; note: string; disagreements: Dis[]
}
const KIND: Record<Pair['kind'], string> = { interview: 'AI interview answers', live_task: 'Live task work', test: 'Test answers', contact: 'Contact details' }

export default function JobInsights({ jobId, jobRef }: { jobId: string; jobRef: string }) {
  const { data: cal } = useApi<{ rounds: CalRound[] }>(`/api/jobs/${jobId}/calibration`)
  const { data: scan } = useApi<Scan>(`/api/jobs/${jobId}/integrity-scan`)
  const link = (aid: string) => `/app/jobs/${jobRef}?tab=pipeline&app=${aid}`
  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader title={<span className="flex items-center gap-2"><Scale className="size-4 text-brand-600 dark:text-brand-400" />AI vs your team</span>}
          description="For each AI-scored round: how often the people deciding agreed with the AI. Automatic and top-N decisions are left out, since they follow the score by design." />
        <CardBody className="pt-1">
          {!cal ? <Loading /> : !cal.rounds.length ? <p className="text-sm text-slate-500 dark:text-slate-400">This flow has no AI-scored rounds.</p> : (
            <div className="grid gap-4">{cal.rounds.map(r => (
              <div key={r.round_id} className="rounded-xl p-4 ring-1 ring-slate-200 dark:ring-ink-700">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div className="font-semibold">{r.name} <span className="text-xs font-normal text-slate-500 dark:text-slate-400">{SHORT_LABEL[r.type]}</span></div>
                  {r.agreement != null && <Badge tone={r.agreement >= 80 ? 'success' : r.agreement >= 65 ? 'warning' : 'danger'}>{r.agreement}% agree</Badge>}
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                  <Stat k="Decided by people" v={r.decided} />
                  <Stat k="Agreed / compared" v={r.compared ? `${r.agree} / ${r.compared}` : '-'} />
                  <Stat k="Avg score, passed" v={r.avg_score_passed ?? '-'} />
                  <Stat k="Avg score, rejected" v={r.avg_score_rejected ?? '-'} />
                </dl>
                <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">AI "pass" means a score of {r.mark_source === 'pass mark' ? `${r.mark} or more (your pass mark)` : 'at least 50 (no pass mark set)'}{r.type === 'ai_interview' ? '; for interviews, the Strong / No recommendation (Maybe is not counted)' : ''}.</p>
                <p className="mt-2 text-sm">{r.note}</p>
                {r.disagreements.length > 0 && <details className="mt-2"><summary className="cursor-pointer text-sm font-medium">Where they disagreed most ({r.disagreements.length})</summary>
                  <ul className="mt-2 divide-y divide-slate-100 text-sm dark:divide-ink-800">{r.disagreements.map(d => (
                    <li key={d.application_id} className="flex flex-wrap items-center gap-2 py-2">
                      <a className="font-medium text-brand-600 hover:underline dark:text-brand-400" href={link(d.application_id)}>{d.name || 'Candidate'}</a>
                      <span className="tabular text-slate-500 dark:text-slate-400">score {d.score ?? '-'}</span>
                      <Badge tone={d.ai === 'pass' ? 'success' : 'danger'}>AI: {d.ai}</Badge><Badge tone={d.decision === 'pass' ? 'success' : 'danger'}>{d.by || 'Team'}: {d.decision}</Badge>
                      {d.reason && <span className="w-full text-xs text-slate-500 dark:text-slate-400">"{d.reason}"</span>}
                    </li>))}</ul></details>}
              </div>))}</div>)}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={<span className="flex items-center gap-2"><Copy className="size-4 text-brand-600 dark:text-brand-400" />Copied answers across candidates</span>}
          description="Compares candidates of this job with each other: the same wording in interview answers or live-task work, the same wrong options in tests, and one phone number on two records." />
        <CardBody className="pt-1">
          {!scan ? <Loading /> : <>
            <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">Compared so far: {Object.entries(scan.compared).map(([k, n]) => `${KIND[k as Pair['kind']] || k} of ${n} candidate${n === 1 ? '' : 's'}`).join(', ') || 'nothing yet'} ({scan.applications} applications in total).</p>
            {!scan.pairs.length ? <Empty icon={<Copy />} title="No look-alike pairs found">Nothing two candidates shared beyond what most candidates say anyway.</Empty> : <>
              <Alert tone="info" className="mb-3">A match is a reason to look, not proof. Classmates can learn from the same notes; check the evidence and the recordings before acting.</Alert>
              <ul className="grid gap-3">{scan.pairs.map((p, i) => (
                <li key={i} className="rounded-xl p-3 ring-1 ring-amber-200 dark:ring-amber-500/30">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <a className="font-semibold text-brand-600 hover:underline dark:text-brand-400" href={link(p.a.application_id)}>{p.a.name || p.a.email}</a>
                    <span className="text-slate-400">and</span>
                    <a className="font-semibold text-brand-600 hover:underline dark:text-brand-400" href={link(p.b.application_id)}>{p.b.name || p.b.email}</a>
                    <Badge tone="warning">{KIND[p.kind]}</Badge><span className="text-xs text-slate-500 dark:text-slate-400">{p.round}</span>
                  </div>
                  <p className="mt-1 text-sm">{p.detail}</p>
                  {p.sample && <p className="mt-1 rounded-lg bg-slate-50 px-2.5 py-1.5 font-mono text-xs text-slate-700 dark:bg-ink-850 dark:text-slate-200">{p.kind === 'test' ? 'Questions: ' : 'Shared: "'}{p.sample}{p.kind === 'test' ? '' : '"'}</p>}
                </li>))}</ul>
            </>}
          </>}
        </CardBody>
      </Card>
    </div>
  )
}

function Stat({ k, v }: { k: string; v: string | number }) {
  return <div><dt className="text-xs text-slate-500 dark:text-slate-400">{k}</dt><dd className="tabular text-lg font-semibold">{v}</dd></div>
}
