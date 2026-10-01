import { Briefcase, Download, ExternalLink, FileText, Mail, MapPin, Phone, Trash2, UserPlus, Video } from 'lucide-react'
import { useState } from 'react'
import { Badge, Button, Card, CardBody, CardHeader, Select, toast } from '../components/ui'
import { Avatar, BackLink, ErrorBox, KV, Loading, PageHeader, ScoreRing, Tabs, TagInput, useApi } from '../components/kit'
import { api } from '../lib/api'
import { ago, when } from '../lib/format'
import { navigate } from '../lib/router'
import { useMe } from '../lib/session'
import type { Cand } from './JobDetail'
import { ACTION_LABEL, SOURCE_LABEL, STAGE_TONE, actor } from './labels'
import { BreakdownBars, ReportView, SkillChips, type AIReport, type Breakdown } from './match'

interface Detail extends Cand {
  tags: string[]; resume_name?: string; created_at: number; profile: Record<string, any>; parsed: Record<string, any>; resume_text: string
  applications: { id: string; job_id: string; job: string; stage: string; stage_label: string; created_at: number; rating?: number; knockout_failed?: string[]; interview_id?: string }[]
  best_jobs: { job_id: string; title: string; department: string; status: string; score: number; breakdown: Breakdown; knocked_out: string[]; ai_report?: AIReport | null }[]
  activity: { id: string; action: string; detail: string; at: number; user?: string; job?: string }[]
}

