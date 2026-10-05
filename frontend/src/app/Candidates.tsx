import { FileUp, Plus, Search, Upload, Users } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Alert, Badge, Button, Card, Field, Input, Modal, Select, Textarea, cn, toast } from '../components/ui'
import { Ago, Avatar, Empty, ErrorBox, ListSkeleton, PageHeader, Pager, TagInput, useApi } from '../components/kit'
import { api } from '../lib/api'
import { navigate, useLocation } from '../lib/router'
import { useMe } from '../lib/session'
import type { Cand } from './JobDetail'
import { SOURCE_LABEL } from './labels'

type Row = Cand & { applications: number; applied_to?: { job: string; stage: string; stage_label: string }[]; created_at: number; tags: string[]; resume_name?: string }

export default function Candidates() {
  const me = useMe()
  const { query } = useLocation()
  const [q, setQ] = useState(''), [dq, setDq] = useState(''), [skill, setSkill] = useState(''), [minY, setMinY] = useState(''), [src, setSrc] = useState(''), [page, setPage] = useState(1)
  useEffect(() => { const t = setTimeout(() => { setDq(q); setPage(1) }, 300); return () => clearTimeout(t) }, [q])
  const params = new URLSearchParams({ q: dq, skill, source: src, page: String(page), limit: '25', ...(minY ? { min_years: minY } : {}) })
  const { data, error, reload } = useApi<{ total: number; page: number; limit: number; items: Row[] }>(`/api/candidates?${params}`)
  const [upload, setUpload] = useState(query.get('upload') === '1'), [add, setAdd] = useState(false)
  return (
    <>
      <PageHeader title="Candidates" description={me.can.see_all ? 'Your talent pool: every resume uploaded, every applicant, everyone who joined the talent pool.' : 'Candidates on the jobs you have access to.'}
        actions={me.can.manage_jobs && <><Button icon={<Plus />} onClick={() => setAdd(true)}>Add manually</Button><Button variant="primary" icon={<Upload />} onClick={() => setUpload(true)}>Upload resumes</Button></>} />
      <Card className="overflow-hidden">
        <div className="grid gap-2 border-b border-slate-100 p-4 dark:border-ink-800 md:grid-cols-[2fr_1fr_1fr_1fr]">
          <div className="relative"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-500 dark:text-slate-400" />
            <Input type="search" aria-label="Search candidates" className="pl-9" placeholder="Search name, email, title, resume text" value={q} onChange={e => setQ(e.target.value)} /></div>
          <Input aria-label="Skill" placeholder="Skill, e.g. React" value={skill} onChange={e => { setSkill(e.target.value); setPage(1) }} />
          <Select aria-label="Experience" value={minY} onChange={e => { setMinY(e.target.value); setPage(1) }}><option value="">Any experience</option>{[1, 2, 3, 5, 8, 10].map(n => <option key={n} value={n}>{n}+ years</option>)}</Select>
          <Select aria-label="Source" value={src} onChange={e => { setSrc(e.target.value); setPage(1) }}><option value="">All sources</option>{Object.entries(SOURCE_LABEL).filter(([k]) => k !== 'sourced').map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
        </div>
        {error ? <div className="p-5"><ErrorBox error={error} retry={reload} /></div> : !data ? <ListSkeleton rows={8} /> : !data.items.length ? (
          dq || skill || minY || src ? <p className="p-10 text-center text-sm text-slate-500">No candidates match.</p>
            : <Empty icon={<Users />} title="No candidates yet" action={me.can.manage_jobs && <Button variant="primary" icon={<Upload />} onClick={() => setUpload(true)}>Upload resumes</Button>}>Upload resumes in bulk (PDF, DOCX or TXT), or share your careers page.</Empty>
        ) : (
          <>
            <ul className="divide-y divide-slate-100 dark:divide-ink-800">
              {data.items.map(c => (
                <li key={c.id}><a href={`/app/candidates/${c.ref}`} className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-slate-50/80 dark:hover:bg-ink-850 sm:px-5">
                  <Avatar name={c.name} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-slate-900 dark:text-white">{c.name}</span><Badge>{SOURCE_LABEL[c.source] || c.source}</Badge>
</div>
                    <div className="truncate text-xs text-slate-500 dark:text-slate-400">{[c.headline, c.years != null ? `${c.years} yrs` : '', c.location, c.email].filter(Boolean).join(' · ')}</div>
                    {!!c.applied_to?.length && <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs"><span className="text-slate-500 dark:text-slate-400">Applied to</span>
                      {c.applied_to.map((a, i) => <span key={i} className="inline-flex items-center gap-1 rounded-md bg-brand-50 px-1.5 py-0.5 font-medium text-brand-800 dark:bg-brand-500/15 dark:text-brand-200">{a.job}<span className={cn('font-normal', a.stage === 'rejected' || a.stage === 'withdrawn' ? 'text-red-600 dark:text-red-300' : a.stage === 'offer' || a.stage === 'hired' ? 'text-emerald-700 dark:text-emerald-300' : 'text-brand-600/80 dark:text-brand-300/80')}>· {a.stage_label}</span></span>)}
                      {c.applications > c.applied_to.length && <span className="text-slate-500 dark:text-slate-400">+{c.applications - c.applied_to.length} more</span>}</div>}
                    <div className="mt-1.5 flex flex-wrap gap-1">{c.skills.slice(0, 8).map(s => <span key={s} className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-600 dark:bg-ink-800 dark:text-slate-300">{s}</span>)}{c.skills.length > 8 && <span className="text-[11px] text-slate-500 dark:text-slate-400">+{c.skills.length - 8}</span>}</div>
                  </div>
                  <span className="text-xs text-slate-500 dark:text-slate-400"><Ago ts={c.created_at} /></span>
                </a></li>
              ))}
            </ul>
            <Pager page={data.page} total={data.total} limit={data.limit} onPage={setPage} />
          </>
        )}
      </Card>
      <UploadDialog open={upload} onClose={() => { setUpload(false); if (query.get('upload')) navigate('/app/candidates', { replace: true }) }} onDone={reload} />
      <AddDialog open={add} onClose={() => setAdd(false)} onDone={reload} />
    </>
  )
}

function UploadDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const ref = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<File[]>([]), [busy, setBusy] = useState(false), [res, setRes] = useState<any>(null), [drag, setDrag] = useState(false)
  async function go() {
    setBusy(true); setRes(null)
    const all = { created: 0, updated: 0, failed: [] as any[] }
    const batches: File[][] = []                             // at most 25 files / 4 MB per request
    for (const f of files) {
      const last = batches[batches.length - 1]
      if (last && last.length < 25 && last.reduce((a, x) => a + x.size, 0) + f.size <= 4e6) last.push(f)
      else batches.push([f])
    }
    for (const b of batches) {
      const fd = new FormData(); b.forEach(f => fd.append('files', f))
      try { const r = await api('/api/candidates/upload', { method: 'POST', body: fd }); all.created += r.created; all.updated += r.updated; all.failed.push(...r.failed) }
      catch (e: any) { all.failed.push(...b.map(f => ({ file: f.name, error: e.message }))) }
    }
    setRes(all); setBusy(false); setFiles([]); onDone()
  }
  const pick = (list: FileList | null) => list && setFiles(f => [...f, ...Array.from(list)].slice(0, 500))
  return (
    <Modal open={open} onOpenChange={o => !o && (onClose(), setRes(null), setFiles([]))} title="Upload resumes" description="PDF, DOCX or TXT, up to 500 at a time. Names, emails, skills, experience and notice period are read automatically. Re-uploading the same email updates that candidate.">
      <div className="mt-4 space-y-3">
        <button type="button" onClick={() => ref.current?.click()} onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={e => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files) }}
          className={`grid w-full place-items-center rounded-2xl border-2 border-dashed px-4 py-8 text-center transition-colors ${drag ? 'border-brand-500 bg-brand-50 dark:bg-brand-500/10' : 'border-slate-200 hover:border-brand-300 dark:border-ink-700'}`}>
          <FileUp className="size-6 text-brand-500" /><span className="mt-2 text-sm font-semibold">Drop files or click to choose</span><span className="text-xs text-slate-500">{files.length ? `${files.length} file${files.length > 1 ? 's' : ''} selected` : 'Max 10 MB each'}</span>
        </button>
        <input ref={ref} type="file" multiple accept=".pdf,.docx,.txt,.md,.rtf,.png,.jpg,.jpeg,.webp" className="hidden" onChange={e => { pick(e.target.files); e.target.value = '' }} />
        {res && <Alert tone={res.failed.length ? 'warning' : 'success'} title={`${res.created} added, ${res.updated} updated${res.failed.length ? `, ${res.failed.length} failed` : ''}`}>
          {res.failed.slice(0, 5).map((f: any, i: number) => <div key={i} className="text-xs">{f.file}: {f.error}</div>)}</Alert>}
        <Button variant="primary" className="w-full" disabled={!files.length} loading={busy} onClick={go} icon={<Upload />}>{busy ? 'Reading resumes…' : `Upload ${files.length || ''}`}</Button>
      </div>
    </Modal>
  )
}

function AddDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ name: '', email: '', phone: '', location: '', headline: '', total_experience_years: '', notice_days: '', resume_text: '' })
  const [sk, setSk] = useState<string[]>([]), [err, setErr] = useState(''), [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF(v => ({ ...v, [k]: e.target.value }))
  async function save() {
    setBusy(true); setErr('')
    try { const c = await api('/api/candidates', { json: { ...f, skills: sk } }); toast('Candidate added'); onDone(); onClose(); navigate(`/app/candidates/${c.ref}`) } catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  return (
    <Modal open={open} onOpenChange={o => !o && onClose()} title="Add a candidate">
      <div className="mt-4 grid max-h-[65vh] gap-3 overflow-y-auto pr-1 sm:grid-cols-2">
        {err && <Alert className="sm:col-span-2" tone="danger">{err}</Alert>}
        <Field label="Name *" htmlFor="c-name"><Input id="c-name" value={f.name} onChange={set('name')} /></Field>
        <Field label="Email" htmlFor="c-email"><Input id="c-email" type="email" value={f.email} onChange={set('email')} /></Field>
        <Field label="Phone" htmlFor="c-phone"><Input id="c-phone" value={f.phone} onChange={set('phone')} /></Field>
        <Field label="Location" htmlFor="c-loc"><Input id="c-loc" value={f.location} onChange={set('location')} /></Field>
        <Field className="sm:col-span-2" label="Current title" htmlFor="c-head"><Input id="c-head" value={f.headline} onChange={set('headline')} /></Field>
        <Field label="Experience (years)" htmlFor="c-yrs"><Input id="c-yrs" type="number" value={f.total_experience_years} onChange={set('total_experience_years')} /></Field>
        <Field label="Notice (days)" htmlFor="c-not"><Input id="c-not" type="number" value={f.notice_days} onChange={set('notice_days')} /></Field>
        <Field className="sm:col-span-2" label="Skills"><TagInput value={sk} onChange={setSk} placeholder="Type and press Enter" /></Field>
        <Field className="sm:col-span-2" label="Resume text or notes" htmlFor="c-cv"><Textarea id="c-cv" value={f.resume_text} onChange={set('resume_text')} /></Field>
      </div>
      <div className="mt-5 flex justify-end"><Button variant="primary" loading={busy} onClick={save}>Add candidate</Button></div>
    </Modal>
  )
}
