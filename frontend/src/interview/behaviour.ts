// Signs that answers come from somewhere else: eyes reading a hidden screen or a phone, a voice that isn't coming
// from the candidate's mouth, earphones connected, a camera feed that can't follow a spontaneous head turn.
// Everything here runs in the browser on numbers from the face mesh and the microphone; nothing is uploaded.
// Each class takes plain numbers so it can be tested without a camera (see tests/e2e_browser.py).

/** Earphones, earbuds and headsets by device label (Chrome shows labels once the camera and mic are allowed). */
export const EARPHONE = /\b(airpods?|buds\d*|earbuds?|earphones?|headphones?|headset|hands-?free|bluetooth|bose|jabra|beats|plantronics|poly\s|jbl|soundcore|nothing ear|boat|sennheiser|skullcandy|wh-\d|wf-\d|galaxy buds|pixel buds|freebuds|oneplus buds|realme buds|redmi buds|airdopes)\b/i

export interface DeviceInfo { kind: string; label: string; deviceId: string }
/** Earphone-like devices that are in use: the microphone actually captured, and the default output. */
export function earphonesInUse(devices: DeviceInfo[], micLabel: string): string[] {
  const out: string[] = []
  if (EARPHONE.test(micLabel)) out.push(micLabel)
  const def = devices.find(d => d.kind === 'audiooutput' && d.deviceId === 'default') || devices.find(d => d.kind === 'audiooutput')
  if (def && EARPHONE.test(def.label)) out.push(def.label.replace(/^Default\s*-\s*/i, ''))
  return [...new Set(out)]
}
/** Earphone-like devices present now that were not there before (connected during the interview). */
export function newEarphones(before: DeviceInfo[], now: DeviceInfo[]): string[] {
  const seen = new Set(before.map(d => d.label))
  return [...new Set(now.filter(d => d.label && !seen.has(d.label) && EARPHONE.test(d.label)).map(d => d.label.replace(/^Default\s*-\s*/i, '')))]
}

/** Blendshape scores (0..1) from MediaPipe's face landmarker, by name. */
export type Shapes = Record<string, number>
export const shapesOf = (cats: { categoryName: string; score: number }[] | undefined): Shapes =>
  Object.fromEntries((cats || []).map(c => [c.categoryName, c.score]))

/** Horizontal gaze in the candidate's frame: < 0 looking to their left, > 0 to their right. Vertical: > 0 down. */
export function gaze(s: Shapes): { h: number; down: number } {
  const left = ((s.eyeLookOutLeft ?? 0) + (s.eyeLookInRight ?? 0)) / 2
  const right = ((s.eyeLookInLeft ?? 0) + (s.eyeLookOutRight ?? 0)) / 2
  return { h: right - left, down: ((s.eyeLookDownLeft ?? 0) + (s.eyeLookDownRight ?? 0)) / 2 }
}

/**
 * Eyes held away from the screen (a phone in the lap, a note beside the laptop) while the head faces the camera,
 * which head-pose checks can't see. Feed ~5 samples a second. Returns 'down' or 'side' once per stretch of 4 s.
 */
export class GazeAway {
  private down = 0
  private side = 0
  constructor(private hz = 5, private sec = 4) {}
  tick(g: { h: number; down: number } | null, blink: number): 'down' | 'side' | null {
    if (!g || blink > 0.5) return null                 // eyes closed: no gaze reading
    this.down = g.down > 0.55 ? this.down + 1 : 0
    this.side = Math.abs(g.h) > 0.55 ? this.side + 1 : 0
    const n = this.hz * this.sec
    if (this.down === n) return 'down'
    if (this.side === n) return 'side'
    return null
  }
}

/**
 * Reading text: the eyes drift slowly one way along a line, then jump back to the start of the next one, again and
 * again. Hidden answer overlays and notes are read like this; people thinking aloud look around irregularly.
 * Counts "line returns" (a fast jump back after a slow sweep) while the candidate is talking. Feed ~5 Hz samples.
 */
