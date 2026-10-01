import { Briefcase, Copy, MapPin, Plus, Search, Users } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Badge, Button, Card, Input, Select } from '../components/ui'
import { Empty, ErrorBox, Loading, PageHeader, useApi, Ago } from '../components/kit'
import { useMe } from '../lib/session'
import { JOB_STATUS } from './labels'

export interface JobRow {
  id: string; ref: string; title: string; department: string; status: string; top_n: number; location: string; employment_type: string; experience: string
  salary: string; created_at: number; updated_at: number; published_at?: number; matched_at?: number; priority?: string; openings?: number
  applications: number; new_applications: number; ai_reports: number; best_score?: number | null; permission: string
}

export default function Jobs() {
  const me = useMe()
  const { data, error, reload } = useApi<JobRow[]>('/api/jobs')
  const [q, setQ] = useState(''), [st, setSt] = useState(''), [dep, setDep] = useState('')
  const deps = useMemo(() => [...new Set((data || []).map(j => j.department).filter(Boolean))].sort(), [data])
  const rows = (data || []).filter(j => (!st || j.status === st) && (!dep || j.department === dep) && (!q || `${j.title} ${j.department} ${j.location}`.toLowerCase().includes(q.toLowerCase())))
  return (
    <>
      <PageHeader title="Jobs" description={me.can.manage_jobs ? 'Every role you are hiring for. Assign hiring managers from a job’s Team tab.' : 'The jobs you have been given access to.'}
        actions={me.can.manage_jobs && <>{me.org && <Button href={`/careers/${me.org.slug}`} target="_blank" icon={<Copy />}>Careers page</Button>}<Button variant="primary" href="/app/jobs/new" icon={<Plus />}>New job</Button></>} />
      <Card className="overflow-hidden">
        <div className="grid gap-2 border-b border-slate-100 p-4 dark:border-ink-800 sm:grid-cols-[2fr_1fr_1fr]">
          <div className="relative"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
            <Input type="search" aria-label="Search jobs" className="pl-9" placeholder="Search title, department or location" value={q} onChange={e => setQ(e.target.value)} /></div>
          <Select aria-label="Status" value={st} onChange={e => setSt(e.target.value)}><option value="">All statuses</option>{Object.entries(JOB_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</Select>
          <Select aria-label="Department" value={dep} onChange={e => setDep(e.target.value)}><option value="">All departments</option>{deps.map(d => <option key={d}>{d}</option>)}</Select>
        </div>
        {error ? <div className="p-5"><ErrorBox error={error} retry={reload} /></div> : !data ? <Loading /> : !rows.length ? (
          data.length ? <p className="p-10 text-center text-sm text-slate-500">No jobs match the filters.</p>
            : <Empty icon={<Briefcase />} title={me.can.manage_jobs ? 'No jobs yet' : 'No jobs assigned to you yet'} action={me.can.manage_jobs && <Button variant="primary" href="/app/jobs/new" icon={<Plus />}>Create your first job</Button>}>
              {me.can.manage_jobs ? 'Create a job, or load sample data from the dashboard.' : 'HR will give you access to the roles you are hiring for.'}</Empty>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-ink-800">
            {rows.map(j => (
              <li key={j.id}>
                <a href={`/app/jobs/${j.ref}`} className="grid gap-3 px-5 py-4 transition-colors hover:bg-slate-50/80 dark:hover:bg-ink-850 md:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))_auto] md:items-center">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2"><span className="truncate font-semibold text-slate-900 dark:text-white">{j.title}</span>
                      <Badge tone={JOB_STATUS[j.status]?.tone}>{JOB_STATUS[j.status]?.label}</Badge>
                      {j.priority === 'Urgent' || j.priority === 'High' ? <Badge tone="danger">{j.priority}</Badge> : null}
                      {j.permission === 'edit' && <Badge tone="violet">You can edit</Badge>}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-slate-500 dark:text-slate-400"><span>{j.department}</span>{j.location && <span className="inline-flex items-center gap-1"><MapPin className="size-3" />{j.location}</span>}<span>{j.experience}</span></div>
                  </div>
                  <div className="text-sm"><div className="tabular font-semibold">{j.applications}</div><div className="text-xs text-slate-500 dark:text-slate-400">applicants{j.new_applications ? <span className="text-emerald-600"> · {j.new_applications} new</span> : ''}</div></div>
                  <div className="text-sm"><div className="tabular font-semibold">{j.best_score != null ? Math.round(j.best_score) : '-'}</div><div className="text-xs text-slate-500 dark:text-slate-400">best match</div></div>
                  <div className="text-sm"><div className="tabular font-semibold">{j.ai_reports}/{j.top_n}</div><div className="text-xs text-slate-500 dark:text-slate-400">AI reports</div></div>
                  <div className="text-xs text-slate-500 dark:text-slate-400 md:text-right"><Users className="mr-1 inline size-3" />updated <Ago ts={j.updated_at} /></div>
                </a>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  )
}
