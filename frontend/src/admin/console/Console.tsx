// The platform console (/admin): its own app, separate from any company's workspace. Platform admins run all of
// TalentLoop from here: companies, people, candidates, jobs, interviews, messages, the audit log and platform settings.
import { ArrowLeftRight, Briefcase, Building2, FileDown, FileText, Gauge, LogOut, Mail, Menu, ScrollText, Search, Settings, Shield, Users, Video, X } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Alert, Button, Card, CardBody, CardHeader, Field, Input, Select, Switch, cn, toast } from '../../components/ui'
import { Loading, useApi } from '../../components/kit'
import { ask } from '../../components/dialogs'
import { api } from '../../lib/api'
import { match, navigate } from '../../lib/router'
import { confirmSignOut, useMe } from '../../lib/session'
import { useHealth } from '../../lib/health'
import PlatformAnalytics from '../PlatformAnalytics'
import AIModels from '../AIModels'
import { SampleData, SystemStatus } from '../System'
import { Companies, Company } from './companies'
import { People, Person } from './people'
import { Audit, Candidates, Interviews, Jobs, Outbox, Reports } from './data'
import { CandidatePanel, Head, JobPanel } from './parts'

const NAV: { to: string; label: string; icon: typeof Gauge }[] = [
  { to: '/admin', label: 'Overview', icon: Gauge }, { to: '/admin/companies', label: 'Companies', icon: Building2 }, { to: '/admin/people', label: 'People', icon: Users },
  { to: '/admin/candidates', label: 'Candidates', icon: FileText }, { to: '/admin/jobs', label: 'Jobs', icon: Briefcase }, { to: '/admin/interviews', label: 'AI interviews', icon: Video },
  { to: '/admin/outbox', label: 'Outbox', icon: Mail }, { to: '/admin/audit', label: 'Audit log', icon: ScrollText }, { to: '/admin/reports', label: 'Reports', icon: FileDown }, { to: '/admin/settings', label: 'Platform settings', icon: Settings },
]

