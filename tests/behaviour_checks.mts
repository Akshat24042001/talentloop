// Detector logic on synthetic signals (run by tests/test_behaviour.py). A check passes when the problem does NOT happen.
import { RoomScan, FW, FH, HFOV } from '../frontend/src/interview/roomscan.ts'
import { VoiceWatch } from '../frontend/src/interview/signals.ts'
import { EARPHONE, GazeAway, LipSync, ReadingWatch, earphonesInUse, gaze, newEarphones, voiced } from '../frontend/src/interview/behaviour.ts'

const res: [string, boolean][] = []
const check = (name: string, bug: boolean, d = '') => { res.push([name, bug]); console.log((bug ? 'FAIL ' : 'ok   ') + 'no longer: ' + name + (bug && d ? `  [${d}]` : '')) }
let seed = 7
const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)

// --- earphones by device name
const dev = (kind: string, label: string, deviceId = 'x') => ({ kind, label, deviceId })
check('AirPods as the speaker go unnoticed', earphonesInUse([dev('audiooutput', 'Default - AirPods Pro (Bluetooth)', 'default')], 'MacBook Pro Microphone').length !== 1)
check('a boAt headset microphone goes unnoticed', earphonesInUse([dev('audiooutput', 'Speakers (Realtek(R) Audio)', 'default')], 'Headset (boAt Rockerz 450)').length !== 1)
check('a Jabra headset goes unnoticed', !EARPHONE.test('Headset Microphone (Jabra Evolve 65)'))
check('Galaxy Buds go unnoticed', !EARPHONE.test('Galaxy Buds2 Pro'))
for (const ok of ['MacBook Pro Speakers', 'Speakers (Realtek(R) Audio)', 'Microphone Array (Intel® Smart Sound Technology)', 'FaceTime HD Camera', 'Built-in Audio Analog Stereo', 'Default - Speakers (High Definition Audio Device)', 'LG ULTRAFINE (DisplayPort)', 'Noise suppression mic'])
  check(`a normal laptop device counts as earphones: ${ok}`, EARPHONE.test(ok))
check('earbuds connected mid-interview go unnoticed', newEarphones([dev('audiooutput', 'MacBook Pro Speakers')], [dev('audiooutput', 'MacBook Pro Speakers'), dev('audiooutput', 'AirPods')]).join() !== 'AirPods')
check('a device that was always there counts as newly connected', newEarphones([dev('audiooutput', 'AirPods')], [dev('audiooutput', 'AirPods')]).length !== 0)

// --- gaze held away
const ga = new GazeAway(5, 4)
let fired: string | null = null
for (let i = 0; i < 25; i++) fired = fired || ga.tick({ h: 0.05, down: 0.7 }, 0.1)
check('eyes held down for 4 s go unnoticed', fired !== 'down')
const ga2 = new GazeAway(5, 4); let f2: string | null = null
for (let i = 0; i < 200; i++) f2 = f2 || ga2.tick({ h: (rnd() - 0.5) * 0.4, down: 0.15 + rnd() * 0.3 }, 0.1)
check('normal glances count as eyes off screen', f2 !== null)
const ga3 = new GazeAway(5, 4); let f3: string | null = null
for (let i = 0; i < 40; i++) f3 = f3 || ga3.tick({ h: 0, down: 0.8 }, 0.9)
check('closed eyes (a blink or thinking) count as looking down', f3 !== null)
check('gaze direction is not read from the blendshapes', Math.abs(gaze({ eyeLookOutLeft: 0.8, eyeLookInRight: 0.8 }).h) < 0.5)

