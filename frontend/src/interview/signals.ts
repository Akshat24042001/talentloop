// Integrity signals computed in the candidate's browser. Only events (and the usual snapshots) are sent; no face
// data or audio analysis leaves the device. Every signal is a flag for a person to review, never a rejection.

/** Software cameras (OBS, ManyCam, phone-as-webcam apps...) can feed a pre-recorded or another person's video. */
export const VIRTUAL_CAMERA = /\b(obs|virtual|manycam|xsplit|snap camera|camtwist|mmhmm|vcam|e2esoft|splitcam|youcam|chromacam|nvidia broadcast|droidcam|epoccam|iriun|ivcam|camo|ndi|altercam|webcamoid)\b/i

export async function virtualCameraLabel(track: MediaStreamTrack | undefined): Promise<string> {
  const labels = [track?.label || '']
  try { (await navigator.mediaDevices.enumerateDevices()).forEach(d => { if (d.kind === 'videoinput' && d.deviceId === track?.getSettings().deviceId) labels.push(d.label) }) } catch { /* not allowed */ }
  return labels.find(l => VIRTUAL_CAMERA.test(l)) || ''
}

/** Head yaw from MediaPipe face keypoints (0 right eye, 1 left eye, 2 nose tip): nose offset over eye distance. */
export function yaw(kp: { x: number; y: number }[] | undefined): number | null {
  if (!kp || kp.length < 3) return null
  const r = kp[0]!, l = kp[1]!, n = kp[2]!
  const eye = Math.abs(l.x - r.x)
  return eye > 0.01 ? (n.x - (l.x + r.x) / 2) / eye : null
}

/** Liveness: the candidate turns their head to one side and then the other (a photo or a looped video can't). */
export class HeadTurn {
  private seen = { a: false, b: false }
  passed = false
  feed(y: number | null): boolean {
    if (y == null || this.passed) return this.passed
    if (y > 0.3) this.seen.a = true
    if (y < -0.3) this.seen.b = true
    this.passed = this.seen.a && this.seen.b
    return this.passed
  }
  progress() { return (this.seen.a ? 1 : 0) + (this.seen.b ? 1 : 0) }
}

/** Answer timing: silence before the answer, words and speed. Several long silences followed by long, fast,
 * fluent answers is a pattern worth a human look (reading from a source). */
export class AnswerTiming {
  private aiEnd = 0
  private first = 0
  private last = 0
  private words = 0
  private suspicious = 0
  reported = false
  aiStarted(): { delay: number; words: number; wpm: number } | null {
    const out = this.first && this.aiEnd ? { delay: (this.first - this.aiEnd) / 1000, words: this.words, wpm: this.last > this.first ? Math.round(this.words / ((this.last - this.first) / 60000)) : 0 } : null
    this.aiEnd = 0; this.first = 0; this.last = 0; this.words = 0
    if (out && out.delay >= 6 && out.words >= 60 && out.wpm >= 140) this.suspicious++
    return out
  }
  aiEnded() { this.aiEnd = Date.now(); this.first = 0; this.words = 0 }
  heard(final: boolean, text: string) {
    if (!this.aiEnd) return
    const now = Date.now()
    if (!this.first) this.first = now
    this.last = now
    if (final) this.words += (text.match(/\S+/g) || []).length
  }
  pattern(): boolean { if (this.suspicious >= 3 && !this.reported) { this.reported = true; return true } return false }
}

/** Possible second voice: a sustained run of voiced speech whose pitch is far from the candidate's usual pitch.
 * Uses autocorrelation on the microphone (no recording, no upload). Short pitch errors are ignored: it needs
 * about three seconds of clearly different voice within a few seconds. */
export class VoiceWatch {
  private buf: Float32Array<ArrayBuffer>
  private base: number[] = []
  private baseline = 0
  private recent: boolean[] = []
  constructor(private analyser: AnalyserNode, private rate: number) { this.buf = new Float32Array(analyser.fftSize) }
  private pitch(): number | null {
    const b = this.buf
    this.analyser.getFloatTimeDomainData(b)
    let rms = 0
    for (const v of b) rms += v * v
    if (Math.sqrt(rms / b.length) < 0.02) return null
    const minLag = Math.floor(this.rate / 350), maxLag = Math.min(b.length - 1, Math.floor(this.rate / 75))
    let best = 0, lag = 0
    for (let k = minLag; k <= maxLag; k++) {
      let s = 0, e1 = 0, e2 = 0
      for (let i = 0; i + k < b.length; i++) { s += b[i]! * b[i + k]!; e1 += b[i]! * b[i]!; e2 += b[i + k]! * b[i + k]! }
      const c = s / Math.sqrt(e1 * e2 || 1)
      if (c > best) { best = c; lag = k }
    }
    return best > 0.8 && lag ? this.rate / lag : null
  }
  /** Call about every 100 ms while the candidate may be speaking. Returns a description when a second voice is likely. */
  tick(): string | null {
    const p = this.pitch()
    if (p == null) { if (this.recent.length) this.recent.push(false); this.recent = this.recent.slice(-40); return null }
    if (!this.baseline) {
      this.base.push(p)
      if (this.base.length >= 80) { const s = [...this.base].sort((a, b) => a - b); this.baseline = s[Math.floor(s.length / 2)]! }
      return null
    }
    const r = p / this.baseline
    this.recent.push(r > 1.55 || r < 0.65)
    this.recent = this.recent.slice(-40)
    if (this.recent.filter(Boolean).length >= 28) { this.recent = []; return `${Math.round(p)} Hz against the usual ${Math.round(this.baseline)} Hz` }
    return null
  }
}

/** Face match with face-api (self-hosted models): the registration photo, or the face at the start of the call. */
export class FaceMatch {
  private api: any = null
  private ref: Float32Array | null = null
  refSource: 'registration' | 'start' | '' = ''
  async load(): Promise<boolean> {
    if (this.api) return true
    const m: any = await import('@vladmandic/face-api')
    const api = m.default || m
    await Promise.all([api.nets.tinyFaceDetector.loadFromUri('/vendor/face-api'), api.nets.faceLandmark68TinyNet.loadFromUri('/vendor/face-api'),
      api.nets.faceRecognitionNet.loadFromUri('/vendor/face-api')])
    this.api = api
    return true
  }
  private async descriptor(input: HTMLImageElement | HTMLVideoElement): Promise<Float32Array | null> {
    const d = await this.api.detectAllFaces(input, new this.api.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.5 })).withFaceLandmarks(true).withFaceDescriptors()
    return d.length === 1 ? d[0].descriptor : null
  }
  async setReferenceImage(url: string): Promise<boolean> {
    const img = new Image()
    img.src = url
    await img.decode()
    this.ref = await this.descriptor(img)
    if (this.ref) this.refSource = 'registration'
    return !!this.ref
  }
  async setReferenceFrame(v: HTMLVideoElement): Promise<boolean> {
    this.ref = await this.descriptor(v)
    if (this.ref) this.refSource = 'start'
    return !!this.ref
  }
  get ready() { return !!this.ref }
  /** Distance to the reference (face-api: under about 0.6 is the same person), or null without exactly one face. */
  async distance(v: HTMLVideoElement): Promise<number | null> {
    if (!this.ref) return null
    const d = await this.descriptor(v)
    return d ? this.api.euclideanDistance(this.ref, d) : null
  }
}
