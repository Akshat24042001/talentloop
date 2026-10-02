import { Briefcase, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Alert, Badge, Button, Card, toast } from '../components/ui'
import { Empty, ErrorBox, ListSkeleton, PageHeader, useApi } from '../components/kit'
import { api } from '../lib/api'
import { useMe } from '../lib/session'
import { JOB_STATUS, VERDICT } from './labels'

interface Ov {
  jobs: { id: string; ref: string; title: string; department: string; status: string; top_n: number; location: string; ai_pending: number; scored: number
    shortlist: { candidate_id: string; ref: string; name: string; score: number; ai_score?: number | null; verdict?: string; knocked_out: boolean; applied: boolean }[] }[]
  pool: number; ai_pending: number; ai_budget: number; mock: boolean; model: string
}

export default function MatchCenter() {
  const me = useMe()
  const { data, error, reload } = useApi<Ov>('/api/match/overview')
  const [busy, setBusy] = useState(false)
  async function runAll() {
    setBusy(true)
    try { const r = await api('/api/match/ai-reports', { json: {} }); toast(r.error ? `${r.generated ? `${r.generated} written. ` : ''}${r.error}` : `${r.generated} AI report${r.generated === 1 ? '' : 's'} written${r.skipped_over_budget ? `, ${r.skipped_over_budget} left for the next run` : ''}`); reload() }
    catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  return (
    <>
      <PageHeader title="Match center" description="The shortlist for every open job, side by side. Ranking is free and instant; AI reports are written only for each shortlist."
        actions={me.can.manage_jobs && data && data.ai_pending > 0 && <Button variant="primary" icon={<Sparkles />} loading={busy} onClick={runAll}>Write {Math.min(data.ai_pending, data.ai_budget)} AI reports</Button>} />
      {error ? <ErrorBox error={error} retry={reload} /> : !data ? <ListSkeleton rows={4} avatar={false} /> : (
        <>
          <Card className="mb-4 grid grid-cols-2 divide-x divide-slate-100 text-center dark:divide-ink-800 sm:grid-cols-4">
            {[['Candidates ranked', data.pool], ['Open jobs', data.jobs.length], ['AI reports pending', data.ai_pending], ['Per-run AI limit', data.ai_budget]].map(([k, v]) => (
              <div key={k as string} className="p-4"><div className="tabular text-2xl font-semibold">{v}</div><div className="text-xs text-slate-500 dark:text-slate-400">{k}</div></div>))}
          </Card>
          {data.mock && <Alert className="mb-4" tone="info" icon={<Sparkles />}>Demo AI is on: match reports are simulated. Set LLM_MOCK=0 and an LLM key for real reports ({data.model}).</Alert>}
          {!data.jobs.length ? <Card><Empty icon={<Briefcase />} title="No open jobs">Publish a job to see its shortlist here.</Empty></Card> : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {data.jobs.map(j => (
                <Card key={j.id} className="flex flex-col">
                  <div className="flex items-start justify-between gap-2 border-b border-slate-100 p-4 dark:border-ink-800">
                    <div className="min-w-0"><a href={`/app/jobs/${j.ref}`} className="font-semibold hover:underline">{j.title}</a><div className="truncate text-xs text-slate-500">{j.department}{j.location ? ` · ${j.location}` : ''}</div></div>
                    <Badge tone={JOB_STATUS[j.status]?.tone}>{JOB_STATUS[j.status]?.label}</Badge>
                  </div>
                  <ol className="flex-1 divide-y divide-slate-100 dark:divide-ink-800">
                    {j.shortlist.length ? j.shortlist.map((s, i) => (
                      <li key={s.candidate_id}><a href={`/app/candidates/${s.ref}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-ink-850">
                        <span className="tabular w-4 text-xs font-bold text-slate-400">{i + 1}</span>
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">{s.name}</span>
                        {s.applied && <Badge tone="brand">Applied</Badge>}
                        {s.verdict ? <Badge tone={VERDICT[s.verdict]?.tone}>{VERDICT[s.verdict]?.label}</Badge> : <span className="text-[11px] text-slate-400">no report</span>}
                        <span className="tabular w-7 text-right text-sm font-bold">{Math.round(s.score)}</span>
                      </a></li>)) : <li className="p-4 text-sm text-slate-500">No matching candidates yet.</li>}
                  </ol>
                  <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5 text-xs text-slate-500 dark:border-ink-800">
                    <span>{j.scored} ranked · top {j.top_n} shortlisted</span>{j.ai_pending > 0 && <span className="text-amber-600">{j.ai_pending} report{j.ai_pending > 1 ? 's' : ''} pending</span>}
                  </div>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </>
  )
}
