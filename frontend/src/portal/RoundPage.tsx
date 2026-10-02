// The candidate's page for one round (/r/<token>): a proctored test, a video or role-task recording, a practical
// task upload, the AI interview start page, or booking a human interview.
import { AlarmClock, CalendarCheck, CalendarPlus, Camera, CircleCheck, Download, FileUp, Headphones, Maximize, Mic, Phone, RotateCcw, Send, Square, UserRound, Video } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Badge, Button, Card, Field, Modal, Spinner, Textarea, cn, toast } from '../components/ui'
import { when } from '../lib/format'
import { Frame, HowItWorks, PageState, Preview, fmtClock, getJSON, grab, send, useCamera, useLoad, type Brand, type Transparency } from './common'

interface Page {
  type: string; name: string; status: string; status_label: string; deadline_at: number | null; message: string; org: Brand; job: { title: string }
  candidate: { first_name: string; has_photo: boolean }; transparency: Transparency; finished: boolean; current: boolean; withdrawn: boolean; status_link: string
  human_requested: boolean; accommodation: string | null
  test?: { sections: { label: string; count: number; minutes: number }[]; negative_marking: number; max_exits: number; require_camera: boolean; started: boolean; sessions_used: number; max_sessions: number; window: { opens_at: number | null; closes_at: number | null; open: boolean; college: string } | null; extra_time: boolean; done?: boolean }
  recording?: { prompt: string; brief: string; max_seconds: number; retakes: number; prepare_seconds: number; uploaded: boolean }
  task?: { instructions: string; file_types: string; attachment: string | null; rubric: string[]; uploaded: string | null }
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
            <div className="mb-3 flex gap-2"><span className="tabular font-semibold text-slate-400">{it.n}.</span><p className="flex-1 whitespace-pre-line font-medium">{it.text}</p>{it.marks !== 1 && <span className="text-xs text-slate-500">{it.marks} marks</span>}</div>
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

// ---------------------------------------------------------------------------------------------- AI interview
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
        : iv.url ? <div className="flex flex-wrap gap-2"><Button variant="primary" size="lg" icon={<Mic />} href={iv.url}>Start the interview</Button>
          {iv.phone_available && <Button size="lg" icon={<Phone />} onClick={callMe} disabled={!!calling}>{calling ? `Calling …${calling}` : 'Call my phone instead'}</Button>}</div>
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
function BookRound({ p, base, reload }: { p: Page; base: string; reload: () => void }) {
  const iv = p.interview as { booking: { starts_at: number; ends_at: number; location: string; interviewer: string; has_link: boolean } | null; slots: Slot[]; reschedules_left: number; duration_min: number; mode: string }
  const [pick, setPick] = useState(''), [busy, setBusy] = useState(false), [change, setChange] = useState(false), [err, setErr] = useState('')
  async function book() {
    setBusy(true); setErr('')
    try { await send(`${base}/book`, { slot_id: pick }); toast('Booked'); setChange(false); reload() } catch (e: any) { setErr(e.message); reload() }
    setBusy(false)
  }
  if (p.finished && !iv.booking) return <Done title="This interview round is complete" link={p.status_link} />
  const days = new Map<string, Slot[]>()
  for (const s of iv.slots) { const k = new Date(s.starts_at * 1000).toDateString(); days.set(k, [...(days.get(k) || []), s]) }
  const mode = { video: 'Video call', in_person: 'In person', phone: 'Phone call' }[iv.mode] || iv.mode
  return (
    <div className="space-y-4">
      {iv.booking && !change ? (
        <Card className="p-5">
          <div className="flex items-start gap-3"><CalendarCheck className="size-6 text-emerald-600" /><div className="text-sm">
            <div className="text-base font-semibold">{when(iv.booking.starts_at)}</div>
            <div className="text-slate-600 dark:text-slate-300">{mode}, {iv.duration_min} minutes{iv.booking.interviewer ? ` with ${iv.booking.interviewer}` : ''}{iv.booking.location ? ` · ${iv.booking.location}` : ''}</div></div></div>
          <div className="mt-4 flex flex-wrap gap-2">
            {iv.booking.has_link && <Button variant="primary" icon={<Video />} href={`${base}/join`} target="_blank">Join the meeting</Button>}
            <Button icon={<CalendarPlus />} href={`${base}/calendar.ics`}>Add to calendar</Button>
            {iv.reschedules_left > 0 && iv.slots.length > 0 && !p.finished && <Button variant="ghost" onClick={() => setChange(true)}>Change the time</Button>}
          </div>
        </Card>
      ) : !iv.slots.length ? <Alert tone="info" title="No times available right now">The hiring team will add more times soon. Check back on this page.</Alert> : (
        <Card className="p-5">
          <div className="mb-3 text-sm font-semibold">Pick a time ({mode}, {iv.duration_min} minutes){iv.booking && <span className="font-normal text-slate-500"> · {iv.reschedules_left} change(s) left</span>}</div>
          <div className="space-y-4">{[...days.entries()].map(([d, list]) => (
            <div key={d}><div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">{new Date(list[0]!.starts_at * 1000).toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'short' })}</div>
              <div className="flex flex-wrap gap-2">{list.map(s => <button key={s.id} aria-pressed={pick === s.id} onClick={() => setPick(s.id)}
                className={cn('tabular rounded-lg px-3 py-2 text-sm font-medium ring-1', pick === s.id ? 'bg-brand-600 text-white ring-brand-600' : 'ring-slate-200 hover:bg-slate-50 dark:ring-ink-700 dark:hover:bg-ink-850')}>
                {new Date(s.starts_at * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</button>)}</div></div>))}</div>
          {err && <Alert className="mt-3" tone="danger">{err}</Alert>}
          <div className="mt-4 flex gap-2"><Button variant="primary" icon={<CalendarCheck />} disabled={!pick} loading={busy} onClick={book}>{iv.booking ? 'Move my interview' : 'Book this time'}</Button>
            {change && <Button onClick={() => setChange(false)}>Keep my current time</Button>}</div>
          <p className="mt-2 text-xs text-slate-500">Times are shown in your device's time zone.</p>
        </Card>)}
      <HowItWorks t={p.transparency} />
      {!iv.booking && <p className="flex items-center gap-1.5 text-xs text-slate-500"><Camera className="size-3.5" />You'll get a calendar invite by email once you book.</p>}
    </div>
  )
}
