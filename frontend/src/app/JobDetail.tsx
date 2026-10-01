import { Copy, Download, ExternalLink, FileText, Pause, Pencil, Play, Plus, Sparkles, Trash2, UserPlus, Users, Video, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Field, Modal, Select, Textarea, Tip, copyText, toast } from '../components/ui'
import { Avatar, BackLink, Empty, ErrorBox, KV, Loading, PageHeader, ScoreBar, ScoreRing, Tabs, useApi, Ago } from '../components/kit'
import { api } from '../lib/api'
import { ago, when } from '../lib/format'
import { navigate, useLocation } from '../lib/router'
import { useMe } from '../lib/session'
import { ACTION_LABEL, JOB_STATUS, STAGE_TONE, actor } from './labels'
import { BreakdownBars, ReportView, SkillChips, type AIReport, type Breakdown } from './match'

interface Job {
  id: string; ref: string; title: string; department: string; status: string; top_n: number; location: string; employment_type: string; experience: string; salary: string
  fields: Record<string, any>; permission: 'manage' | 'edit' | 'view'; collaborators: { id: string; user_id: string; name: string; email: string; permission: string }[]
  created_by?: { name: string; email: string }; missing_to_publish: string[]; careers_url: string; applications: number; created_at: number; updated_at: number; published_at?: number
}
interface JD { title: string; company: string; facts: string[]; sections: { title: string; body?: string; items?: string[] }[]; contact?: string }
export interface Cand { id: string; ref: string; name: string; email: string; phone?: string; location?: string; headline?: string; years?: number | null; skills: string[]; source: string; has_resume: boolean; notice_days?: number | null; current_company?: string }
interface MatchRow { rank: number; score: number; breakdown: Breakdown; knocked_out: boolean; ai_score?: number | null; ai_report?: AIReport | null; candidate: Cand; application?: { id: string; stage: string; stage_label: string } | null }
interface AppRow { id: string; stage: string; stage_label: string; created_at: number; rating?: number | null; notes?: string; knockout_failed?: string[]; answers?: Record<string, any>; cover_letter?: string; interview_id?: string; interview_ref?: string; source?: string; candidate: Cand; match?: { score: number; rank: number; ai_score?: number; verdict?: string } | null }

type Tab = 'overview' | 'pipeline' | 'matches' | 'team' | 'activity'

export default function JobDetail({ id }: { id: string }) {
  const { query } = useLocation()
  const [tab, setTab] = useState<Tab>((query.get('tab') as Tab) || 'matches')
  const { data: job, error, reload } = useApi<Job>(`/api/jobs/${id}`)
  const me = useMe()
  const switchTab = (t: Tab) => { setTab(t); navigate(`/app/jobs/${id}?tab=${t}`, { replace: true, keepScroll: true }) }
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!job) return <Loading />
  const st = JOB_STATUS[job.status]!
  async function setStatus(s: string) {
    try { await api(`/api/jobs/${id}`, { method: 'PATCH', json: { status: s } }); toast(s === 'open' ? 'Job is live' : `Job ${JOB_STATUS[s]!.label.toLowerCase()}`); reload() } catch (e: any) { toast(e.message) }
  }
  const careers = `${location.origin}${job.careers_url}`
  return (
    <>
      <PageHeader back={<BackLink href="/app/jobs">All jobs</BackLink>}
        title={<span className="flex flex-wrap items-center gap-3">{job.title}<Badge tone={st.tone}>{st.label}</Badge></span>}
        description={[job.department, job.location, job.employment_type, job.experience, job.salary].filter(Boolean).join(' · ')}
        actions={<>
          {job.permission !== 'view' && <Button href={`/app/jobs/${id}/edit`} icon={<Pencil />}>Edit JD</Button>}
          {job.permission === 'manage' && (job.status === 'open' ? <Button icon={<Pause />} onClick={() => setStatus('paused')}>Pause</Button>
            : <Button variant="primary" icon={<Play />} disabled={job.missing_to_publish.length > 0} onClick={() => setStatus('open')}>{job.status === 'draft' ? 'Publish' : 'Reopen'}</Button>)}
        </>} />
      {job.status === 'draft' && job.missing_to_publish.length > 0 && <Alert className="mb-4" tone="info" title="Draft">To publish, fill in: {job.missing_to_publish.join(', ')}.</Alert>}
      {job.status === 'open' && !job.fields.internal_only && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm ring-1 ring-slate-200 dark:bg-ink-900 dark:ring-ink-700">
          <span className="text-slate-500">Public job post:</span><a href={job.careers_url} target="_blank" rel="noopener" className="truncate font-medium text-brand-600 hover:underline dark:text-brand-300">{careers}</a>
          <Button size="sm" variant="ghost" icon={<Copy />} onClick={() => copyText(careers, 'Job link copied')}>Copy</Button>
        </div>
      )}
      <Tabs className="mb-5" value={tab} onChange={switchTab} tabs={[
        { id: 'matches', label: 'Best matches' }, { id: 'pipeline', label: 'Applicants', count: job.applications },
        { id: 'overview', label: 'Job description' }, { id: 'team', label: 'Team access', count: job.collaborators.length }, { id: 'activity', label: 'Activity' }]} />
      {tab === 'overview' && <Overview job={job} />}
      {tab === 'matches' && <Matches job={job} canManage={job.permission === 'manage'} />}
      {tab === 'pipeline' && <Pipeline job={job} />}
      {tab === 'team' && <TeamAccess job={job} reload={reload} canManage={job.permission === 'manage' && me.can.manage_jobs} />}
      {tab === 'activity' && <Activity id={id} />}
    </>
  )
}

