// Shared pieces of the platform console: tables, filters, side panels and the detail panels for candidates and jobs
// (opened from anywhere in the console, so a platform admin never has to leave it).
import * as Dialog from '@radix-ui/react-dialog'
import { Download, ExternalLink, Trash2, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Badge, Button, Card, Input, Select, cn, toast } from '../../components/ui'
import { Ago, KV, Loading, Pager, Tabs, useApi } from '../../components/kit'
import { ask } from '../../components/dialogs'
import { api } from '../../lib/api'
import { navigate } from '../../lib/router'
import { JOB_STATUS, SOURCE_LABEL, STAGE_TONE } from '../../app/labels'

export const label = (s: string) => s.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())
export const go = (to: string) => navigate(to)

export interface Paged<T> { total: number; page: number; size: number; items: T[] }

/** Page title row of the console. */
export function Head({ title, sub, children }: { title: ReactNode; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0"><h1 className="text-2xl font-semibold tracking-tight">{title}</h1>{sub && <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{sub}</p>}</div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  )
}

/** Filters in one row above a table. */
export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="mb-3 flex flex-wrap items-center gap-2">{children}</div>
}

export function SearchBox({ value, onChange, placeholder = 'Search' }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return <Input type="search" aria-label={placeholder} className="w-full sm:w-72" placeholder={placeholder} value={value} onChange={e => onChange(e.target.value)} />
}

/** Every company, for filters. */
export function OrgSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { data } = useApi<{ id: string; name: string }[]>('/api/admin/orgs')
  return (
    <Select searchable aria-label="Company" className="w-full sm:w-60" value={value} onChange={e => onChange(e.target.value)}>
      <option value="">All companies</option>
      {(data || []).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
    </Select>
  )
}

export interface Col<T> { h: string; cell: (r: T) => ReactNode; className?: string }
/** A plain data table; rows open on click (and Enter) when `onOpen` is given. */
export function Table<T extends { id: string }>({ rows, cols, onOpen, empty = 'Nothing here.' }: { rows: T[] | null | undefined; cols: Col<T>[]; onOpen?: (r: T) => void; empty?: string }) {
  if (!rows) return <Card><Loading /></Card>
  return (
    <Card className="overflow-x-auto">
      {rows.length === 0 ? <p className="p-6 text-sm text-slate-500 dark:text-slate-400">{empty}</p> : (
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs text-slate-500 dark:text-slate-400">{cols.map(c => <th key={c.h} className={cn('whitespace-nowrap px-4 py-3 font-medium', c.className)}>{c.h}</th>)}</tr></thead>
          <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{rows.map(r => (
            <tr key={r.id} tabIndex={onOpen ? 0 : undefined} onClick={onOpen ? () => onOpen(r) : undefined} onKeyDown={onOpen ? e => e.key === 'Enter' && onOpen(r) : undefined}
              className={cn(onOpen && 'cursor-pointer hover:bg-slate-50 focus-visible:bg-slate-50 focus-visible:outline-none dark:hover:bg-ink-850 dark:focus-visible:bg-ink-850')}>
              {cols.map(c => <td key={c.h} className={cn('px-4 py-3 align-top', c.className)}>{c.cell(r)}</td>)}
            </tr>))}</tbody>
        </table>
      )}
    </Card>
  )
}

export function Paging({ data, page, setPage }: { data: Paged<unknown> | null; page: number; setPage: (p: number) => void }) {
  if (!data) return null
  return <div className="mt-3 flex items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400"><span>{data.total} in total</span><Pager page={page} total={data.total} limit={data.size} onPage={setPage} /></div>
}

