import { Briefcase, Download, ExternalLink, FileText, Mail, MapPin, Pencil, Phone, Trash2, UserPlus, Video, FileBarChart } from 'lucide-react'
import { useState } from 'react'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Field, Input, Modal, Select, Textarea, toast } from '../components/ui'
import { Ago, Avatar, BackLink, ErrorBox, KV, PageHeader, PageSkeleton, ScoreRing, Tabs, TagInput, useApi } from '../components/kit'
import { api } from '../lib/api'
import { when } from '../lib/format'
import { navigate } from '../lib/router'
import { useMe } from '../lib/session'
import type { Cand } from './JobDetail'
import { ACTION_LABEL, SOURCE_LABEL, STAGE_TONE, actor } from './labels'
import { BreakdownBars, ReportView, SkillChips, type AIReport, type Breakdown } from './match'
import { ask } from '../components/dialogs'

interface Detail extends Cand {
  tags: string[]; resume_name?: string; resume_type?: string; resume_v?: string; college?: string; created_at: number; profile: Record<string, any>; parsed: Record<string, any>; resume_text: string
  applications: { id: string; ref?: string; job_id: string; job_ref: string; interview_ref?: string; job: string; department?: string; job_status?: string; stage: string; stage_label: string; created_at: number; updated_at?: number; source?: string; round?: string | null; round_status?: string | null; rating?: number; knockout_failed?: string[]; interview_id?: string }[]
  best_jobs: { job_id: string; job_ref: string; title: string; department: string; status: string; score: number; breakdown: Breakdown; knocked_out: string[]; ai_report?: AIReport | null }[]
  best_fit_min_score?: number
  activity: { id: string; action: string; detail: string; at: number; user?: string; job?: string }[]
}

