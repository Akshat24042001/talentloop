// The candidate's page for one round (/r/<token>): a proctored test, a video or role-task recording, a practical
// task upload, the AI interview start page, or booking a human interview.
import { AlarmClock, CalendarCheck, CalendarPlus, CircleCheck, Download, FileUp, Headphones, Maximize, Mic, MonitorUp, Phone, RotateCcw, Send, Square, UserRound, Video } from 'lucide-react'
import { ask } from '../components/dialogs'
import SlotPicker, { fullWhen } from '../components/SlotPicker'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Badge, Button, Card, Field, Input, Modal, Select, Spinner, Textarea, cn, toast } from '../components/ui'
import { when } from '../lib/format'
import { Frame, HowItWorks, PageState, Preview, fmtClock, getJSON, grab, send, useCamera, useLoad, type Brand, type Transparency } from './common'

interface Page {
  type: string; name: string; status: string; status_label: string; deadline_at: number | null; message: string; org: Brand; job: { title: string }
  candidate: { first_name: string; has_photo: boolean }; transparency: Transparency; finished: boolean; current: boolean; withdrawn: boolean; status_link: string
  human_requested: boolean; accommodation: string | null
  test?: { sections: { label: string; count: number; minutes: number }[]; negative_marking: number; max_exits: number; require_camera: boolean; started: boolean; sessions_used: number; max_sessions: number; window: { opens_at: number | null; closes_at: number | null; open: boolean; college: string } | null; extra_time: boolean; done?: boolean }
  recording?: { prompt: string; brief: string; max_seconds: number; retakes: number; prepare_seconds: number; uploaded: boolean }
  task?: { instructions: string; file_types: string; attachment: string | null; rubric: string[]; uploaded: string | null }
  references?: { min: number; max: number; require_manager: boolean; referees: { id: string; name: string; email: string; relationship: string; answered: boolean }[]; relations: Record<string, string> }
  live?: { instructions: string; minutes: number; deliverable: 'code' | 'text' | 'file' | 'none'; language: string; snapshot_every_sec: number; rubric: string[]
    started_at: number | null; ends_at: number | null; draft: string; submitted: boolean; file: string | null; server_now: number }
  interview?: any
}

export default function RoundPage({ token }: { token: string }) {
  const { data, error, reload } = useLoad<Page>(`/api/r/${token}`)
  useEffect(() => { if (data) document.title = `${data.name} · ${data.org.name}` }, [data])
  if (error || !data) return <PageState error={error} loading={!data} />
  const base = `/api/r/${token}`
  const closed = data.withdrawn || (!data.current && data.type !== 'human_interview')
  return (
    <Frame org={data.org} wide={data.type === 'test'}>
      <div className="mb-5">
        <p className="text-sm text-slate-500">{data.job.title} · {data.org.name}</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">{data.name}</h1>
        {data.deadline_at && !data.finished && <p className="mt-1 flex items-center gap-1.5 text-sm text-slate-600 dark:text-slate-300"><AlarmClock className="size-4" />Please complete by {when(data.deadline_at)}</p>}
        {data.message && <p className="mt-3 whitespace-pre-line text-sm">{data.message}</p>}
      </div>
      {data.status === 'expired' ? <Alert tone="warning" title="The deadline has passed">Please contact the hiring team if you need more time.</Alert>
        : closed && !data.finished ? <Alert tone="info" title="This step is closed">Check your <a className="font-semibold underline" href={data.status_link}>application status page</a> for what's next.</Alert>
        : data.type === 'test' ? <TestRound p={data} base={base} onDone={reload} />
        : data.type === 'video_intro' || data.type === 'role_task' ? <RecordRound p={data} base={base} onDone={reload} />
        : data.type === 'practical_task' ? <TaskRound p={data} base={base} onDone={reload} />
        : data.type === 'reference_check' ? <RefRound p={data} base={base} onDone={reload} />
        : data.type === 'live_task' ? <LiveRound p={data} base={base} onDone={reload} />
        : data.type === 'ai_interview' ? <AIRound p={data} base={base} reload={reload} />
        : data.type === 'human_interview' ? <BookRound p={data} base={base} reload={reload} />
        : <Alert tone="info">Nothing to do here. <a className="font-semibold underline" href={data.status_link}>See your application status.</a></Alert>}
      {data.status_link && <p className="mt-8 text-center text-sm"><a className="font-medium text-brand-600 dark:text-brand-400 hover:underline" href={data.status_link}>Your application status, accommodations and help</a></p>}
    </Frame>
  )
}

function Done({ title, children, link }: { title: string; children?: React.ReactNode; link?: string }) {
  return <Card className="p-8 text-center"><CircleCheck className="mx-auto size-10 text-emerald-500" /><h2 className="mt-3 text-lg font-semibold">{title}</h2>
    {children && <div className="mt-1 text-sm text-slate-600 dark:text-slate-300">{children}</div>}
    {link && <Button className="mt-4" href={link}>Your application status</Button>}</Card>
}

// ---------------------------------------------------------------------------------------------- test
interface Item { n: number; qid: string; kind: 'single' | 'multiple' | 'numeric'; text: string; options: string[]; marks: number; answer: number[] | number | null }
interface Section { index: number; count: number; section: string; label: string; items: Item[]; ends_at: number | null; seconds: number; server_now: number }