/** Right-hand panel over the console. */
export function SidePanel({ open, onClose, title, sub, actions, children }: { open: boolean; onClose: () => void; title: ReactNode; sub?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <Dialog.Root open={open} onOpenChange={o => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink-950/40 backdrop-blur-[2px]" />
        <Dialog.Content aria-describedby={undefined} className="fixed inset-y-0 right-0 z-50 flex w-full max-w-2xl flex-col bg-white shadow-2xl focus:outline-none dark:bg-ink-900">
          <header className="flex items-start gap-3 border-b border-slate-100 px-5 py-4 dark:border-ink-800">
            <div className="min-w-0 flex-1"><Dialog.Title className="truncate text-lg font-semibold">{title}</Dialog.Title>{sub && <div className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{sub}</div>}</div>
            <Dialog.Close aria-label="Close" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-ink-800"><X className="size-5" /></Dialog.Close>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {actions && <footer className="flex flex-wrap gap-2 border-t border-slate-100 px-5 py-3 dark:border-ink-800">{actions}</footer>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export const StageBadge = ({ s }: { s: string }) => <Badge tone={STAGE_TONE[s] || 'neutral'}>{label(s)}</Badge>
export const JobStatus = ({ s }: { s: string }) => <Badge tone={JOB_STATUS[s]?.tone || 'neutral'}>{JOB_STATUS[s]?.label || label(s)}</Badge>
export const CompanyLink = ({ id, name }: { id?: string | null; name: string }) => id && name
  ? <button type="button" className="text-left font-medium text-brand-600 hover:underline dark:text-brand-300" onClick={e => { e.stopPropagation(); go(`/admin/companies/${id}`) }}>{name}</button>
  : <span className="text-slate-500">{name || '-'}</span>

// ---------------------------------------------------------------------------
// candidate panel
// ---------------------------------------------------------------------------
interface CandidateFull {
  id: string; name: string; email: string; phone: string; location: string; headline: string; company: string; org_id: string; source: string; tags: string[]; sample: boolean
  current_company: string; college: string; years: number | null; notice_days: number | null; expected_salary: number | null; skills: string
  resume_name: string; has_resume_file: boolean; resume_text: string; created_at: number; updated_at: number
  applications: { id: string; job: string; job_id: string; stage: string; rating: number | null; created_at: number; notes: string }[]
  messages: { subject: string; status: string; channel: string; created_at: number }[]
}
export function CandidatePanel({ id, onClose, onChanged }: { id: string | null; onClose: () => void; onChanged?: () => void }) {
  const { data: c, error } = useApi<CandidateFull>(id ? `/api/console/candidates/${id}` : null)
  const [tab, setTab] = useState<'profile' | 'resume' | 'activity'>('profile')
  const [job, setJob] = useState<string | null>(null)
  async function erase() {
    if (!c || !await ask(`Erase ${c.name} from ${c.company}? Their profile, resume, applications, interviews and messages are deleted for good. This cannot be undone.`, { confirm: 'Erase for good' })) return
    try { await api(`/api/console/candidates/${c.id}`, { method: 'DELETE' }); toast('Candidate erased'); onChanged?.(); onClose() } catch (e: any) { toast(e.message) }
  }
  return (
    <SidePanel open={!!id} onClose={onClose} title={c?.name || 'Candidate'} sub={c && <><CompanyLink id={c.org_id} name={c.company} /> · {c.email || 'no email'}{c.sample && <> · <Badge tone="warning">Sample</Badge></>}</>}
      actions={c && <>
        {c.has_resume_file && <Button size="sm" icon={<Download />} href={`/api/console/candidates/${c.id}/resume`} target="_blank">Resume file</Button>}
        <Button size="sm" variant="ghost" className="ml-auto text-red-600" icon={<Trash2 />} onClick={erase}>Erase candidate</Button></>}>
      {error ? <p className="text-sm text-red-600">{error}</p> : !c ? <Loading /> : <>
        <Tabs className="mb-4" value={tab} onChange={setTab} tabs={[{ id: 'profile', label: 'Profile' }, { id: 'resume', label: 'Resume text' }, { id: 'activity', label: 'Applications', count: c.applications.length }]} />
        {tab === 'profile' && <dl className="divide-y divide-slate-100 dark:divide-ink-800">
          <KV k="Headline">{c.headline}</KV><KV k="Phone">{c.phone}</KV><KV k="Location">{c.location}</KV>
          <KV k="Current company">{c.current_company}</KV><KV k="College">{c.college}</KV><KV k="Experience">{c.years != null ? `${c.years} years` : ''}</KV>
          <KV k="Notice period">{c.notice_days != null ? `${c.notice_days} days` : ''}</KV><KV k="Expected salary">{c.expected_salary ? c.expected_salary.toLocaleString() : ''}</KV>
          <KV k="Skills"><span className="font-normal">{c.skills.split(/[|,]/).map(x => x.trim()).filter(Boolean).join(", ")}</span></KV><KV k="Came from">{SOURCE_LABEL[c.source] || label(c.source || '')}</KV>
          <KV k="Tags">{c.tags.join(', ')}</KV><KV k="Added"><Ago ts={c.created_at} /></KV><KV k="Resume file">{c.resume_name}</KV>
        </dl>}
        {tab === 'resume' && (c.resume_text ? <pre className="whitespace-pre-wrap rounded-xl bg-slate-50 p-4 text-xs leading-relaxed dark:bg-ink-850">{c.resume_text}</pre> : <p className="text-sm text-slate-500">No resume text.</p>)}
        {tab === 'activity' && <div className="space-y-4">
          {c.applications.length ? <ul className="space-y-2">{c.applications.map(a => (
            <li key={a.id}><button type="button" onClick={() => setJob(a.job_id)} className="flex w-full items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2 text-left text-sm hover:bg-slate-100 dark:bg-ink-850 dark:hover:bg-ink-800">
              <span className="font-medium">{a.job}</span><span className="flex items-center gap-2"><StageBadge s={a.stage} /><span className="text-xs text-slate-500"><Ago ts={a.created_at} /></span></span></button></li>))}</ul>
            : <p className="text-sm text-slate-500">Not applied to any job.</p>}
          <div><h3 className="mb-2 text-sm font-semibold">Messages</h3>{c.messages.length ? <ul className="space-y-1 text-sm">{c.messages.map((m, i) => <li key={i} className="flex justify-between gap-2"><span className="truncate">{m.subject}</span><span className="shrink-0 text-xs text-slate-500">{label(m.status)} · <Ago ts={m.created_at} /></span></li>)}</ul> : <p className="text-sm text-slate-500">None.</p>}</div>
        </div>}
      </>}
      <JobPanel id={job} onClose={() => setJob(null)} />
    </SidePanel>
  )
}

// ---------------------------------------------------------------------------
// job panel
// ---------------------------------------------------------------------------
interface JobFull {
  id: string; title: string; department: string; status: string; company: string; org_id: string; fields: Record<string, any>; rounds: { name: string; type: string }[]
  created_by: string; created_at: number; published_at: number | null; stages: Record<string, number>; applications: { candidate_id: string; name: string; email: string; stage: string; created_at: number }[]
}
const JD_KEYS: [string, string][] = [['summary', 'Summary'], ['responsibilities', 'Responsibilities'], ['must_have_skills', 'Must-have skills'], ['nice_to_have_skills', 'Nice to have'],
  ['tools', 'Tools'], ['location', 'Location'], ['work_mode', 'Work mode'], ['employment_type', 'Employment type'], ['experience_min', 'Experience from (years)'], ['experience_max', 'Experience to (years)'],
  ['salary_min', 'Salary from'], ['salary_max', 'Salary to'], ['education', 'Education'], ['benefits', 'Benefits']]
const show = (v: unknown) => Array.isArray(v) ? (v.length ? <ul className="list-disc space-y-0.5 pl-4 text-left font-normal">{v.map((x, i) => <li key={i}>{String(x)}</li>)}</ul> : '') : v == null ? '' : String(v)
export function JobPanel({ id, onClose, onChanged }: { id: string | null; onClose: () => void; onChanged?: () => void }) {
  const { data: j, error, reload } = useApi<JobFull>(id ? `/api/console/jobs/${id}` : null)
  const [tab, setTab] = useState<'jd' | 'people'>('jd')
  const [cand, setCand] = useState<string | null>(null)
  async function setStatus(st: string) {
    if (!j || !await ask(`Set "${j.title}" at ${j.company} to ${JOB_STATUS[st]?.label || st}?${st === 'open' ? ' It shows on their careers page and people can apply.' : ' It no longer takes applications.'}`, { confirm: 'Change status', danger: st !== 'open' })) return
    try { await api(`/api/console/jobs/${j.id}`, { method: 'PATCH', json: { status: st } }); toast('Status changed'); reload(); onChanged?.() } catch (e: any) { toast(e.message) }
  }
  return (
    <SidePanel open={!!id} onClose={onClose} title={j?.title || 'Job'} sub={j && <><CompanyLink id={j.org_id} name={j.company} /> · <JobStatus s={j.status} />{j.department && <> · {j.department}</>}</>}
      actions={j && <div className="flex w-full flex-wrap items-center gap-2"><span className="text-xs text-slate-500">Status</span>
        <Select aria-label="Job status" className="w-40" value={j.status} onChange={e => setStatus(e.target.value)}>{Object.entries(JOB_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</Select></div>}>
      {error ? <p className="text-sm text-red-600">{error}</p> : !j ? <Loading /> : <>
        <Tabs className="mb-4" value={tab} onChange={setTab} tabs={[{ id: 'jd', label: 'Job description' }, { id: 'people', label: 'Applicants', count: j.applications.length }]} />
        {tab === 'jd' && <dl className="divide-y divide-slate-100 dark:divide-ink-800">
          {JD_KEYS.filter(([k]) => j.fields[k] != null && j.fields[k] !== '' && !(Array.isArray(j.fields[k]) && !j.fields[k].length)).map(([k, l]) => <KV key={k} k={l}>{show(j.fields[k])}</KV>)}
          <KV k="Hiring rounds">{j.rounds.map(r => r.name).join(' → ')}</KV><KV k="Created by">{j.created_by}</KV><KV k="Created"><Ago ts={j.created_at} /></KV><KV k="Published"><Ago ts={j.published_at} /></KV>
        </dl>}
        {tab === 'people' && <>
          <div className="mb-3 flex flex-wrap gap-1.5">{Object.entries(j.stages).map(([k, n]) => <Badge key={k} tone={STAGE_TONE[k] || 'neutral'}>{label(k)} {n}</Badge>)}</div>
          {j.applications.length ? <ul className="space-y-1.5">{j.applications.map(a => (
            <li key={a.candidate_id}><button type="button" onClick={() => setCand(a.candidate_id)} className="flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-ink-850">
              <span className="min-w-0"><span className="block truncate font-medium">{a.name}</span><span className="block truncate text-xs text-slate-500">{a.email}</span></span><StageBadge s={a.stage} /></button></li>))}</ul>
            : <p className="text-sm text-slate-500">No applicants yet.</p>}
        </>}
      </>}
      <CandidatePanel id={cand} onClose={() => setCand(null)} />
    </SidePanel>
  )
}

export const ExtLink = ({ href, children }: { href: string; children: ReactNode }) =>
  <a className="inline-flex items-center gap-1 text-brand-600 hover:underline dark:text-brand-300" href={href} target="_blank" rel="noopener">{children}<ExternalLink className="size-3" /></a>
