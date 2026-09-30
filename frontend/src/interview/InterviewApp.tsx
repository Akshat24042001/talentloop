import {
  AudioLines, Bot, Captions, CaptionsOff, Check, Eye, Lock, MessageSquareText, Mic, MicOff, Monitor, MonitorUp, PhoneOff,
  RefreshCw, ScreenShare, ScreenShareOff, ShieldCheck, Sun, TriangleAlert, UserRound, Video, Volume2, WifiOff, X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { Button, Logo, Modal, Spinner, Tip, Toaster, TooltipProvider, cn, toast } from '../components/ui'
import { InterviewEngine, isMobile, type CheckKey, type State } from './engine'

const engine = new InterviewEngine()
// Stable ref callbacks: an inline arrow would detach and re-attach the stream on every render.
const vref = {
  preview: (el: HTMLVideoElement | null) => engine.attach('preview', el),
  sharePreview: (el: HTMLVideoElement | null) => engine.attach('sharePreview', el),
  self: (el: HTMLVideoElement | null) => engine.attach('self', el),
  screen: (el: HTMLVideoElement | null) => engine.attach('screen', el),
}
;(window as any).__mediaLive = () => engine.liveTracks()

function useEngine(): State { return useSyncExternalStore(engine.subscribe, engine.getState) }
/** Level meters update DOM directly at 60 fps (no React re-render). */
function useLevel(cb: (mic: number, ai: number) => void) { useEffect(() => engine.onLevels(cb), [cb]) }

export default function InterviewApp() {
  const s = useEngine()
  useEffect(() => { engine.load() }, [])
  useEffect(() => { document.body.classList.add('call-mode') }, [])
  return (
    <TooltipProvider>
      {s.step === 'call' ? <CallStage s={s} /> : <PreCall s={s} />}
      <Overlays s={s} />
      <Toaster dark />
    </TooltipProvider>
  )
}

// =====================================================================================================
// Before and after the call
// =====================================================================================================
function Shell({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="relative min-h-dvh overflow-hidden bg-ink-950 text-slate-100">
      <div aria-hidden className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[900px] -translate-x-1/2 rounded-full bg-brand-600/20 blur-[120px]" />
      <div aria-hidden className="pointer-events-none absolute -bottom-40 right-0 h-[380px] w-[520px] rounded-full bg-violet-600/10 blur-[120px]" />
      <header className="relative mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
        <Logo />
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white/5 px-3 py-1 text-xs font-medium text-slate-300 ring-1 ring-white/10"><Lock className="size-3.5" />Secure AI interview</span>
      </header>
      <main className={cn('relative mx-auto px-5 pb-16', wide ? 'max-w-6xl' : 'max-w-3xl')}>{children}</main>
    </div>
  )
}

function PreCall({ s }: { s: State }) {
  if (s.step === 'loading') return <Shell><div className="grid min-h-[60vh] place-items-center"><Spinner className="size-7 text-brand-400" /></div></Shell>
  if (s.step === 'blocked') return <Shell><div id="blocker" className="mt-10 rounded-2xl bg-red-500/10 p-6 text-red-200 ring-1 ring-red-500/20"><TriangleAlert className="mb-2 size-6" />{s.blocked}</div></Shell>
  if (s.step === 'consent') return <Consent s={s} />
  if (s.step === 'check') return <Lobby s={s} />
  return <Done s={s} />
}

function Consent({ s }: { s: State }) {
  const P = s.P!
  const [agree, setAgree] = useState(!!P.resuming)
  const first = P.candidate_name?.split(' ')[0]
  const mw = P.max_warnings
  const rules: { icon: ReactNode; strict?: boolean; text: ReactNode; show?: boolean }[] = [
    { icon: <MessageSquareText />, text: <>An <b>AI interviewer</b> talks with you, one question at a time. The question is always on your screen, and you can say <b>"please repeat"</b> any time.</> },
    { icon: <Sun />, text: <>Sit somewhere quiet and well lit, using the latest <b>Chrome or Edge</b>{P.require_screen_share ? <> on a <b>laptop or desktop</b></> : null}. Headphones help.</> },
    { icon: <UserRound />, text: <>Keep your <b>camera on</b> and your face visible. Only you should be in view.</> },
    { icon: <Eye />, strict: P.enforce_focus, text: !P.enforce_focus ? <><b>Stay on this screen.</b> Leaving the page or switching windows is recorded for HR.</>
      : mw > 0 ? <><b>Stay on this screen.</b> If you switch tabs, windows or apps, the interviewer will warn you. After <b>{mw} warning{mw === 1 ? '' : 's'}</b>, the next time ends the interview.</>
      : <><b>Stay on this screen.</b> Switching tabs, windows or apps <b>ends the interview immediately</b>.</> },
    { icon: <Monitor />, strict: true, show: P.block_multi_monitor, text: <>Use <b>one screen only</b>. Disconnect any extra monitor first. A second screen counts as leaving the interview.</> },
    { icon: <ScreenShare />, show: P.require_screen_share, text: <>You'll <b>share your entire screen</b> for the whole interview.</> },
    { icon: <RefreshCw />, text: <>If your connection drops, rejoin within <b>{P.reconnect_window_sec} seconds</b>.</> },
  ]
  return (
    <Shell wide>
      <div className="grid gap-8 pt-4 lg:grid-cols-[1.15fr_.85fr] lg:gap-12 lg:pt-10">
        <section className="animate-rise">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-500/15 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-brand-300"><Bot className="size-3.5" />AI interview</span>
          <h1 id="title" className="mt-4 text-3xl font-semibold tracking-tight text-white sm:text-4xl">{P.role || 'Interview'}</h1>
          {P.company && <p className="mt-1 text-lg text-slate-400">{P.company}</p>}
          <p className="mt-5 text-[15px] leading-relaxed text-slate-300">{first ? `Hi ${first}, welcome.` : 'Welcome.'} This is a first-round conversation with an AI interviewer. Here's how it works:</p>
          <ul className="mt-6 grid gap-2.5">
            {rules.filter(r => r.show !== false).map((r, i) => (
              <li key={i} className="flex gap-3.5 rounded-2xl bg-white/[.03] p-3.5 ring-1 ring-white/[.07]">
                <span className={cn('grid size-9 shrink-0 place-items-center rounded-xl [&_svg]:size-[18px]', r.strict ? 'bg-red-500/15 text-red-300' : 'bg-brand-500/15 text-brand-300')}>{r.icon}</span>
                <span className="text-sm leading-relaxed text-slate-300 [&_b]:font-semibold [&_b]:text-white">{r.text}</span>
              </li>
            ))}
          </ul>
        </section>
        <aside className="lg:pt-12">
          <div className="sticky top-6 rounded-3xl bg-ink-850/80 p-6 shadow-2xl ring-1 ring-white/10 backdrop-blur">
            <h2 className="text-lg font-semibold text-white">{P.resuming ? 'Rejoin your interview' : 'Before you begin'}</h2>
            <p className="mt-1 text-sm text-slate-400">Next, we'll check your camera, microphone{P.require_screen_share ? ', screen' : ''} and connection.</p>
            <label className="mt-5 flex cursor-pointer gap-3 rounded-2xl bg-white/[.04] p-4 ring-1 ring-white/10 hover:bg-white/[.06]">
              <input id="consent" type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)} className="mt-0.5 size-[18px] shrink-0 accent-brand-500" />
              <span className="text-[12.5px] leading-relaxed text-slate-300">I agree that this interview (my camera video, audio, screen if shared, snapshots, transcript and the events above) will be recorded and processed by AI services, including cloud providers that may be outside India, only to evaluate my application. A person at the company reviews the result and makes the decision. I can ask HR for a human interview instead, and ask for my data to be deleted.</span>
            </label>
            <Button id="toCheck" variant="primary" size="lg" className="mt-5 w-full" disabled={!agree || s.rejoin.left === 0} onClick={() => engine.toCheck()}>
              {P.resuming ? 'Rejoin your interview' : 'Continue to device check'}
            </Button>
            {s.rejoin.left != null && <p className="mt-3 text-center text-sm text-amber-300">{s.rejoin.left > 0 ? `${s.rejoin.left}s left to rejoin` : 'Rejoin window has passed.'}</p>}
          </div>
        </aside>
      </div>
    </Shell>
  )
}