function Overview({ job }: { job: Job }) {
  const { data: jd } = useApi<JD>(`/api/jobs/${job.id}/jd`)
  const me = useMe()
  async function dup() { const r = await api(`/api/jobs/${job.id}/duplicate`, { method: 'POST' }); toast('Copied as a new draft'); navigate(`/app/jobs/${r.ref}/edit`) }
  async function del() { if (!confirm(`Delete "${job.title}" with its applications and matches? Candidates stay in your pool.`)) return; await api(`/api/jobs/${job.id}`, { method: 'DELETE' }); toast('Job deleted'); navigate('/app/jobs') }
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
      <Card className="p-6 sm:p-8">
        {!jd ? <Loading /> : (
          <article>
            <h2 className="text-2xl font-semibold tracking-tight">{jd.title}</h2>
            <p className="mt-1 font-medium text-slate-600 dark:text-slate-300">{jd.company}</p>
            <div className="mt-3 flex flex-wrap gap-1.5">{jd.facts.map(f => <Badge key={f}>{f}</Badge>)}</div>
            {jd.sections.map(s => (
              <section key={s.title} className="mt-6">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-brand-700 dark:text-brand-300">{s.title}</h3>
                {s.body && s.body.split('\n').filter(Boolean).map((p, i) => <p key={i} className="mt-2 text-sm leading-relaxed text-slate-700 dark:text-slate-200">{p}</p>)}
                {s.items && <ul className="mt-2 space-y-1.5 text-sm text-slate-700 dark:text-slate-200">{s.items.map((it, i) => <li key={i} className="flex gap-2"><span className="mt-2 size-1.5 shrink-0 rounded-full bg-brand-400" />{it}</li>)}</ul>}
              </section>
            ))}
          </article>
        )}
      </Card>
      <div className="space-y-4">
        <Card><CardBody className="space-y-2">
          <Button variant="primary" className="w-full" href={`/api/jobs/${job.id}/jd.pdf`} target="_blank" icon={<Download />}>Download JD as PDF</Button>
          {job.status === 'open' && <Button className="w-full" href={job.careers_url} target="_blank" icon={<ExternalLink />}>View public post</Button>}
          {job.permission === 'manage' && me.can.manage_jobs && <Button className="w-full" variant="ghost" icon={<Copy />} onClick={dup}>Duplicate job</Button>}
        </CardBody></Card>
        <Card><CardHeader title="Details" /><CardBody className="pt-2"><dl className="divide-y divide-slate-100 dark:divide-ink-800">
          <KV k="Openings">{job.fields.openings}</KV><KV k="Priority">{job.fields.priority}</KV><KV k="Seniority">{job.fields.seniority}</KV>
          <KV k="Requisition">{job.fields.requisition_id}</KV><KV k="Reports to">{job.fields.reports_to}</KV><KV k="Deadline">{job.fields.deadline}</KV>
          <KV k="Shortlist size">{job.top_n}</KV><KV k="Created by">{job.created_by?.name}</KV><KV k="Published">{job.published_at ? when(job.published_at) : '-'}</KV>
        </dl></CardBody></Card>
        {job.permission === 'manage' && me.can.manage_jobs && <Button variant="ghost" className="w-full text-red-600 dark:text-red-400" icon={<Trash2 />} onClick={del}>Delete job</Button>}
      </div>
    </div>
  )
}

