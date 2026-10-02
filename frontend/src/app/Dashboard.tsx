import { ArrowRight, Briefcase, CircleAlert, Plus, Upload, UserPlus, Users, Video } from 'lucide-react'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Stat } from '../components/ui'
import { Ago, CardsSkeleton, ErrorBox, ListSkeleton, PageHeader, useApi } from '../components/kit'
import { healthProblems, useHealth } from '../lib/health'
import { useMe } from '../lib/session'
import { ACTION_LABEL, actor } from './labels'

interface Dash {
  jobs: { open: number; draft: number; paused: number; closed: number }; candidates: number; new_candidates_7d: number | null
  applications: number; applications_7d: number; applications_14d: number[]; pipeline: { id: string; label: string; count: number }[]
  interviews: { total: number; completed: number; in_progress: number }; ai_reports: number
  attention: { job_id: string; job_ref?: string; title: string; reason: string }[]
  activity: { id: string; action: string; detail: string; at: number; job_id?: string; job_ref?: string; job?: string; candidate_id?: string; user?: string }[]
}

export default function Dashboard() {
  const me = useMe()
  const { data: d, error, reload } = useApi<Dash>('/api/dashboard')
  const h = useHealth()
  const first = d && d.jobs.open + d.jobs.draft + d.jobs.paused + d.jobs.closed === 0 && d.candidates === 0
  const problems = h ? healthProblems(h) : []
  const max14 = Math.max(1, ...(d?.applications_14d || [0]))
  const maxPipe = Math.max(1, ...(d?.pipeline.map(p => p.count) || [0]))
  return (
    <>
      <PageHeader title={`Good ${new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 17 ? 'afternoon' : 'evening'}, ${(me.user.name || '').split(' ')[0] || 'there'}`}
        description={`${me.org?.name} · ${me.role_label}`}
        actions={me.can.manage_jobs && <><Button href="/app/candidates?upload=1" icon={<Upload />}>Upload resumes</Button><Button variant="primary" href="/app/jobs/new" icon={<Plus />}>New job</Button></>} />
      {problems.length > 0 && me.platform_admin && <div className="mb-5 space-y-2">{problems.map(p => <Alert key={p} tone="warning" icon={<CircleAlert />}>{p}</Alert>)}</div>}
      {error ? <ErrorBox error={error} retry={reload} /> : !d ? <><CardsSkeleton /><div className="mt-5"><ListSkeleton rows={4} avatar={false} /></div></> : (
        <>
          {first && me.can.manage_jobs && (
            <Card className="mb-5 overflow-hidden">
              <div className="grid gap-6 bg-gradient-to-br from-brand-50 to-violet-50 p-6 dark:from-brand-500/10 dark:to-violet-500/10 ">
                <div>
                  <h2 className="text-lg font-semibold">Welcome to TalentLoop</h2>
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Three steps to your first shortlist.</p>
                  <ol className="mt-4 space-y-2 text-sm">
                    <li className="flex items-center gap-2"><Briefcase className="size-4 text-brand-600 dark:text-brand-400" /><a className="font-medium hover:underline" href="/app/jobs/new">Create a job</a> <span className="text-slate-500">(only 7 fields are required)</span></li>
                    <li className="flex items-center gap-2"><Users className="size-4 text-brand-600 dark:text-brand-400" /><a className="font-medium hover:underline" href="/app/candidates?upload=1">Upload resumes</a> <span className="text-slate-500">or share your careers page</span></li>
                    <li className="flex items-center gap-2"><UserPlus className="size-4 text-brand-600 dark:text-brand-400" /><a className="font-medium hover:underline" href="/app/team">Invite your team</a> <span className="text-slate-500">HR and hiring managers</span></li>
                  </ol>
                </div>
              </div>
            </Card>
          )}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <a href="/app/jobs"><Stat label="Open jobs" value={d.jobs.open} sub={`${d.jobs.draft} draft · ${d.jobs.paused} paused`} icon={<Briefcase />} /></a>
            <a href="/app/candidates"><Stat label="Candidates" value={d.candidates} sub={d.new_candidates_7d != null ? `${d.new_candidates_7d} new this week` : 'on your jobs'} icon={<Users />} /></a>
            <Stat label="Applications" value={d.applications} sub={`${d.applications_7d} in the last 7 days`} icon={<ArrowRight />} />
            <a href="/app/interviews"><Stat label="AI interviews" value={d.interviews.total} sub={`${d.interviews.completed} completed · ${d.interviews.in_progress} live`} icon={<Video />} /></a>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Pipeline" description="Applications by stage across your jobs" />
              <CardBody>
                <div className="space-y-2.5">
                  {d.pipeline.map(p => (
                    <div key={p.id} className="grid grid-cols-[96px_1fr_40px] items-center gap-3 text-sm">
                      <span className="text-slate-600 dark:text-slate-300">{p.label}</span>
                      <span className="relative h-3 rounded-r-[4px] bg-[var(--track)]"><i className="absolute inset-y-0 left-0 min-w-[2px] rounded-r-[4px]" style={{ width: `${(p.count / maxPipe) * 100}%`, background: p.id === 'rejected' ? 'var(--status-critical)' : p.id === 'hired' ? 'var(--status-good)' : 'var(--series-1)' }} /></span>
                      <span className="tabular text-right font-semibold">{p.count}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-6">
                  <div className="mb-2 flex justify-between text-xs text-slate-500 dark:text-slate-400"><span>Applications, last 14 days</span><span>{d.ai_reports} AI match reports written</span></div>
                  <div className="flex h-16 items-end gap-1">
                    {d.applications_14d.map((n, i) => <span key={i} title={`${n} application${n === 1 ? '' : 's'}`} className="flex-1 rounded-t-[3px] bg-[var(--series-1)]" style={{ height: `${Math.max(4, (n / max14) * 100)}%`, opacity: n ? 1 : 0.25 }} />)}
                  </div>
                </div>
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Needs attention" />
              <CardBody className="pt-3">
                {!d.attention.length ? <p className="text-sm text-slate-500 dark:text-slate-400">All clear. Nothing waiting on you.</p> : (
                  <ul className="space-y-3">{d.attention.map(a => (
                    <li key={a.job_id}><a href={`/app/jobs/${a.job_ref || a.job_id}`} className="block rounded-xl p-3 ring-1 ring-slate-200/70 hover:bg-slate-50 dark:ring-ink-700 dark:hover:bg-ink-850">
                      <div className="text-sm font-semibold">{a.title}</div><div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{a.reason}</div></a></li>
                  ))}</ul>
                )}
              </CardBody>
            </Card>
          </div>
          <Card className="mt-4">
            <CardHeader title="Recent activity" />
            <CardBody className="pt-3">
              {!d.activity.length ? <p className="text-sm text-slate-500">No activity yet.</p> : (
                <ul className="divide-y divide-slate-100 dark:divide-ink-800">{d.activity.map(a => (
                  <li key={a.id} className="flex flex-wrap items-baseline justify-between gap-2 py-2.5 text-sm">
                    <span className="min-w-0"><Badge tone="neutral">{ACTION_LABEL[a.action] || a.action}</Badge> <span className="text-slate-700 dark:text-slate-200">{a.detail}</span>
                      {a.job && a.job_id && <> · <a className="text-brand-600 hover:underline dark:text-brand-300" href={`/app/jobs/${a.job_ref || a.job_id}`}>{a.job}</a></>}</span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">{actor(a)} · <Ago ts={a.at} /></span>
                  </li>
                ))}</ul>
              )}
            </CardBody>
          </Card>
        </>
      )}
    </>
  )
}