function CheckRow({ id, c, icon }: { id: string; c: State['checks'][CheckKey]; icon: ReactNode }) {
  if (c.hidden) return null
  return (
    <li id={id} className={cn('flex items-center gap-3 rounded-xl px-3.5 py-3 ring-1 transition-colors', c.state || 'pending',
      c.state === 'ok' ? 'bg-emerald-500/[.07] ring-emerald-500/20' : c.state === 'bad' ? 'bg-red-500/10 ring-red-500/25' : 'bg-white/[.03] ring-white/[.07]')}>
      <span className="text-slate-400 [&_svg]:size-[18px]">{icon}</span>
      <span className={cn('min-w-0 flex-1 text-sm', c.state === 'bad' ? 'text-red-200' : 'text-slate-200')}>{c.text}</span>
      {c.state === 'ok' ? <span className="grid size-6 place-items-center rounded-full bg-emerald-500 text-white"><Check className="size-3.5" strokeWidth={3} /></span>
        : c.state === 'bad' ? <span className="grid size-6 place-items-center rounded-full bg-red-500 text-white"><X className="size-3.5" strokeWidth={3} /></span>
        : <Spinner className="size-5 text-slate-500" />}
    </li>
  )
}

function Lobby({ s }: { s: State }) {
  const P = s.P!
  const meter = useRef<HTMLDivElement>(null)
  useLevel(useMemo(() => (mic: number) => { if (meter.current) meter.current.style.transform = `scaleX(${Math.min(1, mic * 1.1)})` }, []))
  const [beeped, setBeeped] = useState(false)
  return (
    <Shell wide>
      <div className="grid items-start gap-6 pt-2 lg:grid-cols-[1.45fr_1fr] lg:gap-10 lg:pt-6">
        <section>
          <div className="relative aspect-video overflow-hidden rounded-3xl bg-ink-900 shadow-2xl ring-1 ring-white/10">
            <video id="preview" ref={vref.preview} className="mirror size-full object-cover" autoPlay muted playsInline />
            {!s.checks.cam.state && <div className="absolute inset-0 grid place-items-center text-sm text-slate-400"><span className="flex items-center gap-2"><Spinner className="size-4" />Starting your camera...</span></div>}
            <div className="absolute inset-x-0 bottom-0 flex items-end justify-between gap-3 bg-gradient-to-t from-black/60 to-transparent p-4">
              <span className="rounded-lg bg-black/50 px-2.5 py-1 text-xs font-semibold text-white backdrop-blur">{P.candidate_name || 'You'}</span>
              <div className="flex items-center gap-2 rounded-lg bg-black/50 px-2.5 py-1.5 backdrop-blur">
                <Mic className="size-3.5 text-slate-200" />
                <div className="h-1.5 w-24 overflow-hidden rounded-full bg-white/20"><div ref={meter} className="h-full origin-left scale-x-0 rounded-full bg-emerald-400 transition-transform duration-75" /></div>
              </div>
            </div>
            {s.sharing && <div className="absolute right-3 top-3 w-[34%] overflow-hidden rounded-xl bg-black shadow-xl ring-2 ring-white/20">
              <video id="sharePreview" ref={vref.sharePreview} className="aspect-video w-full object-contain" autoPlay muted playsInline />
              <span className="absolute bottom-1.5 left-1.5 rounded-md bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold text-white">Your screen</span>
            </div>}
          </div>
          <p className="mt-3 text-center text-sm text-slate-400">Say "Hello, my name is ..." to test your microphone.</p>
        </section>
        <aside className="rounded-3xl bg-ink-850/80 p-6 shadow-2xl ring-1 ring-white/10 backdrop-blur">
          <h2 className="text-xl font-semibold text-white">Ready to join?</h2>
          <p className="mt-1 text-sm text-slate-400">{P.role}{P.company ? ` · ${P.company}` : ''}</p>
          <ul className="mt-5 grid gap-2">
            <CheckRow id="ckCam" c={s.checks.cam} icon={<Video />} />
            <CheckRow id="ckMic" c={s.checks.mic} icon={<Mic />} />
            <CheckRow id="ckFace" c={s.checks.face} icon={<UserRound />} />
            <CheckRow id="ckScreen" c={s.checks.screen} icon={<Monitor />} />
            <CheckRow id="ckShare" c={s.checks.share} icon={<ScreenShare />} />
          </ul>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button id="speakerBtn" variant="ghost" size="sm" className="text-slate-300 hover:bg-white/10 hover:text-white" icon={<Volume2 />} onClick={() => { engine.speakerTest(); setBeeped(true) }}>{beeped ? 'Heard a beep? Good.' : 'Test speakers'}</Button>
            {P.require_screen_share && <Button id="shareBtn" variant="ghost" size="sm" className="text-slate-300 hover:bg-white/10 hover:text-white" icon={<MonitorUp />} onClick={() => engine.share(true)}>{s.sharing ? 'Share a different screen' : 'Share entire screen'}</Button>}
          </div>
          {s.shareErr && <p className="mt-3 text-sm text-red-300">{s.shareErr}</p>}
          {s.err2 && <p className="mt-3 rounded-xl bg-red-500/10 p-3 text-sm text-red-200 ring-1 ring-red-500/20">{s.err2}</p>}
          <Button id="startBtn" variant="primary" size="lg" className="mt-6 w-full" disabled={!s.startReady} loading={s.starting} onClick={() => engine.begin()}>Join interview</Button>
          <p id="checkMsg" className="mt-3 min-h-5 text-center text-sm text-slate-400">{s.rejoin.left != null ? (s.rejoin.left > 0 ? `${s.rejoin.left}s left to rejoin` : 'Rejoin window has passed.') : s.checkMsg}</p>
        </aside>
      </div>
    </Shell>
  )
}