// --- reading: slow sweep, fast return, line after line, at 5 Hz
function runReading(gen: (t: number) => number, talking = true, secs = 30): number | null {
  const r = new ReadingWatch(); let got: number | null = null
  for (let t = 0; t <= secs * 1000; t += 200) { const n = r.tick(t, gen(t), talking); if (n) got = got ?? n }
  return got
}
const line = (t: number) => { const p = (t % 2000) / 2000; return p < 0.85 ? -0.25 + 0.5 * (p / 0.85) : 0.25 - 0.5 * ((p - 0.85) / 0.15) }   // 1.7 s sweep, 0.3 s return
check('reading line by line goes unnoticed', runReading(t => line(t) + (rnd() - 0.5) * 0.04) === null)
check('reading counts while the candidate is silent', runReading(line, false) !== null)
check('steady eye contact counts as reading', runReading(() => (rnd() - 0.5) * 0.06) !== null)
check('slow thinking glances count as reading', runReading(t => 0.3 * Math.sin(t / 1500)) !== null)
check('random looking around counts as reading', runReading(() => (rnd() - 0.5) * 0.5) !== null, String(runReading(() => (rnd() - 0.5) * 0.5)))

let fp = 0, miss = 0
for (let k = 1; k <= 50; k++) {
  seed = k * 9973
  if (runReading(() => (rnd() - 0.5) * 0.5) !== null) fp++
  if (runReading(t => (rnd() - 0.5) * 0.2 + 0.25 * Math.sin(t / 900)) !== null) fp++          // looking around while thinking
  const widths = Array.from({ length: 20 }, () => 0.7 + rnd() * 0.6)                                 // each line a different length
  if (runReading(t => line(t) * widths[Math.floor(t / 2000) % 20]! + (rnd() - 0.5) * 0.05) === null) miss++
}
check('random or thinking glances count as reading (100 runs)', fp > 0, `${fp} false alarms`)
check('reading is missed (50 runs)', miss > 2, `${miss} missed`)

// --- lips: a voice with a moving jaw is the candidate; a voice with a still mouth is someone else
const lip = (jaw: () => number, speech = true, n = 60) => { const l = new LipSync(); let hit = false; for (let i = 0; i < n; i++) hit = l.tick(speech, jaw()) || hit; return hit }
check('a voice with a still mouth goes unnoticed', !lip(() => 0.11 + rnd() * 0.01))
check('the candidate talking counts as someone else', lip(() => 0.05 + rnd() * 0.35))
check('a still mouth in silence counts as someone else', lip(() => 0.1, false))
check('a wide-open still mouth (yawn) counts as someone else', lip(() => 0.6))
check('a face lost from view counts as someone else', (() => { const l = new LipSync(); let h = false; for (let i = 0; i < 60; i++) h = l.tick(true, null) || h; return h })())

// --- voiced sound: speech pitch vs noise
const rate = 48000, N = 2048
const tone = (f: number) => Float32Array.from({ length: N }, (_, i) => 0.3 * Math.sin(2 * Math.PI * f * i / rate) + 0.1 * Math.sin(2 * Math.PI * 2 * f * i / rate))
check('a 140 Hz voice is not recognised as a voice', !voiced(tone(140), rate))
check('white noise counts as a voice', voiced(Float32Array.from({ length: N }, () => (rnd() - 0.5) * 0.6), rate))
check('a 2 kHz whine counts as a voice', voiced(Float32Array.from({ length: N }, (_, i) => 0.3 * Math.sin(2 * Math.PI * 2000 * i / rate) * (rnd() > 0.5 ? 1 : -1)), rate))


