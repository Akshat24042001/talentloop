// Public pages: the candidate's application status, the manager's decision page, the interviewer's feedback
// page, campus drive registration and the placement officer's results.
import { Camera, Check, CircleCheck, Circle, CircleDot, ClipboardList, FileText, Hand, Mic, RotateCcw, Square, Star, Trash2, UserRound, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Alert, Badge, Button, Card, Field, Input, Modal, Select, Textarea, cn } from '../components/ui'
import { when } from '../lib/format'
import { Frame, HowItWorks, PageState, Preview, grab, send, useCamera, useLoad, type Brand, type Transparency } from './common'

// ---------------------------------------------------------------------------------------------- status page
interface Status {
  org: Brand; job: { title: string; ref: string }; candidate: { name: string; email: string }; stage: string; stage_label: string; applied_at: number
  steps: { name: string; type: string; status: string; label: string; current: boolean; link: string | null; transparency: Transparency | null }[]
  human_requested: boolean; accommodation: { request?: string; status?: string; extra_time_pct?: number; hr_note?: string } | null; has_ai_round: boolean; contact: string
}

export function StatusPage({ token }: { token: string }) {
  const { data, error, reload } = useLoad<Status>(`/api/status/${token}`)
  const [modal, setModal] = useState<'' | 'acc' | 'human' | 'withdraw' | 'delete'>(''), [text, setText] = useState(''), [err, setErr] = useState(''), [deleted, setDeleted] = useState(false)
  useEffect(() => { if (data) document.title = `Your application · ${data.org.name}` }, [data])
  if (deleted) return <Frame><Alert tone="success" title="Your data has been deleted">Your profile, resume, applications and recordings with this company were erased.</Alert></Frame>
  if (error || !data) return <PageState error={error} loading={!data} />
  const base = `/api/status/${token}`
  async function act(path: string, body: unknown) {
    setErr('')
    try { await send(`${base}/${path}`, body); setModal(''); setText(''); if (path === 'delete') setDeleted(true); else reload() } catch (e: any) { setErr(e.message) }
  }
  const closed = ['rejected', 'withdrawn', 'offer', 'hired'].includes(data.stage)
  const cur = data.steps.find(s => s.current)
  return (
    <Frame org={data.org}>
      <p className="text-sm text-slate-500">Hi {data.candidate.name.split(' ')[0]}, your application for</p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight">{data.job.title}</h1>
      <div className="mt-2 flex flex-wrap items-center gap-2"><Badge tone={data.stage === 'rejected' ? 'danger' : ['offer', 'hired'].includes(data.stage) ? 'success' : 'brand'}>{data.stage_label}</Badge><span className="text-sm text-slate-500">Applied {when(data.applied_at)}</span></div>
      {cur?.link && !closed && <Card className="mt-5 flex flex-wrap items-center gap-3 p-5"><div className="min-w-0 flex-1"><div className="text-sm text-slate-500">Your next step</div><div className="font-semibold">{cur.name}</div></div><Button variant="primary" href={cur.link}>Open</Button></Card>}
      <Card className="mt-5 p-5">
        <ol className="space-y-3">{data.steps.map((s, i) => {
          const done = ['passed', 'submitted', 'skipped'].includes(s.status), bad = ['failed', 'expired', 'no_show'].includes(s.status)
          return (
            <li key={i} className="flex items-start gap-3">
              {done ? <CircleCheck className="mt-0.5 size-5 text-emerald-500" /> : s.current ? <CircleDot className="mt-0.5 size-5 text-brand-500" /> : bad ? <X className="mt-0.5 size-5 text-red-500" /> : <Circle className="mt-0.5 size-5 text-slate-300" />}
              <div className="min-w-0 flex-1"><div className={cn('text-sm font-semibold', !s.current && !done && 'text-slate-500')}>{s.name}</div><div className="text-xs text-slate-500">{s.label}</div>
                {s.current && s.transparency && <details className="mt-1"><summary className="cursor-pointer text-xs font-medium text-brand-600 dark:text-brand-400">How this step works</summary><HowItWorks className="mt-2" t={s.transparency} /></details>}</div>
              {s.link && <Button size="sm" href={s.link}>Open</Button>}
            </li>)
        })}</ol>
      </Card>
      {data.accommodation?.request && <Alert className="mt-4" tone={data.accommodation.status === 'declined' ? 'warning' : 'info'} title={`Your accommodation request: ${data.accommodation.status}`}>
        "{data.accommodation.request}"{data.accommodation.status === 'approved' && data.accommodation.extra_time_pct ? ` You have ${data.accommodation.extra_time_pct}% extra time on tests.` : ''}{data.accommodation.hr_note ? ` ${data.accommodation.hr_note}` : ''}</Alert>}
      {data.human_requested && <Alert className="mt-4" tone="info" icon={<UserRound />}>You asked for an interview with a person. The hiring team will get back to you.</Alert>}
      {!closed && <Card className="mt-5 p-5 text-sm">
        <div className="font-semibold">Need something?</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {!data.accommodation?.request && <Button size="sm" icon={<Hand />} onClick={() => setModal('acc')}>Ask for an accommodation</Button>}
          {data.has_ai_round && !data.human_requested && <Button size="sm" icon={<UserRound />} onClick={() => setModal('human')}>Ask for a human interviewer</Button>}
          <Button size="sm" variant="ghost" onClick={() => setModal('withdraw')}>Withdraw my application</Button>
        </div>
        {data.contact && <p className="mt-3 text-slate-500">Questions: {data.contact}</p>}
      </Card>}
      <p className="mt-6 text-center"><button className="text-xs text-slate-500 hover:text-red-600 hover:underline" onClick={() => setModal('delete')}><Trash2 className="mr-1 inline size-3" />Delete all my data with {data.org.name}</button></p>
      <Modal open={modal === 'acc'} onOpenChange={() => setModal('')} title="Ask for an accommodation" description="For example extra time on tests, a screen reader, captions, or a different interview format. Only the hiring team sees this."
        footer={<><Button onClick={() => setModal('')}>Cancel</Button><Button variant="primary" disabled={text.trim().length < 5} onClick={() => act('accommodation', { request: text })}>Send</Button></>}>
        {err && <Alert className="mt-3" tone="danger">{err}</Alert>}<Textarea className="mt-4" rows={4} aria-label="What you need" value={text} onChange={e => setText(e.target.value)} /></Modal>
      <Modal open={modal === 'human'} onOpenChange={() => setModal('')} title="Ask for a human interviewer" description="The hiring team decides and replies. A note helps (optional)."
        footer={<><Button onClick={() => setModal('')}>Cancel</Button><Button variant="primary" onClick={() => act('human', { note: text })}>Send request</Button></>}>
        <Textarea className="mt-4" rows={3} aria-label="Note" value={text} onChange={e => setText(e.target.value)} /></Modal>
      <Modal open={modal === 'withdraw'} onOpenChange={() => setModal('')} title="Withdraw your application?" description="You won't get further steps for this role. Your data is kept unless you delete it."
        footer={<><Button onClick={() => setModal('')}>Keep my application</Button><Button variant="danger" onClick={() => act('withdraw', {})}>Withdraw</Button></>}>{err && <Alert className="mt-3" tone="danger">{err}</Alert>}</Modal>
      <Modal open={modal === 'delete'} onOpenChange={() => setModal('')} title="Delete all your data?" description={`This erases your profile, resume, every application and recording with ${data.org.name}. It can't be undone. Type DELETE to confirm.`}
        footer={<><Button onClick={() => setModal('')}>Cancel</Button><Button variant="danger" disabled={text !== 'DELETE'} onClick={() => act('delete', { confirm: text })}>Delete everything</Button></>}>
        {err && <Alert className="mt-3" tone="danger">{err}</Alert>}<Input className="mt-4" aria-label="Type DELETE" value={text} onChange={e => setText(e.target.value)} /></Modal>
    </Frame>
  )
}