function Done({ s }: { s: State }) {
  const [rating, setRating] = useState(0)
  const [comment, setComment] = useState('')
  const tone = s.done.tone
  return (
    <Shell>
      <div id="s4" className="mx-auto mt-6 max-w-xl animate-rise rounded-3xl bg-ink-850/80 p-8 text-center shadow-2xl ring-1 ring-white/10 backdrop-blur sm:mt-14">
        <div className={cn('mx-auto grid size-16 place-items-center rounded-2xl [&_svg]:size-8',
          tone === 'ok' ? 'bg-emerald-500/15 text-emerald-300' : tone === 'info' ? 'bg-brand-500/15 text-brand-300' : 'bg-red-500/15 text-red-300')}>
          {tone === 'ok' ? <Check strokeWidth={2.5} /> : tone === 'info' ? (s.done.title === 'Wrapping up' ? <Spinner /> : <Check />) : <TriangleAlert />}
        </div>
        <h1 id="doneTitle" className="mt-5 text-2xl font-semibold tracking-tight text-white">{s.done.title}</h1>
        <p id="doneMsg" className="mt-2 text-[15px] leading-relaxed text-slate-300">{s.done.msg}</p>
        <p id="uploadMsg" className="mt-3 min-h-5 text-sm text-slate-400">{s.uploadMsg}</p>
        {s.rejoin.show && (
          <div id="reconnectBox" className="mt-4 flex flex-col items-center gap-2">
            <Button id="reconnectBtn" variant="primary" size="lg" icon={<RefreshCw />} disabled={s.starting || s.rejoin.left === 0} loading={s.starting} onClick={() => engine.begin()}>Rejoin now</Button>
            <span id="rejoinLeft" className="text-sm text-amber-300">{s.rejoin.left == null ? '' : s.rejoin.left > 0 ? `${s.rejoin.left}s left to rejoin` : 'Rejoin window has passed.'}</span>
            {s.shareErr && <span className="text-sm text-red-300">{s.shareErr}</span>}
          </div>
        )}
        {s.feedback.show && (
          <div id="fbBox" className="mt-8 border-t border-white/10 pt-6">
            <h3 className="font-semibold text-white">How was this interview experience?</h3>
            <div id="stars" className="mt-3 flex justify-center gap-1.5">
              {[1, 2, 3, 4, 5].map(n => (
                <button key={n} type="button" aria-label={`${n} star${n > 1 ? 's' : ''}`} onClick={() => setRating(n)}
                  className={cn('grid size-11 place-items-center rounded-xl text-2xl ring-1 transition', n <= rating ? 'bg-amber-400/15 text-amber-300 ring-amber-400/40' : 'text-slate-500 ring-white/10 hover:text-slate-300')}>★</button>
              ))}
            </div>
            <textarea value={comment} onChange={e => setComment(e.target.value)} placeholder="Anything we should improve? (optional)"
              className="mt-4 min-h-20 w-full rounded-xl bg-white/[.04] p-3 text-sm text-slate-100 ring-1 ring-white/10 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-500" />
            <div className="mt-3 flex items-center justify-center gap-3">
              <Button id="fbSend" variant="primary" disabled={!rating || s.feedback.sent} onClick={() => engine.sendFeedback(rating, comment)}>Send feedback</Button>
              <span id="fbDone" className="text-sm text-emerald-300">{s.feedback.sent ? 'Thank you!' : s.feedback.error}</span>
            </div>
          </div>
        )}
      </div>
    </Shell>
  )
}

