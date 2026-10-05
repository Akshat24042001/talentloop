// Platform console: data across every company (candidates, jobs, AI interviews, audit log, outbox).
// Each list filters by company and opens details in a side panel.
import { Download, RotateCcw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Alert, Badge, Button, Modal, Select, toast } from '../../components/ui'
import { Ago } from '../../components/kit'
import { useApi } from '../../components/kit'
import { api } from '../../lib/api'
import { ACTION_LABEL, JOB_STATUS } from '../../app/labels'
import { CandidatePanel, CompanyLink, FilterBar, Head, InterviewPanel, JobPanel, JobStatus, OrgSelect, Paging, SearchBox, Table, label, type Paged } from './parts'

/** Debounced text for search boxes, and a page that resets when any filter changes. */
function useFilters<T extends Record<string, string>>(init: T) {
  const [f, setF] = useState(init), [q, setQ] = useState(''), [dq, setDq] = useState(''), [page, setPage] = useState(1)
  useEffect(() => { const t = setTimeout(() => setDq(q), 300); return () => clearTimeout(t) }, [q])
  useEffect(() => setPage(1), [dq, JSON.stringify(f)])   // eslint-disable-line react-hooks/exhaustive-deps
  const qs = new URLSearchParams({ q: dq, page: String(page), ...f }).toString()
  return { f, set: (k: keyof T, v: string) => setF({ ...f, [k]: v }), q, setQ, page, setPage, qs }
}

interface CandRow { id: string; name: string; email: string; phone: string; company: string; org_id: string; headline: string; current_company: string; years: number | null; location: string; sample: boolean; applications: number; created_at: number }
export function Candidates({ org }: { org?: string }) {
  const fl = useFilters({ org: org || '', sample: '' })
  const { data, reload } = useApi<Paged<CandRow>>(`/api/console/candidates?${fl.qs}`)
  const [open, setOpen] = useState<string | null>(null)
  return (<>
    {!org && <Head title="Candidates" sub="Every candidate on the platform, from every company." />}
    <FilterBar>
      <SearchBox value={fl.q} onChange={fl.setQ} placeholder="Name, email, phone, company, skill" />
      {!org && <OrgSelect value={fl.f.org} onChange={v => fl.set('org', v)} />}
      <Select aria-label="Sample data" className="w-full sm:w-44" value={fl.f.sample} onChange={e => fl.set('sample', e.target.value)}>
        <option value="">Real and sample</option><option value="hide">Real only</option><option value="only">Sample only</option></Select>
    </FilterBar>
    <Table rows={data?.items} onOpen={r => setOpen(r.id)} empty="No candidates match." cols={[
      { h: 'Candidate', cell: r => <><div className="font-semibold">{r.name} {r.sample && <Badge tone="warning">Sample</Badge>}</div><div className="text-xs text-slate-500">{r.email || r.phone}</div></> },
      ...(org ? [] : [{ h: 'Company', cell: (r: CandRow) => <CompanyLink id={r.org_id} name={r.company} /> }]),
      { h: 'Now', cell: r => <span className="text-slate-600 dark:text-slate-300">{r.headline || r.current_company || '-'}</span> },
      { h: 'Exp.', cell: r => r.years != null ? `${r.years} y` : '-', className: 'whitespace-nowrap tabular-nums' },
      { h: 'Jobs', cell: r => r.applications, className: 'tabular-nums' },
      { h: 'Added', cell: r => <Ago ts={r.created_at} />, className: 'whitespace-nowrap text-xs text-slate-500' },
    ]} />
    <Paging data={data} page={fl.page} setPage={fl.setPage} />
    <CandidatePanel id={open} onClose={() => setOpen(null)} onChanged={reload} />
  </>)
}