function TestRound({ p, base, onDone }: { p: Page; base: string; onDone: () => void }) {
  const t = p.test!
  const [phase, setPhase] = useState<'intro' | 'run' | 'done'>(t.done || p.finished ? 'done' : 'intro')
  const [consent, setConsent] = useState(false), [busy, setBusy] = useState(false), [err, setErr] = useState('')
  const [sec, setSec] = useState<Section | null>(null), [result, setResult] = useState<any>(null)
  const cam = useCamera(t.require_camera && phase !== 'done')
  const minutes = t.sections.reduce((a, s) => a + s.minutes, 0)
  async function start() {
    setBusy(true); setErr('')
    try {
      await document.documentElement.requestFullscreen?.().catch(() => {})
      const fd = new FormData(); fd.append('consent', '1')
      if (cam.stream) { const b = await grab(cam.stream); if (b) fd.append('photo', b, 'start.jpg') }
      const r = await send(`${base}/test/start`, undefined, fd)
      if (r.done) { setPhase('done'); onDone() } else { setSec(r.section); setPhase('run') }
    } catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  if (phase === 'done') return <Done title="Your test is submitted" link={p.status_link}>{result ? <>Your score: <b>{result.overall}%</b>{result.sections?.length > 1 && <> ({result.sections.map((x: any) => `${x.label} ${x.pct}%`).join(', ')})</>}</> : 'Thank you. The hiring team will be in touch about the next step.'}</Done>
  if (phase === 'run' && sec) return <TestRunner base={base} first={sec} stream={cam.stream} onFinish={r => { setResult(r); setPhase('done'); document.fullscreenElement && document.exitFullscreen().catch(() => {}) }} />
  const resume = t.started && t.sessions_used > 0
  const windowClosed = t.window && !t.window.open
  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="grid gap-5 sm:grid-cols-[1fr_220px]">
          <div className="text-sm">
            <div className="font-semibold">{t.sections.length} section(s), about {Math.round(minutes)} minutes{t.extra_time && <Badge tone="success" className="ml-2">Extra time included</Badge>}</div>
            <ul className="mt-2 space-y-1">{t.sections.map((s, i) => <li key={i} className="flex justify-between rounded-lg bg-slate-50 px-3 py-1.5 dark:bg-ink-850"><span>{s.label}</span><span className="tabular text-slate-500">{s.count} questions · {s.minutes} min</span></li>)}</ul>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-slate-600 dark:text-slate-300">
              <li>Each section has its own timer. When it ends, the next section starts; you can't go back.</li>
              <li>Answers save as you go. If your connection drops you can resume once{t.sessions_used ? ` (used ${t.sessions_used} of ${t.max_sessions} sittings)` : ''}.</li>
              <li>Stay in full screen on this tab. Leaving it more than {t.max_exits} time(s) submits the test.</li>
              {t.negative_marking ? <li>Wrong answers lose {t.negative_marking} of a mark. Blank answers lose nothing.</li> : <li>There is no negative marking.</li>}
            </ul>
          </div>
          {t.require_camera && <div>{cam.error ? <Alert tone="danger">{cam.error}</Alert> : <Preview stream={cam.stream} className="aspect-[4/3] w-full" />}
            <p className="mt-1.5 text-xs text-slate-500">Photos are taken now and then during the test, for the hiring team to review.</p></div>}
        </div>
      </Card>
      <HowItWorks t={p.transparency} />
      {windowClosed && <Alert tone="warning" title={`The test window for ${t.window!.college} is not open`}>{t.window!.opens_at && Date.now() / 1000 < t.window!.opens_at ? `It opens ${when(t.window!.opens_at)}.` : 'Please contact the hiring team.'}</Alert>}
      {err && <Alert tone="danger">{err}</Alert>}
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={consent} onChange={e => setConsent(e.target.checked)} />
        <span>I agree to take this test on my own, and to the camera photos and screen-activity notes described above, which only the hiring team sees.</span></label>
      <Button variant="primary" size="lg" icon={<Maximize />} loading={busy} disabled={!consent || !!windowClosed || (t.require_camera && !cam.stream)} onClick={start}>{resume ? 'Resume the test' : 'Start the test'}</Button>
    </div>
  )
}

function TestRunner({ base, first, stream, onFinish }: { base: string; first: Section; stream: MediaStream | null; onFinish: (r: any) => void }) {
  const [sec, setSec] = useState(first)
  const [ans, setAns] = useState<Record<string, number[] | number | null>>(() => Object.fromEntries(first.items.map(i => [i.qid, i.answer])))
  const [saving, setSaving] = useState(0), [failed, setFailed] = useState(false)
  const [left, setLeft] = useState(0), [warn, setWarn] = useState(''), [confirmNext, setConfirmNext] = useState(false)
  const deadline = useRef(0), busy = useRef(false)
  const load = useCallback((s: Section) => {
    setSec(s); setAns(Object.fromEntries(s.items.map(i => [i.qid, i.answer])))
    deadline.current = s.ends_at ? Date.now() / 1000 + (s.ends_at - s.server_now) : Date.now() / 1000 + s.seconds
    window.scrollTo(0, 0)
  }, [])
  useEffect(() => { load(first) }, [first, load])
  const finish = useCallback((r: any) => { if (r?.done) { onFinish(r.result); return true } if (r?.section) load(r.section); return false }, [load, onFinish])
  // timer: when a section's time is up, ask the server for the next one
  useEffect(() => {
    const t = setInterval(async () => {
      const l = deadline.current - Date.now() / 1000
      setLeft(l)
      if (l <= -1 && !busy.current) { busy.current = true; try { finish(await getJSON(`${base}/test/section`)) } catch { /* retry next tick */ } busy.current = false }
    }, 500)
    return () => clearInterval(t)
  }, [base, finish])
  // integrity events
  useEffect(() => {
    const ev = async (type: string, detail = '') => {
      try {
        const r = await send(`${base}/event`, { type, detail })
        if (r.submitted) { onFinish(null); return }
        if (['tab_hidden', 'window_blur', 'fullscreen_exit'].includes(type)) setWarn(`You left the test screen (${r.exits} of ${r.max_exits} allowed). Please stay on this tab in full screen.`)
      } catch { /* offline: ignore */ }
    }
    const vis = () => document.hidden && ev('tab_hidden')
    const blur = () => !document.hidden && ev('window_blur')
    const fs = () => !document.fullscreenElement && ev('fullscreen_exit')
    const cp = (e: ClipboardEvent) => { e.preventDefault(); ev(e.type) }
    const ctx = (e: MouseEvent) => e.preventDefault()
    document.addEventListener('visibilitychange', vis); window.addEventListener('blur', blur); document.addEventListener('fullscreenchange', fs)
    document.addEventListener('copy', cp); document.addEventListener('paste', cp); document.addEventListener('cut', cp); document.addEventListener('contextmenu', ctx)
    return () => {
      document.removeEventListener('visibilitychange', vis); window.removeEventListener('blur', blur); document.removeEventListener('fullscreenchange', fs)
      document.removeEventListener('copy', cp); document.removeEventListener('paste', cp); document.removeEventListener('cut', cp); document.removeEventListener('contextmenu', ctx)
    }
  }, [base, onFinish])
  // camera snapshots every 2-4 minutes
  useEffect(() => {
    if (!stream) return
    let t: ReturnType<typeof setTimeout>
    const shoot = async () => {
      try { const b = await grab(stream, 480, 0.7); if (b) { const fd = new FormData(); fd.append('image', b, 'snap.jpg'); fd.append('reason', 'routine'); await send(`${base}/snapshot`, undefined, fd) } } catch { /* best effort */ }
      t = setTimeout(shoot, (120 + Math.random() * 120) * 1000)
    }
    t = setTimeout(shoot, 20000)
    return () => clearTimeout(t)
  }, [stream, base])
  async function answer(it: Item, v: number[] | number | null) {
    setAns(a => ({ ...a, [it.qid]: v })); setSaving(n => n + 1)
    let ok = false
    for (let i = 0; i < 3 && !ok; i++) {
      try { const r = await send(`${base}/test/answer`, { section: sec.index, qid: it.qid, answer: v }); ok = true; if (r.done) finish(await getJSON(`${base}/test/section`)) }
      catch { await new Promise(r => setTimeout(r, 800 * (i + 1))) }
    }
    setFailed(!ok); setSaving(n => n - 1)
  }
  async function next() {
    setConfirmNext(false)
    try { finish(await send(`${base}/test/${sec.index + 1 >= sec.count ? 'submit' : 'next'}`)) } catch (e: any) { toast(e.message) }
  }
  const answered = sec.items.filter(i => { const a = ans[i.qid]; return Array.isArray(a) ? a.length > 0 : a != null && a !== ('' as any) }).length
  const last = sec.index + 1 >= sec.count
  return (
    <div className="select-none">
      <div className="sticky top-0 z-20 -mx-4 mb-4 flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur dark:border-ink-800 dark:bg-ink-900/95">
        <div className="min-w-0 flex-1"><div className="text-xs text-slate-500">Section {sec.index + 1} of {sec.count}</div><div className="truncate font-semibold">{sec.label}</div></div>
        <span className="text-sm text-slate-500">{answered}/{sec.items.length} answered</span>
        <span className="text-xs text-slate-500">{failed ? <span className="text-red-600">Not saved, retrying…</span> : saving ? 'Saving…' : 'Saved'}</span>
        <span className={cn('tabular rounded-lg px-3 py-1 text-lg font-bold', left < 60 ? 'bg-red-50 text-red-600 dark:bg-red-500/15' : 'bg-slate-100 dark:bg-ink-800')} aria-live="polite">{fmtClock(left)}</span>
        {stream && <Preview stream={stream} className="hidden h-12 w-16 sm:block" />}
      </div>
      {warn && <Alert className="mb-4" tone="warning">{warn}</Alert>}
      {!document.fullscreenElement && document.documentElement.requestFullscreen && <Button size="sm" className="mb-4" icon={<Maximize />} onClick={() => document.documentElement.requestFullscreen().catch(() => {})}>Return to full screen</Button>}
      <ol className="space-y-4">{sec.items.map(it => {
        const a = ans[it.qid]
        return (
          <Card key={it.qid} className="p-5">
            <div className="mb-3 flex gap-2"><span className="tabular font-semibold text-slate-500 dark:text-slate-400">{it.n}.</span><p className="flex-1 whitespace-pre-line font-medium">{it.text}</p>{it.marks !== 1 && <span className="text-xs text-slate-500">{it.marks} marks</span>}</div>
            {it.kind === 'numeric' ? <input type="number" step="any" aria-label={`Answer to question ${it.n}`} className="h-10 w-48 rounded-xl px-3 ring-1 ring-slate-200 dark:bg-ink-850 dark:ring-ink-700" defaultValue={typeof a === 'number' ? a : ''} onBlur={e => answer(it, e.target.value === '' ? null : +e.target.value)} />
              : <div className="space-y-2">{it.options.map((o, i) => {
                const on = Array.isArray(a) && a.includes(i)
                return (
                  <label key={i} className={cn('flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2.5 ring-1', on ? 'bg-brand-50 ring-brand-400 dark:bg-brand-500/15' : 'ring-slate-200 hover:bg-slate-50 dark:ring-ink-700 dark:hover:bg-ink-850')}>
                    <input type={it.kind === 'single' ? 'radio' : 'checkbox'} name={it.qid} className="mt-1" checked={on}
                      onChange={() => answer(it, it.kind === 'single' ? [i] : on ? (a as number[]).filter(x => x !== i) : [...(Array.isArray(a) ? a : []), i])} />
                    <span className="text-sm">{o}</span></label>)
              })}
                {Array.isArray(a) && a.length > 0 && <button className="text-xs text-slate-500 hover:underline" onClick={() => answer(it, [])}>Clear answer</button>}</div>}
          </Card>)
      })}</ol>
      <div className="mt-6 flex justify-end"><Button variant="primary" size="lg" icon={<Send />} onClick={() => setConfirmNext(true)}>{last ? 'Submit the test' : 'Next section'}</Button></div>
      <Modal open={confirmNext} onOpenChange={setConfirmNext} title={last ? 'Submit the test?' : 'Go to the next section?'} description={`You answered ${answered} of ${sec.items.length}. You can't come back to this section.`}
        footer={<><Button onClick={() => setConfirmNext(false)}>Keep working</Button><Button variant="primary" onClick={next}>{last ? 'Submit' : 'Next section'}</Button></>} />
    </div>
  )
}