function Matches({ job, canManage }: { job: Job; canManage: boolean }) {
  const [limit, setLimit] = useState(Math.max(job.top_n, 10))
  const { data, error, reload, loading } = useApi<{ top_n: number; pool: number; ai_pending: number; ai_budget: number; items: MatchRow[]; matched_at: number; can_run_ai: boolean }>(`/api/jobs/${job.id}/matches?limit=${limit}`)
  const [busy, setBusy] = useState(false)
  async function runAI() {
    setBusy(true)
    try { const r = await api('/api/match/ai-reports', { json: { job_ids: [job.id] } }); toast(r.error ? `${r.generated ? `${r.generated} written. ` : ''}${r.error}` : r.generated ? `${r.generated} AI report${r.generated > 1 ? 's' : ''} written` : 'Reports are up to date'); reload() }
    catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  async function addToPipeline(c: Cand) {
    try { await api(`/api/jobs/${job.id}/applications`, { json: { candidate_id: c.id, stage: 'shortlisted' } }); toast(`${c.name} shortlisted`); reload() } catch (e: any) { toast(e.message) }
  }
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!data) return <Loading />
  const shortlist = data.items.slice(0, data.top_n), rest = data.items.slice(data.top_n)
  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div className="text-sm"><b>{data.pool}</b> candidates in your pool ranked instantly by skills, experience, relevance, location and notice period. The AI writes reports for the top <b>{data.top_n}</b> only.
          <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">Ranked <Ago ts={data.matched_at} />. Updates automatically when the job or candidates change.</div></div>
        {data.can_run_ai && canManage && (data.ai_pending > 0
          ? <Button variant="primary" icon={<Sparkles />} loading={busy} onClick={runAI}>Write {Math.min(data.ai_pending, data.ai_budget)} AI report{data.ai_pending > 1 ? 's' : ''}</Button>
          : <Badge tone="success" icon={<Sparkles />}>AI reports up to date</Badge>)}
      </Card>
      {!data.items.length ? <Card><Empty icon={<Users />} title="No matching candidates yet" action={canManage && <Button href="/app/candidates?upload=1" icon={<Plus />}>Upload resumes</Button>}>Upload resumes or share the careers page. Candidates who share no skills or keywords with this job are not listed.</Empty></Card> : (
        <>
          <h3 className="text-sm font-semibold text-slate-500 dark:text-slate-400">Shortlist · top {data.top_n}</h3>
          {shortlist.map(m => <MatchCard key={m.candidate.id} m={m} job={job} onAdd={addToPipeline} canManage={canManage} />)}
          {rest.length > 0 && <>
            <h3 className="pt-2 text-sm font-semibold text-slate-500 dark:text-slate-400">Next best</h3>
            {rest.map(m => <MatchCard key={m.candidate.id} m={m} job={job} onAdd={addToPipeline} canManage={canManage} compact />)}
          </>}
          {data.items.length >= limit && <Button className="w-full" loading={loading} onClick={() => setLimit(l => l + 20)}>Show more</Button>}
        </>
      )}
    </div>
  )
}