interface JobRow { id: string; title: string; department: string; status: string; company: string; org_id: string; location: string; applications: number; created_at: number }
export function Jobs({ org }: { org?: string }) {
  const fl = useFilters({ org: org || '', status: '' })
  const { data, reload } = useApi<Paged<JobRow>>(`/api/console/jobs?${fl.qs}`)
  const [open, setOpen] = useState<string | null>(null)
  return (<>
    {!org && <Head title="Jobs" sub="Every job description on the platform, with its company and applicants." />}
    <FilterBar>
      <SearchBox value={fl.q} onChange={fl.setQ} placeholder="Title or department" />
      {!org && <OrgSelect value={fl.f.org} onChange={v => fl.set('org', v)} />}
      <Select aria-label="Status" className="w-full sm:w-40" value={fl.f.status} onChange={e => fl.set('status', e.target.value)}>
        <option value="">Any status</option>{Object.entries(JOB_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</Select>
    </FilterBar>
    <Table rows={data?.items} onOpen={r => setOpen(r.id)} empty="No jobs match." cols={[
      { h: 'Job', cell: r => <><div className="font-semibold">{r.title}</div><div className="text-xs text-slate-500">{[r.department, r.location].filter(Boolean).join(' · ') || '-'}</div></> },
      ...(org ? [] : [{ h: 'Company', cell: (r: JobRow) => <CompanyLink id={r.org_id} name={r.company} /> }]),
      { h: 'Status', cell: r => <JobStatus s={r.status} /> },
      { h: 'Applicants', cell: r => r.applications, className: 'tabular-nums' },
      { h: 'Created', cell: r => <Ago ts={r.created_at} />, className: 'whitespace-nowrap text-xs text-slate-500' },
    ]} />
    <Paging data={data} page={fl.page} setPage={fl.setPage} />
    <JobPanel id={open} onClose={() => setOpen(null)} onChanged={reload} />
  </>)
}

interface IvRow { id: string; candidate: string; email: string; role: string; status: string; channel: string; company: string; org_id: string; candidate_id: string | null; recommendation?: string; overall?: number; created_at: number }
export function Interviews({ org }: { org?: string }) {
  const fl = useFilters({ org: org || '', status: '' })
  const { data } = useApi<Paged<IvRow>>(`/api/console/interviews?${fl.qs}`)
  const [iv, setIv] = useState<string | null>(null)
  return (<>
    {!org && <Head title="AI interviews" sub="Every AI interview on the platform." />}
    <FilterBar>
      <SearchBox value={fl.q} onChange={fl.setQ} placeholder="Candidate, email or role" />
      {!org && <OrgSelect value={fl.f.org} onChange={v => fl.set('org', v)} />}
      <Select aria-label="Status" className="w-full sm:w-44" value={fl.f.status} onChange={e => fl.set('status', e.target.value)}>
        <option value="">Any status</option>{['created', 'in_progress', 'completed', 'scored', 'incomplete'].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select>
    </FilterBar>
    <Table rows={data?.items} onOpen={r => setIv(r.id)} empty="No interviews match." cols={[
      { h: 'Candidate', cell: r => <><div className="font-semibold">{r.candidate || '-'}</div><div className="text-xs text-slate-500">{r.email}</div></> },
      ...(org ? [] : [{ h: 'Company', cell: (r: IvRow) => <CompanyLink id={r.org_id} name={r.company} /> }]),
      { h: 'Role', cell: r => r.role || '-' },
      { h: 'Status', cell: r => <Badge tone={r.status === 'scored' || r.status === 'completed' ? 'success' : r.status === 'incomplete' ? 'warning' : 'neutral'}>{label(r.status)}</Badge> },
      { h: 'Result', cell: r => r.overall != null ? <span className="tabular-nums">{Math.round(r.overall)}{r.recommendation ? ` · ${label(r.recommendation)}` : ''}</span> : '-' },
      { h: 'When', cell: r => <Ago ts={r.created_at} />, className: 'whitespace-nowrap text-xs text-slate-500' },
    ]} />
    <Paging data={data} page={fl.page} setPage={fl.setPage} />
    <InterviewPanel id={iv} onClose={() => setIv(null)} />
  </>)
}

interface ActRow { id: string; at: number; action: string; detail: string; company: string; org_id: string | null; user: string; user_id: string | null }
export function Audit({ org, user }: { org?: string; user?: string }) {
  const fl = useFilters({ org: org || '', action: '', user: user || '' })
  const { data } = useApi<Paged<ActRow> & { actions: string[] }>(`/api/console/activity?${fl.qs}`)
  return (<>
    {!org && !user && <Head title="Audit log" sub="Everything that happened, in every company, newest first. Changes made in this console are logged as Platform admin." />}
    <FilterBar>
      <SearchBox value={fl.q} onChange={fl.setQ} placeholder="Search the details" />
      {!org && <OrgSelect value={fl.f.org} onChange={v => fl.set('org', v)} />}
      <Select searchable aria-label="Action" className="w-full sm:w-52" value={fl.f.action} onChange={e => fl.set('action', e.target.value)}>
        <option value="">Every action</option>{(data?.actions || []).map(a => <option key={a} value={a}>{ACTION_LABEL[a] || label(a)}</option>)}</Select>
    </FilterBar>
    <Table rows={data?.items} empty="Nothing logged." cols={[
      { h: 'When', cell: r => <Ago ts={r.at} />, className: 'whitespace-nowrap text-xs text-slate-500' },
      ...(org ? [] : [{ h: 'Company', cell: (r: ActRow) => <CompanyLink id={r.org_id} name={r.company} /> }]),
      { h: 'Who', cell: r => <span className="text-xs">{r.user}</span> },
      { h: 'What', cell: r => <><Badge tone={r.action === 'platform_admin' ? 'violet' : 'neutral'}>{r.action === 'platform_admin' ? 'Platform admin' : ACTION_LABEL[r.action] || label(r.action)}</Badge> <span className="text-slate-700 dark:text-slate-200">{r.detail}</span></> },
    ]} />
    <Paging data={data} page={fl.page} setPage={fl.setPage} />
  </>)
}

interface MsgRow { id: string; to: string; subject: string; body: string; channel: string; status: string; error: string; created_at: number; sent_at?: number | null; company: string; org_id?: string; template?: string }
const MSG_TONE: Record<string, 'success' | 'warning' | 'danger' | 'neutral' | 'brand'> = { sent: 'success', queued: 'brand', failed: 'danger', held: 'warning', skipped: 'neutral', not_configured: 'warning' }
export function Outbox({ org }: { org?: string }) {
  const fl = useFilters({ org: org || '', status: '' })
  const { data, reload } = useApi<Paged<MsgRow> & { counts: Record<string, number>; channels: { production?: boolean; dev_email_to?: string; email: boolean } }>(`/api/console/messages?${fl.qs}`)
  const [open, setOpen] = useState<MsgRow | null>(null)
  async function retry(m: MsgRow) {
    try { await api(`/api/console/messages/${m.id}/retry`, { method: 'POST' }); toast('Queued again'); reload() } catch (e: any) { toast(e.message) }
  }
  return (<>
    {!org && <Head title="Outbox" sub="Every email and WhatsApp message the platform sent or tried to send." />}
    {data && !data.channels.email && <Alert className="mb-3" tone="warning">Email is not set up on the server (SMTP_*), so nothing is sent.</Alert>}
    {data?.channels.production === false && <Alert className="mb-3" tone="warning">Development: emails go only to {data.channels.dev_email_to || 'nobody (DEV_EMAIL_TO is empty)'}.</Alert>}
    <FilterBar>
      <SearchBox value={fl.q} onChange={fl.setQ} placeholder="Recipient or subject" />
      {!org && <OrgSelect value={fl.f.org} onChange={v => fl.set('org', v)} />}
      <Select aria-label="Status" className="w-full sm:w-44" value={fl.f.status} onChange={e => fl.set('status', e.target.value)}>
        <option value="">Any status</option>{Object.entries(data?.counts || {}).map(([k, n]) => <option key={k} value={k}>{label(k)} ({n})</option>)}</Select>
    </FilterBar>
    <Table rows={data?.items} onOpen={setOpen} empty="No messages." cols={[
      { h: 'To', cell: r => <><div className="font-medium">{r.to}</div><div className="text-xs text-slate-500">{r.channel}</div></> },
      ...(org ? [] : [{ h: 'Company', cell: (r: MsgRow) => <CompanyLink id={r.org_id} name={r.company} /> }]),
      { h: 'Subject', cell: r => <span className="line-clamp-2">{r.subject}</span> },
      { h: 'Status', cell: r => <><Badge tone={MSG_TONE[r.status] || 'neutral'}>{label(r.status)}</Badge>{r.error && <div className="mt-1 max-w-56 text-xs text-slate-500">{r.error}</div>}</> },
      { h: 'When', cell: r => <Ago ts={r.created_at} />, className: 'whitespace-nowrap text-xs text-slate-500' },
      { h: '', cell: r => r.status !== 'sent' && r.status !== 'queued' ? <Button size="sm" variant="ghost" icon={<RotateCcw />} onClick={e => { e.stopPropagation(); retry(r) }}>Retry</Button> : null },
    ]} />
    <Paging data={data} page={fl.page} setPage={fl.setPage} />
    <Modal open={!!open} onOpenChange={o => !o && setOpen(null)} title={open?.subject || ''} description={open ? `${open.channel} to ${open.to} · ${open.company}` : ''} wide
      footer={<Button onClick={() => setOpen(null)}>Close</Button>}>
      <pre className="mt-3 max-h-[50vh] overflow-y-auto whitespace-pre-wrap text-sm">{open?.body}</pre>
    </Modal>
  </>)
}

const REPORTS: [string, string, string, boolean][] = [
  ['companies', 'Companies', 'Every company with its people, jobs, candidates, applications, interviews and AI use.', false],
  ['people', 'People', 'Every account: companies and roles, email confirmed, sign-ins, admin rights.', false],
  ['candidates', 'Candidates', 'Every candidate with company, contact details, experience and source.', true],
  ['jobs', 'Jobs', 'Every job with company, status, location and number of applicants.', true],
  ['applications', 'Applications', 'Who applied to what, and where each application stands.', true],
  ['interviews', 'AI interviews', 'Every AI interview with status, overall score and recommendation.', true],
  ['audit', 'Audit log', 'Everything that happened (up to 100,000 most recent entries).', true],
]
export function Reports() {
  const [org, setOrg] = useState('')
  return (<>
    <Head title="Reports" sub="Download any part of the platform as a spreadsheet (CSV, opens in Excel or Google Sheets). Downloads are written to the audit log." />
    <FilterBar><OrgSelect value={org} onChange={setOrg} /><span className="text-xs text-slate-500">Company filter applies to the reports marked "by company".</span></FilterBar>
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{REPORTS.map(([k, t, d, byOrg]) => (
      <div key={k} className="flex flex-col justify-between gap-3 rounded-2xl bg-white p-4 ring-1 ring-slate-200 dark:bg-ink-900 dark:ring-ink-700">
        <div><div className="flex items-center gap-2 font-semibold">{t}{byOrg && <Badge>by company</Badge>}</div><p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{d}</p></div>
        <Button size="sm" icon={<Download />} href={`/api/console/export/${k}.csv${byOrg && org ? `?org=${org}` : ''}`}>Download CSV</Button>
      </div>))}</div>
  </>)
}