// ---------------------------------------------------------------------------------------------- one-page candidate summary
interface OnePage {
  org: Brand; candidate: { name: string; headline: string; location: string; years: number | null; notice_days: number | null; expected_salary: number | null; current_company: string; college: string; skills: string[]; has_resume: boolean }
  job: { title: string; department: string }; rounds: { round: string; status: string; score: number | null; reasons?: string[]; stability?: string; ai_gaps?: string[]; sections?: { section: string; pct: number }[]; summary?: string; improvements?: string[]; recommendation?: string; feedback?: { decision: string; rating: number; notes: string }; integrity?: string[] }[]
  notes: string; rating: number | null
}
const RT: Record<string, string> = { application: 'Application', cv_screening: 'CV screening', test: 'Test', video_intro: 'Video introduction', role_task: 'Role task', practical_task: 'Practical task', live_task: 'Live task', ai_interview: 'AI interview', human_interview: 'Interview', manager_approval: 'Manager approval' }

function Summary({ d, resumeUrl }: { d: OnePage; resumeUrl?: string }) {
  const c = d.candidate
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start gap-3"><div className="min-w-0 flex-1"><h2 className="text-xl font-semibold">{c.name}</h2>
        <p className="text-sm text-slate-500">{[c.headline, c.current_company, c.location].filter(Boolean).join(' · ')}</p></div>
        {c.has_resume && resumeUrl && <Button size="sm" icon={<FileText />} href={resumeUrl} target="_blank">Resume</Button>}</div>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {[['Experience', c.years != null ? `${c.years} years` : '-'], ['Notice', c.notice_days != null ? `${c.notice_days} days` : '-'], ['Expected salary', c.expected_salary ? c.expected_salary.toLocaleString() : '-'], ['College', c.college || '-']].map(([k, v]) =>
          <div key={k} className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-ink-850"><dt className="text-xs text-slate-500">{k}</dt><dd className="font-medium">{v}</dd></div>)}</dl>
      {c.skills.length > 0 && <div className="mt-3 flex flex-wrap gap-1">{c.skills.map(s => <Badge key={s}>{s}</Badge>)}</div>}
      <ol className="mt-4 space-y-2">{d.rounds.filter(r => r.round !== 'application' && r.round !== 'manager_approval').map((r, i) => (
        <li key={i} className="rounded-xl p-3 text-sm ring-1 ring-slate-200 dark:ring-ink-700">
          <div className="flex items-center gap-2"><span className="flex-1 font-semibold">{RT[r.round] || r.round}</span>{r.recommendation && <Badge tone={r.recommendation === 'Strong' ? 'success' : r.recommendation === 'No' ? 'danger' : 'warning'}>{r.recommendation}</Badge>}{r.score != null && <span className="tabular font-bold">{Math.round(r.score)}</span>}</div>
          {r.sections && <p className="text-slate-600 dark:text-slate-300">{r.sections.map(s => `${s.section} ${s.pct}%`).join(' · ')}</p>}
          {r.reasons && <ul className="list-disc pl-5 text-slate-600 dark:text-slate-300">{r.reasons.slice(0, 4).map(x => <li key={x}>{x}</li>)}</ul>}
          {r.summary && <p className="text-slate-600 dark:text-slate-300">{r.summary}</p>}
          {r.feedback && <p className="text-slate-600 dark:text-slate-300">Interviewer: {({ pass: 'Select', fail: 'Reject', hold: 'Hold' } as Record<string, string>)[r.feedback.decision]}{r.feedback.rating ? `, ${r.feedback.rating}/5` : ''}{r.feedback.notes ? `. ${r.feedback.notes.slice(0, 300)}` : ''}</p>}
          {r.integrity && <p className="text-red-600">Integrity: {r.integrity.join('; ')}</p>}
        </li>))}</ol>
      {d.notes && <p className="mt-3 text-sm"><span className="font-semibold">Team notes:</span> {d.notes}</p>}
    </Card>
  )
}

// ---------------------------------------------------------------------------------------------- manager decision
interface Decide extends OnePage { status: string; decision: string; decided_by: string; reason: string; decided: boolean; current: boolean; approvers: string[] }
export function DecidePage({ token }: { token: string }) {
  const { data, error, reload } = useLoad<Decide>(`/api/decide/${token}`)
  const [choice, setChoice] = useState<'' | 'select' | 'reject' | 'hold'>(''), [reason, setReason] = useState(''), [name, setName] = useState(''), [err, setErr] = useState(''), [busy, setBusy] = useState(false)
  useEffect(() => { if (data) document.title = `Decision: ${data.candidate.name}` }, [data])
  if (error || !data) return <PageState error={error} loading={!data} />
  async function submit() {
    setBusy(true); setErr('')
    try { await send(`/api/decide/${token}`, { decision: choice, reason, name }); reload() } catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  const done = data.decided || !data.current
  return (
    <Frame org={data.org} wide>
      <p className="text-sm text-slate-500">Hiring decision for</p><h1 className="mb-5 text-2xl font-semibold tracking-tight">{data.job.title}</h1>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Summary d={data} resumeUrl={`/api/decide/${token}/resume`} />
        <Card className="h-fit p-5">
          {done ? <Alert tone="success" title="Decision recorded">{data.decision ? `${({ pass: 'Selected', fail: 'Rejected', hold: 'On hold' } as Record<string, string>)[data.decision] || data.decision}` : data.status}{data.decided_by ? ` by ${data.decided_by}` : ''}.{data.reason ? ` "${data.reason}"` : ''}</Alert> : <>
            <div className="mb-3 font-semibold">Your decision</div>
            <div className="grid grid-cols-3 gap-2">{(['select', 'hold', 'reject'] as const).map(c => (
              <button key={c} aria-pressed={choice === c} onClick={() => setChoice(c)} className={cn('rounded-xl py-3 text-sm font-semibold ring-1', choice === c ? (c === 'select' ? 'bg-emerald-600 text-white ring-emerald-600' : c === 'reject' ? 'bg-red-600 text-white ring-red-600' : 'bg-amber-500 text-white ring-amber-500') : 'ring-slate-200 dark:ring-ink-700')}>
                {{ select: 'Select', hold: 'Hold', reject: 'Reject' }[c]}</button>))}</div>
            {choice && <div className="mt-3 space-y-3">
              <Field label={`Reason${choice === 'select' ? ' (optional)' : ''}`} htmlFor="dc-r"><Textarea id="dc-r" className="min-h-0" rows={3} value={reason} onChange={e => setReason(e.target.value)} /></Field>
              <Field label="Your name" htmlFor="dc-n"><Input id="dc-n" value={name} onChange={e => setName(e.target.value)} placeholder={data.approvers[0] || ''} /></Field>
              {err && <Alert tone="danger">{err}</Alert>}
              <Button variant="primary" className="w-full" loading={busy} disabled={choice !== 'select' && reason.trim().length < 3} onClick={submit}>Confirm</Button></div>}
          </>}
        </Card>
      </div>
    </Frame>
  )
}

// ---------------------------------------------------------------------------------------------- interviewer feedback
interface FB extends OnePage { round: string; booking: { starts_at: number; ends_at: number; meeting_url?: string; location?: string } | null; feedback: any; status: string; prep_kit: { focus?: string[]; questions?: string[]; watch_for?: string[] } }
export function FeedbackPage({ token }: { token: string }) {
  const { data, error, reload } = useLoad<FB>(`/api/feedback/${token}`)
  const [f, setF] = useState({ decision: '', rating: 0, notes: '', name: '', attended: true }), [file, setFile] = useState<Blob | null>(null), [err, setErr] = useState(''), [busy, setBusy] = useState(false)
  useEffect(() => { if (data) document.title = `Interview: ${data.candidate.name}` }, [data])
  if (error || !data) return <PageState error={error} loading={!data} />
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setErr('')
    const fd = new FormData(); fd.append('data', JSON.stringify({ ...f, decision: f.attended ? f.decision : 'hold', rating: f.rating || null }))
    if (file) fd.append('recording', file, file instanceof File ? file.name : 'interview.webm')
    try { await send(`/api/feedback/${token}`, undefined, fd); reload() } catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  const kit = data.prep_kit || {}
  return (
    <Frame org={data.org} wide>
      <p className="text-sm text-slate-500">{data.round} · {data.job.title}</p><h1 className="text-2xl font-semibold tracking-tight">{data.candidate.name}</h1>
      {data.booking && <p className="mb-5 mt-1 text-sm text-slate-600 dark:text-slate-300">{when(data.booking.starts_at)}{data.booking.location ? ` · ${data.booking.location}` : ''}{data.booking.meeting_url && <> · <a className="font-medium text-brand-600 dark:text-brand-400 hover:underline" href={data.booking.meeting_url} target="_blank" rel="noopener">Meeting link</a></>}</p>}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-5">
          <Card className="p-5"><div className="mb-2 flex items-center gap-2 font-semibold"><ClipboardList className="size-4 text-brand-500" />Prep kit</div>
            {kit.focus?.length ? <><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Focus on</div><ul className="mb-3 list-disc pl-5 text-sm">{kit.focus.map(x => <li key={x}>{x}</li>)}</ul></> : null}
            {kit.questions?.length ? <><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Questions to ask</div><ol className="mb-3 list-decimal space-y-1 pl-5 text-sm">{kit.questions.map(x => <li key={x}>{x}</li>)}</ol></> : null}
            {kit.watch_for?.length ? <><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Watch for</div><ul className="list-disc pl-5 text-sm">{kit.watch_for.map(x => <li key={x}>{x}</li>)}</ul></> : null}
          </Card>
          <Summary d={data} />
        </div>
        <Card className="h-fit p-5">
          {data.feedback ? <Alert tone="success" title="Feedback submitted">Thank you. {data.feedback.by ? `Recorded for ${data.feedback.by}.` : ''}</Alert> : (
            <form onSubmit={submit} className="space-y-3">
              <div className="font-semibold">Your feedback</div>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!f.attended} onChange={e => setF({ ...f, attended: !e.target.checked })} />The candidate didn't attend (no-show)</label>
              {f.attended && <>
                <div className="grid grid-cols-3 gap-2">{(['pass', 'hold', 'fail'] as const).map(c => <button type="button" key={c} aria-pressed={f.decision === c} onClick={() => setF({ ...f, decision: c })}
                  className={cn('rounded-xl py-2.5 text-sm font-semibold ring-1', f.decision === c ? (c === 'pass' ? 'bg-emerald-600 text-white ring-emerald-600' : c === 'fail' ? 'bg-red-600 text-white ring-red-600' : 'bg-amber-500 text-white ring-amber-500') : 'ring-slate-200 dark:ring-ink-700')}>{{ pass: 'Select', hold: 'Hold', fail: 'Reject' }[c]}</button>)}</div>
                <Field label="Rating"><div className="flex gap-1">{[1, 2, 3, 4, 5].map(n => <button type="button" key={n} aria-label={`${n} stars`} onClick={() => setF({ ...f, rating: n })} className={n <= f.rating ? 'text-amber-400' : 'text-slate-300 dark:text-ink-600'}><Star className="size-6" fill="currentColor" /></button>)}</div></Field>
                <Field label="Notes" htmlFor="fb-n" hint="AI writes a short summary for the candidate's profile from your notes and the recording."><Textarea id="fb-n" rows={6} value={f.notes} onChange={e => setF({ ...f, notes: e.target.value })} /></Field>
                <RecordingInput value={file} onChange={setFile} />
              </>}
              <Field label="Your name" htmlFor="fb-name"><Input id="fb-name" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required /></Field>
              {err && <Alert tone="danger">{err}</Alert>}
              <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={f.attended && !f.decision}>Submit feedback</Button>
            </form>)}
        </Card>
      </div>
    </Frame>
  )
}

/** Attach an interview recording: upload a file, or record audio in the browser during an in-person interview. */
function RecordingInput({ value, onChange }: { value: Blob | null; onChange: (b: Blob | null) => void }) {
  const [rec, setRec] = useState<MediaRecorder | null>(null), [secs, setSecs] = useState(0), [err, setErr] = useState('')
  const t = useRef<ReturnType<typeof setInterval> | null>(null)
  useEffect(() => () => { if (t.current) clearInterval(t.current) }, [])
  async function start() {
    setErr('')
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true })
      const chunks: Blob[] = [], m = new MediaRecorder(s)
      m.ondataavailable = e => e.data.size && chunks.push(e.data)
      m.onstop = () => { s.getTracks().forEach(x => x.stop()); if (t.current) clearInterval(t.current); onChange(new Blob(chunks, { type: m.mimeType || 'audio/webm' })); setRec(null) }
      m.start(1000); setRec(m); setSecs(0); const st = Date.now(); t.current = setInterval(() => setSecs((Date.now() - st) / 1000), 1000)
    } catch { setErr('Microphone access was blocked.') }
  }
  return (
    <Field label="Recording (optional)" hint="An audio or video file up to 80 MB, or record here. It's transcribed for the summary.">
      {value ? <div className="flex items-center gap-2 text-sm"><Badge tone="success" icon={<Check />}>{value instanceof File ? value.name : `Recorded ${Math.round(secs / 60)} min`}</Badge><Button type="button" size="sm" variant="ghost" icon={<RotateCcw />} onClick={() => onChange(null)}>Remove</Button></div>
        : rec ? <Button type="button" variant="danger" size="sm" icon={<Square />} onClick={() => rec.stop()}>Stop ({Math.floor(secs / 60)}:{String(Math.floor(secs % 60)).padStart(2, '0')})</Button>
          : <div className="flex flex-wrap gap-2"><Button type="button" size="sm" icon={<Mic />} onClick={start}>Record audio</Button>
            <label className="inline-flex h-8 cursor-pointer items-center rounded-lg px-3 text-[13px] font-semibold ring-1 ring-slate-200 dark:ring-ink-700">Upload a file<input type="file" accept="audio/*,video/*" className="sr-only" onChange={e => onChange(e.target.files?.[0] || null)} /></label></div>}
      {err && <p className="mt-1 text-xs text-red-600">{err}</p>}
    </Field>
  )
}

