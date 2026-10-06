// The candidate-side interview engine: devices, Vapi call, recording + chunked upload, face checks, snapshots,
// integrity signals (warnings spoken by the interviewer), rejoin window. Framework-free; React subscribes to
// `state` (useSyncExternalStore) and to `onLevels` for the 60 fps audio meters.
import { post } from '../lib/api'
import { AnswerTiming, FaceMatch, HeadTurn, VoiceWatch, virtualCameraLabel, yaw } from './signals'
import { GazeAway, LipSync, ReadingWatch, SpeechLevel, earphonesInUse, gaze, newEarphones, shapesOf, type DeviceInfo } from './behaviour'

const CHUNK_MS = 5000
// How long the candidate must be away before it counts. Short enough that a glance at another tab or app counts;
// shorter blips are counted too, and three within 90 seconds are a violation of their own.
const CONFIRM_MS: Record<string, number> = { tab_hidden: 300, window_blur: 700 }
const BLIP_WINDOW_MS = 90000, BLIPS_ALLOWED = 2, FULLSCREEN_GRACE_MS = 10000, OFF_CAMERA_SEC = 8

export type CheckState = '' | 'ok' | 'bad'
export interface Check { state: CheckState; text: string; hidden: boolean }
export type CheckKey = 'cam' | 'mic' | 'face' | 'live' | 'room' | 'ears' | 'screen' | 'share'
export interface Display { q_id: string; main: string; text: string; kind: 'question' | 'follow_up' | 'rephrase' | 'closing' }
export interface Line { id: number; role: 'ai' | 'you'; text: string; final: boolean; warn?: boolean }
export interface PublicInfo {
  candidate_name?: string; role?: string; company?: string; status: string; disqualified: boolean
  enforce_focus: boolean; block_multi_monitor: boolean; max_warnings: number; expired: boolean
  available_from?: number | null; not_open_yet: boolean; require_screen_share: boolean; face_detection: boolean
  snapshots: boolean; reconnect_window_sec: number; resuming: boolean; reconnect_seconds_left: number | null
  liveness_check?: boolean; identity_check?: boolean; has_reference_photo?: boolean
  room_scan?: boolean; ear_check?: boolean; vision_check_sec?: number; vision_available?: boolean
  human_requested?: boolean; locked?: boolean; opening?: 'pick' | 'now' | 'fixed'; booking?: { starts_at: number; ends_at: number } | null; needs_booking?: boolean
}
export interface Slots { opening: string; booking: { starts_at: number; ends_at: number } | null; can_change: boolean; why: string
  changes_left: number; timezone: string; deadline: number; minutes: number; slots: number[] }
export interface State {
  step: 'loading' | 'blocked' | 'code' | 'schedule' | 'consent' | 'check' | 'call' | 'done'
  company: string; codeErr: string; codeBusy: boolean
  sched: Slots | null; schedErr: string; schedBusy: boolean
  blocked: string
  P: PublicInfo | null
  checks: Record<CheckKey, Check>
  startReady: boolean; checkMsg: string; err2: string; err3: string; shareErr: string
  roomScan: { running: boolean; left: number }
  spot: { left: number } | null
  starting: boolean
  status: 'connecting' | 'speaking' | 'listening'
  question: Display | null
  lines: Line[]
  muted: boolean; sharing: boolean; hasVolume: boolean
  warnings: number; maxWarnings: number
  warnBar: { title: string; text: string; final: boolean } | null
  overlay: { share: boolean; fs: boolean; mon: boolean; dq: boolean }
  offline: boolean
  done: { title: string; msg: string; tone: 'ok' | 'bad' | 'info' }
  uploadMsg: string
  rejoin: { show: boolean; left: number | null }
  feedback: { show: boolean; sent: boolean; error: string }
}

type Rec = { rid: string; seq: number; kind: 'camera' | 'screen'; ext: string; mr: MediaRecorder }
type Away = { kind: string; t0: number; confirmed: boolean; shots: number; timer?: number; shotTimer?: number }
type VideoKind = 'preview' | 'self' | 'screen' | 'sharePreview'

export const isMobile = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent) ||
  (navigator.maxTouchPoints > 1 && !/Windows|Macintosh|Linux x86/.test(navigator.userAgent))