export default function CandidateDetail({ id }: { id: string }) {
  const me = useMe()
  const { data: c, error, reload } = useApi<Detail>(`/api/candidates/${id}`)
  const [tab, setTab] = useState<'apps' | 'fit' | 'resume' | 'text' | 'profile' | 'activity' | null>(c0Tab())
  const [editing, setEditing] = useState(false)
  const [addTo, setAddTo] = useState('')
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!c) return <PageSkeleton />
  const p = c.profile
  const cur = tab ?? (c.applications.length ? 'apps' : 'fit')
  async function add() {
    try { await api(`/api/jobs/${addTo}/applications`, { json: { candidate_id: c!.id } }); toast('Added to the job'); setAddTo(''); reload() } catch (e: any) { toast(e.message) }
  }
  async function del() { if (!await ask(`Delete ${c!.name} and their resume? This cannot be undone.`)) return; await api(`/api/candidates/${id}`, { method: 'DELETE' }); toast('Deleted'); navigate('/app/candidates') }
  async function saveTags(tags: string[]) { try { await api(`/api/candidates/${id}`, { method: 'PATCH', json: { tags } }); reload() } catch (e: any) { toast(e.message) } }
  const notApplied = c.best_jobs.filter(b => !c.applications.some(a => a.job_id === b.job_id))
  return (
    <>
      <PageHeader back={<BackLink href="/app/candidates">All candidates</BackLink>}
        title={<span className="flex items-center gap-3"><Avatar name={c.name} size="lg" />{c.name}</span>}
        description={[c.headline, c.current_company, c.years != null ? `${c.years} years` : ''].filter(Boolean).join(' · ')}
        actions={<>{c.has_resume && <Button onClick={() => setTab('resume')} icon={<FileText />}>View resume</Button>}
          {c.has_resume && <Button href={`/api/candidates/${c.id}/resume?download=1&v=${c.resume_v}`} icon={<Download />}>Download</Button>}
          {me.can.manage_jobs && <Button variant="primary" onClick={() => setEditing(true)} icon={<Pencil />}>Edit</Button>}</>} />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          <Tabs className="mb-4" value={cur} onChange={setTab} tabs={[{ id: 'apps', label: 'Applied to', count: c.applications.length }, { id: 'fit', label: 'Best-fit jobs', count: c.best_jobs.length }, ...(c.has_resume ? [{ id: 'resume' as const, label: 'Resume' }] : []),
            { id: 'text', label: 'Resume text' }, { id: 'profile', label: 'Profile' }, { id: 'activity', label: 'Activity' }]} />
          {cur === 'apps' && (
            <div className="space-y-3">
              {!c.applications.length && <Card><CardBody><p className="text-sm font-medium">Hasn't applied to any job yet</p>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{me.can.manage_jobs ? 'Add them to a job from the panel on the right, or check Best-fit jobs.' : 'They show here once they apply or HR adds them to a job.'}</p></CardBody></Card>}
              {c.applications.map(a => (
                <Card key={a.id} className="p-4 sm:p-5">
                  <div className="flex flex-wrap items-start gap-3">
                    <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300"><Briefcase className="size-5" /></span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2"><a href={`/app/jobs/${a.job_ref}`} className="font-semibold hover:underline">{a.job}</a>
                        <Badge tone={STAGE_TONE[a.stage]}>{a.stage_label}</Badge>{a.job_status && a.job_status !== 'open' && <Badge>Job {a.job_status}</Badge>}</div>
                      <div className="mt-1 text-sm text-slate-600 dark:text-slate-300">{a.round ? <>Now at <b>{a.round}</b>{a.round_status ? ` · ${a.round_status.replace(/_/g, ' ')}` : ''}</> : a.stage_label}</div>
                      <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{[a.department, `applied ${when(a.created_at)}`, a.source ? (SOURCE_LABEL[a.source] || a.source) : '', a.rating ? `rated ${a.rating}/5` : ''].filter(Boolean).join(' · ')}</div>
                      {!!a.knockout_failed?.length && <div className="mt-1.5 text-xs text-red-600 dark:text-red-400">Knockouts: {a.knockout_failed.join('; ')}</div>}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" variant="primary" href={`/app/jobs/${a.job_ref}?tab=pipeline&app=${a.ref || a.id}`}>Open in pipeline</Button>
                      {a.interview_ref && <Button size="sm" icon={<Video />} href={`/app/interviews/${a.interview_ref}`}>Interview report</Button>}
                    </div>
                  </div>
                </Card>))}
            </div>
          )}
          {cur === 'fit' && (
            <div className="space-y-3">
              {!c.best_jobs.length && <Card><CardBody>
                <p className="text-sm font-medium">Not a strong fit for any open job right now</p>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Jobs show here only when {c.name.split(' ')[0]} scores at least {c.best_fit_min_score ?? 55} and isn't screened out. New jobs are checked automatically.{me.can.manage_team && <> You can change the minimum in <a className="underline" href="/app/settings?tab=matching">Settings, Matching</a>.</>}</p>
              </CardBody></Card>}
              {c.best_jobs.map(b => (
                <Card key={b.job_id} className="p-4 sm:p-5">
                  <div className="flex flex-wrap items-start gap-4">
                    <ScoreRing value={b.score} label="Match score" />
                    <div className="min-w-0 flex-1">
                      <a href={`/app/jobs/${b.job_ref}`} className="font-semibold hover:underline">{b.title}</a>
                      <div className="text-xs text-slate-500">{b.department}{b.knocked_out.length ? ` · screened out: ${b.knocked_out.join(', ')}` : ''}</div>
                      <div className="mt-2"><SkillChips b={b.breakdown} /></div>
                    </div>
                    <Button size="sm" variant="ghost" icon={<FileBarChart />} href={`/app/jobs/${b.job_ref}/match/${c.ref}`}>Full report</Button>
                    {me.can.manage_jobs && <Button size="sm" variant="subtle" icon={<Video />} href={`/app/interviews/new?job=${b.job_ref}&candidate=${c.ref}`}>Interview</Button>}
                  </div>
                  <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,300px)_1fr]"><BreakdownBars b={b.breakdown} />{b.ai_report ? <ReportView r={b.ai_report} compact /> : <p className="self-center text-xs text-slate-500">AI reports are written for each job's shortlist only.</p>}</div>
                </Card>
              ))}
            </div>
          )}
          {cur === 'resume' && c.has_resume && <ResumeViewer c={c} />}
          {cur === 'text' && <Card><CardBody><pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-700 dark:text-slate-200">{c.resume_text || 'No resume text.'}</pre></CardBody></Card>}
          {cur === 'profile' && <Card><CardBody>
            {p.summary && <p className="mb-4 text-sm leading-relaxed">{p.summary}</p>}
            {(p.experience || []).map((e: any, i: number) => <div key={i} className="mb-3"><div className="font-semibold">{e.title} · {e.company}</div><div className="text-xs text-slate-500">{e.start} – {e.end || 'Present'}</div><p className="mt-1 whitespace-pre-line text-sm">{e.description}</p></div>)}
            {(p.education || []).map((e: any, i: number) => <div key={i} className="text-sm">{e.degree} {e.field} · {e.school} {e.year}</div>)}
            <dl className="mt-4 divide-y divide-slate-100 dark:divide-ink-800">
              <KV k="Expected salary">{p.expected_salary}</KV><KV k="Current salary">{p.current_salary}</KV><KV k="Work authorisation">{p.work_authorization}</KV>
              <KV k="Willing to relocate">{p.willing_to_relocate == null ? '' : p.willing_to_relocate ? 'Yes' : 'No'}</KV><KV k="LinkedIn">{p.linkedin}</KV><KV k="Portfolio">{p.portfolio}</KV>
              <KV k="Parsed experience">{c.parsed.years != null ? `${c.parsed.years} yrs (${c.parsed.years_source})` : ''}</KV>
            </dl>
          </CardBody></Card>}
          {cur === 'activity' && <Card><CardBody><ul className="space-y-2 text-sm">{c.activity.map(a => <li key={a.id}><Badge>{ACTION_LABEL[a.action] || a.action}</Badge> {a.detail} <span className="text-xs text-slate-500">· {actor(a)} · {when(a.at)}</span></li>)}</ul></CardBody></Card>}
        </div>
        <div className="space-y-4">
          <Card><CardBody className="space-y-2 text-sm">
            {c.email && <a href={`mailto:${c.email}`} className="flex items-center gap-2 hover:underline"><Mail className="size-4 text-slate-400" />{c.email}</a>}
            {c.phone && <a href={`tel:${c.phone}`} className="flex items-center gap-2"><Phone className="size-4 text-slate-400" />{c.phone}</a>}
            {c.location && <div className="flex items-center gap-2"><MapPin className="size-4 text-slate-400" />{c.location}</div>}
            {p.linkedin && <a href={p.linkedin.startsWith('http') ? p.linkedin : `https://${p.linkedin}`} target="_blank" rel="noopener" className="flex items-center gap-2 text-brand-600 dark:text-brand-400 hover:underline"><ExternalLink className="size-4" />LinkedIn</a>}
            <div className="pt-2 text-xs text-slate-500">{SOURCE_LABEL[c.source] || c.source} · added <Ago ts={c.created_at} />{c.notice_days != null ? ` · ${c.notice_days} days notice` : ''}</div>
          </CardBody></Card>
          <Card><CardHeader title="Applications" /><CardBody className="space-y-2 pt-3">
            {!c.applications.length && <p className="text-sm text-slate-500">Not in any job pipeline yet.</p>}
            {c.applications.map(a => <a key={a.id} href={`/app/jobs/${a.job_ref}?tab=pipeline&app=${a.ref || a.id}`} className="flex items-center justify-between gap-2 rounded-lg p-2 text-sm hover:bg-slate-50 dark:hover:bg-ink-850"><span className="flex items-center gap-2"><Briefcase className="size-4 text-slate-400" />{a.job}</span><Badge tone={STAGE_TONE[a.stage]}>{a.stage_label}</Badge></a>)}
            {me.can.manage_jobs && notApplied.length > 0 && <div className="flex gap-2 pt-2">
              <Select aria-label="Job" className="py-1.5 text-[13px]" value={addTo} onChange={e => setAddTo(e.target.value)}><option value="">Add to a job…</option>{notApplied.map(b => <option key={b.job_id} value={b.job_id}>{b.title}</option>)}</Select>
              <Button size="sm" disabled={!addTo} onClick={add} icon={<UserPlus />}>Add</Button></div>}
          </CardBody></Card>
          <Card><CardHeader title="Skills" /><CardBody className="pt-3"><div className="flex flex-wrap gap-1.5">{c.skills.map(s => <span key={s} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-ink-800 dark:text-slate-200">{s}</span>)}</div></CardBody></Card>
          {me.can.manage_jobs && <Card><CardHeader title="Tags" /><CardBody className="pt-3"><TagInput value={c.tags} onChange={saveTags} placeholder="e.g. referral, top-10" /></CardBody></Card>}
          {me.can.manage_jobs && <Button variant="ghost" className="w-full text-red-600 dark:text-red-400" icon={<Trash2 />} onClick={del}>Delete candidate</Button>}
        </div>
      </div>
      {editing && <EditCandidate c={c} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); reload() }} />}
    </>
  )
}

