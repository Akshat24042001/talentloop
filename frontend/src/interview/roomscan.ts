/** Room scan coverage: did the camera really sweep the whole room, up and down as well?
 *
 * The scan used to be "12 seconds of video": holding the laptop still, or wiggling it, passed. This measures the
 * camera's own rotation from the pictures it sees (global motion between small grey frames, no sensors needed), adds up the
 * angles it has looked at, and only completes when the whole circle plus the ceiling side and the floor side were seen.
 * Pure logic with no browser calls, so tests/behaviour_checks.mts runs it on synthetic frames. */

export const FW = 80, FH = 45                    // grey frame size used for the measurement
export const HFOV = 66                           // typical laptop webcam horizontal field of view, degrees
const VFOV = HFOV * FH / FW
const BIN = 5                                    // degrees per coverage bin
export const NEED_CIRCLE = 330                   // degrees of the circle that must have been in view
export const NEED_UP = 12, NEED_DOWN = 14        // degrees of tilt each way from where the camera started
const MAX_DX = 14, MAX_DY = 7

export interface ScanProgress {
  circle: number            // degrees of the circle seen (0-360)
  up: number; down: number  // degrees tilted up / down from the start
  done: boolean
  hint: string              // what to do next
  tooFast: boolean; dark: boolean
}

export interface Shift { dx: number; dy: number; ok: boolean; edge: boolean }

/** How far `cur` is shifted against `prev` (scene content moving left in the picture = camera turning right = dx > 0). */
export function estimateShift(prev: Uint8Array, cur: Uint8Array): Shift {
  let mean = 0, n = 0
  for (let i = 0; i < prev.length; i += 7) { mean += prev[i]!; n++ }
  mean /= n
  let varsum = 0
  for (let i = 0; i < prev.length; i += 7) varsum += (prev[i]! - mean) ** 2
  if (Math.sqrt(varsum / n) < 4) return { dx: 0, dy: 0, ok: false, edge: false }          // blank wall or dark picture
  let best = Infinity, bx = 0, by = 0, total = 0, cnt = 0
  const sads: number[][] = []
  for (let dy = -MAX_DY; dy <= MAX_DY; dy++) {
    const row: number[] = []
    for (let dx = -MAX_DX; dx <= MAX_DX; dx++) {
      let sad = 0, m = 0
      for (let y = MAX_DY; y < FH - MAX_DY; y += 2) {
        const o1 = y * FW, o2 = (y + dy) * FW
        for (let x = MAX_DX; x < FW - MAX_DX; x += 2) { sad += Math.abs(cur[o1 + x]! - prev[o2 + x + dx]!); m++ }
      }
      sad /= m; row.push(sad); total += sad; cnt++
      if (sad < best) { best = sad; bx = dx; by = dy }
    }
    sads.push(row)
  }
  const avg = total / cnt
  if (best > avg * 0.7) return { dx: 0, dy: 0, ok: false, edge: false }                    // no clear match
  let fx = bx
  const row = sads[by + MAX_DY]!, i = bx + MAX_DX                                          // sub-pixel: parabola through the neighbours
  if (i > 0 && i < row.length - 1) { const a = row[i - 1]!, b = row[i]!, c = row[i + 1]!, d = a - 2 * b + c; if (d > 1e-6) fx = bx + 0.5 * (a - c) / d }
  return { dx: fx, dy: by, ok: true, edge: Math.abs(bx) >= MAX_DX - 1 || Math.abs(by) >= MAX_DY - 1 }
}

export class RoomScan {
  yaw = 0; pitch = 0                       // degrees since the start; yaw + = turning right, pitch + = looking up
  minPitch = 0; maxPitch = 0
  private bins = new Uint8Array(360 / BIN)
  private anchor: Uint8Array | null = null
  private bad = 0; frames = 0; fast = 0; dark = 0
  /** Sector (30 degrees) of the circle -> the yaw it was first entered at; the page takes a photo when this returns true. */
  private sectors = new Set<number>()
  private upShot = false; private downShot = false

  private mark() {
    const a0 = this.yaw - HFOV / 2, a1 = this.yaw + HFOV / 2
    for (let a = a0; a <= a1; a += BIN) this.bins[(((Math.floor(a / BIN)) % this.bins.length) + this.bins.length) % this.bins.length] = 1
  }
  get circle(): number { let n = 0; for (const b of this.bins) n += b; return n * BIN }
  get up(): number { return Math.max(0, this.maxPitch) }
  get down(): number { return Math.max(0, -this.minPitch) }

  /** Feed a grey frame. Returns what to photograph now, if anything: 'sector' (a new part of the room), 'up' or 'down'. */
  feed(frame: Uint8Array): 'sector' | 'up' | 'down' | null {
    this.frames++
    if (!this.anchor) { this.anchor = frame; this.mark(); this.sectors.add(0); return 'sector' }
    const s = estimateShift(this.anchor, frame)
    if (!s.ok) { this.bad++; return null }
    if (s.edge) this.fast++
    // Only act on a clear movement: tiny shifts are measured against the same anchor until they add up (no rounding loss).
    if (Math.abs(s.dx) < 3 && Math.abs(s.dy) < 3 && !s.edge) return null
    this.yaw += s.dx * HFOV / FW
    this.pitch -= s.dy * VFOV / FH                 // scene moving down in the picture (dy < 0) = camera looking up
    this.minPitch = Math.min(this.minPitch, this.pitch); this.maxPitch = Math.max(this.maxPitch, this.pitch)
    this.anchor = frame
    this.mark()
    const sec = (((Math.floor(this.yaw / 30)) % 12) + 12) % 12
    if (!this.sectors.has(sec)) { this.sectors.add(sec); return 'sector' }
    if (!this.upShot && this.up >= NEED_UP) { this.upShot = true; return 'up' }
    if (!this.downShot && this.down >= NEED_DOWN) { this.downShot = true; return 'down' }
    return null
  }
  /** The picture was too dark or too flat for the whole scan so far. */
  get unreadable(): boolean { return this.frames >= 20 && this.bad / this.frames > 0.8 }

  progress(): ScanProgress {
    const circle = Math.min(360, this.circle), done = circle >= NEED_CIRCLE && this.up >= NEED_UP && this.down >= NEED_DOWN
    const dark = this.unreadable, tooFast = this.frames >= 10 && this.fast / this.frames > 0.25
    const hint = dark ? 'The picture is too dark or too plain to follow. Turn on a light and show things in the room.'
      : tooFast ? 'Too fast. Turn slowly so the whole room is seen.'
      : circle < NEED_CIRCLE ? (this.frames < 8 ? 'Pick up your laptop and turn slowly in a full circle: left, behind you, right.'
        : `Keep turning slowly all the way around (${Math.round(circle / 360 * 100)}% of the room seen).`)
      : this.up < NEED_UP ? 'Now tilt the camera up to show the ceiling and the top of the walls.'
      : this.down < NEED_DOWN ? 'Now tilt the camera down to show the floor and under your desk.'
      : 'Room covered.'
    return { circle, up: this.up, down: this.down, done, hint, tooFast, dark }
  }
}