const extendedDisplay = (): boolean | null => {
  const v = (screen as unknown as { isExtended?: unknown }).isExtended
  return typeof v === 'boolean' ? v : null
}
const within = <T,>(p: Promise<T>, ms: number) => Promise.race([p, new Promise<void>(r => setTimeout(r, ms))])
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms))
const norm = (s: string) => String(s || '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim()

export class InterviewEngine {
  // The link's encrypted key (k); old links carried the interview id (id). The server maps either to the interview.
  readonly iid = new URLSearchParams(location.search).get('k') || new URLSearchParams(location.search).get('id') || ''
  state: State = {
    step: 'loading', blocked: '', P: null, company: '', codeErr: '', codeBusy: false, sched: null, schedErr: '', schedBusy: false,
    checks: { cam: { state: '', text: 'Camera', hidden: false }, mic: { state: '', text: 'Microphone', hidden: false },
      face: { state: '', text: 'Your face is clearly visible', hidden: false }, live: { state: '', text: 'Turn your head slowly to one side, then the other', hidden: true },
      room: { state: '', text: 'Show the room: turn your camera slowly all around you', hidden: true }, ears: { state: '', text: 'No earphones or earbuds (checked from the head-turn photos)', hidden: true }, screen: { state: '', text: 'Single screen', hidden: true },
      share: { state: '', text: 'Entire screen shared', hidden: true } },
    startReady: false, checkMsg: '', err2: '', err3: '', shareErr: '', starting: false, roomScan: { running: false, left: 0 }, spot: null,
    status: 'connecting', question: null, lines: [], muted: false, sharing: false, hasVolume: false,
    warnings: 0, maxWarnings: 2, warnBar: null, overlay: { share: false, fs: false, mon: false, dq: false }, offline: false,
    done: { title: 'Thank you', msg: 'Your interview is complete. The HR team will get back to you.', tone: 'ok' },
    uploadMsg: '', rejoin: { show: false, left: null }, feedback: { show: false, sent: false, error: '' },
  }
  private listeners = new Set<() => void>()
  private levelListeners = new Set<(mic: number, ai: number) => void>()
  private videos: Partial<Record<VideoKind, HTMLVideoElement>> = {}
  private Vapi: any = null
  private vapiReady: Promise<void>
  private vapi: any = null
  private stream: MediaStream | null = null
  private screenStream: MediaStream | null = null
  private audioCtx: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private inCall = false
  private ended = false
  private terminated = false
  private endedByCandidate = false
  private events: { type: string; ts: number; detail: string }[] = []
  private cooldown: Record<string, number> = {}
  private faceDet: any = null
  private faceOk = false
  private micOk = false
  private faceState = { missing: 0, missingOn: false, multi: 0, away: 0, people: 0, phone: 0, screen: 0, tick: 0 }
  private objDet: any = null
  // face mesh (eyes and lips) during the call: reading, eyes off screen, a voice that isn't the candidate's
  private mesh: any = null
  private gazeAway = new GazeAway(5, 4)
  private reading = new ReadingWatch()
  private lips = new LipSync()
  private speech: SpeechLevel | null = null
  private devices: DeviceInfo[] = []
  private earDevices: string[] = []
  private lastYaw: number | null = null
  private spotSeen = false
  private camChecksFailed = false
  private roomDone = false
  private earsDone = false
  private earShots: (string | null)[] = [null, null]
  private earBusy = false
  private lastObj = { persons: 0, phones: 0, screens: 0 }
  private blips: number[] = []
  private fsTimer = 0
  private camRec: Rec | null = null
  private screenRec: Rec | null = null
  private upQueue: { rid: string; kind: string; seq: number; ext: string; blob: Blob }[] = []
  private upBusy = false
  private upFailed = false
  private timers: Record<string, number | undefined> = {}
  private pickerUntil = 0
  private away: Away | null = null
  private monBlocked = false
  private lastQKey = ''
  private lineId = 0
  private warnTimer?: number
  private aiLevel = 0
  private lastWarnSay = ''
  private head = new HeadTurn()
  private liveDone = false
  private liveSince = 0
  private match = new FaceMatch()
  private matchMiss = 0
  private timing = new AnswerTiming()

  constructor() {
    this.vapiReady = import(/* @vite-ignore */ '/vendor/vapi-web.mjs' as string)
      .then((m: any) => { this.Vapi = m.default?.default || m.default || m })
      .catch(e => console.error('voice SDK failed to load', e))
    setInterval(() => this.flushEvents(), 5000)
    this.installIntegrityListeners()
  }

  // ------------------------------------------------------------ store
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn) } }
  getState = () => this.state
  private set(patch: Partial<State>) { this.state = { ...this.state, ...patch }; this.listeners.forEach(f => f()) }
  private setCheck(k: CheckKey, state: CheckState, text?: string, hidden?: boolean) {
    const c = this.state.checks[k]
    this.set({ checks: { ...this.state.checks, [k]: { state, text: text ?? c.text, hidden: hidden ?? c.hidden } } })
  }
  onLevels(fn: (mic: number, ai: number) => void) { this.levelListeners.add(fn); return () => { this.levelListeners.delete(fn) } }
  attach(kind: VideoKind, el: HTMLVideoElement | null) {
    if (!el) { delete this.videos[kind]; return }
    this.videos[kind] = el
    const src = kind === 'screen' || kind === 'sharePreview' ? this.screenStream : this.stream
    if (el.srcObject !== src) el.srcObject = src
    if (src) el.play().catch(() => {})
  }
  /** Live camera/mic/screen tracks (0 once the interview has released every device). */
  liveTracks() { return [this.stream, this.screenStream].flatMap(m => m?.getTracks() || []).filter(t => t.readyState === 'live').length }
  private bindVideos() { (Object.keys(this.videos) as VideoKind[]).forEach(k => this.attach(k, this.videos[k]!)) }

  // ------------------------------------------------------------ helpers
  private once(key: string, ms: number) { const n = Date.now(); if (this.cooldown[key] && n - this.cooldown[key] < ms) return false; this.cooldown[key] = n; return true }
  private ev(type: string, detail: unknown = '') { this.events.push({ type, ts: Date.now(), detail: String(detail).slice(0, 200) }) }
  private async flushEvents() {
    if (!this.events.length) return
    const b = this.events.splice(0)
    try { await post(`/api/interviews/${this.iid}/events`, { sent_at: Date.now(), events: b }) } catch { this.events.unshift(...b) }
  }
  private closed(title: string, msg: string, tone: State['done']['tone'] = 'bad') { this.set({ step: 'done', done: { title, msg, tone } }) }
  private get P() { return this.state.P! }

  // ------------------------------------------------------------ load
  async load() {
    if (!this.iid) return this.set({ step: 'blocked', blocked: 'This interview link is not valid.' })
    if ((navigator as any).webdriver) this.ev('automation_detected', 'the browser is controlled by automation software')
    const r = await fetch(`/api/interviews/${this.iid}/public`).catch(() => null)
    if (!r || !r.ok) return this.set({ step: 'blocked', blocked: 'This interview link is not valid.' })
    const P: PublicInfo = await r.json()
    if (P.locked) return this.set({ step: 'code', company: (P as any).company || '' })
    this.state = { ...this.state, P, maxWarnings: P.max_warnings }
    document.title = `Interview · ${P.role || ''}`
    const ch = this.state.checks
    this.set({ checks: { ...ch, screen: { ...ch.screen, hidden: !P.block_multi_monitor }, share: { ...ch.share, hidden: !P.require_screen_share },
      face: { ...ch.face, hidden: !P.face_detection }, live: { ...ch.live, hidden: !P.liveness_check || P.resuming },
      room: { ...ch.room, hidden: !P.room_scan || P.resuming }, ears: { ...ch.ears, hidden: !P.ear_check || P.resuming } } })
    if (!P.room_scan || P.resuming) this.roomDone = true
    if (!P.ear_check || P.resuming) this.earsDone = true
    if (!P.liveness_check || P.resuming) this.liveDone = true
    if (P.disqualified) return this.closed('Interview closed', 'This interview was stopped because the interview rules were broken after warnings. Please contact HR if you think this is a mistake.')
    if (P.status === 'completed' || P.status === 'scored') return this.closed('Thank you', 'Your interview is complete. The HR team will get back to you.', 'ok')
    if (P.status === 'incomplete' || P.status === 'cancelled') return this.closed('Interview closed', 'This interview is closed. Please contact HR if you think this is a mistake.')
    if (P.expired) return this.closed('Link expired', 'Please contact HR for a new link.')
    if (P.needs_booking || (P.opening === 'pick' && P.booking && P.not_open_yet)) return this.openSchedule()
    if (P.not_open_yet) return this.set({ step: 'blocked', blocked: `This interview opens at ${new Date((P.available_from || 0) * 1000).toLocaleString()}. Please come back then.` })
    const missing: string[] = []
    if (!navigator.mediaDevices?.getUserMedia) missing.push('camera/microphone access')
    if (!window.MediaRecorder) missing.push('video recording')
    if (!window.AudioContext) missing.push('audio processing')
    if (P.require_screen_share && (!navigator.mediaDevices?.getDisplayMedia || isMobile)) missing.push('screen sharing (use a laptop or desktop)')
    if (missing.length) return this.set({ step: 'blocked', blocked: `This browser can't run the interview (missing: ${missing.join(', ')}). Open the link in the latest Chrome or Edge${P.require_screen_share ? ' on a laptop or desktop' : ''}.` })
    this.set({ step: 'consent' })
    if (P.resuming && P.reconnect_seconds_left !== null) this.startRejoinCountdown(P.reconnect_seconds_left)
  }

  // ------------------------------------------------------------ access code and booking a time
  async unlock(code: string) {
    this.set({ codeBusy: true, codeErr: '' })
    try { await post(`/api/interviews/${this.iid}/unlock`, { code }); this.set({ codeBusy: false }); await this.load() }
    catch (e: any) { this.set({ codeBusy: false, codeErr: e?.message || 'That code isn\'t right.' }) }
  }
  async requestHuman(note: string) {
    try { await post(`/api/interviews/${this.iid}/request-human`, { note }); if (this.state.P) this.set({ P: { ...this.state.P, human_requested: true } }); return '' }
    catch (e: any) { return e?.message || 'Could not send your request.' }
  }
  async resendCode() {
    try { await post(`/api/interviews/${this.iid}/resend-code`, {}); return '' } catch (e: any) { return e?.message || 'Could not send the code.' }
  }
  async openSchedule() {
    this.set({ step: 'schedule', schedErr: '' })
    try { const r = await fetch(`/api/interviews/${this.iid}/slots`); if (!r.ok) throw new Error(); this.set({ sched: await r.json() }) }
    catch { this.set({ schedErr: 'Could not load the available times. Refresh the page to try again.' }) }
  }
  async book(startsAt: number) {
    this.set({ schedBusy: true, schedErr: '' })
    try { this.set({ sched: await post<Slots>(`/api/interviews/${this.iid}/book`, { starts_at: startsAt }), schedBusy: false }); await this.load() }
    catch (e: any) { this.set({ schedBusy: false, schedErr: e?.message || 'Could not book that time.' }); this.openSchedule() }
  }

  // ------------------------------------------------------------ step 2: device check
  async toCheck() {
    post(`/api/interviews/${this.iid}/consent`, { version: 'v5' }).catch(() => {})
    this.set({ step: 'check', err2: '' })
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 24 } } })
    } catch (e: any) {
      this.setCheck('cam', 'bad')
      return this.set({ err2: `Camera or microphone blocked: ${e.message}. Allow access in the browser's address bar, then reload the page.` })
    }
    this.setCheck('cam', 'ok', 'Camera works')
    this.bindVideos()
    this.stream.getVideoTracks()[0]!.onended = () => { if (this.inCall) this.ev('camera_off') }
    this.stream.getAudioTracks()[0]!.onended = () => { if (this.inCall) this.ev('mic_off') }
    this.checkAudioDevices()
    navigator.mediaDevices.addEventListener?.('devicechange', () => this.checkAudioDevices())
    this.audioCtx = new AudioContext()
    this.analyser = this.audioCtx.createAnalyser(); this.analyser.fftSize = 512
    this.audioCtx.createMediaStreamSource(this.stream).connect(this.analyser)
    this.meterLoop()
    this.sendDevice()
    this.initFace()
    virtualCameraLabel(this.stream.getVideoTracks()[0]).then(l => { if (l) { this.ev('virtual_camera', l); setTimeout(() => this.snap('virtual_camera'), 1500) } })
    if (this.P.identity_check) this.initMatch()
    this.checkMonitors()
    this.timers.mon = window.setInterval(() => this.monTick(), 2000)
    ;(screen as any).addEventListener?.('change', () => this.monTick())
    if (this.P.resuming) { this.micOk = true; this.setCheck('mic', 'ok', 'Microphone works') }
    this.updateStart()
  }

  private meterLoop() {
    const a = this.analyser!, buf = new Uint8Array(a.fftSize)
    let heard = 0, loudMuted = 0
    const tick = () => {
      if (!this.stream) return
      a.getByteTimeDomainData(buf)
      let peak = 0
      for (const v of buf) peak = Math.max(peak, Math.abs(v - 128))
      const pct = Math.min(100, peak * 1.6)
      const muted = this.state.muted
      if (!this.micOk && pct > 25 && ++heard > 8) { this.micOk = true; this.setCheck('mic', 'ok', 'Microphone works'); this.updateStart() }
      // Talking while muted (e.g. someone being consulted): the camera recording still captures the room.
      if (this.inCall && muted) {
        loudMuted = pct > 30 ? loudMuted + 1 : Math.max(0, loudMuted - 1)
        if (loudMuted > 90 && this.once('vwm', 20000)) { this.ev('speaker_voice_while_muted'); this.snap('voice_while_muted'); loudMuted = 0 }
      }
      this.aiLevel *= 0.9
      this.levelListeners.forEach(f => f(muted && this.inCall ? 0 : pct / 100, this.aiLevel))
      requestAnimationFrame(tick)
    }
    tick()
  }

  private checkMonitors() {
    if (!this.P.block_multi_monitor) return true
    const ext = extendedDisplay()
    if (ext === null) { this.setCheck('screen', 'ok', 'Single screen (not checkable in this browser)'); return true }
    this.setCheck('screen', ext ? 'bad' : 'ok', ext ? 'Second screen connected: disconnect it, or set displays to "Duplicate"' : 'Single screen')
    return !ext
  }
  private monTick() {
    const ext = extendedDisplay()
    if (!this.inCall) { if (!this.ended) { this.checkMonitors(); this.updateStart() } return }
    if (!this.P.block_multi_monitor) { if (ext && this.once('mm', 60000)) this.ev('multi_monitor', 'screen changed'); return }
    if (ext && !this.monBlocked) {
      this.monBlocked = true; this.ev('multi_monitor', 'second screen connected during the call')
      this.set({ overlay: { ...this.state.overlay, mon: true } }); this.snap('multi_monitor')
      within(this.snapScreen('multi_monitor'), 1500).then(() => this.violation('multi_monitor', 'screen.isExtended'))
    } else if (!ext && this.monBlocked) {
      this.monBlocked = false; this.ev('multi_monitor_removed'); this.set({ overlay: { ...this.state.overlay, mon: false } })
    }
  }

  private updateStart() {
    if (!this.state.P || this.ended) return
    const P = this.P
    const faceNeeded = P.face_detection && (!!this.faceDet || this.camChecksFailed)
    const monOk = !P.block_multi_monitor || extendedDisplay() !== true
    const shareOk = !P.require_screen_share || !!this.screenStream?.active
    const liveOk = this.liveDone || !faceNeeded
    const roomOk = this.roomDone, earsOk = (this.earsDone || !faceNeeded) && !this.earDevices.length
    const ready = !!this.stream && this.micOk && !this.camChecksFailed && (!faceNeeded || this.faceOk) && liveOk && roomOk && earsOk && monOk && shareOk
    this.set({ startReady: ready, checkMsg: ready ? 'All set. Join when you are ready.'
      : !this.micOk ? 'Say a few words so we can check your microphone.'
      : this.camChecksFailed ? 'Camera checks could not start. Open this link in the latest Chrome or Edge.'
      : faceNeeded && !this.faceOk ? (this.state.checks.face.text.startsWith('Only') ? 'Only you may be in view of the camera.' : 'Position your face in the camera, in good light.')
      : !liveOk ? 'Turn your head slowly to one side, then the other.'
      : !earsOk ? (this.state.checks.ears.state === 'bad' ? 'Take out earphones or earbuds, then check again.' : 'Checking for earphones...')
      : !roomOk ? 'Show the room: press "Scan the room" and turn your camera slowly around you.'
      : !monOk ? 'Disconnect the second screen to continue.'
      : !shareOk ? 'Share your entire screen to continue.' : '' })
  }

  speakerTest() {
    const ctx = this.audioCtx || new AudioContext()
    const o = ctx.createOscillator(), g = ctx.createGain()
    o.frequency.value = 523; g.gain.value = 0.15; o.connect(g).connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.7)
  }

  private sendDevice() {
    const cam = this.stream!.getVideoTracks()[0], mic = this.stream!.getAudioTracks()[0]
    const nav = navigator as any
    post(`/api/interviews/${this.iid}/device`, {
      platform: nav.userAgentData?.platform || navigator.platform, screen: `${screen.width}x${screen.height}`,
      window: `${innerWidth}x${innerHeight}`, extended_display: String(extendedDisplay() ?? 'unknown'),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, language: navigator.language,
      cores: navigator.hardwareConcurrency, memory_gb: nav.deviceMemory ?? '', touch: navigator.maxTouchPoints,
      browser: (nav.userAgentData?.brands || []).map((b: any) => `${b.brand} ${b.version}`).join(', ') || navigator.userAgent.slice(0, 120),
      camera: cam?.label || '', microphone: mic?.label || '', connection: nav.connection?.effectiveType || '',
    }).catch(() => {})
    if (extendedDisplay() === true) this.ev('multi_monitor', 'at system check')
  }

  // ------------------------------------------------------------ face detection (in the browser, nothing uploaded)
  private async initFace() {
    if (!this.P.face_detection) return
    try {
      const vision: any = await import(/* @vite-ignore */ '/vendor/mediapipe/vision_bundle.mjs' as string)
      const fileset = await vision.FilesetResolver.forVisionTasks('/vendor/mediapipe/wasm')
      this.faceDet = await vision.FaceDetector.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: '/vendor/models/blaze_face_short_range.tflite', delegate: 'CPU' },
        runningMode: 'VIDEO', minDetectionConfidence: 0.5 })
      // The face model only sees faces near the camera; this one finds whole people anywhere in the room, plus phones
      // and screens (COCO classes). Measured: it finds a second person standing back that the face model misses.
      this.objDet = await vision.ObjectDetector.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: '/vendor/models/efficientdet_lite0.tflite', delegate: 'CPU' },
        runningMode: 'VIDEO', scoreThreshold: 0.35, maxResults: 12 })
      try {
        this.mesh = await vision.FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: '/vendor/models/face_landmarker.task', delegate: 'CPU' },
          runningMode: 'VIDEO', numFaces: 1, outputFaceBlendshapes: true })
      } catch (e: any) { this.mesh = null; this.ev('behaviour_checks_unavailable', e?.message) }
    } catch (e: any) {
      // Never pass silently: without camera checks the interview can't be proctored, so it can't start.
      console.warn('camera checks unavailable', e); this.ev('camera_checks_unavailable', e?.message); this.camChecksFailed = true
      this.setCheck('face', 'bad', 'Camera checks could not start. Open this link in the latest Chrome or Edge on a laptop or desktop.')
      this.faceDet = null; this.objDet = null; this.updateStart(); return
    }
    this.timers.face = window.setInterval(() => this.faceTick(), 1000)
  }
  /** People, phones and other screens in a frame. A second person counts from 0.4 (measured: 0.41 for a person
   * standing well back), and only when seen on several checks in a row. */
  private objects(v: HTMLVideoElement) {
    const r = { persons: 0, phones: 0, screens: 0 }
    if (!this.objDet) return r
    try {
      for (const d of this.objDet.detectForVideo(v, performance.now()).detections) {
        const c = d.categories?.[0]; if (!c) continue
        if (c.categoryName === 'person' && c.score >= 0.4) r.persons++
        else if (c.categoryName === 'cell phone' && c.score >= 0.45) r.phones++
        else if ((c.categoryName === 'tv' || c.categoryName === 'laptop') && c.score >= 0.5) r.screens++
      }
    } catch { /* a dropped frame */ }
    return r
  }
  private frame(width = 512): string | null {
    const v = this.videos.self?.videoWidth ? this.videos.self : this.videos.preview
    if (!v || !v.videoWidth) return null
    const c = document.createElement('canvas'); c.width = width; c.height = Math.round(width * v.videoHeight / v.videoWidth)
    c.getContext('2d')!.drawImage(v, 0, 0, c.width, c.height)
    return c.toDataURL('image/jpeg', 0.78).split(',')[1] || null
  }
  private async visionCheck(reason: 'room' | 'ears' | 'periodic', images: string[]): Promise<any> {
    try { return await post(`/api/interviews/${this.iid}/vision-check`, { reason, images }) } catch { return { checked: false } }
  }
  private faceTick() {
    const v = this.inCall ? this.videos.self : this.videos.preview
    if (!this.faceDet || !this.stream || !v || !v.videoWidth || document.hidden) return
    // Real faces score ~0.85+. Present: >= 0.6. A second person must be clear (>= 0.75) to avoid shadows/posters.
    let n = 0, strong = 0, dets: any[] = []
    try {
      dets = this.faceDet.detectForVideo(v, performance.now()).detections
      const sc: number[] = dets.map((d: any) => d.categories?.[0]?.score ?? 1)
      n = sc.filter(x => x >= 0.6).length; strong = sc.filter(x => x >= 0.75).length
    } catch { return }
    const fs = this.faceState
    if (this.objDet && ++fs.tick % 2 === 0) this.lastObj = this.objects(v)
    const persons = this.lastObj.persons
    if (!this.inCall) {
      const ok = n === 1 && persons <= 1
      const crowd = n > 1 || persons > 1
      if (ok !== this.faceOk || crowd !== this.state.checks.face.text.startsWith('Only')) {
        this.faceOk = ok
        this.setCheck('face', ok ? 'ok' : crowd ? 'bad' : '', crowd ? 'Only you should be in view: someone else is visible' : 'Your face is clearly visible'); this.updateStart()
        if (ok) this.checkIdentityAtStart()
      }
      if (ok && !this.liveDone) this.liveTick(dets[0]?.keypoints)
      if (ok && this.liveDone && !this.earsDone && this.state.checks.ears.state !== 'bad') this.earCheck()   // head-turn check off or skipped
      return
    }
    if (n === 0) {
      fs.missing++
      if (fs.missing === 3 && !fs.missingOn) { fs.missingOn = true; this.ev('face_missing_start'); this.snap('no_face') }
      if (fs.missing === OFF_CAMERA_SEC && this.once('offcam', 60000)) this.violation('left_camera', `no face for ${OFF_CAMERA_SEC}s`)
    } else { if (fs.missingOn) { fs.missingOn = false; this.ev('face_missing_end') } fs.missing = 0 }
    if (strong >= 2) {
      if (++fs.multi >= 2 && this.once('multi', 30000)) { this.ev('multiple_faces', `${n} faces`); this.snap('multiple_faces') }
    } else fs.multi = 0
    // Someone else in the room: a second person (whole body, any distance) or a second clear face, on 3 checks in a
    // row (about 6 seconds). A real warning that counts towards ending the interview (server setting strict_room).
    if (fs.tick % 2 === 0) {
      const people = Math.max(persons, strong)
      fs.people = people >= 2 ? fs.people + 1 : 0
      if (fs.people === 3 && this.once('people', 30000)) { this.ev('extra_person', `${people} people for 6s`); this.snap('extra_person'); this.violation('multiple_people', `${people} people in view`) }
      fs.phone = this.lastObj.phones ? fs.phone + 1 : 0
      if (fs.phone === 2 && this.once('phone', 45000)) { this.ev('phone_visible', 'phone in view for 4s'); this.snap('phone_visible'); this.violation('phone_visible', 'phone in view') }
      fs.screen = this.lastObj.screens ? fs.screen + 1 : 0
      if (fs.screen === 3 && this.once('screen2', 120000)) { this.ev('second_screen_visible', 'another screen in view'); this.snap('second_screen') }
    }
    // Head turned well away (reading a phone or another screen) for several seconds: a flag for review, not a warning.
    const y = n === 1 ? yaw(dets[0]?.keypoints) : null
    this.lastYaw = y
    fs.away = y != null && Math.abs(y) > 0.55 ? fs.away + 1 : 0
    if (fs.away === 6 && this.once('look', 45000)) { this.ev('looking_away', `head turned ${y! > 0 ? 'right' : 'left'} for 6s`); this.snap('looking_away') }
  }

  // ------------------------------------------------------------ earphones by device, eyes and lips, spot checks
  /** Earphones by their device name: the microphone in use and the default speaker. Before the start this blocks
   * like the ear photo check; earphones connected during the call count as an earphones warning. */
  private async checkAudioDevices() {
    if (!this.state.P || !this.P.ear_check) return
    let list: DeviceInfo[] = []
    try { list = (await navigator.mediaDevices.enumerateDevices()).map(d => ({ kind: d.kind, label: d.label, deviceId: d.deviceId })) } catch { return }
    const mic = this.stream?.getAudioTracks()[0]?.label || ''
    if (this.inCall) {
      const added = newEarphones(this.devices, list)
      if (added.length && this.once('eardev', 60000)) { this.ev('earphones_connected', added.join(', ')); this.violation('earphones', `connected ${added[0]}`) }
    } else {
      const found = earphonesInUse(list, mic)
      if (found.join() !== this.earDevices.join()) {
        this.earDevices = found
        if (found.length) { this.ev('earphones_device', found.join(', ')); this.setCheck('ears', 'bad', `Disconnect ${found[0]}: the interview uses your computer's own speaker and microphone.`) }
        else if (this.state.checks.ears.text.startsWith('Disconnect')) this.setCheck('ears', this.earsDone ? 'ok' : '', this.earsDone ? 'No earphones or earbuds' : 'No earphones or earbuds (checked from the head-turn photos)')
        this.updateStart()
      }
    }
    this.devices = list
  }
  /** About 5 times a second during the call: where the eyes look and whether the lips move with the voice. */
  private meshTick() {
    const v = this.videos.self
    if (!this.mesh || !this.inCall || !v?.videoWidth || document.hidden) return
    let r: any
    try { r = this.mesh.detectForVideo(v, performance.now()) } catch { return }
    const sh = r?.faceBlendshapes?.[0]?.categories
    const talking = !!this.speech?.speaking() && this.state.status !== 'speaking' && !this.state.muted
    if (!sh) { this.lips.reset(); this.reading.tick(performance.now(), null, false); return }
    const s = shapesOf(sh), g = gaze(s), blink = ((s.eyeBlinkLeft ?? 0) + (s.eyeBlinkRight ?? 0)) / 2
    const away = this.gazeAway.tick(g, blink)
    if (away && this.once('eyes', 40000)) { this.ev('eyes_off_screen', away === 'down' ? 'eyes down (below the screen) for 4s' : 'eyes to the side for 4s'); this.snap('eyes_off_screen') }
    const lines = this.reading.tick(performance.now(), blink > 0.5 ? null : g.h, talking)
    if (lines && this.once('reading', 60000)) { this.ev('reading_pattern', `${lines} line-by-line eye sweeps in 25s while answering`); this.snap('reading_pattern') }
    if (this.lips.tick(talking, s.jawOpen ?? null) && this.once('lips', 60000)) { this.ev('voice_not_lips', 'a voice spoke for ~3s while the candidate\'s lips stayed still'); this.snap('voice_not_lips') }
  }
  /** Twice per interview, at unplanned moments: "turn your head to the side and back". A real person does it in a
   * second; a replayed video, a face-swap or someone hiding something below the camera struggles. */
  private scheduleSpotChecks() {
    if (!this.P.face_detection) return
    const at = [150 + Math.random() * 150, 480 + Math.random() * 240]
    at.forEach((sec, i) => { this.timers[`spot${i}`] = window.setTimeout(() => this.spotCheck(), sec * 1000) })
  }
  private spotCheck() {
    if (!this.inCall || this.ended || this.state.spot || document.hidden) return
    this.spotSeen = false
    this.ev('spot_check', 'asked to turn head')
    let left = 12
    this.set({ spot: { left } })
    const t = window.setInterval(() => {
      if (this.lastYaw != null && Math.abs(this.lastYaw) > 0.35) this.spotSeen = true
      left--
      if (this.spotSeen || left <= 0 || !this.inCall) {
        clearInterval(t); this.set({ spot: null })
        if (!this.inCall) return
        if (this.spotSeen) this.ev('spot_check_passed')
        else { this.ev('spot_check_failed', 'did not turn their head within 12s'); this.snap('spot_check_failed') }
      } else this.set({ spot: { left } })
    }, 1000)
  }

  // ------------------------------------------------------------ liveness (head turn) and face match
  private liveTick(kp: { x: number; y: number }[] | undefined) {
    if (!this.liveSince) this.liveSince = Date.now()
    const before = this.head.progress()
    const y = yaw(kp)
    // Head turned well to each side: the ear on that side faces the camera. These two photos go to the ear check.
    if (y != null && y <= -0.4 && !this.earShots[0]) this.earShots[0] = this.frame(640)
    if (y != null && y >= 0.4 && !this.earShots[1]) this.earShots[1] = this.frame(640)
    if (this.head.feed(y)) {
      this.liveDone = true; this.ev('liveness_passed'); this.setCheck('live', 'ok', 'Head-turn check done'); this.earCheck(); this.updateStart(); return
    }
    if (this.head.progress() > before) this.setCheck('live', '', 'Good. Now turn to the other side')
    if (Date.now() - this.liveSince > 30000) {   // never block a candidate on it: note it for HR and move on
      this.liveDone = true; this.ev('liveness_failed', 'not completed in 30 seconds'); this.snap('liveness')
      this.setCheck('live', 'ok', 'Head-turn check skipped'); this.earCheck(); this.updateStart()
    }
  }
  /** Before the start: the candidate turns the camera slowly around the room for 12 seconds. Every frame is checked
   * here for other people; three photos go to the AI photo check and are kept for HR. */
  async roomScan() {
    if (this.state.roomScan.running || !this.objDet) return
    const v = this.videos.preview
    if (!v || !v.videoWidth) return
    let most = 0, phone = 0
    const shots: string[] = []
    this.setCheck('room', '', 'Turn your camera (or laptop) slowly to the left, behind you, and to the right')
    for (let left = 12; left > 0; left--) {
      this.set({ roomScan: { running: true, left } })
      const o = this.objects(v)
      most = Math.max(most, o.persons); phone = Math.max(phone, o.phones)
      if (left === 11 || left === 7 || left === 3) { const f = this.frame(640); if (f) shots.push(f) }
      await new Promise(r => setTimeout(r, 1000))
    }
    this.set({ roomScan: { running: false, left: 0 } })
    if (most >= 2) {
      this.ev('room_scan_failed', `${most} people seen`); this.snap('room_scan_failed')
      this.setCheck('room', 'bad', 'Someone else was seen. You must be alone in the room. Scan again when you are.'); this.roomDone = false; return this.updateStart()
    }
    this.setCheck('room', '', 'Checking the room photos...')
    const r = await this.visionCheck('room', shots)
    if (r?.checked && r.people > 1) {
      this.ev('room_scan_failed', `AI photo check: ${r.people} people${r.note ? `. ${r.note}` : ''}`)
      this.setCheck('room', 'bad', 'Someone else was seen in the room photos. You must be alone. Scan again when you are.'); this.roomDone = false; return this.updateStart()
    }
    this.ev('room_scan_passed', r?.checked ? 'AI photo check: nobody else' : `nobody else seen on this device${phone ? '; a phone was in view' : ''}`)
    this.roomDone = true; this.setCheck('room', 'ok', 'Room checked: nobody else with you'); this.updateStart()
  }
  /** Before the start: photos of both ears (from the head turn) checked by the AI for earphones and earbuds. */
  async earCheck() {
    if (!this.P.ear_check || this.P.resuming || this.earsDone || this.earBusy) return
    this.earBusy = true
    try { await this.earCheckRun() } finally { this.earBusy = false }
    // the photos may look fine while earbuds are connected by Bluetooth: the device name still wins
    if (this.earDevices.length) this.setCheck('ears', 'bad', `Disconnect ${this.earDevices[0]}: the interview uses your computer's own speaker and microphone.`)
  }
  private async earCheckRun() {
    const shots = this.earShots.filter((x): x is string => !!x)
    if (!shots.length) { const f = this.frame(640); if (f) shots.push(f) }
    if (!shots.length) return
    this.setCheck('ears', '', 'Checking for earphones and earbuds...')
    const r = await this.visionCheck('ears', shots)
    if (r?.checked && r.earphones === 'yes') {
      this.ev('ear_check_failed', r.note || 'earphones or earbuds seen')
      this.setCheck('ears', 'bad', 'Earphones or earbuds seen. Take them out (use your device speaker), then check again.')
      return this.updateStart()
    }
    if (!r?.checked || r.earphones === 'unclear') this.ev('ear_check_unverified', r?.checked ? 'ears not clearly visible in the photos' : `not checked by AI (${r?.reason || 'unavailable'})`)
    else this.ev('ear_check_passed')
    this.earsDone = true
    this.setCheck('ears', 'ok', r?.checked && r.earphones === 'no' ? 'No earphones or earbuds seen' : 'Ear photos saved for the hiring team to review')
    this.updateStart()
  }
  /** After a failed ear check: turn the head again for new ear photos. */
  retryEars() {
    this.earShots = [null, null]; this.earsDone = false
    if (this.P.liveness_check) { this.liveDone = false; this.liveSince = 0; this.head = new HeadTurn(); this.setCheck('live', '', 'Turn your head slowly to one side, then the other') }
    else this.earCheck()
    this.setCheck('ears', '', 'Turn your head to each side again for new photos'); this.updateStart()
  }
  private async initMatch() {
    try {
      await this.match.load()
      if (this.P.has_reference_photo && !await this.match.setReferenceImage(`/api/interviews/${this.iid}/reference-photo`))
        this.ev('identity_check_unavailable', 'no clear face in the registration photo')
    } catch (e: any) { this.ev('identity_check_unavailable', e?.message || 'face match failed to load') }
  }
  private matchedAtStart = false
  private async checkIdentityAtStart() {
    if (this.matchedAtStart || this.match.refSource !== 'registration' || !this.videos.preview) return
    this.matchedAtStart = true
    try {
      const d = await this.match.distance(this.videos.preview)
      if (d == null) { this.matchedAtStart = false; return }
      if (d > 0.6) { this.ev('identity_mismatch', `at the system check (distance ${d.toFixed(2)})`); this.snap('identity_mismatch') }
      else this.ev('identity_match', `distance ${d.toFixed(2)}`)
    } catch { /* face match is best effort */ }
  }
  private async matchTick() {
    const v = this.videos.self
    if (!v?.videoWidth || document.hidden) return
    try {
      if (!this.match.ready) { await this.match.setReferenceFrame(v); return }
      const d = await this.match.distance(v)
      if (d == null) return
      this.matchMiss = d > 0.6 ? this.matchMiss + 1 : 0
      if (this.matchMiss >= 2 && this.once('idmatch', 120000)) {
        this.ev(this.match.refSource === 'registration' ? 'identity_mismatch' : 'person_changed', `distance ${d.toFixed(2)}`); this.snap('identity_mismatch'); this.matchMiss = 0
      }
    } catch { /* best effort */ }
  }

  // ------------------------------------------------------------ snapshots: camera, and a frame of the shared screen
  private upload(blob: Blob | null, reason: string, source: 'camera' | 'screen') {
    if (blob) fetch(`/api/interviews/${this.iid}/snapshot?reason=${reason}&source=${source}`, { method: 'POST', headers: { 'Content-Type': 'image/jpeg' }, body: blob }).catch(() => {})
  }
  private snap(reason: string) {
    if (!this.state.P?.snapshots || !this.stream) return
    const v = this.videos.self?.videoWidth ? this.videos.self : this.videos.preview
    if (!v || !v.videoWidth) return
    const c = document.createElement('canvas'); c.width = 400; c.height = Math.round(400 * v.videoHeight / v.videoWidth)
    c.getContext('2d')!.drawImage(v, 0, 0, c.width, c.height)
    c.toBlob(b => this.upload(b, reason, 'camera'), 'image/jpeg', 0.72)
  }
  private async snapScreen(reason: string) {
    const t = this.screenStream?.getVideoTracks()[0]
    if (!this.state.P?.snapshots || !t || t.readyState !== 'live') return
    // ImageCapture reads the track directly, so it works while this tab is in the background.
    let src: CanvasImageSource | null = null, w = 0, h = 0
    const IC = (window as any).ImageCapture
    if (IC) { try { const bmp = await new IC(t).grabFrame(); src = bmp; w = bmp.width; h = bmp.height } catch { /* fall back to the video element */ } }
    const sv = this.videos.screen || this.videos.sharePreview
    if (!src && sv?.videoWidth) { src = sv; w = sv.videoWidth; h = sv.videoHeight }
    if (!src || !w) return
    for (const [W, q] of [[1280, 0.62], [960, 0.5], [720, 0.42]] as const) {
      const c = document.createElement('canvas'); c.width = Math.min(W, w); c.height = Math.round(c.width * h / w)
      c.getContext('2d')!.drawImage(src, 0, 0, c.width, c.height)
      const b = await new Promise<Blob | null>(r => c.toBlob(r, 'image/jpeg', q))
      if (b && b.size < 680 * 1024) { this.upload(b, reason, 'screen'); return }
    }
  }

  // ------------------------------------------------------------ screen sharing
  private async startShare(required: boolean) {
    this.pickerUntil = Infinity   // the browser's picker takes focus: not "leaving the interview"
    let s: MediaStream
    try {
      s = await navigator.mediaDevices.getDisplayMedia({ video: { displaySurface: 'monitor', frameRate: { ideal: 5, max: 10 } }, audio: false,
        monitorTypeSurfaces: 'include', selfBrowserSurface: 'exclude', surfaceSwitching: 'exclude' } as any)
    } finally { this.pickerUntil = Date.now() + 3000 }
    const t = s.getVideoTracks()[0]!
    const surf = (t.getSettings() as any).displaySurface
    if (required && surf && surf !== 'monitor') {
      this.ev('screen_share_not_monitor', surf); s.getTracks().forEach(x => x.stop())
      throw new Error('Please choose "Entire screen", not a window or a tab.')
    }
    this.screenStream?.getTracks().forEach(x => x.stop())
    this.screenStream = s
    t.onended = () => {
      if (this.screenRec) { this.stopRec(this.screenRec); this.screenRec = null }
      this.screenStream = null; this.bindVideos(); this.set({ sharing: false })
      if (this.ended || this.terminated) return
      if (this.inCall) { this.ev('screen_share_stopped'); this.snap('share_stopped'); if (this.P.require_screen_share) this.set({ overlay: { ...this.state.overlay, share: true } }) }
      else { this.setCheck('share', ''); this.updateStart() }
    }
    this.ev('screen_share_started', surf || '')
    this.setCheck('share', 'ok', 'Entire screen shared'); this.bindVideos(); this.set({ sharing: true })
    if (this.inCall) this.screenRec = this.startRec(new MediaStream([t]), 'screen', 700000)
    this.updateStart()
  }
  async share(required = this.P.require_screen_share): Promise<boolean> {
    this.set({ shareErr: '' })
    try { await this.startShare(required); return true }
    catch (e: any) { if (e?.name === 'NotAllowedError') this.ev('screen_share_denied'); this.set({ shareErr: e?.name === 'NotAllowedError' ? 'Screen sharing was not allowed. Click share again and choose "Entire screen".' : (e?.message || String(e)) }); return false }
  }
  async reshare() { if (await this.share(true)) this.set({ overlay: { ...this.state.overlay, share: false } }) }
  async toggleShare(): Promise<string | void> {
    if (this.screenStream?.active) {
      if (this.P.require_screen_share) return 'Screen sharing is required and stays on until the interview ends.'
      this.ev('screen_share_stopped', 'by candidate')
      if (this.screenRec) { await this.stopRec(this.screenRec); this.screenRec = null }
      this.stopScreenShare(); return
    }
    await this.share()
  }
  private stopScreenShare() {
    this.screenStream?.getTracks().forEach(t => { t.onended = null; t.stop() })
    this.screenStream = null; this.bindVideos(); this.set({ sharing: false })
  }
  private stopCamera() {
    this.stream?.getTracks().forEach(t => { t.onended = null; t.stop() })
    this.stream = null; this.bindVideos()
    clearInterval(this.timers.mon); clearInterval(this.timers.face); clearInterval(this.timers.mesh)
    clearTimeout(this.timers.spot0); clearTimeout(this.timers.spot1)
    try { if (this.audioCtx && this.audioCtx.state !== 'closed') this.audioCtx.close() } catch { /* already closed */ }
  }

  // ------------------------------------------------------------ recording: camera + BOTH voices, uploaded while recording
  private pickMime(video: boolean) {
    const t = video ? ['video/webm;codecs=vp8,opus', 'video/webm;codecs=vp9,opus', 'video/webm', 'video/mp4'] : ['video/webm;codecs=vp8', 'video/webm', 'video/mp4']
    return t.find(x => MediaRecorder.isTypeSupported(x))
  }
  private startRec(ms: MediaStream, kind: 'camera' | 'screen', bps: number): Rec | null {
    const mimeType = this.pickMime(kind === 'camera')
    if (!mimeType) { this.ev('recorder_unsupported', kind); return null }
    const rec: Rec = { rid: Math.random().toString(36).slice(2, 10) + Date.now().toString(36), seq: 0, kind, ext: mimeType.startsWith('video/mp4') ? 'mp4' : 'webm',
      mr: new MediaRecorder(ms, { mimeType, videoBitsPerSecond: bps, audioBitsPerSecond: 64000 }) }
    rec.mr.ondataavailable = e => { if (e.data.size) { this.upQueue.push({ rid: rec.rid, kind, seq: rec.seq++, ext: rec.ext, blob: e.data }); this.pump() } }
    rec.mr.start(CHUNK_MS)
    return rec
  }
  private stopRec(rec: Rec | null) {
    return new Promise<void>(res => { if (!rec || rec.mr.state === 'inactive') return res(); rec.mr.onstop = () => setTimeout(res, 50); rec.mr.stop() })
  }
  private async pump() {
    if (this.upBusy) return
    this.upBusy = true
    while (this.upQueue.length) {
      const c = this.upQueue[0]!
      let ok = false, fatal = false
      for (let i = 0; i < 5 && !ok && !fatal; i++) {
        try {
          const r = await fetch(`/api/interviews/${this.iid}/media/chunk?rid=${c.rid}&seq=${c.seq}&ext=${c.ext}&kind=${c.kind}&chunk_sec=${CHUNK_MS / 1000}`,
            { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: c.blob })
          ok = r.ok; fatal = [409, 410, 413].includes(r.status) && !ok
        } catch { /* retry */ }
        if (!ok && !fatal) await sleep(1500 * (i + 1))
      }
      if (!ok) { this.upFailed = true; this.ev('recording_upload_failed', `${c.kind} ${c.seq}`); this.upQueue = this.upQueue.filter(x => x.rid !== c.rid); continue }
      this.upQueue.shift()
    }
    this.upBusy = false
  }
  private startCameraRecording() {
    // Mix the candidate's mic and the interviewer's voice, so the video has the whole conversation.
    const ctx = this.audioCtx!
    const mix = ctx.createMediaStreamDestination()
    ctx.createMediaStreamSource(this.stream!).connect(mix)
    this.camRec = this.startRec(new MediaStream([...this.stream!.getVideoTracks(), ...mix.stream.getAudioTracks()]), 'camera', 450000)
    let tries = 0
    const t = setInterval(() => {
      const el: HTMLAudioElement | null = this.vapi?.getAudioPlayer?.() || document.querySelector('audio[data-participant-id]')
      const src = el?.srcObject as MediaStream | null
      if (src && src.getAudioTracks().length) {
        try { ctx.createMediaStreamSource(src).connect(mix) } catch (e: any) { this.ev('ai_audio_not_recorded', e.message) }
        clearInterval(t)
      } else if (++tries > 60 || !this.inCall) { if (this.inCall) this.ev('ai_audio_not_recorded', 'no assistant audio element'); clearInterval(t) }
    }, 500)
  }
  private async drainUploads() {
    if (!this.upQueue.length && !this.upBusy) return
    this.set({ uploadMsg: 'Saving your recording. Please keep this page open...' })
    const t0 = Date.now()
    while ((this.upQueue.length || this.upBusy) && Date.now() - t0 < 120000) await sleep(300)
    this.set({ uploadMsg: this.upFailed ? 'Part of the recording could not be saved. HR still has the call audio and transcript.' : 'Recording saved.' })
  }

  // ------------------------------------------------------------ call
  private setStatus(status: State['status']) { if (status !== 'speaking') this.aiLevel = 0; this.set({ status }) }
  private renderQuestion(q: Display | null | undefined) {
    if (!q) return
    const key = `${q.kind}|${q.text}`
    if (key === this.lastQKey) return
    this.lastQKey = key; this.set({ question: q })
  }
  private async pollProgress() {
    try {
      const p = await (await fetch(`/api/interviews/${this.iid}/progress`)).json()
      this.renderQuestion(p.question)
      if (p.warnings) this.set({ warnings: p.warnings, maxWarnings: p.max_warnings })
      if (p.disqualified && this.inCall && !this.terminated) this.handleTermination('')
    } catch { /* next poll */ }
  }
  private addLine(role: Line['role'], text: string, final: boolean, warn = false) {
    const lines = this.state.lines.slice()
    const last = lines[lines.length - 1]
    if (role === 'you' && last && last.role === 'you' && !last.final) lines[lines.length - 1] = { ...last, text, final }
    else lines.push({ id: ++this.lineId, role, text, final, warn })
    this.set({ lines: lines.slice(-40) })
  }

  async begin() {
    if (this.state.starting) return
    // A rejoin after a drop must share the screen again first (sharing stops when a call ends).
    if (this.P.require_screen_share && !this.screenStream?.active) { if (!await this.share(true)) return }
    this.set({ starting: true })
    try { await this.beginInner() } finally { this.set({ starting: false }) }
  }
  private async beginInner() {
    this.ended = false
    clearInterval(this.timers.rejoin)
    if (!this.stream) return this.set({ step: 'check', err2: 'Camera is not ready. Please allow camera and microphone access.' })
    this.set({ step: 'call', status: 'connecting', err3: '', rejoin: { show: false, left: null } })
    try { await document.documentElement.requestFullscreen({ navigationUI: 'hide' }) } catch { /* not supported (iOS) */ }
    if (this.audioCtx!.state === 'suspended') await this.audioCtx!.resume()
    await this.vapiReady
    if (!this.Vapi) return this.set({ err3: 'Could not load the voice component. Check your internet connection and reload.' })
    let cfg: any
    try { cfg = await post(`/api/interviews/${this.iid}/assistant`, {}) }
    catch (e: any) { this.set({ err3: e.message }); if (e.status === 410 || e.status === 409) this.closeFinal(e.message); return }
    const vapi = this.vapi = new this.Vapi(cfg.publicKey)
    vapi.on('call-start', () => {
      this.inCall = true; this.setStatus('speaking'); this.ev('call_start')
      try {
        const an = this.audioCtx!.createAnalyser(); an.fftSize = 2048
        this.audioCtx!.createMediaStreamSource(this.stream!).connect(an)
        this.speech = new SpeechLevel(an, this.audioCtx!.sampleRate)
      } catch { this.speech = null }
      if (this.mesh) this.timers.mesh = window.setInterval(() => this.meshTick(), 200)
      this.scheduleSpotChecks()
      this.startCameraRecording()
      if (this.screenStream?.active && !this.screenRec) this.screenRec = this.startRec(new MediaStream(this.screenStream.getVideoTracks()), 'screen', 700000)
      setTimeout(() => { this.snap('reference'); this.snapScreen('reference') }, 3000)
      this.timers.snap = window.setInterval(() => { this.snap('periodic'); this.snapScreen('periodic') }, 60000)
      this.timers.hb = window.setInterval(() => post(`/api/interviews/${this.iid}/heartbeat`, {}).catch(() => {}), 5000)
      this.pollProgress(); this.timers.prog = window.setInterval(() => this.pollProgress(), 4000)
      if (this.P.identity_check) this.timers.match = window.setInterval(() => this.matchTick(), 45000)
      if (this.P.identity_check) setTimeout(() => this.matchTick(), 8000)
      if (this.P.vision_check_sec && this.P.vision_available) {
        // AI photo checks at unpredictable times (the interval +-25%), first one within the first minute.
        const next = (first = false) => { this.timers.vision = window.setTimeout(() => { this.visionTick(); next() }, first ? 25000 + Math.random() * 30000 : this.P.vision_check_sec! * 1000 * (0.75 + Math.random() * 0.5)) }
        next(true)
      }
      try {
        const an = this.audioCtx!.createAnalyser(); an.fftSize = 2048
        this.audioCtx!.createMediaStreamSource(this.stream!).connect(an)
        const watch = new VoiceWatch(an, this.audioCtx!.sampleRate)
        this.timers.voice = window.setInterval(() => {
          if (this.state.status === 'speaking' || this.state.muted || document.hidden) return
          const r = watch.tick()
          if (r && this.once('voice2', 90000)) { this.ev('second_voice', r); this.snap('second_voice') }
        }, 100)
      } catch { /* no audio analysis on this browser */ }
    })
    vapi.on('speech-start', () => {
      this.setStatus('speaking')
      const t = this.timing.aiStarted()
      if (t) this.ev('answer_timing', `${t.delay.toFixed(1)}s pause, ${t.words} words, ${t.wpm} wpm`)
      if (this.timing.pattern()) this.ev('answer_pattern', 'three or more long pauses followed by long, fast answers')
    })
    vapi.on('speech-end', () => { this.setStatus('listening'); this.timing.aiEnded() })
    vapi.on('volume-level', (v: number) => { if (!this.state.hasVolume) this.set({ hasVolume: true }); this.aiLevel = Math.min(1, (+v || 0) * 1.8) })
    vapi.on('message', (m: any) => {
      if (m.type !== 'transcript') return
      if (m.role === 'assistant' && m.transcriptType === 'final') {
        // The warning is already in the transcript (added when it was issued); skip Vapi's echo of it, whole or in parts.
        const t = norm(m.transcript)
        if (this.lastWarnSay && t && this.lastWarnSay.includes(t)) return
        this.addLine('ai', m.transcript, true); this.pollProgress()
      }
      else if (m.role === 'user') { this.addLine('you', m.transcript, m.transcriptType === 'final'); this.timing.heard(m.transcriptType === 'final', m.transcript || '') }
    })
    vapi.on('error', (e: unknown) => { this.ev('vapi_error', JSON.stringify(e).slice(0, 200)); console.error(e) })
    vapi.on('call-end', () => this.finish())
    try {
      const call = await vapi.start(cfg.assistant)
      if (call?.id) post(`/api/interviews/${this.iid}/started`, { call_id: call.id }).catch(() => {})
    } catch (e: any) { this.set({ err3: `Could not start the call: ${e?.message || e}` }); this.inCall = false }
  }

  toggleMute() {
    if (!this.vapi) return
    const m = !this.vapi.isMuted(); this.vapi.setMuted(m); this.ev(m ? 'mute_on' : 'mute_off'); this.set({ muted: m })
  }
  endInterview() { this.ev('ended_by_candidate'); this.endedByCandidate = true; this.vapi?.stop() }

  private async finish() {
    if (this.ended) return
    this.ended = true; this.inCall = false
    ;['hb', 'prog', 'snap', 'match', 'voice', 'vision'].forEach(k => clearInterval(this.timers[k]))
    if (this.away) { clearTimeout(this.away.timer); clearInterval(this.away.shotTimer); this.away = null }
    if (this.faceState.missingOn) { this.faceState.missingOn = false; this.ev('face_missing_end') }
    this.ev('call_end')
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
    this.set({ step: 'done', overlay: { share: false, fs: false, mon: false, dq: false }, warnBar: null,
      done: { title: 'Wrapping up', msg: 'Saving your interview...', tone: 'info' } })
    await Promise.all([this.stopRec(this.camRec), this.stopRec(this.screenRec)]); this.camRec = this.screenRec = null
    this.stopScreenShare()   // the call is over: never keep capturing the candidate's screen
    if (this.terminated) {
      this.closed('Interview stopped', 'The interview was stopped because you left the interview screen after being warned. The hiring team has been informed.')
      this.stopCamera()
    }
    await this.flushEvents()
    await this.drainUploads()
    let res: any = { status: 'completed' }
    try { res = await post(`/api/interviews/${this.iid}/complete`, { ended_by_candidate: this.endedByCandidate }) } catch { /* assume completed */ }
    if (this.terminated) return
    if (res.status === 'in_progress') {
      this.ev('call_dropped'); this.flushEvents()
      this.closed('The call dropped', 'If this was a connection problem, rejoin now to continue from the same question.')
      this.set({ rejoin: { show: true, left: null } })
      // The server's clock decides; the window started when the call dropped, not now.
      this.startRejoinCountdown(res.reconnect_seconds_left ?? res.reconnect_window_sec ?? this.P.reconnect_window_sec)
      return
    }
    this.stopCamera()
    if (res.status === 'incomplete') this.closed('Interview ended', 'You ended the interview. The HR team will review what was completed.', 'info')
    else this.closed('Thank you!', 'Your interview is complete. The HR team will review it and get back to you.', 'ok')
    this.set({ feedback: { show: true, sent: false, error: '' } })
  }
  private closeFinal(msg: string) {
    this.closed('Interview closed', msg); this.set({ rejoin: { show: false, left: null } })
    clearInterval(this.timers.rejoin); this.stopScreenShare(); this.stopCamera()
  }
  private startRejoinCountdown(sec: number) {
    let left = Math.max(0, Math.floor(sec))
    clearInterval(this.timers.rejoin)
    const tick = () => {
      this.set({ rejoin: { ...this.state.rejoin, left } })
      if (left <= 0) {
        clearInterval(this.timers.rejoin)
        if (!this.inCall) this.closeFinal('The time to rejoin has passed, so the interview is closed. Please contact HR if this was a technical problem.')
      }
      left--
    }
    tick(); this.timers.rejoin = window.setInterval(tick, 1000)
  }
  async sendFeedback(rating: number, comment: string) {
    try { await post(`/api/interviews/${this.iid}/feedback`, { rating, comment }); this.set({ feedback: { show: true, sent: true, error: '' } }) }
    catch (e: any) { this.set({ feedback: { show: true, sent: false, error: e.message } }) }
  }

  // ------------------------------------------------------------ leaving the interview: warn, then stop
  // A short confirm delay filters out focus blips (OS notifications, the share picker). What was on the screen
  // at that moment is captured from the screen share, and the interviewer says the warning out loud.
  private awayStart(kind: string) {
    if (!this.inCall || this.terminated || Date.now() < this.pickerUntil) return
    if (this.away) { if (kind === 'tab_hidden') this.away.kind = 'tab_hidden'; return }
    const a: Away = { kind, t0: Date.now(), confirmed: false, shots: 0 }
    a.timer = window.setTimeout(() => this.confirmAway(a), CONFIRM_MS[kind])
    this.away = a
  }
  private async confirmAway(a: Away) {
    if (this.away !== a || a.confirmed || !this.inCall) return
    a.confirmed = true
    this.snap(a.kind)
    a.shotTimer = window.setInterval(() => { if (this.away === a && a.shots++ < 3) this.snapScreen(`${a.kind}_away`) }, 8000)
    // Capture the screen before reporting: a final violation ends the call, and with it the screen share.
    await within(this.snapScreen(a.kind), 1500)
    this.violation(a.kind, `away ${Math.round((Date.now() - a.t0) / 1000)}s+`)
  }
  private awayEnd() {
    const a = this.away
    if (!a) return
    clearTimeout(a.timer); clearInterval(a.shotTimer); this.away = null
    if (a.confirmed && this.inCall) setTimeout(() => this.snap('tab_return'), 500)
    else if (this.inCall && !this.terminated && Date.now() - a.t0 > 120) {
      // Too short to be a warning on its own, but a pattern of quick looks elsewhere is.
      const now = Date.now()
      this.ev('quick_switch', `${a.kind} ${now - a.t0}ms`)
      this.blips = [...this.blips.filter(x => now - x < BLIP_WINDOW_MS), now]
      if (this.blips.length > BLIPS_ALLOWED) { this.blips = []; this.snap('quick_switches'); this.violation('quick_switches', `${BLIPS_ALLOWED + 1} quick switches in ${BLIP_WINDOW_MS / 1000}s`) }
    }
  }
  private async visionTick() {
    if (!this.inCall || document.hidden) return
    const f = this.frame(640); if (!f) return
    const r = await this.visionCheck('periodic', [f])
    if (!r?.checked || !this.inCall) return
    if (r.people > 1) { this.ev('extra_person', `AI photo check: ${r.people} people`); this.violation('multiple_people', `AI photo check: ${r.people} people`) }
    else if (r.earphones === 'yes') this.violation('earphones', r.note || 'AI photo check: earphones')
    else if (r.phone) { this.ev('phone_visible', 'AI photo check'); this.violation('phone_visible', 'AI photo check: phone') }
  }
  private async violation(kind: string, detail: string) {
    const camera = ['left_camera', 'multiple_people', 'phone_visible', 'earphones'].includes(kind)
    if (camera ? !this.P.face_detection : !this.P.enforce_focus && kind !== 'multi_monitor') return
    await this.flushEvents()   // the evidence reaches the server before a warning that may end the interview
    let r: any
    try { r = await post(`/api/interviews/${this.iid}/violation`, { type: kind, detail }) }
    catch (e: any) { this.ev('violation_report_failed', e.message); return }
    if (!r || r.action === 'ignored') return
    if (r.action === 'remind') {   // camera or focus reminder: spoken, recorded for HR, never counts as a warning
      this.set({ warnBar: { title: 'Reminder', final: false, text: ({ left_camera: 'Please stay in view of your camera.', multiple_people: 'Please make sure you are alone.', phone_visible: 'Please put your phone away.', earphones: 'Please take out earphones or earbuds.', quick_switches: 'Please keep the interview screen in front of you.' } as Record<string, string>)[kind] || 'Please stay focused on the interview.' } })
      clearTimeout(this.warnTimer); this.warnTimer = window.setTimeout(() => this.set({ warnBar: null }), 7000)
      this.lastWarnSay = norm(r.say); this.addLine('ai', r.say, true, true); this.speak(r.say, false)
      return
    }
    const max = r.max_warnings ?? this.P.max_warnings
    this.set({ warnings: r.warning, maxWarnings: max })
    if (r.action === 'terminate') return this.handleTermination(r.say)
    const what = ({ multi_monitor: 'A second screen was connected.', tab_hidden: 'You left the interview tab.', window_blur: 'You switched to another window.',
      quick_switches: 'You kept switching away from the interview.', fullscreen_exit: "You left full screen and didn't come back.",
      left_camera: 'You stepped out of the camera view.', multiple_people: 'Someone else was in view of the camera.',
      phone_visible: 'A phone was in view of the camera.', earphones: 'Earphones or earbuds were seen.' } as Record<string, string>)[kind] || 'The interview rules were broken.'
    const final = r.warning >= max
    this.set({ warnBar: { title: final ? 'Final warning' : `Warning ${r.warning} of ${max}`, final,
      text: `${what} ${final ? 'If it happens again, the interview ends.' : ['left_camera', 'multiple_people', 'phone_visible', 'earphones'].includes(kind) ? 'Stay in view, alone, with no phone and no earphones. This has been noted for the hiring team.' : 'Please stay on this screen. This has been noted for the hiring team.'}` } })
    clearTimeout(this.warnTimer); this.warnTimer = window.setTimeout(() => this.set({ warnBar: null }), 9000)
    this.lastWarnSay = norm(r.say)
    this.addLine('ai', r.say, true, true)
    this.speak(r.say, false)
  }
  private speak(text: string, endAfter: boolean) {
    if (!text || !this.vapi) return
    // interruptAssistantEnabled: cut in even if the interviewer is mid-sentence (the warning re-asks the question).
    try { this.vapi.say(text, endAfter, false, true) } catch (e: any) { this.ev('warning_not_spoken', e.message) }
  }
  private handleTermination(say: string) {
    if (this.terminated) return
    this.terminated = true
    this.set({ warnBar: null, overlay: { ...this.state.overlay, dq: true } })
    if (say) this.speak(say, true)
    // The interviewer hangs up after speaking; if the call is still up, end it anyway.
    setTimeout(() => { if (this.inCall && this.vapi) this.vapi.stop() }, say ? 16000 : 4000)
  }
  async returnFullscreen() {
    try { await document.documentElement.requestFullscreen({ navigationUI: 'hide' }) } catch { /* unsupported */ }
    this.set({ overlay: { ...this.state.overlay, fs: false } })
  }

  private installIntegrityListeners() {
    document.addEventListener('visibilitychange', () => {
      if (!this.inCall) return
      if (document.hidden) { this.ev('tab_hidden'); this.awayStart('tab_hidden') } else { this.ev('tab_visible'); this.awayEnd() }
    })
    window.addEventListener('blur', () => { if (!this.inCall || document.hidden || Date.now() < this.pickerUntil) return; this.ev('window_blur'); this.awayStart('window_blur') })
    window.addEventListener('focus', () => { if (!this.inCall) return; if (!document.hidden) this.ev('window_focus'); this.awayEnd() })
    document.addEventListener('fullscreenchange', () => {
      if (!this.inCall) return
      if (!document.fullscreenElement) {
        this.ev('fullscreen_exit'); this.set({ overlay: { ...this.state.overlay, fs: true } })
        clearTimeout(this.fsTimer)
        this.fsTimer = window.setTimeout(() => { if (this.inCall && !document.fullscreenElement) { this.snapScreen('fullscreen_exit'); this.violation('fullscreen_exit', `not back after ${FULLSCREEN_GRACE_MS / 1000}s`) } }, FULLSCREEN_GRACE_MS)
      } else { clearTimeout(this.fsTimer); this.ev('fullscreen_enter'); this.set({ overlay: { ...this.state.overlay, fs: false } }) }
    })
    ;(['copy', 'cut', 'paste'] as const).forEach(t => document.addEventListener(t, (e: ClipboardEvent) => {
      if (!this.inCall) return
      const txt = t === 'paste' ? (e.clipboardData?.getData('text') || '') : String(getSelection() || '')
      this.ev(t, `${txt.length} chars`); if (t !== 'paste') e.preventDefault()
    }, true))
    document.addEventListener('contextmenu', e => { if (this.inCall) { e.preventDefault(); if (this.once('ctx', 5000)) this.ev('context_menu') } })
    document.addEventListener('keydown', e => {
      if (!this.inCall) return
      const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey
      const devtools = e.key === 'F12' || (mod && e.shiftKey && ['i', 'j', 'c'].includes(k)) || (e.metaKey && e.altKey && ['i', 'j', 'c'].includes(k))
      if (devtools) { e.preventDefault(); this.ev('devtools_suspected', 'shortcut'); return }
      if (mod && ['c', 'v', 'x', 'a', 'p', 's', 'u', 'f', 't', 'n', 'tab'].includes(k)) { this.ev('shortcut', (e.ctrlKey ? 'Ctrl+' : 'Cmd+') + e.key); if (['p', 's', 'u'].includes(k)) e.preventDefault() }
      if (e.altKey && k === 'tab') this.ev('shortcut', 'Alt+Tab')
    }, true)
    document.addEventListener('keyup', e => { if (this.inCall && e.key === 'PrintScreen') this.ev('print_screen') }, true)
    window.addEventListener('online', () => { if (this.inCall) { this.ev('network_online'); this.set({ offline: false }) } })
    window.addEventListener('offline', () => { if (this.inCall) { this.ev('network_offline'); this.set({ offline: true }) } })
    window.addEventListener('resize', () => { if (this.inCall && !isMobile && innerWidth < screen.availWidth * 0.6 && this.once('small', 30000)) this.ev('window_small', `${innerWidth}x${innerHeight}`) })
    setInterval(() => {  // docked developer tools make the page much smaller than the window
      if (!this.inCall || isMobile) return
      const gapW = outerWidth - innerWidth * (devicePixelRatio || 1) / (window.visualViewport?.scale || 1), gapH = outerHeight - innerHeight
      if ((gapW > 320 || gapH > 320) && !document.fullscreenElement && this.once('dev', 60000)) this.ev('devtools_suspected', `gap ${Math.round(gapW)}x${Math.round(gapH)}`)
    }, 3000)
    window.addEventListener('beforeunload', e => {
      if (this.inCall || this.upQueue.length) { e.preventDefault(); e.returnValue = '' }
      if (this.inCall) this.events.push({ type: 'call_dropped', ts: Date.now(), detail: 'page closed or reloaded' })
      if (this.events.length) navigator.sendBeacon(`/api/interviews/${this.iid}/events`, new Blob([JSON.stringify({ sent_at: Date.now(), events: this.events })], { type: 'application/json' }))
    })
  }
}