function c0Tab(): 'apps' | 'fit' | 'resume' | null {
  const t = new URLSearchParams(location.search).get('tab')
  return t === 'resume' || t === 'fit' || t === 'apps' ? t : null
}

function ResumeViewer({ c }: { c: Detail }) {
  const src = `/api/candidates/${c.id}/resume?v=${c.resume_v}`
  const [loaded, setLoaded] = useState(false)
  if (c.resume_type !== 'pdf') return (
    <Card><CardBody>
      <Alert tone="info" title={`${(c.resume_type || 'This').toUpperCase()} files can't be shown in the browser`}>Here is the text read from it. <a className="font-semibold underline" href={`${src}&download=1`}>Download the original</a>.</Alert>
      <pre className="mt-4 whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-700 dark:text-slate-200">{c.resume_text || 'No text could be read from this file.'}</pre>
    </CardBody></Card>)
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5 text-sm dark:border-ink-800">
        <span className="truncate font-medium">{c.resume_name || 'Resume'}</span>
        <span className="flex gap-2"><Button size="sm" variant="ghost" href={src} target="_blank" icon={<ExternalLink />}>Open in new tab</Button>
          <Button size="sm" variant="ghost" href={`${src}&download=1`} icon={<Download />}>Download</Button></span>
      </div>
      <div className="relative h-[78vh] bg-slate-100 dark:bg-ink-850">
        {!loaded && <div className="absolute inset-0 grid place-items-center text-sm text-slate-500">Loading resume…</div>}
        <iframe title={`Resume of ${c.name}`} src={`${src}#view=FitH`} onLoad={() => setLoaded(true)} className="relative size-full" />
      </div>
    </Card>
  )
}

