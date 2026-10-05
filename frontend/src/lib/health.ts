import { createElement, useEffect, useState } from 'react'
import { api } from './api'

// Everyone gets mock + link bases; `detail` (models, storage, keys) only comes back for platform admins.
export interface Health {
  env?: string; production?: boolean
  mock: boolean; public_url: string; app_url?: string; detail?: boolean
  fast_model?: string; smart_model?: string; free_models?: boolean; model_note?: string; llm_key_set?: boolean
  vapi_key_set?: boolean; admin_weak?: boolean; ffmpeg?: boolean
  live_turns?: { turns: number; failed: number; avg_ms: number }
  storage?: { s3: boolean; s3_error: string | null; persistent_disk: boolean }
  platform?: { database: string; persistent_db: boolean; platform_admins_configured: boolean }
}
let healthP: Promise<Health> | null = null
export function useHealth(): Health | null {
  const [h, set] = useState<Health | null>(null)
  useEffect(() => { (healthP ||= api<Health>('/api/health', { quiet401: true })).then(set).catch(() => { healthP = null }) }, [])
  return h
}
// Shown on every page outside production, so nobody mistakes a development server for the real one.
export function DevRibbon() {
  const h = useHealth()
  if (!h || h.production !== false) return null
  return createElement('div', { role: 'status', title: 'APP_ENV is not production: emails go only to the developer inbox, WhatsApp is off.',
    className: 'pointer-events-none fixed left-1/2 top-0 z-[60] -translate-x-1/2 rounded-b-lg bg-amber-400 px-3 py-1 text-xs font-bold uppercase tracking-wide text-amber-950 shadow-lg ring-1 ring-amber-600/40' },
    h.env === 'testing' ? 'Testing' : 'Development')
}
/** On a development server, screens that ask for an emailed code say where the email really goes (DEV_EMAIL_TO). */
export function DevMailNote() {
  const h = useHealth()
  if (!h || h.production !== false) return null
  return createElement('p', { role: 'note', className: 'rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-200 dark:ring-amber-500/30' },
    'Development server: every email goes to the developer inbox (DEV_EMAIL_TO), not to this address.')
}
export function healthProblems(h: Health): string[] {
  const bad: string[] = []
  if (!h.detail || !h.storage) return bad
  if (!h.mock && !h.llm_key_set) bad.push('LLM_API_KEY is missing')
  if (!h.public_url) bad.push('PUBLIC_URL is not set, so Vapi cannot reach this server')
  if (!h.vapi_key_set) bad.push('VAPI_PUBLIC_KEY is missing')
  if (!h.storage.s3 && !h.storage.persistent_disk) bad.push('File storage is temporary: a restart wipes interviews and resumes (set S3_*, see DEPLOY.md)')
  if (h.storage.s3_error) bad.push(`Storage error: ${h.storage.s3_error}`)
  if (h.platform && !h.platform.persistent_db) bad.push('The database is temporary (SQLite on a free server): set DATABASE_URL to your Supabase Postgres, see DEPLOY.md')
  if (h.live_turns && h.live_turns.turns >= 10 && h.live_turns.failed / h.live_turns.turns > 0.2)
    bad.push(`The live interviewer's AI model failed ${h.live_turns.failed} of ${h.live_turns.turns} turns in the last hour (rate limits or a slow model). Interviews fall back to safe prompts; set a paid FAST_MODEL for real candidates.`)
  if (h.admin_weak) bad.push('ADMIN_KEY is weak: use a long random string or remove it')
  return bad
}
