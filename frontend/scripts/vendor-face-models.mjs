// Copies the three face-api models the interview uses for the face match into public/vendor/face-api
// (self-hosted, nothing loaded from a CDN). Runs before every build; the copies are not committed.
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = join(root, 'node_modules', '@vladmandic', 'face-api', 'model')
const dst = join(root, 'public', 'vendor', 'face-api')
const files = ['tiny_face_detector_model', 'face_landmark_68_tiny_model', 'face_recognition_model'].flatMap(m => [`${m}-weights_manifest.json`, `${m}.bin`])
if (!existsSync(src)) { console.error('face-api models not found: run npm ci first'); process.exit(1) }
mkdirSync(dst, { recursive: true })
for (const f of files) copyFileSync(join(src, f), join(dst, f))
console.log(`face-api models copied to public/vendor/face-api (${files.length} files)`)