export default function CandidateDetail({ id }: { id: string }) {
  const me = useMe()
  const { data: c, error, reload } = useApi<Detail>(`/api/candidates/${id}`)
  const [tab, setTab] = useState<'fit' | 'resume' | 'profile' | 'activity'>('fit')
  const [addTo, setAddTo] = useState('')
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!c) return <Loading />
  const p = c.profile
  async function add() {
    try { await api(`/api/jobs/${addTo}/applications`, { json: { candidate_id: c!.id } }); toast('Added to the job'); setAddTo(''); reload() } catch (e: any) { toast(e.message) }
  }
  async function del() { if (!confirm(`Delete ${c!.name} and their resume? This cannot be undone.`)) return; await api(`/api/candidates/${id}`, { method: 'DELETE' }); toast('Deleted'); navigate('/app/candidates') }
  async function saveTags(tags: string[]) { try { await api(`/api/candidates/${id}`, { method: 'PATCH', json: { tags } }); reload() } catch (e: any) { toast(e.message) } }
  const notApplied = c.best_jobs.filter(b => !c.applications.some(a => a.job_id === b.job_id))
  return (
    <>
      <PageHeader back={<BackLink href="/app/candidates">All candidates</BackLink>}
        title={<span className="flex items-center gap-3"><Avatar name={c.name} size="lg" />{c.name}</span>}
        description={[c.headline, c.current_company, c.years != null ? `${c.years} years` : ''].filter(Boolean).join(' · ')}
        actions={<>{c.has_resume && <Button href={`/api/candidates/${id}/resume`} target="_blank" icon={<FileText />}>View resume</Button>}
          {c.has_resume && <Button href={`/api/candidates/${id}/resume?download=1`} icon={<Download />}>Download</Button>}</>} />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          <Tabs className="mb-4" value={tab} onChange={setTab} tabs={[{ id: 'fit', label: 'Best-fit jobs', count: c.best_jobs.length }, { id: 'resume', label: 'Resume text' }, { id: 'profile', label: 'Profile' }, { id: 'activity', label: 'Activity' }]} />
          {tab === 'fit' && (
            <div className="space-y-3">
              {!c.best_jobs.length && <Card><CardBody><p className="text-sm text-slate-500">No open jobs to compare against yet.</p></CardBody></Card>}
              {c.best_jobs.map(b => (
                <Card key={b.job_id} className="p-4 sm:p-5">
                  <div className="flex flex-wrap items-start gap-4">
                    <ScoreRing value={b.score} label="Match score" />
                    <div className="min-w-0 flex-1">
                      <a href={`/app/jobs/${b.job_id}`} className="font-semibold hover:underline">{b.title}</a>
                      <div className="text-xs text-slate-500">{b.department}{b.knocked_out.length ? ` · screened out: ${b.knocked_out.join(', ')}` : ''}</div>
                      <div className="mt-2"><SkillChips b={b.breakdown} /></div>
                    </div>
                    {me.can.manage_jobs && <Button size="sm" variant="subtle" icon={<Video />} href={`/app/interviews/new?job=${b.job_id}&candidate=${c.id}`}>Interview</Button>}
                  </div>
                  <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,300px)_1fr]"><BreakdownBars b={b.breakdown} />{b.ai_report ? <ReportView r={b.ai_report} compact /> : <p className="self-center text-xs text-slate-500">AI reports are written for each job's shortlist only.</p>}</div>
                </Card>
              ))}
            </div>
          )}
          {tab === 'resume' && <Card><CardBody><pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-700 dark:text-slate-200">{c.resume_text || 'No resume text.'}</pre></CardBody></Card>}
          {tab === 'profile' && <Card><CardBody>
            {p.summary && <p className="mb-4 text-sm leading-relaxed">{p.summary}</p>}
            {(p.experience || []).map((e: any, i: number) => <div key={i} className="mb-3"><div className="font-semibold">{e.title} · {e.company}</div><div className="text-xs text-slate-500">{e.start} – {e.end || 'Present'}</div><p className="mt-1 whitespace-pre-line text-sm">{e.description}</p></div>)}
            {(p.education || []).map((e: any, i: number) => <div key={i} className="text-sm">{e.degree} {e.field} · {e.school} {e.year}</div>)}
            <dl className="mt-4 divide-y divide-slate-100 dark:divide-ink-800">
              <KV k="Expected salary">{p.expected_salary}</KV><KV k="Current salary">{p.current_salary}</KV><KV k="Work authorisation">{p.work_authorization}</KV>
              <KV k="Willing to relocate">{p.willing_to_relocate == null ? '' : p.willing_to_relocate ? 'Yes' : 'No'}</KV><KV k="LinkedIn">{p.linkedin}</KV><KV k="Portfolio">{p.portfolio}</KV>
              <KV k="Parsed experience">{c.parsed.years != null ? `${c.parsed.years} yrs (${c.parsed.years_source})` : ''}</KV>
            </dl>
          </CardBody></Card>}
          {tab === 'activity' && <Card><CardBody><ul className="space-y-2 text-sm">{c.activity.map(a => <li key={a.id}><Badge>{ACTION_LABEL[a.action] || a.action}</Badge> {a.detail} <span className="text-xs text-slate-500">· {actor(a)} · {when(a.at)}</span></li>)}</ul></CardBody></Card>}
        </div>
        <div className="space-y-4">
          <Card><CardBody className="space-y-2 text-sm">
            {c.email && <a href={`mailto:${c.email}`} className="flex items-center gap-2 hover:underline"><Mail className="size-4 text-slate-400" />{c.email}</a>}
            {c.phone && <a href={`tel:${c.phone}`} className="flex items-center gap-2"><Phone className="size-4 text-slate-400" />{c.phone}</a>}
            {c.location && <div className="flex items-center gap-2"><MapPin className="size-4 text-slate-400" />{c.location}</div>}
            {p.linkedin && <a href={p.linkedin.startsWith('http') ? p.linkedin : `https://${p.linkedin}`} target="_blank" rel="noopener" className="flex items-center gap-2 text-brand-600 hover:underline"><ExternalLink className="size-4" />LinkedIn</a>}
            <div className="pt-2 text-xs text-slate-500">{SOURCE_LABEL[c.source] || c.source} · added {ago(c.created_at)}{c.notice_days != null ? ` · ${c.notice_days} days notice` : ''}</div>
          </CardBody></Card>
          <Card><CardHeader title="Applications" /><CardBody className="space-y-2 pt-3">
            {!c.applications.length && <p className="text-sm text-slate-500">Not in any job pipeline yet.</p>}
            {c.applications.map(a => <a key={a.id} href={`/app/jobs/${a.job_id}?tab=pipeline`} className="flex items-center justify-between gap-2 rounded-lg p-2 text-sm hover:bg-slate-50 dark:hover:bg-ink-850"><span className="flex items-center gap-2"><Briefcase className="size-4 text-slate-400" />{a.job}</span><Badge tone={STAGE_TONE[a.stage]}>{a.stage_label}</Badge></a>)}
            {me.can.manage_jobs && notApplied.length > 0 && <div className="flex gap-2 pt-2">
              <Select aria-label="Job" className="py-1.5 text-[13px]" value={addTo} onChange={e => setAddTo(e.target.value)}><option value="">Add to a job…</option>{notApplied.map(b => <option key={b.job_id} value={b.job_id}>{b.title}</option>)}</Select>
              <Button size="sm" disabled={!addTo} onClick={add} icon={<UserPlus />}>Add</Button></div>}
          </CardBody></Card>
          <Card><CardHeader title="Skills" /><CardBody className="pt-3"><div className="flex flex-wrap gap-1.5">{c.skills.map(s => <span key={s} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-ink-800 dark:text-slate-200">{s}</span>)}</div></CardBody></Card>
          {me.can.manage_jobs && <Card><CardHeader title="Tags" /><CardBody className="pt-3"><TagInput value={c.tags} onChange={saveTags} placeholder="e.g. referral, top-10" /></CardBody></Card>}
          {me.can.manage_jobs && <Button variant="ghost" className="w-full text-red-600 dark:text-red-400" icon={<Trash2 />} onClick={del}>Delete candidate</Button>}
        </div>
      </div>
    </>
  )
}
