// Copies the country flag SVGs (country-flag-icons, MIT) into public/flags so the phone field can show them as plain images,
// loaded only when seen, with no outside request. Runs before dev and build.
import { cpSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const from = resolve(root, 'node_modules/country-flag-icons/3x2')
if (!existsSync(from)) { console.warn('country-flag-icons is not installed: run npm install'); process.exit(0) }
mkdirSync(resolve(root, 'public/flags'), { recursive: true })
cpSync(from, resolve(root, 'public/flags'), { recursive: true })
console.log('flags copied to public/flags')