export default function Console({ path }: { path: string }) {
  const me = useMe()
  const [menu, setMenu] = useState(false)
  useEffect(() => { document.title = 'Platform console · TalentLoop' }, [])
  let page: ReactNode, p: Record<string, string> | null
  if ((p = match('/admin/companies/:id', path))) page = <Company key={p.id} id={p.id!} />
  else if ((p = match('/admin/people/:id', path))) page = <Person key={p.id} id={p.id!} />
  else page = ({ '/admin': <Overview />, '/admin/companies': <Companies />, '/admin/people': <People />, '/admin/candidates': <Candidates />, '/admin/jobs': <Jobs />,
    '/admin/interviews': <Interviews />, '/admin/outbox': <Outbox />, '/admin/audit': <Audit />, '/admin/reports': <Reports />, '/admin/settings': <PlatformSettings /> } as Record<string, ReactNode>)[path]
    ?? <div className="py-24 text-center"><h1 className="text-xl font-semibold">Not found</h1><Button className="mt-4" onClick={() => navigate('/admin')}>Back to the overview</Button></div>
  const active = (to: string) => to === '/admin' ? path === '/admin' : path === to || path.startsWith(to + '/')
  const nav = (
    <nav className="flex h-full flex-col gap-1 p-3">
      <div className="mb-4 flex items-center gap-2 px-2 pt-1"><span className="grid size-8 place-items-center rounded-lg bg-violet-500 text-white"><Shield className="size-4" /></span>
        <div><div className="text-sm font-bold text-white">TalentLoop</div><div className="text-[11px] font-medium uppercase tracking-wider text-violet-300">Platform console</div></div></div>
      {NAV.map(n => (
        <a key={n.to} href={n.to} onClick={e => { e.preventDefault(); setMenu(false); navigate(n.to) }} aria-current={active(n.to) ? 'page' : undefined}
          className={cn('flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium', active(n.to) ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5 hover:text-white')}>
          <n.icon className="size-4" />{n.label}</a>))}
      <div className="mt-auto space-y-1 border-t border-white/10 pt-3">
        {me.org && <a href="/app" className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-300 hover:bg-white/5 hover:text-white"><ArrowLeftRight className="size-4" />My workspace ({me.org.name})</a>}
        <div className="flex items-center justify-between gap-2 px-3 py-2"><div className="min-w-0"><div className="truncate text-sm font-medium text-white">{me.user.name}</div><div className="truncate text-xs text-slate-400">{me.user.email}</div></div>
          <button type="button" aria-label="Sign out" title="Sign out" onClick={confirmSignOut} className="rounded-lg p-2 text-slate-400 hover:bg-white/10 hover:text-white"><LogOut className="size-4" /></button></div>
      </div>
    </nav>
  )
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-ink-950">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 bg-ink-950 lg:block dark:border-r dark:border-ink-800">{nav}</aside>
      {menu && <div className="fixed inset-0 z-40 lg:hidden"><div className="absolute inset-0 bg-black/40" onClick={() => setMenu(false)} /><aside className="absolute inset-y-0 left-0 w-72 bg-ink-950">{nav}</aside></div>}
      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur dark:border-ink-800 dark:bg-ink-900/90 sm:px-6">
          <button type="button" aria-label="Open menu" className="rounded-lg p-2 lg:hidden" onClick={() => setMenu(true)}><Menu className="size-5" /></button>
          <GlobalSearch />
          <div className="ml-auto shrink-0">
            {me.org ? <Button href="/app" icon={<LogOut className="rotate-180" />} title={`Leave the console and use TalentLoop as ${me.org.name}'s ${me.role_label || 'member'}`}>
                <span className="hidden sm:inline">Exit to {me.org.name}</span><span className="sm:hidden">Exit</span></Button>
              : <Button href="/admin/companies" title="You aren't in any company. Create one (with yourself as owner) to use the normal app.">No workspace yet</Button>}
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{page}</main>
      </div>
    </div>
  )
}

function Overview() {
  return (<>
    <Head title="Overview" sub="The whole platform at a glance. Click a tile, a person or a company to go deeper." />
    <PlatformAnalytics />
  </>)
}

/** One search box for companies, people, candidates and jobs across the platform. */
interface Found { orgs: { id: string; name: string; slug: string }[]; users: { id: string; name: string; email: string }[]; candidates: { id: string; name: string; email: string; company: string }[]; jobs: { id: string; title: string; company: string }[] }
function GlobalSearch() {
  const [q, setQ] = useState(''), [res, setRes] = useState<Found | null>(null), [open, setOpen] = useState(false)
  const [cand, setCand] = useState<string | null>(null), [job, setJob] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return }
    const t = setTimeout(() => api<Found>(`/api/console/search?q=${encodeURIComponent(q.trim())}`).then(setRes).catch(() => setRes(null)), 250)
    return () => clearTimeout(t)
  }, [q])
  useEffect(() => { const h = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }; document.addEventListener('mousedown', h); return () => document.removeEventListener('mousedown', h) }, [])
  const pick = (fn: () => void) => { setOpen(false); setQ(''); fn() }
  const none = res && !res.orgs.length && !res.users.length && !res.candidates.length && !res.jobs.length
  const Group = ({ title, children }: { title: string; children: ReactNode }) => <div className="py-1"><div className="px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{title}</div>{children}</div>
  const Item = ({ onClick, main, sub }: { onClick: () => void; main: string; sub?: string }) =>
    <button type="button" onClick={() => pick(onClick)} className="flex w-full flex-col px-3 py-1.5 text-left hover:bg-slate-50 dark:hover:bg-ink-850"><span className="truncate text-sm font-medium">{main}</span>{sub && <span className="truncate text-xs text-slate-500">{sub}</span>}</button>
  return (
    <div ref={box} className="relative w-full max-w-xl">
      <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-500" />
      <Input type="search" aria-label="Search the whole platform" className="pl-9" placeholder="Search companies, people, candidates, jobs" value={q} onFocus={() => setOpen(true)} onChange={e => { setQ(e.target.value); setOpen(true) }} />
      {q && <button type="button" aria-label="Clear" className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400" onClick={() => setQ('')}><X className="size-4" /></button>}
      {open && res && <div className="absolute inset-x-0 top-full z-30 mt-2 max-h-[70vh] overflow-y-auto rounded-xl bg-white py-1 shadow-xl ring-1 ring-slate-200 dark:bg-ink-900 dark:ring-ink-700">
        {none && <p className="px-3 py-3 text-sm text-slate-500">Nothing found.</p>}
        {!!res.orgs.length && <Group title="Companies">{res.orgs.map(o => <Item key={o.id} main={o.name} sub={`/${o.slug}`} onClick={() => navigate(`/admin/companies/${o.id}`)} />)}</Group>}
        {!!res.users.length && <Group title="People">{res.users.map(u => <Item key={u.id} main={u.name || u.email} sub={u.email} onClick={() => navigate(`/admin/people/${u.id}`)} />)}</Group>}
        {!!res.candidates.length && <Group title="Candidates">{res.candidates.map(c => <Item key={c.id} main={c.name} sub={`${c.company} · ${c.email}`} onClick={() => setCand(c.id)} />)}</Group>}
        {!!res.jobs.length && <Group title="Jobs">{res.jobs.map(j => <Item key={j.id} main={j.title} sub={j.company} onClick={() => setJob(j.id)} />)}</Group>}
      </div>}
      <CandidatePanel id={cand} onClose={() => setCand(null)} />
      <JobPanel id={job} onClose={() => setJob(null)} />
    </div>
  )
}