// --- room scan coverage, on a synthetic panorama (360 degrees, ceiling and floor) seen through a moving 80x45 window
{
  const PPD = FW / HFOV                                   // pixels per degree
  const PW = Math.round(360 * PPD), PH = 45 + 2 * 40      // panorama: full circle wide, 40 px of ceiling and floor beyond the view
  let sd = 3; const r2 = () => ((sd = (sd * 16807) % 2147483647) / 2147483647)
  let pan = new Float32Array(PW * PH).map(() => r2() * 255)
  for (let k = 0; k < 2; k++) { const o = new Float32Array(pan.length); for (let y = 1; y < PH - 1; y++) for (let x = 0; x < PW; x++) o[y * PW + x] = (pan[y * PW + x]! * 2 + pan[y * PW + (x + 1) % PW]! + pan[y * PW + (x + PW - 1) % PW]! + pan[(y - 1) * PW + x]! + pan[(y + 1) * PW + x]!) / 6; pan = o }
  const view = (yawDeg: number, pitchDeg: number, noise = 0) => {                 // pitch + = looking up = window moves up
    const out = new Uint8Array(FW * FH), cx = Math.round(yawDeg * PPD), cy = 40 - Math.round(pitchDeg * PPD)
    for (let y = 0; y < FH; y++) for (let x = 0; x < FW; x++) out[y * FW + x] = Math.max(0, Math.min(255, pan[Math.max(0, Math.min(PH - 1, cy + y)) * PW + (((cx + x - FW / 2) % PW) + PW) % PW]! + (noise ? (r2() - 0.5) * noise : 0)))
    return out
  }
  const run = (path: (t: number) => [number, number], steps: number, noise = 0) => { const rs = new RoomScan(); for (let i = 0; i <= steps; i++) { const [y, p] = path(i / steps); rs.feed(view(y, p, noise)) } return rs }
  const slow = (t: number) => t * 400                       // 400 degrees of turning in `steps` frames
  const full = run(t => [slow(t), 0], 200)
  check('a full circle is measured as less than 300 degrees', full.circle < 300, `${full.circle}`)
  check('a full circle without looking up or down is accepted', full.progress().done)
  const tilt = run(t => [slow(t), t < 0.5 ? 30 * Math.sin(t * Math.PI * 4) : -25 * Math.sin((t - 0.5) * Math.PI * 4)], 240)
  check('turning plus tilting up and down is not accepted', !tilt.progress().done, JSON.stringify([tilt.circle, tilt.up, tilt.down].map(Math.round)))
  check('looking up is not measured', tilt.up < 10, `${tilt.up}`)
  check('looking down is not measured', tilt.down < 10, `${tilt.down}`)
  const still = run(() => [0, 0], 120)
  check('a camera held still counts as the whole room', still.circle > 120, `${still.circle}`)
  const wiggle = run(t => [35 * Math.sin(t * 40), 0], 240)
  check('wiggling left and right counts as the whole room', wiggle.circle > 200, `${wiggle.circle}`)
  const half = run(t => [t * 190, 0], 100)
  check('turning only halfway round counts as the whole room', half.circle > 280, `${half.circle}`)
  const noisy = run(t => [slow(t), 0], 200, 14)
  check('picture noise breaks the measurement of a full turn', noisy.circle < 280, `${noisy.circle}`)
  const upOnly = run(t => [slow(t), 20 * Math.sin(t * Math.PI)], 200)
  check('looking only up is counted as looking down', upOnly.down > 5 || upOnly.up < 12, `${upOnly.up} ${upOnly.down}`)
  const wall = new RoomScan(); const flat = new Uint8Array(FW * FH).fill(120); for (let i = 0; i < 60; i++) wall.feed(flat)
  check('a blank wall counts as a room scan', wall.progress().done || !wall.progress().dark)
  const shots: string[] = []; const rs3 = new RoomScan(); for (let i = 0; i <= 200; i++) { const [y, p] = [slow(i / 200), 0]; const r = rs3.feed(view(y, p)); if (r) shots.push(r) }
  check('photos are not taken all around the room', shots.filter(x => x === 'sector').length < 10, `${shots.length}`)
}