export class ReadingWatch {
  private hs: { t: number; h: number }[] = []
  private returns: number[] = []
  private lastReturn = 0
  tick(t: number, h: number | null, talking: boolean): number | null {
    if (h == null || !talking) { this.hs = []; return null }
    this.hs.push({ t, h })
    this.hs = this.hs.filter(x => t - x.t <= 3000)
    if (this.hs.length < 5) return null
    const last = this.hs[this.hs.length - 1]!
    const prev = this.hs.filter(x => last.t - x.t <= 450)[0]!       // where the eyes were ~0.4 s ago (2 samples at 5 Hz)
    const jump = last.h - prev.h
    // the sweep before the jump: at least 0.6 s going the other way, slowly
    const sweep = this.hs.filter(x => x.t <= prev.t && prev.t - x.t <= 2500)
    if (sweep.length >= 3 && t - this.lastReturn > 600) {
      const travel = prev.h - sweep[0]!.h, span = (prev.t - sweep[0]!.t) / 1000
      // a reading sweep is smooth and one-way: most steps go with the travel and none is a jump of its own
      const steps = sweep.slice(1).map((x, i) => x.h - sweep[i]!.h)
      const along = steps.filter(d => Math.sign(d) === Math.sign(travel) || Math.abs(d) < 0.02).length / Math.max(1, steps.length)
      const smooth = steps.every(d => Math.abs(d) < 0.15)
      if (Math.abs(jump) >= 0.22 && Math.sign(jump) === -Math.sign(travel) && Math.abs(travel) >= 0.18 && span >= 0.6 &&
          Math.abs(jump) >= Math.abs(travel) * 0.6 && along >= 0.7 && smooth) {
        this.lastReturn = t
        this.returns.push(t)
        this.hs = [last]
      }
    }
    this.returns = this.returns.filter(x => t - x <= 25000)
    if (this.returns.length >= 5) { const n = this.returns.length; this.returns = []; return n }
    return null
  }
}

/**
 * A voice is heard but the candidate's mouth isn't moving: someone else is answering, prompting, or audio is played
 * into the microphone. Feed ~5 Hz: whether the mic hears speech (and the AI isn't talking), and jaw-open.
 */
export class LipSync {
  private jaw: number[] = []
  private speechTicks = 0
  private stillTicks = 0
  tick(speech: boolean, jawOpen: number | null): boolean {
    if (jawOpen == null) { this.reset(); return false }
    this.jaw.push(jawOpen)
    this.jaw = this.jaw.slice(-5)                       // the last second
    if (!speech) { this.speechTicks = Math.max(0, this.speechTicks - 1); this.stillTicks = Math.max(0, this.stillTicks - 1); return false }
    this.speechTicks++
    const mean = this.jaw.reduce((a, b) => a + b, 0) / this.jaw.length
    const spread = Math.max(...this.jaw) - Math.min(...this.jaw)
    // Measured: a resting face can show jawOpen ~0.12 with lips apart, so judge movement, not openness. Speaking moves
    // the jaw by well over 0.1 within a second; a still mouth stays within a few hundredths.
    if (this.jaw.length >= 5 && mean < 0.3 && spread < 0.04) this.stillTicks++
    if (this.speechTicks >= 15 && this.stillTicks >= 12) { this.reset(); return true }   // ~3 s of speech, ~2.4 s of it with a still mouth
    return false
  }
  reset() { this.jaw = []; this.speechTicks = 0; this.stillTicks = 0 }
}

/** A human voice in the microphone: louder than the room's noise floor AND voiced (periodic at a speaking pitch,
 * 75-350 Hz), so fans, typing, traffic and most music don't count. Use an analyser with fftSize >= 2048. */
export class SpeechLevel {
  private floor = 0.01
  private buf: Float32Array<ArrayBuffer>
  constructor(private analyser: AnalyserNode, private rate: number) { this.buf = new Float32Array(analyser.fftSize) }
  speaking(): boolean {
    const b = this.buf
    this.analyser.getFloatTimeDomainData(b)
    let e = 0
    for (const v of b) e += v * v
    const r = Math.sqrt(e / b.length)
    this.floor = r < this.floor ? r : this.floor * 0.995 + r * 0.005
    if (r <= Math.max(0.02, this.floor * 3)) return false
    return voiced(b, this.rate)
  }
}

/** Normalised autocorrelation peak in the speaking-pitch range (decimated by 2 to stay cheap). */
export function voiced(b: Float32Array, rate: number): boolean {
  const minLag = Math.floor(rate / 350), maxLag = Math.min(b.length - 2, Math.floor(rate / 75))
  let best = 0
  for (let k = minLag; k <= maxLag; k += 2) {
    let s = 0, e1 = 0, e2 = 0
    for (let i = 0; i + k < b.length; i += 2) { s += b[i]! * b[i + k]!; e1 += b[i]! * b[i]!; e2 += b[i + k]! * b[i + k]! }
    const c = s / Math.sqrt(e1 * e2 || 1)
    if (c > best) best = c
  }
  return best > 0.6
}
