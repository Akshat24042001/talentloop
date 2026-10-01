// Hiring reports (funnel, time to hire, drop-off by round, sources and colleges) and the audit log.
import { Download, ScrollText } from 'lucide-react'
import { useState } from 'react'
import { Card, CardBody, CardHeader, Input, Select } from '../components/ui'
import { Empty, ErrorBox, Loading, PageHeader, Pager, useApi } from '../components/kit'
import { HBarChart } from '../components/charts'
import { when } from '../lib/format'
import { ACTION_LABEL, actor } from './labels'

interface Group { name: string; applications: number; screened: number; interviewed: number; selected: number; avg_score: number | null; selection_rate: number | null }
interface Rep {
  total: number; funnel: { key: string; label: string; n: number }[]; job: { id: string; title: string } | null
  rounds: { key: string; label: string; type: string; entered: number; completed: number; passed: number; failed: number; missed: number; completion_rate: number | null; pass_rate: number | null; avg_score: number | null }[]
  time_to_hire: { n: number; median: number | null; average: number | null }; time_to_reject: { n: number; median: number | null; average: number | null }
  by_source: Group[]; by_college: Group[]
}
const SOURCE: Record<string, string> = { careers: 'Careers page', campus: 'Campus drive', talent_pool: 'Talent pool', upload: 'Uploaded', bulk: 'Bulk upload', sourced: 'Sourced', imap: 'Mailbox', demo: 'Sample' }

export function Reports() {
  const [job, setJob] = useState(''), [days, setDays] = useState('90')
  const { data: jobs } = useApi<{ id: string; title: string }[]>('/api/jobs')
  const { data, error, reload } = useApi<Rep>(`/api/reports?job=${job}&days=${days}`)
  if (error) return <ErrorBox error={error} retry={reload} />
  const top = data?.funnel[0]?.n || 0
  return (
    <>
      <PageHeader title="Reports" description="Where candidates come from, where they drop off and how long hiring takes."
        actions={<><Select aria-label="Job" value={job} onChange={e => setJob(e.target.value)}><option value="">All jobs</option>{jobs?.map(j => <option key={j.id} value={j.id}>{j.title}</option>)}</Select>
          <Select aria-label="Period" value={days} onChange={e => setDays(e.target.value)}><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="365">Last 12 months</option><option value="0">All time</option></Select></>} />
      {!data ? <Loading /> : !data.total ? <Card><Empty title="No applications in this period">Reports fill in as candidates apply and move through your flows.</Empty></Card> : (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card><CardHeader title="Funnel" description={`${data.total} applications`} /><CardBody>
            <HBarChart valueLabel="Candidates" max={top} rows={data.funnel.map(f => ({ key: f.key, label: f.label, value: f.n, display: String(f.n), sub: top ? `${Math.round((f.n / top) * 100)}% of applicants` : undefined }))} />
          </CardBody></Card>
          <Card><CardHeader title="Time to decision" description="From application to the final decision." /><CardBody className="grid grid-cols-2 gap-4">
            {([['Selected', data.time_to_hire], ['Not progressed', data.time_to_reject]] as const).map(([l, t]) => (
              <div key={l} className="rounded-xl bg-slate-50 p-4 dark:bg-ink-850"><div className="text-sm text-slate-500">{l}</div>
                <div className="tabular mt-1 text-2xl font-semibold">{t.median != null ? `${t.median} days` : '-'}</div>
                <div className="text-xs text-slate-500">median{t.average != null ? ` · average ${t.average} days` : ''} · {t.n} candidate(s)</div></div>))}
          </CardBody></Card>
          <Card className="lg:col-span-2"><CardHeader title="Drop-off by round" description={data.job ? `Rounds of ${data.job.title}` : 'All jobs, by round type'} /><CardBody className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm"><thead className="text-left text-xs uppercase tracking-wide text-slate-500"><tr><th className="py-2">Round</th><th>Reached</th><th>Completed</th><th>Passed</th><th>Not progressed</th><th>Missed deadline / no-show</th><th>Avg score</th></tr></thead>
              <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{data.rounds.map(r => (
                <tr key={r.key}><td className="py-2 font-medium">{r.label}</td><td className="tabular">{r.entered}</td>
                  <td className="tabular">{r.completed}{r.completion_rate != null && <span className="text-slate-500"> ({r.completion_rate}%)</span>}</td>
                  <td className="tabular">{r.passed}{r.pass_rate != null && <span className="text-slate-500"> ({r.pass_rate}%)</span>}</td>
                  <td className="tabular">{r.failed}</td><td className="tabular">{r.missed}</td><td className="tabular">{r.avg_score ?? '-'}</td></tr>))}</tbody></table>
          </CardBody></Card>
          <GroupCard title="By source" rows={data.by_source} label={n => SOURCE[n] || n} />
          <GroupCard title="By college" rows={data.by_college} label={n => n} empty="No college data yet (campus drives and resumes with a college fill this in)." />
        </div>)}
    </>
  )
}