interface PS { signups_open: boolean; banner: string; banner_tone: 'info' | 'warning' | 'danger' }
function PlatformSettings() {
  const { data, reload } = useApi<PS>('/api/console/settings')
  const h = useHealth()
  const [f, setF] = useState<PS | null>(null)
  useEffect(() => { if (data) setF(data) }, [data])
  async function save() {
    if (!f || !await ask('Save platform settings? They apply to every company at once.', { confirm: 'Save', danger: false })) return
    try { await api('/api/console/settings', { method: 'PUT', json: f }); toast('Saved'); reload() } catch (e: any) { toast(e.message) }
  }
  return (<>
    <Head title="Platform settings" sub="Settings for the whole platform. Server keys stay in the hosting environment and are only shown as set or not set." />
    <div className="space-y-5">
      <Card><CardHeader title="Access and announcements" /><CardBody className="space-y-4">
        {!f ? <Loading /> : <>
          <Switch id="ps-signups" checked={f.signups_open} onChange={v => setF({ ...f, signups_open: v })} label="Anyone can create a new company (sign-up is open)" />
          {!f.signups_open && <Alert tone="warning">New companies can't sign up. Invited people can still join, and addresses in PLATFORM_ADMIN_EMAILS can still sign up.</Alert>}
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px]">
            <Field label="Banner for every signed-in user" htmlFor="ps-banner" hint="For example a maintenance window. Leave empty for none."><Input id="ps-banner" maxLength={300} value={f.banner} onChange={e => setF({ ...f, banner: e.target.value })} /></Field>
            <Field label="Tone" htmlFor="ps-tone"><Select id="ps-tone" value={f.banner_tone} onChange={e => setF({ ...f, banner_tone: e.target.value as PS['banner_tone'] })}><option value="info">Information</option><option value="warning">Warning</option><option value="danger">Urgent</option></Select></Field>
          </div>
          {f.banner && <Alert tone={f.banner_tone}>{f.banner}</Alert>}
          <div className="flex justify-end"><Button variant="primary" disabled={JSON.stringify(f) === JSON.stringify(data)} onClick={save}>Save</Button></div>
        </>}
      </CardBody></Card>
      <AIModels />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]"><SystemStatus /><SampleData /></div>
      {h && <Card><CardHeader title="Environment" description="Read from the server. Change these in the hosting environment (Render > Environment), then redeploy." /><CardBody className="text-sm">
        <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
          <li>Environment: <b>{h.env || 'unknown'}</b>{h.production === false && ' (emails go only to the developer inbox)'}</li>
          <li>Public address: <b>{(h as any).app_url || h.public_url || 'not set'}</b></li>
        </ul></CardBody></Card>}
    </div>
  </>)
}