function MatchCard({ m, job, onAdd, canManage, compact }: { m: MatchRow; job: Job; onAdd: (c: Cand) => void; canManage: boolean; compact?: boolean }) {
  const [open, setOpen] = useState(!compact)
  const c = m.candidate
  return (
    <Card className={m.knocked_out ? 'opacity-70' : ''}>
      <div className="flex flex-wrap items-start gap-4 p-4 sm:p-5">
        <span className="tabular w-6 pt-3 text-center text-sm font-bold text-slate-400">{m.rank}</span>
        <ScoreRing value={m.score} label="Match score" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <a href={`/app/candidates/${c.ref}`} className="font-semibold text-slate-900 hover:underline dark:text-white">{c.name}</a>
            {m.application && <Badge tone={STAGE_TONE[m.application.stage]}>{m.application.stage_label}</Badge>}
            {m.breakdown.applied && !m.application && <Badge tone="brand">Applied</Badge>}
            {m.knocked_out && <Badge tone="danger">{(m.breakdown.knocked_out || []).join(', ') || 'Screened out'}</Badge>}
          </div>
          <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{[c.headline, c.years != null ? `${c.years} yrs` : '', c.location, c.notice_days != null ? `${c.notice_days}d notice` : ''].filter(Boolean).join(' · ')}</div>
          <div className="mt-2"><SkillChips b={m.breakdown} /></div>
        </div>
        <div className="flex flex-wrap gap-2">
          {!compact || open ? null : <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>Details</Button>}
          {canManage && !m.application && <Button size="sm" icon={<UserPlus />} onClick={() => onAdd(c)}>Shortlist</Button>}
          {canManage && <Tip label="Send an AI first-round interview"><Button size="sm" variant="subtle" icon={<Video />} href={`/app/interviews/new?job=${job.ref}&candidate=${c.ref}${m.application ? `&application=${m.application.id}` : ''}`}>Interview</Button></Tip>}
        </div>
      </div>
      {open && (
        <div className="grid gap-4 border-t border-slate-100 p-4 dark:border-ink-800 sm:p-5 lg:grid-cols-[minmax(0,320px)_1fr]">
          <BreakdownBars b={m.breakdown} />
          {m.ai_report ? <ReportView r={m.ai_report} compact /> : <p className="self-center text-sm text-slate-500 dark:text-slate-400">{compact ? 'Outside the shortlist: no AI report (saves tokens). Raise the shortlist size in the JD to include it.' : 'No AI report yet. Use "Write AI reports" above.'}</p>}
        </div>
      )}
    </Card>
  )
}