function GroupCard({ title, rows, label, empty }: { title: string; rows: Group[]; label: (n: string) => string; empty?: string }) {
  function csv() {
    const head = ['Name', 'Applications', 'Passed screening', 'Interviewed', 'Selected', 'Selection rate %', 'Avg score']
    const lines = [head, ...rows.map(r => [label(r.name), r.applications, r.screened, r.interviewed, r.selected, r.selection_rate ?? '', r.avg_score ?? ''])]
    const body = lines.map(l => l.map(x => `"${String(x).replace(/"/g, '""')}"`).join(',')).join('\n')
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([body], { type: 'text/csv' })); a.download = `${title.toLowerCase().replace(/\s+/g, '-')}.csv`; a.click()
  }
  return (
    <Card><CardHeader title={title} action={rows.length > 0 && <button className="inline-flex items-center gap-1 text-sm font-medium text-brand-600" onClick={csv}><Download className="size-4" />CSV</button>} />
      <CardBody className="overflow-x-auto">{!rows.length ? <p className="text-sm text-slate-500">{empty || 'No data.'}</p> : (
        <table className="w-full text-sm"><thead className="text-left text-xs uppercase tracking-wide text-slate-500"><tr><th className="py-2">Name</th><th>Applied</th><th>Interviewed</th><th>Selected</th><th>Rate</th><th>Avg score</th></tr></thead>
          <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{rows.map(r => <tr key={r.name}><td className="max-w-48 truncate py-2 font-medium">{label(r.name)}</td><td className="tabular">{r.applications}</td><td className="tabular">{r.interviewed}</td>
            <td className="tabular">{r.selected}</td><td className="tabular">{r.selection_rate != null ? `${r.selection_rate}%` : '-'}</td><td className="tabular">{r.avg_score ?? '-'}</td></tr>)}</tbody></table>)}
      </CardBody></Card>
  )
}

interface Audit { total: number; items: { id: string; action: string; detail: string; at: number; job?: string | null; job_ref?: string | null; user?: string | null }[]; actions: string[]; users: { id: string; name: string; email: string }[] }
export function AuditLog() {
  const [f, setF] = useState({ action: '', user: '', q: '' }), [page, setPage] = useState(1)
  const { data, error, reload } = useApi<Audit>(`/api/audit?${new URLSearchParams({ ...f, page: String(page) })}`)
  if (error) return <ErrorBox error={error} retry={reload} />
  return (
    <>
      <PageHeader title="Audit log" description="Every change made in this workspace: who did it and when. Kept for compliance reviews." />
      <Card className="mb-3 flex flex-wrap gap-2 p-3">
        <Input type="search" aria-label="Search details" className="min-w-48 flex-1" placeholder="Search details" value={f.q} onChange={e => { setF({ ...f, q: e.target.value }); setPage(1) }} />
        <Select aria-label="Action" className="w-48" value={f.action} onChange={e => { setF({ ...f, action: e.target.value }); setPage(1) }}><option value="">All actions</option>{data?.actions.map(a => <option key={a} value={a}>{ACTION_LABEL[a] || a}</option>)}</Select>
        <Select aria-label="Person" className="w-48" value={f.user} onChange={e => { setF({ ...f, user: e.target.value }); setPage(1) }}><option value="">Everyone</option><option value="system">System / candidates</option>{data?.users.map(u => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}</Select>
      </Card>
      {!data ? <Loading /> : !data.items.length ? <Card><Empty icon={<ScrollText />} title="Nothing recorded">Try other filters.</Empty></Card> : <>
        <Card className="overflow-x-auto"><table className="w-full min-w-[640px] text-sm"><thead className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-ink-800"><tr><th className="px-4 py-2.5">When</th><th>Who</th><th>Action</th><th>Details</th></tr></thead>
          <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{data.items.map(a => (
            <tr key={a.id} className="align-top"><td className="whitespace-nowrap px-4 py-2.5 text-slate-500">{when(a.at)}</td><td className="py-2.5 pr-3">{actor(a)}</td><td className="py-2.5 pr-3 font-medium">{ACTION_LABEL[a.action] || a.action}</td>
              <td className="py-2.5 pr-4">{a.detail}{a.job && a.job_ref && <> · <a className="text-brand-600 hover:underline" href={`/app/jobs/${a.job_ref}`}>{a.job}</a></>}</td></tr>))}</tbody></table></Card>
        <Pager page={page} total={data.total} limit={100} onPage={setPage} />
      </>}
    </>
  )
}
