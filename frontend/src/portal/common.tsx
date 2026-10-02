// Shared pieces of the public pages behind private links (no sign-in): the branded frame, fetch helpers,
// the "how this round works" box and the camera helpers used by tests, recordings and drive registration.
import { Info, ShieldCheck } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Alert, Card, Logo, Spinner, cn } from '../components/ui'
import { ApiError } from '../lib/api'

export interface Brand { name: string; logo_url: string; brand_color: string; slug: string }
export interface Transparency { measures: string[]; how: string[]; human: string }

export async function getJSON<T = any>(url: string): Promise<T> {
  const r = await fetch(url)
  const d = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(d.detail || r.statusText, r.status)
  return d
}
export async function send<T = any>(url: string, body?: unknown, form?: FormData): Promise<T> {
  const r = await fetch(url, form ? { method: 'POST', body: form } : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) })
  const d = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(typeof d.detail === 'string' ? d.detail : r.statusText, r.status)
  return d
}

export function useLoad<T>(url: string) {
  const [data, setData] = useState<T | null>(null), [error, setError] = useState(''), [n, setN] = useState(0)
  useEffect(() => { getJSON<T>(url).then(d => { setData(d); setError('') }).catch(e => setError(e.message)) }, [url, n])
  return { data, error, reload: () => setN(x => x + 1), setData }
}

export function Frame({ org, children, wide }: { org?: Brand | null; children: ReactNode; wide?: boolean }) {
  useEffect(() => { if (org?.brand_color) document.documentElement.style.setProperty('--org', org.brand_color) }, [org?.brand_color])
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-ink-950">
      <header className="border-b border-slate-200 bg-white dark:border-ink-800 dark:bg-ink-900">
        <div className={cn('mx-auto flex h-14 items-center gap-3 px-4', wide ? 'max-w-5xl' : 'max-w-2xl')}>
          {org?.logo_url ? <img src={org.logo_url} alt={org.name} className="h-7 max-w-40 object-contain" /> : org ? <span className="font-semibold">{org.name}</span> : <Logo />}
        </div>
      </header>
      <main className={cn('mx-auto px-4 py-6 sm:py-10', wide ? 'max-w-5xl' : 'max-w-2xl')}>{children}</main>
      <footer className="pb-8 text-center text-xs text-slate-500 dark:text-slate-400">Powered by TalentLoop</footer>
    </div>
  )
}

export function PageState({ error, loading }: { error?: string; loading?: boolean }) {
  if (error) return <Frame><Alert tone="danger" title="This link can't be opened">{error}</Alert></Frame>
  if (loading) return <Frame><div className="grid place-items-center py-24"><Spinner className="size-6 text-brand-500" /></div></Frame>
  return null
}

export function HowItWorks({ t, className }: { t: Transparency; className?: string }) {
  if (!t.measures.length && !t.how.length && !t.human) return null
  return (
    <Card className={cn('p-5 text-sm', className)}>
      <div className="mb-2 flex items-center gap-2 font-semibold"><Info className="size-4 text-brand-500" />How this step works</div>
      {t.measures.length > 0 && <><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">What we look at</div><ul className="mb-2 mt-1 list-disc pl-5">{t.measures.map(m => <li key={m}>{m}</li>)}</ul></>}
      {t.how.length > 0 && <ul className="mb-2 list-disc space-y-0.5 pl-5 text-slate-600 dark:text-slate-300">{t.how.map(m => <li key={m}>{m}</li>)}</ul>}
      {t.human && <p className="flex items-start gap-1.5 text-slate-600 dark:text-slate-300"><ShieldCheck className="mt-0.5 size-4 shrink-0 text-emerald-600" />{t.human}</p>}
    </Card>
  )
}

/** Camera (and optionally microphone) stream with cleanup. */
export function useCamera(on: boolean, audio = false) {
  const [stream, setStream] = useState<MediaStream | null>(null), [error, setError] = useState('')
  useEffect(() => {
    if (!on) return
    let s: MediaStream | null = null, dead = false
    navigator.mediaDevices?.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' }, audio })
      .then(x => { if (dead) x.getTracks().forEach(t => t.stop()); else { s = x; setStream(x) } })
      .catch(e => setError(e?.name === 'NotAllowedError' ? 'Camera access was blocked. Allow it in your browser settings and reload the page.' : 'No camera found. Please use a device with a camera.'))
    return () => { dead = true; s?.getTracks().forEach(t => t.stop()); setStream(null) }
  }, [on, audio])
  return { stream, error }
}

export function Preview({ stream, className, mirrored = true }: { stream: MediaStream | null; className?: string; mirrored?: boolean }) {
  const ref = useRef<HTMLVideoElement>(null)
  useEffect(() => { if (ref.current && stream) { ref.current.srcObject = stream; ref.current.play().catch(() => {}) } }, [stream])
  return <video ref={ref} muted playsInline className={cn('rounded-xl bg-black object-cover', mirrored && '-scale-x-100', className)} />
}

/** A JPEG frame from a live stream (for snapshots and the registration photo). */
export async function grab(stream: MediaStream, width = 640, quality = 0.8): Promise<Blob | null> {
  const v = document.createElement('video')
  v.muted = true; v.playsInline = true; v.srcObject = stream
  await v.play().catch(() => {})
  if (!v.videoWidth) await new Promise(r => setTimeout(r, 300))
  const w = Math.min(width, v.videoWidth || width), h = Math.round(w * ((v.videoHeight || 3) / (v.videoWidth || 4)))
  const c = document.createElement('canvas'); c.width = w; c.height = h
  c.getContext('2d')!.drawImage(v, 0, 0, w, h)
  v.srcObject = null
  return new Promise(res => c.toBlob(b => res(b), 'image/jpeg', quality))
}

export function fmtClock(sec: number) { const s = Math.max(0, Math.round(sec)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` }