// --- second voice: synthetic speakers (harmonics shaped by vowel formants), 100 ms per tick
{
  const R = 48000, NF = 2048
  const VOWELS = [[700, 1220, 2600], [270, 2290, 3010], [300, 870, 2240], [530, 1840, 2480], [570, 840, 2410]]
  type Spk = { f0: number; k: number; tilt: number }
  const fft = (re: Float64Array, im: Float64Array) => {
    const n = re.length
    for (let i = 1, j = 0; i < n; i++) { let bit = n >> 1; for (; j & bit; bit >>= 1) j ^= bit; j ^= bit; if (i < j) { [re[i], re[j]] = [re[j]!, re[i]!]; [im[i], im[j]] = [im[j]!, im[i]!] } }
    for (let len = 2; len <= n; len <<= 1) { const a = -2 * Math.PI / len; for (let i = 0; i < n; i += len) for (let k = 0; k < len / 2; k++) {
      const wr = Math.cos(a * k), wi = Math.sin(a * k), ur = re[i + k]!, ui = im[i + k]!, vr = re[i + k + len / 2]! * wr - im[i + k + len / 2]! * wi, vi = re[i + k + len / 2]! * wi + im[i + k + len / 2]! * wr
      re[i + k] = ur + vr; im[i + k] = ui + vi; re[i + k + len / 2] = ur - vr; im[i + k + len / 2] = ui - vi } }
  }
  let td = new Float32Array(NF), fd = new Float32Array(NF / 2), ph = 0
  const an: any = { fftSize: NF, frequencyBinCount: NF / 2, getFloatTimeDomainData: (b: Float32Array) => b.set(td), getFloatFrequencyData: (b: Float32Array) => b.set(fd) }
  const say = (sp: Spk, vowel: number, f0j: number) => {
    const f0 = sp.f0 * f0j, F = VOWELS[vowel]!.map(x => x * sp.k)
    td = new Float32Array(NF)
    for (let h = 1; h * f0 < 5500; h++) {
      const f = h * f0, env = F.reduce((a, c, i) => a + Math.exp(-((f - c) ** 2) / (2 * (90 + 40 * i) ** 2)) * (i === 0 ? 1 : 0.6), 0.02) * Math.pow(f / 300, sp.tilt / 6.02)
      for (let i = 0; i < NF; i++) td[i] += 0.08 * env * Math.sin(2 * Math.PI * f * (i + ph) / R)
    }
    ph += NF / 3
    const re = new Float64Array(NF), im = new Float64Array(NF)
    for (let i = 0; i < NF; i++) re[i] = td[i]! * (0.42 - 0.5 * Math.cos(2 * Math.PI * i / NF) + 0.08 * Math.cos(4 * Math.PI * i / NF))
    fft(re, im)
    fd = new Float32Array(NF / 2).map((_, k) => 20 * Math.log10(Math.hypot(re[k]!, im[k]!) / NF + 1e-9))
  }
  const talk = (w: VoiceWatch, sp: Spk, seconds: number, jitter = 0.05) => {
    let hit: string | null = null
    for (let t = 0; t < seconds * 10; t++) {
      if (t % 4 === 0) { /* syllable: a new vowel */ }
      say(sp, Math.floor(t / 3 + rnd() * 2) % 5, 1 + (rnd() - 0.5) * 2 * jitter)
      hit = w.tick() || hit
    }
    return hit
  }
  const A: Spk = { f0: 120, k: 1.0, tilt: -6 }, B: Spk = { f0: 138, k: 0.9, tilt: -9 }, FEM: Spk = { f0: 205, k: 1.17, tilt: -5 }, A_LOUD: Spk = { f0: 120, k: 1.0, tilt: -6 }
  let w = new VoiceWatch(an, R); talk(w, A, 15)
  check('the same speaker for a minute raises a second-voice flag', !!talk(w, A, 60, 0.08))
  w = new VoiceWatch(an, R); talk(w, A, 15)
  check('a high-pitched voice joining does not raise a second-voice flag', !talk(w, FEM, 12))
  w = new VoiceWatch(an, R); talk(w, A, 15)
  check('a different voice of the same sex and a similar pitch goes unnoticed', !talk(w, B, 25))
  w = new VoiceWatch(an, R); talk(w, A, 15); talk(w, A, 20)
  check('the same speaker after other speech raises a flag', !!talk(w, A_LOUD, 30, 0.1))
}

const bad = res.filter(([, b]) => b)
if (bad.length) { console.log(`${bad.length} BEHAVIOUR CHECK(S) FAILED`); process.exit(1) }
console.log(`BEHAVIOUR CHECKS PASSED (${res.length})`)