function Pipeline({ job }: { job: Job }) {
  const { data, error, reload } = useApi<{ stages: { id: string; label: string }[]; items: AppRow[] }>(`/api/jobs/${job.id}/applications`)
  const [stage, setStage] = useState('')
  const [sel, setSel] = useState<AppRow | null>(null)
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!data) return <Loading />
  const counts = Object.fromEntries(data.stages.map(s => [s.id, data.items.filter(a => a.stage === s.id).length]))
  const rows = data.items.filter(a => !stage || a.stage === stage).sort((a, b) => (b.match?.score ?? -1) - (a.match?.score ?? -1))
  async function move(a: AppRow, s: string) {
    try { await api(`/api/applications/${a.id}`, { method: 'PATCH', json: { stage: s } }); toast(`${a.candidate.name} → ${data!.stages.find(x => x.id === s)?.label}`); reload() } catch (e: any) { toast(e.message) }
  }
  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2">
        <button onClick={() => setStage('')} className={`rounded-full px-3 py-1.5 text-sm font-medium ring-1 ring-inset ${!stage ? 'bg-slate-900 text-white ring-slate-900 dark:bg-white dark:text-ink-900' : 'bg-white ring-slate-200 dark:bg-ink-900 dark:ring-ink-700'}`}>All <span className="tabular opacity-70">{data.items.length}</span></button>
        {data.stages.map(s => <button key={s.id} onClick={() => setStage(s.id)} className={`rounded-full px-3 py-1.5 text-sm font-medium ring-1 ring-inset ${stage === s.id ? 'bg-slate-900 text-white ring-slate-900 dark:bg-white dark:text-ink-900' : 'bg-white ring-slate-200 dark:bg-ink-900 dark:ring-ink-700'}`}>{s.label} <span className="tabular opacity-70">{counts[s.id]}</span></button>)}
      </div>
      <Card className="overflow-hidden">
        {!rows.length ? <Empty icon={<Users />} title={data.items.length ? 'Nobody in this stage' : 'No applicants yet'}>{data.items.length ? '' : 'Share the public job link, or shortlist people from Best matches.'}</Empty> : (
          <ul className="divide-y divide-slate-100 dark:divide-ink-800">
            {rows.map(a => (
              <li key={a.id} className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
                <Avatar name={a.candidate.name} />
                <button className="min-w-0 flex-1 text-left" onClick={() => setSel(a)}>
                  <div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-slate-900 dark:text-white">{a.candidate.name}</span>
                    {a.knockout_failed?.length ? <Badge tone="danger">Screened out</Badge> : null}{a.rating ? <span className="text-xs text-amber-500">{'★'.repeat(a.rating)}</span> : null}{a.interview_id && <Badge tone="violet" icon={<Video />}>Interview</Badge>}</div>
                  <div className="truncate text-xs text-slate-500 dark:text-slate-400">{[a.candidate.headline, a.candidate.years != null ? `${a.candidate.years} yrs` : '', a.candidate.location, `applied ${ago(a.created_at)}`].filter(Boolean).join(' · ')}</div>
                </button>
                <ScoreBar value={a.match?.score} />
                {job.permission !== 'view' ? (
                  <Select aria-label="Stage" className="w-36 py-1.5 text-[13px]" value={a.stage} onChange={e => move(a, e.target.value)}>{data.stages.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}</Select>
                ) : <Badge tone={STAGE_TONE[a.stage]}>{a.stage_label}</Badge>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {sel && <ApplicationDrawer a={sel} job={job} onClose={() => setSel(null)} onSaved={reload} />}
    </>
  )
}

function ApplicationDrawer({ a, job, onClose, onSaved }: { a: AppRow; job: Job; onClose: () => void; onSaved: () => void }) {
  const [rating, setRating] = useState(a.rating || 0), [notes, setNotes] = useState(a.notes || ''), [busy, setBusy] = useState(false)
  const qs: { id: string; question: string }[] = job.fields.screening_questions || []
  async function save() {
    setBusy(true)
    try { await api(`/api/applications/${a.id}`, { method: 'PATCH', json: { rating: rating || null, notes } }); toast('Saved'); onSaved(); onClose() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  async function removeFromJob() {
    if (!confirm(`Remove ${a.candidate.name} from ${job.title}? They stay in your talent pool.`)) return
    try { await api(`/api/applications/${a.id}`, { method: 'DELETE' }); toast('Removed from the job'); onSaved(); onClose() } catch (e: any) { toast(e.message) }
  }
  return (
    <Modal open onOpenChange={o => !o && onClose()} title={a.candidate.name} description={[a.candidate.email, a.candidate.phone].filter(Boolean).join(' · ')}>
      <div className="mt-4 max-h-[60vh] space-y-4 overflow-y-auto pr-1 text-sm">
        {a.knockout_failed?.length ? <Alert tone="danger" title="Screened out by">{a.knockout_failed.join('; ')}</Alert> : null}
        {qs.length > 0 && <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Screening answers</div>
          <dl className="space-y-1.5">{qs.map(q => <div key={q.id}><dt className="text-slate-500">{q.question}</dt><dd className="font-medium">{String(a.answers?.[q.id] ?? '-')}</dd></div>)}</dl></div>}
        {a.cover_letter && <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Cover letter</div><p className="whitespace-pre-line">{a.cover_letter}</p></div>}
        <Field label="Your rating"><div className="flex gap-1">{[1, 2, 3, 4, 5].map(n => <button key={n} aria-label={`${n} stars`} onClick={() => setRating(n === rating ? 0 : n)} className={`text-2xl ${n <= rating ? 'text-amber-400' : 'text-slate-300 dark:text-ink-600'}`}>★</button>)}</div></Field>
        <Field label="Notes" htmlFor="notes"><Textarea id="notes" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Visible to your team" /></Field>
      </div>
      <div className="mt-5 flex flex-wrap justify-between gap-2">
        <div className="flex gap-2"><Button size="sm" href={`/app/candidates/${a.candidate.ref}`} icon={<FileText />}>Full profile</Button>
          {a.interview_ref && <Button size="sm" href={`/app/interviews/${a.interview_ref}`} icon={<Video />}>Interview report</Button>}</div>
        <span className="flex gap-2">{job.permission === 'manage' && <Button size="sm" variant="ghost" className="text-red-600" onClick={removeFromJob}>Remove from job</Button>}
          <Button variant="primary" size="sm" loading={busy} onClick={save}>Save</Button></span>
      </div>
    </Modal>
  )
}

function TeamAccess({ job, reload, canManage }: { job: Job; reload: () => void; canManage: boolean }) {
  const { data: team } = useApi<{ members: { user_id: string; name: string; email: string; role: string; role_label: string; title: string }[] }>(canManage ? '/api/team' : null)
  const [uid, setUid] = useState(''), [perm, setPerm] = useState('editor')
  useEffect(() => { setUid('') }, [job.collaborators.length])
  const candidates = (team?.members || []).filter(m => !job.collaborators.some(c => c.user_id === m.user_id) && !['owner', 'admin', 'recruiter'].includes(m.role))
  async function add() {
    try { await api(`/api/jobs/${job.id}/collaborators`, { json: { user_id: uid, permission: perm } }); toast('Access given'); reload() } catch (e: any) { toast(e.message) }
  }
  async function remove(cid: string) { try { await api(`/api/jobs/${job.id}/collaborators/${cid}`, { method: 'DELETE' }); reload() } catch (e: any) { toast(e.message) } }
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
      <Card>
        <CardHeader title="Who can work on this job" description="Owners, admins and recruiters can manage every job. Give hiring managers access to just the roles they own." />
        <CardBody>
          {!job.collaborators.length ? <p className="text-sm text-slate-500 dark:text-slate-400">No hiring managers assigned yet.</p> : (
            <ul className="divide-y divide-slate-100 dark:divide-ink-800">{job.collaborators.map(c => (
              <li key={c.id} className="flex items-center gap-3 py-3">
                <Avatar name={c.name || c.email} />
                <div className="min-w-0 flex-1"><div className="truncate font-medium">{c.name}</div><div className="truncate text-xs text-slate-500">{c.email}</div></div>
                <Badge tone={c.permission === 'editor' ? 'violet' : 'neutral'}>{c.permission === 'editor' ? 'Can edit JD' : 'Can review'}</Badge>
                {canManage && <button aria-label="Remove access" onClick={() => remove(c.id)} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600 dark:hover:bg-ink-800"><X className="size-4" /></button>}
              </li>))}</ul>
          )}
        </CardBody>
      </Card>
      {canManage && (
        <Card><CardHeader title="Give access" /><CardBody className="space-y-3">
          {!candidates.length ? <p className="text-sm text-slate-500 dark:text-slate-400">Invite hiring managers from the <a className="font-medium text-brand-600 hover:underline" href="/app/team">Team</a> page first.</p> : <>
            <Field label="Person"><Select value={uid} onChange={e => setUid(e.target.value)}><option value="">Choose…</option>{candidates.map(m => <option key={m.user_id} value={m.user_id}>{m.name || m.email}{m.title ? ` (${m.title})` : ''}</option>)}</Select></Field>
            <Field label="Access" hint={perm === 'editor' ? 'Can write and update the JD, move candidates, see matches. Cannot publish or delete.' : 'Can see the job, candidates and matches, rate and leave notes.'}>
              <Select value={perm} onChange={e => setPerm(e.target.value)}><option value="editor">Can edit the JD</option><option value="reviewer">Can review candidates</option></Select></Field>
            <Button variant="primary" className="w-full" disabled={!uid} onClick={add} icon={<UserPlus />}>Give access</Button>
          </>}
        </CardBody></Card>
      )}
    </div>
  )
}

function Activity({ id }: { id: string }) {
  const { data } = useApi<{ id: string; action: string; detail: string; at: number; user?: string }[]>(`/api/jobs/${id}/activity`)
  if (!data) return <Loading />
  return (
    <Card><CardBody>
      {!data.length ? <p className="text-sm text-slate-500">No activity yet.</p> : (
        <ol className="relative space-y-4 border-l border-slate-200 pl-5 dark:border-ink-700">
          {data.map(a => <li key={a.id} className="text-sm"><span className="absolute -left-1.5 mt-1.5 size-3 rounded-full bg-white ring-2 ring-brand-400 dark:bg-ink-900" />
            <div><Badge>{ACTION_LABEL[a.action] || a.action}</Badge> <span className="text-slate-800 dark:text-slate-100">{a.detail}</span></div>
            <div className="mt-0.5 text-xs text-slate-500">{actor(a)} · {when(a.at)}</div></li>)}
        </ol>
      )}
    </CardBody></Card>
  )
}