// =====================================================================================================
// The call
// =====================================================================================================
function CtrlButton({ id, label, onClick, off, on, children, className }: { id: string; label: string; onClick?: () => void; off?: boolean; on?: boolean; children: ReactNode; className?: string }) {
  return (
    <Tip label={label}>
      <button id={id} type="button" aria-label={label} onClick={onClick}
        className={cn('relative grid size-12 place-items-center rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-400 sm:size-[52px] [&_svg]:size-[22px]',
          off ? 'bg-red-500 text-white hover:bg-red-400' : on ? 'bg-brand-100 text-brand-800 hover:bg-white' : 'bg-white/10 text-white hover:bg-white/20', className)}>
        {children}
      </button>
    </Tip>
  )
}

function AiPresence({ s }: { s: State }) {
  const rings = useRef<(HTMLDivElement | null)[]>([])
  const speaking = s.status === 'speaking'
  useLevel(useMemo(() => (_m: number, ai: number) => {
    rings.current.forEach((r, i) => { if (r) r.style.transform = `scale(${1 + ai * (0.35 + i * 0.3)})` })
  }, []))
  return (
    <div className="flex flex-col items-center gap-6">
      <div className="relative grid size-40 place-items-center sm:size-48">
        {[0, 1, 2].map(i => (
          <div key={i} ref={el => { rings.current[i] = el }}
            className={cn('absolute inset-0 rounded-full transition-transform duration-100', i === 0 ? 'bg-brand-500/25' : i === 1 ? 'bg-violet-500/15' : 'bg-sky-400/10',
              speaking && !s.hasVolume && 'animate-pulse-ring')} style={{ animationDelay: `${i * 0.35}s` }} />
        ))}
        <div className={cn('relative grid size-28 place-items-center rounded-full p-[3px] shadow-[0_20px_60px_-10px_rgba(59,99,243,.6)] sm:size-32',
          'bg-[conic-gradient(from_210deg,#3b63f3,#8b5cf6,#22d3ee,#3b63f3)]', speaking && 'animate-[spin_6s_linear_infinite]')}>
          <div className={cn('grid size-full place-items-center rounded-full bg-[radial-gradient(circle_at_35%_30%,#2a3566,#121831_70%)]', speaking && 'animate-[spin_6s_linear_infinite_reverse]')}>
            <Bot className="size-12 text-brand-100 sm:size-14" strokeWidth={1.6} />
          </div>
        </div>
      </div>
      <div className="text-center">
        <div className="text-lg font-semibold text-white">AI Interviewer</div>
        <div className="mt-1.5 flex h-5 items-center justify-center gap-2 text-sm text-slate-300">
          {speaking && <span className="flex h-3.5 items-end gap-[3px]">{[0, 1, 2, 3].map(i => <i key={i} className="block h-full w-[3px] origin-bottom animate-bar rounded-full bg-brand-300" style={{ animationDelay: `${i * 0.15}s` }} />)}</span>}
          <span id="statusText">{s.status === 'speaking' ? 'Speaking' : s.status === 'listening' ? 'Listening to you' : 'Connecting...'}</span>
        </div>
      </div>
    </div>
  )
}

