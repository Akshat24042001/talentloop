// Detector logic on synthetic signals (run by tests/test_behaviour.py). A check passes when the problem does NOT happen.
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

const bad = res.filter(([, b]) => b)
if (bad.length) { console.log(`${bad.length} BEHAVIOUR CHECK(S) FAILED`); process.exit(1) }
console.log(`BEHAVIOUR CHECKS PASSED (${res.length})`)
