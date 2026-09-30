export function mmss(t: number | null | undefined): string {
  if (t == null || Number.isNaN(t)) return '-'
  let s = Math.round(t)
  const neg = s < 0
  s = Math.abs(s)
  return `${neg ? '-' : ''}${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}
export function when(ts?: number | null): string {
  return ts ? new Date(ts * 1000).toLocaleString([], { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-'
}
export function ago(ts?: number | null): string {
  if (!ts) return '-'
  const s = Date.now() / 1000 - ts
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} d ago`
  return new Date(ts * 1000).toLocaleDateString([], { day: 'numeric', month: 'short' })
}
export function short(s: string | undefined | null, n = 70): string {
  const t = String(s || '')
  return t.length > n ? t.slice(0, n - 1).trimEnd() + '…' : t
}
export function mb(b?: number): string { return b ? `${(b / 1e6).toFixed(1)} MB` : '' }
export function norm(s: string): string { return String(s || '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim() }
export function initials(name?: string | null): string {
  return String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]!.toUpperCase()).join('')
}

export const REC_LABEL: Record<string, string> = { strong_yes: 'Strong yes', yes: 'Yes', maybe: 'Maybe', no: 'No' }
export const REC_TONE: Record<string, Tone> = { strong_yes: 'success', yes: 'success', maybe: 'warning', no: 'danger' }
export const STATUS_LABEL: Record<string, string> = { created: 'Not started', in_progress: 'In progress', completed: 'Completed',
  incomplete: 'Ended early', scored: 'Scored', cancelled: 'Cancelled' }
export const STATUS_TONE: Record<string, Tone> = { created: 'neutral', in_progress: 'brand', completed: 'success', incomplete: 'warning',
  scored: 'success', cancelled: 'neutral' }
export const TYPE_LABEL: Record<string, string> = { warmup: 'Warm-up', hr_mandatory: 'HR question', resume_probe: 'Resume deep-dive',
  jd_skill: 'Skill check', behavioral: 'Behavioral' }
export type Tone = 'neutral' | 'brand' | 'success' | 'warning' | 'danger' | 'violet'