function SelfTile({ s }: { s: State }) {
  const ring = useRef<HTMLDivElement>(null)
  useLevel(useMemo(() => (mic: number) => { if (ring.current) ring.current.style.opacity = String(mic > 0.18 ? Math.min(1, mic * 1.6) : 0) }, []))
  return (
    <div id="meTile" className="relative overflow-hidden rounded-2xl bg-ink-800 shadow-2xl ring-1 ring-white/15">
      <video id="self" ref={vref.self} className="mirror aspect-video w-full object-cover" autoPlay muted playsInline />
      <div ref={ring} className="pointer-events-none absolute inset-0 rounded-2xl opacity-0 ring-[3px] ring-inset ring-brand-400 transition-opacity duration-150" />
      <div className="absolute bottom-2 left-2 flex items-center gap-1.5 rounded-lg bg-black/55 px-2 py-1 text-xs font-semibold text-white backdrop-blur">
        {s.muted && <MicOff id="meMic" className="size-3.5 text-red-400" />}<span>You</span>
      </div>
    </div>
  )
}

function CallStage({ s }: { s: State }) {
  const P = s.P!
  const [panel, setPanel] = useState(true)
  const [endOpen, setEndOpen] = useState(false)
  const tx = useRef<HTMLDivElement>(null)
  useEffect(() => { tx.current?.scrollTo({ top: tx.current.scrollHeight, behavior: 'smooth' }) }, [s.lines])
  const q = s.question
  const canShare = !!navigator.mediaDevices?.getDisplayMedia && !isMobile
  return (
    <div id="s3" className="no-select fixed inset-0 grid grid-rows-[auto_minmax(0,1fr)_auto] bg-ink-950 pt-[env(safe-area-inset-top)] text-slate-100">
      <div aria-hidden className="pointer-events-none absolute left-1/3 top-0 h-[420px] w-[700px] -translate-x-1/2 rounded-full bg-brand-700/15 blur-[120px]" />
      {/* top bar */}
      <header className="relative flex items-center justify-between gap-3 px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <Logo compact />
          <div className="min-w-0">
            <div id="callTitle" className="truncate text-sm font-semibold text-white">{P.role}</div>
            {P.company && <div className="truncate text-xs text-slate-400">{P.company}</div>}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {s.offline && <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/15 px-2.5 py-1 text-xs font-semibold text-red-300"><WifiOff className="size-3.5" />Reconnecting</span>}
          {s.warnings > 0 && <span id="warnPill" className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold', s.warnings >= s.maxWarnings ? 'bg-red-500/15 text-red-300' : 'bg-amber-500/15 text-amber-300')}>
            <TriangleAlert className="size-3.5" />{s.warnings > s.maxWarnings ? 'Stopped' : s.warnings === s.maxWarnings ? 'Final warning' : `${s.warnings} warning${s.warnings === 1 ? '' : 's'}`}</span>}
          <span className="hidden items-center gap-1.5 rounded-full bg-white/5 px-2.5 py-1 text-xs font-medium text-slate-300 ring-1 ring-white/10 md:inline-flex"><Eye className="size-3.5" />Stay on this screen</span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/10 px-2.5 py-1 text-[11px] font-bold tracking-wider text-red-300"><span className="size-2 animate-pulse rounded-full bg-red-500" />REC</span>
        </div>
      </header>

      {/* body */}
      <div className={cn('relative grid min-h-0 gap-4 overflow-y-auto px-3 pb-3 sm:px-5 lg:overflow-visible', panel ? 'lg:grid-cols-[minmax(0,1fr)_400px]' : 'lg:grid-cols-1')}>
        <section className="relative min-h-[360px] overflow-hidden rounded-3xl bg-[radial-gradient(120%_90%_at_50%_20%,#1b2447_0%,#12172a_55%,#0d1120_100%)] ring-1 ring-white/[.08] lg:min-h-0">
          <div className="absolute left-4 top-4 flex items-center gap-2 rounded-lg bg-black/30 px-2.5 py-1 text-xs font-medium text-slate-200 ring-1 ring-white/10 backdrop-blur"><AudioLines className="size-3.5 text-brand-300" />Live interview</div>
          <div className="grid size-full min-h-[380px] place-items-center pb-36 pt-14 sm:pb-24 lg:pb-8"><AiPresence s={s} /></div>
          {/* picture-in-picture: you + your screen */}
          <div className="absolute bottom-3 right-3 flex w-[36%] min-w-[124px] max-w-[300px] flex-col gap-2 sm:bottom-4 sm:right-4 sm:w-[30%]">
            <div id="screenTile" className={cn('relative overflow-hidden rounded-2xl bg-black shadow-2xl ring-1 ring-white/15', !s.sharing && 'hidden')}>
              <video id="screenVid" ref={vref.screen} className="aspect-video w-full object-contain" autoPlay muted playsInline />
              <div className="absolute bottom-2 left-2 flex items-center gap-1.5 rounded-lg bg-black/60 px-2 py-1 text-[11px] font-semibold text-white"><ScreenShare className="size-3.5" />You're presenting</div>
            </div>
            <SelfTile s={s} />
          </div>
        </section>

        {panel && (
          <aside className="flex min-h-0 flex-col gap-3 pb-20 lg:pb-0">
            <div className="rounded-3xl bg-ink-850 p-5 ring-1 ring-white/[.08]">
              <div className="flex items-center justify-between">
                <span id="qKind" className={cn('inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider',
                  q?.kind === 'follow_up' ? 'bg-violet-500/15 text-violet-300' : 'bg-brand-500/15 text-brand-300')}>
                  {!q ? 'Starting' : q.kind === 'closing' ? 'Wrapping up' : q.kind === 'follow_up' ? 'Follow-up' : q.kind === 'rephrase' ? 'Rephrased' : 'Current question'}
                </span>
              </div>
              {q?.kind === 'follow_up' && q.main && <p className="mt-3 text-[13px] leading-relaxed text-slate-400"><span className="font-semibold text-slate-300">About: </span>{q.main}</p>}
              <p id="qText" key={q ? `${q.kind}${q.text}` : 'none'} className="mt-3 animate-rise text-xl font-semibold leading-snug text-white sm:text-[22px]">
                {!q ? 'Connecting you to your interviewer...' : q.kind === 'closing' ? "That's the end of the interview. Thank you for your time!" : q.text}
              </p>
              <p className="mt-4 flex gap-2 text-[12.5px] leading-relaxed text-slate-400"><Mic className="mt-0.5 size-3.5 shrink-0" />Answer out loud and take your time. When you finish, just pause. Say "please repeat" if you missed anything.</p>
            </div>
            {s.muted && <div id="mutedBanner" className="flex items-start gap-2.5 rounded-2xl bg-amber-500/10 p-3.5 text-sm text-amber-200 ring-1 ring-amber-500/20"><MicOff className="mt-0.5 size-4 shrink-0" />You're muted, so the interviewer can't hear you. Unmute to answer.</div>}
            {s.err3 && <div className="rounded-2xl bg-red-500/10 p-3.5 text-sm text-red-200 ring-1 ring-red-500/20">{s.err3}</div>}
            <div className="flex min-h-[180px] flex-1 flex-col rounded-3xl bg-ink-850 ring-1 ring-white/[.08] lg:min-h-0">
              <div className="flex items-center gap-2 border-b border-white/[.06] px-5 py-3 text-xs font-semibold uppercase tracking-wider text-slate-400"><MessageSquareText className="size-3.5" />Live transcript</div>
              <div ref={tx} id="captions" aria-live="polite" className="scrollbar-thin min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
                {!s.lines.length && <p className="text-sm text-slate-500">The conversation will appear here.</p>}
                {s.lines.map(l => (
                  <div key={l.id} className={cn('text-sm leading-relaxed', l.warn && 'rounded-xl bg-red-500/10 p-2.5 ring-1 ring-red-500/20')}>
                    <div className={cn('mb-0.5 text-[11px] font-bold uppercase tracking-wider', l.role === 'ai' ? (l.warn ? 'text-red-300' : 'text-brand-300') : 'text-emerald-300')}>{l.role === 'ai' ? 'Interviewer' : 'You'}</div>
                    <div className={cn(l.role === 'you' ? 'text-slate-300' : 'text-slate-100', !l.final && 'opacity-70')}>{l.text}</div>
                  </div>
                ))}
              </div>
            </div>
          </aside>
        )}
      </div>

      {/* control dock */}
      <footer className="relative z-10 flex justify-center px-3 pb-[calc(14px+env(safe-area-inset-bottom))] pt-2">
        <div className="flex items-center gap-2 rounded-[22px] bg-ink-850/90 p-2 shadow-2xl ring-1 ring-white/10 backdrop-blur sm:gap-3 sm:px-3">
          <CtrlButton id="muteBtn" label={s.muted ? 'Unmute microphone' : 'Mute microphone'} off={s.muted} onClick={() => engine.toggleMute()}>{s.muted ? <MicOff /> : <Mic />}</CtrlButton>
          <CtrlButton id="camBtn" label="Your camera stays on during the interview" onClick={() => toast('Your camera stays on for the whole interview.')}>
            <Video /><span className="absolute -bottom-0.5 -right-0.5 grid size-5 place-items-center rounded-full bg-ink-950 text-slate-300 ring-1 ring-white/10"><Lock className="!size-2.5" strokeWidth={3} /></span>
          </CtrlButton>
          {(P.require_screen_share || canShare) && (
            <CtrlButton id="shareBtn2" label={s.sharing ? (P.require_screen_share ? 'Screen sharing is on (required)' : 'Stop sharing') : 'Share screen'} on={s.sharing}
              onClick={async () => { const m = await engine.toggleShare(); if (m) toast(m) }}>{s.sharing ? <ScreenShare /> : <ScreenShareOff />}</CtrlButton>
          )}
          <CtrlButton id="ccBtn" label={panel ? 'Hide question and transcript' : 'Show question and transcript'} on={panel} onClick={() => setPanel(p => !p)}>{panel ? <Captions /> : <CaptionsOff />}</CtrlButton>
          <span className="mx-0.5 h-8 w-px bg-white/10 sm:mx-1" />
          <Tip label="Leave the interview">
            <button id="endBtn" type="button" onClick={() => setEndOpen(true)} aria-label="End interview"
              className="flex h-12 items-center gap-2 rounded-full bg-red-500 px-5 font-semibold text-white transition-colors hover:bg-red-400 sm:h-[52px] [&_svg]:size-[22px]"><PhoneOff /><span className="hidden sm:inline">Leave</span></button>
          </Tip>
        </div>
      </footer>

      {s.warnBar && (
        <div id="warnBar" role="alert" className={cn('fixed left-1/2 top-[calc(12px+env(safe-area-inset-top))] z-40 flex w-[min(600px,calc(100vw-24px))] -translate-x-1/2 animate-rise gap-3 rounded-2xl p-4 shadow-2xl ring-1',
          s.warnBar.final ? 'bg-red-950/95 ring-red-500/50' : 'bg-[#2a1515]/95 ring-red-500/30')}>
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-red-500/20 text-red-300"><TriangleAlert className="size-5" /></span>
          <div><div id="warnTitle" className="font-semibold text-white">{s.warnBar.title}</div><div className="mt-0.5 text-sm text-red-100/90">{s.warnBar.text}</div></div>
        </div>
      )}
      <Modal open={endOpen} onOpenChange={setEndOpen} dark id="endModal" icon={<PhoneOff />} title="Leave the interview?"
        description={<>If you leave now, you <b className="text-white">won't be able to rejoin</b> or continue this interview.</>}
        footer={<><Button id="endCancel" variant="ghost" className="text-slate-200 hover:bg-white/10 hover:text-white" onClick={() => setEndOpen(false)}>Stay in interview</Button>
          <Button id="endConfirm" variant="danger" onClick={() => { setEndOpen(false); engine.endInterview() }}>Leave interview</Button></>} />
    </div>
  )
}

// Blocking overlays stay mounted (hidden) so their state is easy to see and test.
function Overlay({ id, show, icon, title, children }: { id: string; show: boolean; icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div id={id} className={cn('fixed inset-0 z-50 flex items-center justify-center bg-ink-950/80 p-4 backdrop-blur-sm', !show && 'hidden')} role="dialog" aria-modal="true" aria-labelledby={`${id}-t`}>
      <div className="w-full max-w-md animate-rise rounded-3xl bg-ink-850 p-6 text-slate-100 shadow-2xl ring-1 ring-white/10">
        <div className="mb-4 grid size-12 place-items-center rounded-2xl bg-red-500/15 text-red-300 [&_svg]:size-6">{icon}</div>
        <h2 id={`${id}-t`} className="text-lg font-semibold text-white">{title}</h2>
        <div className="mt-2 text-sm leading-relaxed text-slate-300">{children}</div>
      </div>
    </div>
  )
}
function Overlays({ s }: { s: State }) {
  return (
    <>
      <Overlay id="shareOverlay" show={s.overlay.share} icon={<ScreenShareOff />} title="Screen sharing stopped">
        This interview requires your entire screen to be shared. Share it again to continue. This has been recorded.
        <div className="mt-5"><Button id="reshareBtn" variant="primary" icon={<MonitorUp />} onClick={() => engine.reshare()}>Share entire screen</Button></div>
        {s.shareErr && <p className="mt-3 text-red-300">{s.shareErr}</p>}
      </Overlay>
      <Overlay id="fsOverlay" show={s.overlay.fs && !s.overlay.dq} icon={<Monitor />} title="Please return to full screen">
        Leaving full screen during the interview is recorded.
        <div className="mt-5"><Button id="fsBtn" variant="primary" onClick={() => engine.returnFullscreen()}>Return to full screen</Button></div>
      </Overlay>
      <Overlay id="monOverlay" show={s.overlay.mon} icon={<Monitor />} title="Second screen detected">
        This interview must be taken on one screen. Disconnect the extra monitor (or set your displays to "Duplicate") to continue. The interviewer has been notified.
        <p className="mt-3 text-xs text-slate-400">This closes by itself once only one screen is connected.</p>
      </Overlay>
      <Overlay id="dqOverlay" show={s.overlay.dq} icon={<ShieldCheck />} title="The interview has been stopped">
        You left the interview after the final warning. The hiring team has been informed.
      </Overlay>
    </>
  )
}