function EditCandidate({ c, onClose, onSaved }: { c: Detail; onClose: () => void; onSaved: () => void }) {
  const p = c.profile || {}
  const [f, setF] = useState<Record<string, string>>({
    name: c.name || '', email: c.email || '', phone: c.phone || '', location: c.location || '', headline: c.headline || '',
    current_company: c.current_company || '', total_experience_years: c.years != null ? String(c.years) : '', notice_days: c.notice_days != null ? String(c.notice_days) : '',
    expected_salary: p.expected_salary != null ? String(p.expected_salary) : '', current_salary: p.current_salary != null ? String(p.current_salary) : '',
    college: c.college || p.college || '', linkedin: p.linkedin || '', portfolio: p.portfolio || '', summary: p.summary || '', work_authorization: p.work_authorization || '',
  })
  const [sk, setSk] = useState<string[]>(c.skills)
  const [busy, setBusy] = useState(false), [err, setErr] = useState('')
  const set = (k: string) => (e: { target: { value: string } }) => setF(v => ({ ...v, [k]: e.target.value }))
  async function save() {
    if (!f.name.trim()) { setErr('Name is required.'); return }
    setBusy(true); setErr('')
    try { await api(`/api/candidates/${c.id}`, { method: 'PATCH', json: { profile: { ...f, skills: sk } } }); toast('Candidate updated'); onSaved() }
    catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  const F = (k: string, label: string, type = 'text', wide = false) => (
    <Field className={wide ? 'sm:col-span-2' : ''} label={label} htmlFor={`e-${k}`}><Input id={`e-${k}`} type={type} value={f[k]} onChange={set(k)} /></Field>)
  return (
    <Modal open onOpenChange={o => !o && onClose()} title={`Edit ${c.name}`}>
      <div className="mt-4 grid max-h-[65vh] gap-3 overflow-y-auto pr-1 sm:grid-cols-2">
        {err && <Alert className="sm:col-span-2" tone="danger">{err}</Alert>}
        {F('name', 'Name *')}{F('email', 'Email', 'email')}{F('phone', 'Phone', 'tel')}{F('location', 'Current city')}
        {F('headline', 'Current title')}{F('current_company', 'Current company')}{F('total_experience_years', 'Experience (years)', 'number')}{F('notice_days', 'Notice period (days)', 'number')}
        {F('expected_salary', 'Expected salary (per year)', 'number')}{F('current_salary', 'Current salary (per year)', 'number')}{F('college', 'College')}{F('work_authorization', 'Work authorisation')}
        {F('linkedin', 'LinkedIn', 'text', true)}{F('portfolio', 'Portfolio / GitHub', 'text', true)}
        <Field className="sm:col-span-2" label="Skills"><TagInput value={sk} onChange={setSk} placeholder="Type a skill and press Enter" /></Field>
        <Field className="sm:col-span-2" label="Summary" htmlFor="e-summary"><Textarea id="e-summary" className="min-h-0" rows={3} value={f.summary} onChange={set('summary')} /></Field>
      </div>
      <div className="mt-5 flex justify-end gap-2"><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save}>Save changes</Button></div>
    </Modal>
  )
}