// ---------------------------------------------------------------------------------------------- campus drive registration
type DQ = { id: string; question: string; kind: string; required: boolean }
interface DriveRole { key: string; title: string; facts: string[]; summary: string; questions: DQ[] }
interface DriveInfo { org: Brand; college: string; job: { title: string; facts: string[]; summary: string }; roles?: DriveRole[]; opens_at: number | null; closes_at: number | null; registration_open: boolean; test_open: boolean; require_photo: boolean; questions: DQ[] }
export function DrivePage({ code }: { code: string }) {
  const { data, error } = useLoad<DriveInfo>(`/api/drive/${code}`)
  const [f, setF] = useState({ name: '', email: '', phone: '', degree: '', branch: '', graduation_year: '', cgpa: '' })
  const [answers, setAnswers] = useState<Record<string, Record<string, string>>>({}), [picked, setPicked] = useState<string[]>([]), [consent, setConsent] = useState(false), [resume, setResume] = useState<File | null>(null)
  const [photo, setPhoto] = useState<Blob | null>(null), [camOn, setCamOn] = useState(false), [busy, setBusy] = useState(false), [err, setErr] = useState('')
  const [done, setDone] = useState<{ next_link: string | null; status_link: string; roles?: { role: string; next_link: string | null; status_link: string }[]; already?: string[] } | null>(null)
  const cam = useCamera(camOn)
  useEffect(() => { if (data) document.title = `${data.college} campus drive · ${data.org.name}` }, [data])
  useEffect(() => { if (data?.roles?.length === 1) setPicked([data.roles[0]!.key]) }, [data])
  if (error || !data) return <PageState error={error} loading={!data} />
  const roles: DriveRole[] = data.roles?.length ? data.roles : [{ key: '', title: data.job.title, facts: data.job.facts, summary: data.job.summary, questions: data.questions }]
  const multi = roles.length > 1
  const chosen = roles.filter(r => !multi || picked.includes(r.key))
  const setAns = (role: string, q: string, v: string) => setAnswers(a => ({ ...a, [role]: { ...(a[role] || {}), [q]: v } }))
  // The same question asked by several chosen roles is shown once and answered for all of them.
  const merged: { q: DQ; required: boolean; targets: [string, string][] }[] = []
  for (const r of chosen) for (const q of r.questions) {
    const hit = merged.find(m => m.q.question.trim().toLowerCase() === q.question.trim().toLowerCase() && m.q.kind === q.kind)
    if (hit) { hit.targets.push([r.key, q.id]); hit.required ||= q.required } else merged.push({ q, required: q.required, targets: [[r.key, q.id]] })
  }
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF(v => ({ ...v, [k]: e.target.value }))
  async function snap() { if (cam.stream) { setPhoto(await grab(cam.stream, 640, 0.85)); setCamOn(false) } }
  async function submit(e: FormEvent) {
    e.preventDefault(); setErr('')
    if (multi && !picked.length) { setErr('Choose at least one role to apply for.'); requestAnimationFrame(() => document.getElementById('dv-roles')?.scrollIntoView({ behavior: 'smooth', block: 'center' })); return }
    if (data!.require_photo && !photo) { setErr('Please take a live photo with your camera.'); return }
    setBusy(true)
    const fd = new FormData(); fd.append('data', JSON.stringify({ ...f, consent, roles: chosen.map(r => r.key).filter(Boolean), answers: multi ? answers : (answers[roles[0]!.key] || {}) }))
    if (resume) fd.append('resume', resume); if (photo) fd.append('photo', photo, 'photo.jpg')
    try { setDone(await send(`/api/drive/${code}/register`, undefined, fd)); window.scrollTo(0, 0) }
    catch (e: any) { setErr(e.message); requestAnimationFrame(() => document.getElementById('dv-err')?.scrollIntoView({ behavior: 'smooth', block: 'center' })) }
    setBusy(false)
  }
  if (done) return (
    <Frame org={data.org}><Card className="p-8 text-center"><CircleCheck className="mx-auto size-10 text-emerald-500" /><h1 className="mt-3 text-xl font-semibold">You're registered</h1>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">We also emailed you the links below.</p>
      {(done.roles?.length ?? 0) > 1 ? <ul className="mx-auto mt-4 max-w-md space-y-2 text-left">{done.roles!.map(r => (
        <li key={r.role} className="flex flex-wrap items-center justify-between gap-2 rounded-xl p-3 ring-1 ring-slate-200 dark:ring-ink-700"><span className="font-medium">{r.role}</span>
          <span className="flex gap-2">{r.next_link && <Button size="sm" variant="primary" href={r.next_link}>{data.test_open ? 'Start the test' : 'Test page'}</Button>}<Button size="sm" href={r.status_link}>Status</Button></span></li>))}</ul> : null}
      {!!done.already?.length && <p className="mt-3 text-sm text-slate-500">You had already registered for: {done.already.join(', ')}.</p>}
      <div className="mt-4 flex flex-wrap justify-center gap-2">{(done.roles?.length ?? 0) <= 1 && done.next_link && <Button variant="primary" href={done.next_link}>{data.test_open ? 'Start the test' : 'Your test page'}</Button>}<Button href={done.status_link}>Your application status</Button></div>
      {!data.test_open && data.opens_at && <p className="mt-3 text-sm text-slate-500">The test opens {when(data.opens_at)}.</p>}</Card></Frame>)
  return (
    <Frame org={data.org}>
      <p className="text-sm text-slate-500">{data.org.name} · campus drive</p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight">{multi ? data.college : roles[0]!.title}</h1>
      {multi ? <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{roles.length} roles open for students of {data.college}. Pick the ones you want; you'll get a separate test link for each.</p>
        : <><p className="mt-0.5 text-sm text-slate-500">{data.college}</p><div className="mt-2 flex flex-wrap gap-1.5">{roles[0]!.facts.map(x => <Badge key={x}>{x}</Badge>)}</div>
          {roles[0]!.summary && <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{roles[0]!.summary}</p>}</>}
      {(data.opens_at || data.closes_at) && <p className="mt-2 text-sm">Test window: {data.opens_at ? when(data.opens_at) : 'now'} to {data.closes_at ? when(data.closes_at) : 'open'}</p>}
      {!data.registration_open ? <Alert className="mt-5" tone="warning">Registration for this drive is closed.</Alert> : (
        <Card className="mt-5 p-5 sm:p-6"><form onSubmit={submit} className="space-y-4">
          {multi && <fieldset id="dv-roles"><legend className="mb-2 text-[13px] font-semibold">Roles you're applying for *</legend>
            <div className="grid gap-2 sm:grid-cols-2">{roles.map(r => { const on = picked.includes(r.key); return (
              <label key={r.key} className={cn('flex cursor-pointer gap-3 rounded-xl p-3 ring-1 transition-colors', on ? 'bg-brand-50 ring-2 ring-brand-500 dark:bg-brand-500/15' : 'ring-slate-200 hover:bg-slate-50 dark:ring-ink-700 dark:hover:bg-ink-850')}>
                <input type="checkbox" className="mt-1" checked={on} onChange={() => setPicked(p => on ? p.filter(x => x !== r.key) : [...p, r.key])} />
                <span className="min-w-0"><span className="block font-semibold">{r.title}</span><span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">{r.facts.slice(0, 3).join(' · ')}</span>
                  {r.summary && <span className="mt-1 line-clamp-2 block text-xs text-slate-600 dark:text-slate-300">{r.summary}</span>}</span>
              </label>) })}</div></fieldset>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Full name *" htmlFor="dv-n"><Input id="dv-n" required autoComplete="name" value={f.name} onChange={set('name')} /></Field>
            <Field label="Email *" htmlFor="dv-e"><Input id="dv-e" type="email" required autoComplete="email" value={f.email} onChange={set('email')} /></Field>
            <Field label="Phone *" htmlFor="dv-p"><Input id="dv-p" type="tel" required autoComplete="tel" value={f.phone} onChange={set('phone')} /></Field>
            <Field label="Degree *" htmlFor="dv-d"><Input id="dv-d" required value={f.degree} onChange={set('degree')} placeholder="B.Tech, BCA, B.Com…" /></Field>
            <Field label="Branch" htmlFor="dv-b"><Input id="dv-b" value={f.branch} onChange={set('branch')} /></Field>
            <Field label="Year of passing *" htmlFor="dv-y"><Input id="dv-y" required inputMode="numeric" value={f.graduation_year} onChange={set('graduation_year')} /></Field>
            <Field label="CGPA / %" htmlFor="dv-c"><Input id="dv-c" value={f.cgpa} onChange={set('cgpa')} /></Field>
            <Field label="Resume (optional)" htmlFor="dv-r"><input id="dv-r" type="file" accept=".pdf,.docx,.txt" className="block w-full text-sm" onChange={e => setResume(e.target.files?.[0] || null)} /></Field>
          </div>
          {merged.length > 0 && <div className="space-y-3">{multi && <div className="border-t border-slate-100 pt-3 text-sm font-semibold dark:border-ink-800">A few questions{chosen.length > 1 ? ` for ${chosen.map(r => r.title).join(' and ')}` : ''}</div>}
          {merged.map(m => { const [rk, qid] = m.targets[0]!, val = answers[rk]?.[qid] || '', setV = (v: string) => m.targets.forEach(([r, q]) => setAns(r, q, v)), q = m.q, id = `dq-${rk}-${qid}`; return (
            <Field key={id} label={<>{q.question}{m.required && ' *'}</>} htmlFor={id}>
              {q.kind === 'yes_no' ? <Select id={id} required={m.required} value={val} onChange={e => setV(e.target.value)}><option value="">Select…</option><option value="yes">Yes</option><option value="no">No</option></Select>
                : <Input id={id} type={q.kind === 'number' ? 'number' : 'text'} required={m.required} value={val} onChange={e => setV(e.target.value)} />}</Field>) })}</div>}
          {data.require_photo && <Field label="Live photo *" hint="Used to confirm it's you during the test. Look at the camera in good light.">
            {photo ? <div className="flex items-center gap-3"><img src={URL.createObjectURL(photo)} alt="Your photo" className="h-24 rounded-lg" /><Button type="button" size="sm" icon={<RotateCcw />} onClick={() => { setPhoto(null); setCamOn(true) }}>Retake</Button></div>
              : camOn ? <div className="space-y-2">{cam.error ? <Alert tone="danger">{cam.error}</Alert> : <Preview stream={cam.stream} className="aspect-[4/3] w-full max-w-xs" />}<Button type="button" icon={<Camera />} disabled={!cam.stream} onClick={snap}>Take photo</Button></div>
                : <Button type="button" icon={<Camera />} onClick={() => setCamOn(true)}>Open camera</Button>}</Field>}
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={consent} onChange={e => setConsent(e.target.checked)} required />
            <span>I agree that {data.org.name} may store and process my details, photo and test results to consider me for this role. I can ask for them to be deleted at any time.</span></label>
          <div id="dv-err" aria-live="assertive">{err && <Alert tone="danger" title="Not registered yet">{err}</Alert>}</div>
          <Button type="submit" variant="primary" size="lg" loading={busy}>{multi && picked.length > 1 ? `Register for ${picked.length} roles` : 'Register'}</Button>
        </form></Card>)}
    </Frame>
  )
}

// ---------------------------------------------------------------------------------------------- placement officer results
interface Results { org: Brand; college: string; job: string; roles?: string[]; show_scores: boolean; summary: { registered: number; tested: number; progressed: number }; students: { name: string; role?: string; stage: string; round: string; round_status: string; test_score: number | null; test_taken: boolean }[] }
export function ResultsPage({ code }: { code: string }) {
  const { data, error } = useLoad<Results>(`/api/results/${code}`)
  const [q, setQ] = useState('')
  useEffect(() => { if (data) document.title = `${data.college} results · ${data.job}` }, [data])
  if (error || !data) return <PageState error={error} loading={!data} />
  const rows = data.students.filter(s => !q || s.name.toLowerCase().includes(q.toLowerCase()))
  return (
    <Frame org={data.org} wide>
      <p className="text-sm text-slate-500">Campus drive results · {data.org.name}</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">{data.college}: {data.job}</h1>
      <div className="mt-4 grid grid-cols-3 gap-3">{([['Registered', data.summary.registered], ['Took the test', data.summary.tested], ['Moved ahead', data.summary.progressed]] as const).map(([k, v]) =>
        <Card key={k} className="p-4"><div className="text-sm text-slate-500">{k}</div><div className="tabular text-2xl font-semibold">{v}</div></Card>)}</div>
      <Input type="search" aria-label="Search students" className="mt-4 max-w-xs" placeholder="Search students" value={q} onChange={e => setQ(e.target.value)} />
      <Card className="mt-3 overflow-x-auto"><table className="w-full min-w-[560px] text-sm"><thead className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-ink-800"><tr><th className="px-4 py-2.5">Student</th>{(data.roles?.length ?? 0) > 1 && <th>Role</th>}<th>Status</th><th>Current step</th>{data.show_scores && <th>Test score</th>}</tr></thead>
        <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{rows.map((s, i) => <tr key={i}><td className="px-4 py-2.5 font-medium">{s.name}</td>{(data.roles?.length ?? 0) > 1 && <td>{s.role}</td>}<td>{s.stage}</td><td className="text-slate-500">{s.round}{s.round_status ? ` · ${s.round_status}` : ''}</td>
          {data.show_scores && <td className="tabular">{s.test_score != null ? `${s.test_score}%` : s.test_taken ? '-' : 'Not taken'}</td>}</tr>)}</tbody></table></Card>
      <p className="mt-3 text-xs text-slate-500">This page updates as students move through the process. Share it only with your placement team.</p>
    </Frame>
  )
}

