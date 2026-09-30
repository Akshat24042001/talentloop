import { KeyRound, LayoutDashboard, LogOut, Plus } from 'lucide-react'
import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { Badge, Button, Input, Logo, Modal, Toaster, TooltipProvider, cn } from '../components/ui'
import { adminKey, api, keyRequest, setAdminKey } from '../lib/api'

export interface Health {
  mock: boolean; fast_model: string; smart_model: string; free_models: boolean; model_note: string; llm_key_set: boolean
  public_url: string; vapi_key_set: boolean; admin_weak: boolean; ffmpeg: boolean
  storage: { s3: boolean; s3_error: string | null; persistent_disk: boolean }
}
let healthP: Promise<Health> | null = null
export function useHealth(): Health | null {
  const [h, set] = useState<Health | null>(null)
  useEffect(() => { (healthP ||= api<Health>('/api/health')).then(set).catch(() => { healthP = null }) }, [])
  return h
}
export function healthProblems(h: Health): string[] {
  const bad: string[] = []
  if (!h.mock && !h.llm_key_set) bad.push('LLM_API_KEY is missing')
  if (!h.public_url) bad.push('PUBLIC_URL is not set, so Vapi cannot reach this server')
  if (!h.vapi_key_set) bad.push('VAPI_PUBLIC_KEY is missing')
  if (!h.storage.s3 && !h.storage.persistent_disk) bad.push('Storage is temporary: a restart wipes interviews (set S3_*, see DEPLOY.md)')
  if (h.storage.s3_error) bad.push(`Storage error: ${h.storage.s3_error}`)
  if (h.admin_weak) bad.push('ADMIN_KEY is empty or weak')
  return bad
}

const NAV = [
  { key: 'dashboard', href: '/dashboard.html', label: 'Interviews', icon: LayoutDashboard },
  { key: 'new', href: '/hr.html', label: 'New interview', icon: Plus },
]

function AdminKeyDialog() {
  const open = useSyncExternalStore(keyRequest.subscribe, keyRequest.pending)
  const [k, setK] = useState('')
  return (
    <Modal open={open} onOpenChange={o => { if (!o) keyRequest.resolve(null) }} title="Sign in to TalentLoop"
      description="Enter the admin key (ADMIN_KEY in your server settings). It is kept for this browser tab only.">
      <form className="mt-5 space-y-4" onSubmit={e => { e.preventDefault(); if (k.trim()) { keyRequest.resolve(k.trim()); setK('') } }}>
        <Input id="adminKey" type="password" autoFocus placeholder="Admin key" value={k} onChange={e => setK(e.target.value)} />
        <Button variant="primary" className="w-full" type="submit" icon={<KeyRound />}>Sign in</Button>
      </form>
    </Modal>
  )
}

export function AppShell({ active, children }: { active: 'dashboard' | 'new'; children: ReactNode }) {
  const h = useHealth()
  return (
    <TooltipProvider>
      {/* sidebar (desktop) */}
      <aside className="no-print fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-slate-200/80 bg-white px-4 py-5 dark:border-ink-700 dark:bg-ink-900 lg:flex">
        <a href="/dashboard.html" className="px-2"><Logo /></a>
        <p className="mt-1 px-2 pl-[50px] text-xs text-slate-500 dark:text-slate-400">AI Interviews</p>
        <nav className="mt-8 space-y-1">
          {NAV.map(n => (
            <a key={n.key} href={n.href} className={cn('flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors [&_svg]:size-[18px]',
              active === n.key ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-200' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-ink-800 dark:hover:text-white')}>
              <n.icon />{n.label}
            </a>
          ))}
        </nav>
        <div className="mt-auto space-y-3">
          {h && (
            <div className="rounded-xl bg-slate-50 p-3 text-xs ring-1 ring-slate-200/70 dark:bg-ink-850 dark:ring-ink-700">
              <div className="flex items-center justify-between"><span className="font-semibold text-slate-700 dark:text-slate-200">Server</span>
                {h.mock ? <Badge tone="warning">Demo mode</Badge> : healthProblems(h).length ? <Badge tone="danger">Needs setup</Badge> : <Badge tone="success">Live</Badge>}</div>
              <p className="mt-1.5 leading-relaxed text-slate-500 dark:text-slate-400">{h.mock ? 'Fake AI for testing the flow.' : `Interviewer model: ${h.fast_model}`}</p>
            </div>
          )}
          {adminKey() && <button onClick={() => { setAdminKey(''); location.reload() }} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-ink-800 dark:hover:text-white"><LogOut className="size-4" />Sign out</button>}
        </div>
      </aside>
      {/* top bar (mobile) */}
      <header className="no-print sticky top-0 z-30 flex items-center justify-between border-b border-slate-200/80 bg-white/90 px-4 py-3 backdrop-blur dark:border-ink-700 dark:bg-ink-900/90 lg:hidden">
        <a href="/dashboard.html"><Logo /></a>
        <nav className="flex gap-1">
          {NAV.map(n => <a key={n.key} href={n.href} aria-label={n.label} className={cn('grid size-10 place-items-center rounded-xl [&_svg]:size-5', active === n.key ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-200' : 'text-slate-500 dark:text-slate-300')}><n.icon /></a>)}
        </nav>
      </header>
      <main className="lg:pl-64"><div className="mx-auto max-w-7xl px-4 py-6 sm:px-8 sm:py-8">{children}</div></main>
      <AdminKeyDialog />
      <Toaster />
    </TooltipProvider>
  )
}

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white sm:text-[28px]">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}