// ---------------------------------------------------------------------------------------------- recordings
type SR = { start: () => void; stop: () => void; continuous: boolean; interimResults: boolean; lang: string; onresult: (e: any) => void; onerror: () => void; onend: () => void }
function speech(): SR | null {
  const C = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  return C ? new C() : null
}
function pickMime() {
  for (const m of ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4']) if ((window as any).MediaRecorder?.isTypeSupported?.(m)) return m
  return ''
}

function RecordRound({ p, base, onDone }: { p: Page; base: string; onDone: () => void }) {
  const r = p.recording!
  const [phase, setPhase] = useState<'intro' | 'prepare' | 'record' | 'review' | 'upload' | 'done'>(r.uploaded || p.finished ? 'done' : 'intro')
  const [consent, setConsent] = useState(false), [attempts, setAttempts] = useState(0), [left, setLeft] = useState(0), [err, setErr] = useState('')
  const [blob, setBlob] = useState<Blob | null>(null), [dur, setDur] = useState(0), [progress, setProgress] = useState(0)
  const cam = useCamera(['intro', 'prepare', 'record'].includes(phase), true)
  const rec = useRef<MediaRecorder | null>(null), chunks = useRef<Blob[]>([]), started = useRef(0), transcript = useRef(''), sr = useRef<SR | null>(null)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
  const stopAll = () => { if (timer.current) clearInterval(timer.current); try { sr.current?.stop() } catch { /* not started */ } }
  useEffect(() => stopAll, [])
  function countdown(sec: number, then: () => void) {
    if (timer.current) clearInterval(timer.current)
    const end = Date.now() + sec * 1000; setLeft(sec)
    timer.current = setInterval(() => { const l = (end - Date.now()) / 1000; setLeft(l); if (l <= 0) { clearInterval(timer.current!); then() } }, 250)
  }
  function prepare() { setErr(''); setPhase('prepare'); countdown(r.prepare_seconds, record) }
  function record() {
    if (!cam.stream) return
    chunks.current = []; transcript.current = ''
    const mime = pickMime()
    const m = new MediaRecorder(cam.stream, mime ? { mimeType: mime, videoBitsPerSecond: 1_000_000 } : undefined)
    m.ondataavailable = e => e.data.size && chunks.current.push(e.data)
    m.onstop = () => { stopAll(); setDur((Date.now() - started.current) / 1000); setBlob(new Blob(chunks.current, { type: m.mimeType || 'video/webm' })); setAttempts(a => a + 1); setPhase('review') }
    m.start(1000); rec.current = m; started.current = Date.now(); setPhase('record')
    const s = speech()
    if (s) {
      s.continuous = true; s.interimResults = false; s.lang = 'en-IN'
      s.onresult = (e: any) => { for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) transcript.current += e.results[i][0].transcript + ' ' }
      s.onerror = () => {}; s.onend = () => { if (rec.current?.state === 'recording') try { s.start() } catch { /* already running */ } }
      try { s.start(); sr.current = s } catch { /* no speech API */ }
    }
    countdown(r.max_seconds, () => rec.current?.state === 'recording' && rec.current.stop())
  }
  async function upload() {
    if (!blob) return
    setPhase('upload'); setErr('')
    const fd = new FormData()
    fd.append('video', blob, blob.type.includes('mp4') ? 'recording.mp4' : 'recording.webm')
    fd.append('meta', JSON.stringify({ duration: dur, transcript: transcript.current.trim(), attempts }))
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${base}/recording`)
    xhr.upload.onprogress = e => e.lengthComputable && setProgress(e.loaded / e.total)
    xhr.onload = () => { if (xhr.status < 300) { setPhase('done'); onDone() } else { let d = ''; try { d = JSON.parse(xhr.responseText).detail } catch { /* not JSON */ } setErr(d || 'Upload failed. Please try again.'); setPhase('review') } }
    xhr.onerror = () => { setErr('Upload failed. Check your connection and try again.'); setPhase('review') }
    xhr.send(fd)
  }
  if (phase === 'done') return <Done title="Your recording is submitted" link={p.status_link}>Thank you, {p.candidate.first_name}. The hiring team will review it.</Done>
  const canRetake = attempts <= r.retakes
  return (
    <div className="space-y-4">
      {r.brief && <Card className="p-5"><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Your brief</div><p className="whitespace-pre-line text-sm">{r.brief}</p></Card>}
      <Card className="p-5">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">What to talk about</div><p className="whitespace-pre-line font-medium">{r.prompt}</p>
        <p className="mt-2 text-sm text-slate-500">Up to {r.max_seconds >= 60 ? `${Math.round(r.max_seconds / 6) / 10} minutes` : `${r.max_seconds} seconds`}. {r.prepare_seconds ? `You get ${r.prepare_seconds} seconds to prepare first. ` : ''}{r.retakes ? `You can re-record ${r.retakes} time(s).` : 'One take.'}</p>
      </Card>
      {cam.error && <Alert tone="danger">{cam.error}</Alert>}
      {['intro', 'prepare', 'record'].includes(phase) && (
        <div className="relative"><Preview stream={cam.stream} className="aspect-video w-full" />
          {phase === 'prepare' && <div className="absolute inset-0 grid place-items-center rounded-xl bg-black/50 text-white"><div className="text-center"><div className="text-sm">Recording starts in</div><div className="tabular text-5xl font-bold">{Math.ceil(left)}</div>
            <Button size="sm" className="mt-3" onClick={() => { if (timer.current) clearInterval(timer.current); record() }}>Start now</Button></div></div>}
          {phase === 'record' && <div className="absolute left-3 top-3 flex items-center gap-2 rounded-full bg-red-600 px-3 py-1 text-sm font-semibold text-white"><span className="size-2 animate-pulse rounded-full bg-white" />REC {fmtClock(left)} left</div>}
        </div>)}
      {phase === 'review' && blob && <video controls playsInline src={URL.createObjectURL(blob)} className="aspect-video w-full rounded-xl bg-black" />}
      {phase === 'upload' && <Card className="p-5"><div className="mb-2 flex items-center gap-2 text-sm"><Spinner className="size-4" />Uploading… {Math.round(progress * 100)}%</div><div className="h-2 rounded-full bg-slate-100 dark:bg-ink-800"><div className="h-2 rounded-full bg-brand-500" style={{ width: `${progress * 100}%` }} /></div></Card>}
      {err && <Alert tone="danger">{err}</Alert>}
      {phase === 'intro' && <>
        <HowItWorks t={p.transparency} />
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={consent} onChange={e => setConsent(e.target.checked)} /><span>I agree to be recorded. The video is shared only with the hiring team and deleted under the company's retention policy.</span></label>
        <Button variant="primary" size="lg" icon={<Video />} disabled={!consent || !cam.stream} onClick={prepare}>{r.prepare_seconds ? 'Get ready' : 'Start recording'}</Button>
      </>}
      {phase === 'record' && <Button variant="danger" size="lg" icon={<Square />} onClick={() => rec.current?.stop()}>Stop recording</Button>}
      {phase === 'review' && <div className="flex flex-wrap gap-2"><Button variant="primary" size="lg" icon={<Send />} onClick={upload}>Submit this recording</Button>
        {canRetake && <Button size="lg" icon={<RotateCcw />} onClick={() => { setBlob(null); setPhase('intro') }}>Record again ({r.retakes - attempts + 1} left)</Button>}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------------------------- practical task
function TaskRound({ p, base, onDone }: { p: Page; base: string; onDone: () => void }) {
  const t = p.task!
  const [file, setFile] = useState<File | null>(null), [note, setNote] = useState(''), [busy, setBusy] = useState(false), [err, setErr] = useState('')
  if (t.uploaded || p.finished) return <Done title="Your work is submitted" link={p.status_link}>{t.uploaded ? `We received ${t.uploaded}.` : ''} The hiring team will review it.</Done>
  async function submit() {
    if (!file) return
    setBusy(true); setErr('')
    try { const fd = new FormData(); fd.append('file', file); fd.append('note', note); await send(`${base}/upload`, undefined, fd); onDone() } catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  return (
    <div className="space-y-4">
      <Card className="p-5">
        {t.instructions && <p className="whitespace-pre-line text-sm">{t.instructions}</p>}
        {t.attachment && <Button className="mt-3" icon={<Download />} href={`${base}/attachment`}>Download {t.attachment}</Button>}
      </Card>
      <HowItWorks t={p.transparency} />
      <Card className="space-y-3 p-5">
        <label className="flex cursor-pointer items-center gap-3 rounded-2xl border-2 border-dashed border-slate-200 p-5 hover:border-brand-300 dark:border-ink-700">
          <FileUp className="size-6 text-brand-500" /><span className="min-w-0 flex-1 text-sm"><span className="block font-semibold">{file ? file.name : 'Choose your file'}</span><span className="text-slate-500">{t.file_types ? `Accepted: ${t.file_types}. ` : ''}Max 25 MB.</span></span>
          <input type="file" accept={t.file_types || undefined} className="sr-only" onChange={e => setFile(e.target.files?.[0] || null)} /></label>
        <Field label="Anything to add? (optional)" htmlFor="tk-note"><Textarea id="tk-note" className="min-h-0" rows={3} value={note} onChange={e => setNote(e.target.value)} /></Field>
        {err && <Alert tone="danger">{err}</Alert>}
        <Button variant="primary" size="lg" icon={<Send />} loading={busy} disabled={!file} onClick={submit}>Submit</Button>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------- reference check
function RefRound({ p, base, onDone }: { p: Page; base: string; onDone: () => void }) {
  const R = p.references!
  const blank = () => ({ name: '', email: '', phone: '', company: '', relationship: 'manager' })
  const [rows, setRows] = useState(() => Array.from({ length: R.referees.length ? 0 : R.min }, blank))
  const [busy, setBusy] = useState(false), [err, setErr] = useState('')
  const set = (i: number, k: string, v: string) => setRows(rows.map((r, j) => j === i ? { ...r, [k]: v } : r))
  const total = R.referees.length + rows.length
  async function submit() {
    setBusy(true); setErr('')
    try { await send(`${base}/referees`, { referees: rows }); setRows([]); onDone() } catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  const valid = rows.every(r => r.name.trim() && /^\S+@\S+\.\S+$/.test(r.email.trim()))
  return (
    <div className="space-y-4">
      <HowItWorks t={p.transparency} />
      {R.referees.length > 0 && <Card className="p-5">
        <div className="mb-2 font-semibold">Your referees</div>
        <ul className="divide-y divide-slate-100 text-sm dark:divide-ink-800">{R.referees.map(r => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2"><span><b>{r.name}</b> <span className="text-slate-500 dark:text-slate-400">· {r.relationship} · {r.email}</span></span>
            {r.answered ? <Badge tone="success">Answered</Badge> : <Badge tone="warning">Waiting</Badge>}</li>))}</ul>
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">We emailed each of them. If someone hasn't seen it, ask them to check spam, or tell the hiring team.</p>
      </Card>}
      {(rows.length > 0 || R.referees.length < R.max) && <Card className="space-y-4 p-5">
        <div><div className="font-semibold">{R.referees.length ? 'Add another referee' : `Name ${R.min} to ${R.max} referees`}</div>
          <p className="text-sm text-slate-600 dark:text-slate-300">People who saw your work up close: managers, senior colleagues, clients or teachers.{R.require_manager ? ' At least one must have managed you.' : ''} Please let them know to expect an email.</p></div>
        {rows.map((r, i) => (
          <div key={i} className="grid gap-3 rounded-xl p-3 ring-1 ring-slate-200 sm:grid-cols-2 dark:ring-ink-700">
            <Field label="Name" htmlFor={`rr-n${i}`}><Input id={`rr-n${i}`} value={r.name} onChange={e => set(i, 'name', e.target.value)} /></Field>
            <Field label="Email" htmlFor={`rr-e${i}`}><Input id={`rr-e${i}`} type="email" value={r.email} onChange={e => set(i, 'email', e.target.value)} /></Field>
            <Field label="How they know you" htmlFor={`rr-r${i}`}><Select id={`rr-r${i}`} value={r.relationship} onChange={e => set(i, 'relationship', e.target.value)}>{Object.entries(R.relations).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
            <Field label="Company or college (optional)" htmlFor={`rr-c${i}`}><Input id={`rr-c${i}`} value={r.company} onChange={e => set(i, 'company', e.target.value)} /></Field>
            {rows.length > (R.referees.length ? 1 : R.min) && <Button size="sm" variant="ghost" className="w-fit" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</Button>}
          </div>))}
        <div className="flex flex-wrap gap-2">
          {total < R.max && <Button onClick={() => setRows([...rows, blank()])}>Add a referee</Button>}
          {rows.length > 0 && <Button variant="primary" icon={<Send />} loading={busy} disabled={!valid} onClick={submit}>Send the requests</Button>}
        </div>
        {err && <Alert tone="danger">{err}</Alert>}
      </Card>}
    </div>
  )
}

// ---------------------------------------------------------------------------------------------- live task (screen shared)
const canShare = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getDisplayMedia
function LiveRound({ p, base, onDone }: { p: Page; base: string; onDone: () => void }) {
  const L = p.live!
  const [ends, setEnds] = useState<number | null>(L.ends_at), [skew] = useState(() => L.server_now - Date.now() / 1000)
  const [content, setContent] = useState(L.draft || ''), [note, setNote] = useState(''), [fileName, setFileName] = useState(L.file || '')
  const [stream, setStream] = useState<MediaStream | null>(null), [consent, setConsent] = useState(!!L.started_at)
  const [left, setLeft] = useState(0), [busy, setBusy] = useState(false), [err, setErr] = useState(''), [saved, setSaved] = useState(true)
  const sub = useRef(false), last = useRef(L.draft || ''), cur = useRef(content)
  cur.current = content
  const now = () => Date.now() / 1000 + skew

  async function share(): Promise<MediaStream | null> {
    setErr('')
    try {
      const st = await navigator.mediaDevices.getDisplayMedia({ video: { displaySurface: 'monitor', frameRate: 5 } as MediaTrackConstraints, audio: false })
      const tr = st.getVideoTracks()[0]!
      const surface = (tr.getSettings() as any).displaySurface
      if (surface && surface !== 'monitor') { st.getTracks().forEach(t => t.stop()); setErr('Please share your entire screen, not a window or a tab, so the review sees all your work.'); return null }
      tr.addEventListener('ended', () => { setStream(null); send(`${base}/event`, { type: 'screen_share_stopped' }).catch(() => {}) })
      setStream(st); return st
    } catch { setErr('Screen sharing was not allowed. You need to share your screen to do this task.'); return null }
  }
  async function start() {
    const st = await share(); if (!st) return
    setBusy(true)
    try { const r = await send(`${base}/live/start`); setEnds(r.ends_at); onDone() } catch (e: any) { setErr(e.message); st.getTracks().forEach(t => t.stop()); setStream(null) }
    setBusy(false)
  }
  const submit = useCallback(async (auto = false) => {
    if (sub.current) return
    sub.current = true; setBusy(true); setErr('')
    try { await send(`${base}/live/submit`, { content: cur.current, note, auto }); stream?.getTracks().forEach(t => t.stop()); onDone() }
    catch (e: any) { setErr(e.message); sub.current = false }
    setBusy(false)
  }, [base, note, stream, onDone])

  // countdown on the server clock; submits by itself when time is up
  useEffect(() => {
    if (!ends) return
    const t = setInterval(() => { const l = ends - 15 - now(); setLeft(l); if (l <= 0) submit(true) }, 500)   // the server adds 15 s of grace
    return () => clearInterval(t)
  }, [ends, submit])   // eslint-disable-line react-hooks/exhaustive-deps
  // autosave every 5 seconds when something changed
  useEffect(() => {
    if (!ends) return
    const t = setInterval(async () => { if (cur.current !== last.current) { const v = cur.current; try { await send(`${base}/live/save`, { content: v }); last.current = v; setSaved(true) } catch { /* retried next tick */ } } }, 5000)
    return () => clearInterval(t)
  }, [ends, base])
  // a screenshot of the shared screen at the chosen interval
  useEffect(() => {
    if (!stream || !ends) return
    const snap = async () => { try { const b = await grab(stream, 1280, 0.6); if (b) { const fd = new FormData(); fd.append('image', b, 'screen.jpg'); fd.append('reason', 'screen'); await send(`${base}/snapshot`, undefined, fd) } } catch { /* best effort */ } }
    snap()
    const t = setInterval(snap, Math.max(15, L.snapshot_every_sec) * 1000)
    return () => clearInterval(t)
  }, [stream, ends, base, L.snapshot_every_sec])
  useEffect(() => () => { stream?.getTracks().forEach(t => t.stop()) }, [stream])
  useEffect(() => {
    if (!ends) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault() }
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn)
  }, [ends])

  if (L.submitted || p.finished) return <Done title="Your work is submitted" link={p.status_link}>The hiring team will review your work and how you approached it.</Done>
  async function upload(f: File) {
    setBusy(true); setErr('')
    try { const fd = new FormData(); fd.append('file', f); const r = await send(`${base}/upload`, undefined, fd); setFileName(r.name || f.name); toast('File attached') } catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  function tab(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== 'Tab' || L.deliverable !== 'code') return
    e.preventDefault()
    const el = e.currentTarget, a = el.selectionStart, b = el.selectionEnd
    const v = content.slice(0, a) + '    ' + content.slice(b)
    setContent(v); setSaved(false)
    requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = a + 4 })
  }

  if (!ends) return (
    <div className="space-y-4">
      <Card className="p-5 text-sm">
        <div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-400"><MonitorUp className="size-5" /></span>
          <div><div className="font-semibold">A {L.minutes}-minute live task, done while sharing your screen</div>
            <p className="mt-1 text-slate-600 dark:text-slate-300">You'll see the task when you press Start. Work in any tool you like ({L.deliverable === 'code' ? `your editor or IDE; ${L.language || 'any language'}` : L.deliverable === 'file' ? 'design or office software' : 'any app'}), then hand in your work on this page.</p></div></div>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-slate-600 dark:text-slate-300">
          <li>Use a laptop or desktop with Chrome or Edge. Phones can't share a screen.</li>
          <li>Share your <b>entire screen</b> when asked. A screenshot is kept about every {L.snapshot_every_sec} seconds for the hiring team.</li>
          <li>Close anything private (chats, email, other tabs) before you start.</li>
          <li>The timer runs on our server. If you close this page, it keeps running and what you typed is saved every few seconds.</li>
        </ul>
      </Card>
      <HowItWorks t={p.transparency} />
      {!canShare ? <Alert tone="warning" title="This device can't share its screen">Please open this link on a laptop or desktop in Chrome or Edge.</Alert> : <>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5 size-4 accent-brand-600" checked={consent} onChange={e => setConsent(e.target.checked)} />
          <span>I agree to share my screen and for screenshots to be kept for the hiring team.</span></label>
        {err && <Alert tone="danger">{err}</Alert>}
        <Button variant="primary" size="lg" icon={<MonitorUp />} disabled={!consent} loading={busy} onClick={start}>Share my screen and start</Button>
      </>}
    </div>
  )

  const low = left < 300
  return (
    <div className="space-y-4">
      <div className="sticky top-2 z-10 flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-white/90 p-3 shadow-sm ring-1 ring-slate-200 backdrop-blur dark:bg-ink-900/90 dark:ring-ink-700">
        <span className={cn('tabular flex items-center gap-1.5 text-lg font-bold', low && 'text-red-600 dark:text-red-400')}><AlarmClock className="size-5" />{fmtClock(left)}</span>
        {stream ? <Badge tone="success" icon={<MonitorUp />}>Sharing your screen</Badge> : <Badge tone="danger" icon={<MonitorUp />}>Not sharing</Badge>}
        <span className="text-xs text-slate-500 dark:text-slate-400">{saved ? 'Saved' : 'Saving…'}</span>
      </div>
      {!stream && <Alert tone="warning" title="Your screen isn't being shared">The hiring team can't see your work until you share again. <Button className="mt-2" size="sm" icon={<MonitorUp />} onClick={share}>Share my screen</Button></Alert>}
      <Card className="p-5"><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">The task</div><p className="whitespace-pre-line text-sm">{L.instructions || 'Follow the instructions from the hiring team.'}</p>
        {L.rubric.length > 0 && <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">Reviewed on: {L.rubric.join(', ')}</p>}</Card>
      <Card className="space-y-3 p-5">
        {(L.deliverable === 'code' || L.deliverable === 'text') && <Field label={L.deliverable === 'code' ? `Your code${L.language ? ` (${L.language})` : ''}` : 'Your answer'} htmlFor="lv-work"
          hint={L.deliverable === 'code' ? 'Write here or paste from your editor before time runs out. Tab inserts spaces.' : undefined}>
          <Textarea id="lv-work" rows={16} spellCheck={L.deliverable !== 'code'} value={content} onKeyDown={tab} onChange={e => { setContent(e.target.value); setSaved(false) }}
            className={cn(L.deliverable === 'code' && 'font-mono text-[13px] leading-relaxed')} /></Field>}
        {L.deliverable === 'file' && <label className="flex cursor-pointer items-center gap-3 rounded-2xl border-2 border-dashed border-slate-200 p-5 hover:border-brand-300 dark:border-ink-700">
          <FileUp className="size-6 text-brand-500" /><span className="min-w-0 flex-1 text-sm"><span className="block font-semibold">{fileName ? `Attached: ${fileName}` : 'Attach your file'}</span><span className="text-slate-500 dark:text-slate-400">{fileName ? 'Choose again to replace it. ' : ''}Max 25 MB.</span></span>
          <input type="file" className="sr-only" onChange={e => { const f = e.target.files?.[0]; if (f) upload(f) }} /></label>}
        <Field label="Notes for the reviewer (optional)" htmlFor="lv-note" hint="Assumptions, what you'd do with more time."><Textarea id="lv-note" className="min-h-0" rows={2} value={note} onChange={e => setNote(e.target.value)} /></Field>
        {err && <Alert tone="danger">{err}</Alert>}
        <Button variant="primary" size="lg" icon={<Send />} loading={busy}
          disabled={L.deliverable === 'file' ? !fileName : (L.deliverable === 'code' || L.deliverable === 'text') ? !content.trim() : false}
          onClick={async () => { if (await ask('Submit your work now? You can\'t change it after this.', { confirm: 'Submit' })) submit(false) }}>Submit</Button>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------- AI interview
interface AISched { allowed: boolean; booking: { starts_at: number; ends_at: number; by?: string } | null; can_change: boolean; why: string; changes_left: number; timezone: string; missed: boolean; slots: number[] }
function AIPick({ sch, base, reload, deadline, onDone }: { sch: AISched; base: string; reload: () => void; deadline: number | null; onDone?: () => void }) {
  const [open, setOpen] = useState(!!onDone), [pick, setPick] = useState(''), [busy, setBusy] = useState(false), [err, setErr] = useState('')
  async function book() {
    setBusy(true); setErr('')
    try { await send(`${base}/ai-book`, { starts_at: Number(pick) }); toast('Interview time booked. Check your email for the confirmation.'); onDone?.(); reload() } catch (e: any) { setErr(e.message); reload() }
    setBusy(false)
  }
  if (!open) return (
    <Card className="flex flex-wrap items-center justify-between gap-3 p-4 text-sm">
      <span>{sch.missed ? 'You missed your booked time. No problem: ' : 'Not ready right now? '}Book a time that suits you{deadline ? ` before ${new Date(deadline * 1000).toLocaleDateString([], { day: 'numeric', month: 'short' })}` : ''} and we'll email you a confirmation and reminders.</span>
      <Button icon={<CalendarPlus />} onClick={() => setOpen(true)}>Book a time</Button>
    </Card>)
  return (
    <Card className="p-5">
      <div className="mb-1 text-base font-semibold">{sch.booking ? 'Pick a new time' : 'Book a time for your AI interview'}</div>
      <p className="mb-4 text-sm text-slate-600 dark:text-slate-300">The AI interviewer is available all day. We only show times with room, so your interview starts without waiting.</p>
      <SlotPicker items={sch.slots.map(t => ({ id: String(t), starts_at: t }))} value={pick} onChange={setPick} empty="No times are left before your deadline. You can still start the interview now." />
      {err && <Alert className="mt-3" tone="danger">{err}</Alert>}
      <div className="mt-4 flex flex-wrap gap-2"><Button variant="primary" icon={<CalendarCheck />} disabled={!pick} loading={busy} onClick={book}>{pick ? `Book ${fullWhen(Number(pick))}` : 'Book this time'}</Button>
        <Button onClick={() => { setOpen(false); onDone?.() }}>Not now</Button></div>
    </Card>
  )
}
function AIBooked({ sch, base, reload }: { sch: AISched; base: string; reload: () => void }) {
  const [change, setChange] = useState(false), [busy, setBusy] = useState(false)
  const b = sch.booking!
  async function cancel() {
    if (!await ask('Cancel your interview time? You can book another time or start any time before your deadline.', { confirm: 'Cancel the time' })) return
    setBusy(true)
    try { await send(`${base}/cancel`); toast('Interview time cancelled'); reload() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  if (change) return <AIPick sch={sch} base={base} reload={reload} deadline={null} onDone={() => setChange(false)} />
  return (
    <Card className="p-5">
      <div className="flex items-start gap-3"><span className="grid size-11 shrink-0 place-items-center rounded-xl bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300"><CalendarCheck className="size-5" /></span>
        <div className="text-sm"><div className="text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">Booked{b.by && b.by !== 'candidate' ? ' by the hiring team' : ''}</div>
          <div className="text-lg font-semibold">{fullWhen(b.starts_at)}</div>
          <div className="text-slate-600 dark:text-slate-300">Come back to this page at that time and press Start. We'll remind you a day before, an hour before and when it's time.</div></div></div>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button icon={<CalendarPlus />} href={`${base}/calendar.ics`}>Add to calendar</Button>
        {sch.can_change && <Button icon={<RotateCcw />} onClick={() => setChange(true)}>Change the time</Button>}
        {sch.can_change && <Button variant="ghost" className="text-red-600 dark:text-red-400" loading={busy} onClick={cancel}>Cancel</Button>}
      </div>
      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">{sch.can_change ? `${sch.changes_left} change(s) left, up to 30 minutes before.` : sch.why}</p>
    </Card>
  )
}
const LANG: Record<string, string> = { en: 'English', hi: 'Hindi', 'hi-en': 'Hindi or English (Hinglish is fine)', ta: 'Tamil', te: 'Telugu', kn: 'Kannada', mr: 'Marathi', bn: 'Bengali', gu: 'Gujarati', ml: 'Malayalam' }
function AIRound({ p, base, reload }: { p: Page; base: string; reload: () => void }) {
  const iv = p.interview
  const [human, setHuman] = useState(false), [note, setNote] = useState(''), [asked, setAsked] = useState(p.human_requested), [calling, setCalling] = useState(''), [err, setErr] = useState('')
  useEffect(() => { if (!iv.preparing) return; const t = setInterval(reload, 5000); return () => clearInterval(t) }, [iv.preparing, reload])
  if (p.finished) return <Done title="Your interview is complete" link={p.status_link}>Thank you. A person from the hiring team reviews every interview.</Done>
  async function askHuman() { try { await send(`${base}/request-human`, { note }); setAsked(true); setHuman(false) } catch (e: any) { setErr(e.message) } }
  async function callMe() { setErr(''); try { const r = await send(`${base}/call-me`); setCalling(r.number) } catch (e: any) { setErr(e.message) } }
  return (
    <div className="space-y-4">
      <Card className="p-5 text-sm">
        <div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600 dark:text-brand-400 dark:bg-brand-500/15"><Headphones className="size-5" /></span>
          <div><div className="font-semibold">A {iv.duration_min}-minute voice interview with an AI interviewer</div>
            <p className="mt-1 text-slate-600 dark:text-slate-300">You will talk to an AI assistant, not a person. It starts with a short practice question, then asks about the role and your experience. Language: {LANG[iv.language] || iv.language}.</p></div></div>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-slate-600 dark:text-slate-300"><li>Use a quiet room, a laptop or phone with a camera and microphone, and Chrome, Edge or Safari.</li>
          <li>The interview is recorded and transcribed for the hiring team. You'll be asked to agree before it starts.</li><li>You can ask the interviewer about the company; it answers from information the company approved.</li></ul>
      </Card>
      <HowItWorks t={p.transparency} />
      {err && <Alert tone="danger">{err}</Alert>}
      {iv.preparing ? <Card className="flex items-center gap-3 p-5 text-sm"><Spinner className="size-5 text-brand-500" />Preparing your interview. This takes under a minute; the page updates by itself.</Card>
        : iv.url ? <>
          {iv.schedule?.booking && <AIBooked sch={iv.schedule} base={base} reload={reload} />}
          <div className="flex flex-wrap gap-2"><Button variant="primary" size="lg" icon={<Mic />} href={iv.url}>{iv.schedule?.booking ? 'Start now' : 'Start the interview now'}</Button>
            {iv.phone_available && <Button size="lg" icon={<Phone />} onClick={callMe} disabled={!!calling}>{calling ? `Calling …${calling}` : 'Call my phone instead'}</Button>}</div>
          {iv.schedule?.allowed && !iv.schedule.booking && <AIPick sch={iv.schedule} base={base} reload={reload} deadline={p.deadline_at} />}
        </>
        : <Alert tone="info">The interview link isn't ready. Please check back shortly or contact the hiring team.</Alert>}
      {calling && <Alert tone="success" title="We're calling you now">Answer the call from an unknown number. If you miss it, you can try again later or use the browser.</Alert>}
      {asked ? <Alert tone="info" icon={<UserRound />}>You asked for an interview with a person. The hiring team will reply; you can still take the AI interview if you prefer.</Alert>
        : <button className="text-sm font-medium text-brand-600 dark:text-brand-400 hover:underline" onClick={() => setHuman(true)}>I'd prefer to be interviewed by a person</button>}
      <Modal open={human} onOpenChange={setHuman} title="Ask for a human interviewer" description="The hiring team decides and will get back to you. Tell them anything that helps (optional)."
        footer={<><Button onClick={() => setHuman(false)}>Cancel</Button><Button variant="primary" onClick={askHuman}>Send request</Button></>}>
        <Textarea className="mt-4" rows={3} value={note} onChange={e => setNote(e.target.value)} aria-label="Note" placeholder="For example: I have a speech difference, or I'm not comfortable with AI interviews." />
      </Modal>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------- human interview booking
interface Slot { id: string; starts_at: number; ends_at: number; interviewer: string; location: string }
interface HumanIv {
  booking: { starts_at: number; ends_at: number; location: string; interviewer: string; has_link: boolean; by?: string } | null; slots: Slot[]
  can_change: boolean; why: string; cutoff_hours: number; reschedules_left: number; duration_min: number; mode: string; timezone: string
  time_request: { note: string; at: number } | null; cancelled: { starts_at: number; cancelled_by: string; cancel_reason: string } | null
}
const MODE: Record<string, string> = { video: 'Video call', in_person: 'In person', phone: 'Phone call' }

function BookRound({ p, base, reload }: { p: Page; base: string; reload: () => void }) {
  const iv = p.interview as HumanIv
  const [pick, setPick] = useState(''), [busy, setBusy] = useState(''), [change, setChange] = useState(false), [err, setErr] = useState('')
  const [none, setNone] = useState(false), [note, setNote] = useState(''), [cancel, setCancel] = useState(false), [reason, setReason] = useState('')
  async function run(what: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(what); setErr('')
    try { await fn(); toast(ok); setChange(false); setPick(''); setNone(false); setCancel(false); reload() } catch (e: any) { setErr(e.message); reload() }
    setBusy('')
  }
  if (p.finished && !iv.booking) return <Done title="This interview round is complete" link={p.status_link} />
  const mode = MODE[iv.mode] || iv.mode
  const picker = (
    <Card className="p-5">
      <div className="mb-1 text-base font-semibold">{iv.booking ? 'Pick a new time' : 'Pick a time for your interview'}</div>
      <p className="mb-4 text-sm text-slate-600 dark:text-slate-300">{mode}, {iv.duration_min} minutes.{iv.booking ? ` Your current time is kept until you confirm the new one, and it opens up for others once you move. ${iv.reschedules_left} change(s) left.` : ''}</p>
      <SlotPicker items={iv.slots.map(s => ({ id: s.id, starts_at: s.starts_at, note: s.interviewer || undefined }))} value={pick} onChange={setPick}
        empty="No times are open right now. Tell us what suits you below and we'll email you when new times open." />
      {err && <Alert className="mt-3" tone="danger">{err}</Alert>}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant="primary" icon={<CalendarCheck />} disabled={!pick || !!busy} loading={busy === 'book'}
          onClick={() => run('book', () => send(`${base}/book`, { slot_id: pick }), iv.booking ? 'Interview moved' : 'Interview booked')}>
          {pick ? `${iv.booking ? 'Move to' : 'Book'} ${fullWhen(iv.slots.find(s => s.id === pick)!.starts_at)}` : iv.booking ? 'Move my interview' : 'Book this time'}</Button>
        {change && <Button onClick={() => { setChange(false); setPick('') }}>Keep my current time</Button>}
        <Button variant="ghost" onClick={() => setNone(true)}>None of these times work</Button>
      </div>
    </Card>
  )
  return (
    <div className="space-y-4">
      {iv.cancelled && !iv.booking && <Alert tone="warning" title="Your interview time was cancelled">
        {fullWhen(iv.cancelled.starts_at)} was cancelled {iv.cancelled.cancelled_by === 'candidate' ? 'by you' : 'by the hiring team'}{iv.cancelled.cancel_reason && iv.cancelled.cancelled_by !== 'candidate' ? `: ${iv.cancelled.cancel_reason}` : '.'} Please pick a new time.</Alert>}
      {iv.time_request && !iv.booking && <Alert tone="info" title="We've told the hiring team">You suggested: "{iv.time_request.note}". You'll get an email when new times open.</Alert>}
      {iv.booking && !change ? (
        <Card className="p-5">
          <div className="flex items-start gap-3"><span className="grid size-11 shrink-0 place-items-center rounded-xl bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300"><CalendarCheck className="size-5" /></span>
            <div className="text-sm"><div className="text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">Confirmed{iv.booking.by && iv.booking.by !== 'candidate' ? ' by the hiring team' : ''}</div>
              <div className="text-lg font-semibold">{fullWhen(iv.booking.starts_at)}</div>
              <div className="text-slate-600 dark:text-slate-300">{mode}, {iv.duration_min} minutes{iv.booking.interviewer ? ` with ${iv.booking.interviewer}` : ''}{iv.booking.location ? ` · ${iv.booking.location}` : ''}</div></div></div>
          <div className="mt-4 flex flex-wrap gap-2">
            {iv.booking.has_link && <Button variant="primary" icon={<Video />} href={`${base}/join`} target="_blank">Join the meeting</Button>}
            <Button icon={<CalendarPlus />} href={`${base}/calendar.ics`}>Add to calendar</Button>
            {iv.can_change && !p.finished && <Button icon={<RotateCcw />} onClick={() => setChange(true)}>Change the time</Button>}
            {iv.can_change && !p.finished && <Button variant="ghost" className="text-red-600 dark:text-red-400" onClick={() => setCancel(true)}>Cancel</Button>}
          </div>
          <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">{iv.can_change ? `You can change or cancel up to ${iv.cutoff_hours} hours before (${iv.reschedules_left} change(s) left). The confirmation and calendar invite are in your email.` : iv.why}</p>
        </Card>
      ) : picker}
      {err && !change && iv.booking && <Alert tone="danger">{err}</Alert>}
      <HowItWorks t={p.transparency} />
      <Modal open={none} onOpenChange={setNone} title="Suggest times that work for you" description="The hiring team gets your note and can add times or book one for you. You'll get an email when new times open."
        footer={<><Button onClick={() => setNone(false)}>Cancel</Button><Button variant="primary" loading={busy === 'times'} disabled={note.trim().length < 5}
          onClick={() => run('times', () => send(`${base}/request-times`, { note }), 'Sent to the hiring team')}>Send</Button></>}>
        <Textarea className="mt-4" rows={3} aria-label="Times that suit you" value={note} onChange={e => setNote(e.target.value)} placeholder="For example: weekdays after 5 pm, or Saturday morning" />
      </Modal>
      <Modal open={cancel} onOpenChange={setCancel} title="Cancel this interview time?" description="The time is released for others. You can pick a new time right after, from this page."
        footer={<><Button onClick={() => setCancel(false)}>Keep it</Button><Button variant="danger" loading={busy === 'cancel'}
          onClick={() => run('cancel', () => send(`${base}/cancel`, { reason }), 'Interview time cancelled')}>Cancel the time</Button></>}>
        <Textarea className="mt-4" rows={2} aria-label="Reason (optional)" value={reason} onChange={e => setReason(e.target.value)} placeholder="Reason (optional)" />
      </Modal>
    </div>
  )
}
