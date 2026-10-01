import { useEffect, useState } from 'react'
import { api } from './api'

export interface Health {
  mock: boolean; fast_model: string; smart_model: string; free_models: boolean; model_note: string; llm_key_set: boolean
  public_url: string; app_url?: string; vapi_key_set: boolean; admin_weak: boolean; ffmpeg: boolean
  storage: { s3: boolean; s3_error: string | null; persistent_disk: boolean }
  platform?: { database: string; persistent_db: boolean; platform_admins_configured: boolean }
}
let healthP: Promise<Health> | null = null
export function useHealth(): Health | null {
  const [h, set] = useState<Health | null>(null)
  useEffect(() => { (healthP ||= api<Health>('/api/health', { quiet401: true })).then(set).catch(() => { healthP = null }) }, [])
  return h
}
export function healthProblems(h: Health): string[] {
  const bad: string[] = []
  if (!h.mock && !h.llm_key_set) bad.push('LLM_API_KEY is missing')
  if (!h.public_url) bad.push('PUBLIC_URL is not set, so Vapi cannot reach this server')
  if (!h.vapi_key_set) bad.push('VAPI_PUBLIC_KEY is missing')
  if (!h.storage.s3 && !h.storage.persistent_disk) bad.push('File storage is temporary: a restart wipes interviews and resumes (set S3_*, see DEPLOY.md)')
  if (h.storage.s3_error) bad.push(`Storage error: ${h.storage.s3_error}`)
  if (h.platform && !h.platform.persistent_db) bad.push('The database is temporary (SQLite on a free server): set DATABASE_URL to your Supabase Postgres, see DEPLOY.md')
  if (h.admin_weak) bad.push('ADMIN_KEY is weak: use a long random string or remove it')
  return bad
}
