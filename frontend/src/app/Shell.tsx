import { CalendarClock, ChartColumn, GraduationCap, HandHelping, Inbox, Library, ScrollText, Briefcase, Building2, ChevronsUpDown, LayoutDashboard, LogOut, Menu, Settings, Shield, Sparkles, UserRound, Users, Video, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Badge, Logo, cn, toast } from '../components/ui'
import { Avatar } from '../components/kit'
import { api } from '../lib/api'
import { healthProblems, useHealth } from '../lib/health'
import { useLocation } from '../lib/router'
import { confirmSignOut, useSession } from '../lib/session'
import { Tour, type TourStep } from '../components/Tour'

const NAV = [
  { href: '/app', label: 'Dashboard', icon: LayoutDashboard, exact: true },
  { href: '/app/jobs', label: 'Jobs', icon: Briefcase },
  { href: '/app/candidates', label: 'Candidates', icon: Users },
  { href: '/app/matches', label: 'Match center', icon: Sparkles },
  { href: '/app/interviews', label: 'AI interviews', icon: Video },
  { href: '/app/my-interviews', label: 'My interviews', icon: CalendarClock },
]
const NAV_HIRING = [
  { href: '/app/requests', label: 'Requests', icon: HandHelping },
  { href: '/app/questions', label: 'Question bank', icon: Library },
  { href: '/app/drives', label: 'Campus drives', icon: GraduationCap },
  { href: '/app/outbox', label: 'Outbox', icon: Inbox },
  { href: '/app/reports', label: 'Reports', icon: ChartColumn },
  { href: '/app/audit', label: 'Audit log', icon: ScrollText },
]
const NAV2 = [
  { href: '/app/team', label: 'Team', icon: UserRound },
  { href: '/app/settings', label: 'Settings', icon: Settings },
]

function NavLink({ href, label, icon: Icon, exact, path, onClick }: { href: string; label: string; icon: any; exact?: boolean; path: string; onClick?: () => void }) {
  const on = exact ? path === href : path === href || path.startsWith(href + '/')
  return (
    <a href={href} data-tour={href.replace("/app/", "nav-").replace("/app", "nav-dashboard")} onClick={onClick} aria-current={on ? "page" : undefined} className={cn('flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors [&_svg]:size-[18px]',
      on ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-200' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-ink-800 dark:hover:text-white')}>
      <Icon />{label}
    </a>
  )
}

function OrgSwitcher() {
  const { me, refresh } = useSession()
  const [open, setOpen] = useState(false)
  if (!me?.org) return null
  const others = me.memberships.filter(m => m.org_id !== me.org!.id)
  return (
    <div className="relative">
      <button onClick={() => others.length && setOpen(o => !o)} className={cn('flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left ring-1 ring-slate-200 dark:ring-ink-700', others.length && 'hover:bg-slate-50 dark:hover:bg-ink-850')}>
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-slate-900 text-xs font-bold text-white dark:bg-white dark:text-ink-900">{me.org.name.slice(0, 1).toUpperCase()}</span>
        <span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold">{me.org.name}</span><span className="block truncate text-xs text-slate-500 dark:text-slate-400">{me.role_label}</span></span>
        {others.length > 0 && <ChevronsUpDown className="size-4 text-slate-500 dark:text-slate-400" />}
      </button>
      {open && (
        <div className="absolute inset-x-0 top-full z-40 mt-1 rounded-xl bg-white p-1 shadow-xl ring-1 ring-slate-200 dark:bg-ink-850 dark:ring-ink-700">
          {others.map(m => (
            <button key={m.org_id} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-ink-800"
              onClick={async () => { await api('/api/auth/switch-org', { json: { org_id: m.org_id } }); await refresh(); setOpen(false); toast(`Switched to ${m.name}`); location.href = '/app' }}>
              <Building2 className="size-4 text-slate-500 dark:text-slate-400" />{m.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Sidebar({ path, onNav }: { path: string; onNav?: () => void }) {
  const { me } = useSession()
  const h = useHealth()
  const problems = h ? healthProblems(h) : []
  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <a href="/app" className="px-2" onClick={onNav}><Logo /></a>
      <div className="mt-5"><OrgSwitcher /></div>
      <nav className="mt-5 space-y-0.5">{NAV.map(n => <NavLink key={n.href} {...n} path={path} onClick={onNav} />)}</nav>
      {me?.can.manage_jobs && <>
        <div className="mx-3 mb-1.5 mt-4 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Hiring</div>
        <nav className="space-y-0.5">{NAV_HIRING.filter(n => n.href !== '/app/audit' || me.can.manage_team).map(n => <NavLink key={n.href} {...n} path={path} onClick={onNav} />)}</nav>
      </>}
      <div className="mx-3 my-4 h-px bg-slate-100 dark:bg-ink-800" />
      <nav className="space-y-0.5">
        {NAV2.filter(n => n.href !== '/app/settings' || me?.can.manage_team).map(n => <NavLink key={n.href} {...n} path={path} onClick={onNav} />)}
        {me?.platform_admin && <NavLink href="/admin" label="Platform admin" icon={Shield} path={path} onClick={onNav} />}
      </nav>
      <div className="mt-auto space-y-3 pt-6">
        {h?.detail && me?.platform_admin && (h.mock || problems.length > 0) && (
          <a href="/admin" onClick={onNav} className="block rounded-xl bg-slate-50 p-3 text-xs ring-1 ring-slate-200/70 hover:bg-slate-100 dark:bg-ink-850 dark:ring-ink-700 dark:hover:bg-ink-800">
            <div className="flex items-center justify-between"><span className="font-semibold text-slate-700 dark:text-slate-200">Server</span>
              {problems.length ? <Badge tone="danger">Needs setup</Badge> : <Badge tone="warning">Demo AI</Badge>}</div>
            <p className="mt-1 leading-relaxed text-slate-500 dark:text-slate-400">{problems.length ? `${problems.length} setting${problems.length > 1 ? 's' : ''} to fix` : 'AI is simulated (LLM_MOCK=1).'}</p>
          </a>
        )}
        {me && (
          <div className="flex items-center gap-2.5 rounded-xl px-2 py-1.5">
            <Avatar name={me.user.name || me.user.email} size="sm" />
            <a href="/app/account" onClick={onNav} className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{me.user.name || me.user.email}</span><span className="block truncate text-xs text-slate-500 dark:text-slate-400">{me.user.email}</span></a>
            <button onClick={confirmSignOut} aria-label="Sign out" title="Sign out" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-ink-800 dark:hover:text-white"><LogOut className="size-4" /></button>
          </div>
        )}
      </div>
    </div>
  )
}

function tourSteps(me: NonNullable<ReturnType<typeof useSession>['me']>): TourStep[] {
  const hr = me.can.manage_jobs, first = (me.user.name || '').split(' ')[0]
  const s: TourStep[] = [
    { title: `Welcome${first ? `, ${first}` : ''}!`, body: hr ? 'TalentLoop takes you from a job post to a shortlist and interviews. This 1-minute tour shows where everything is. You can skip it and restart it any time from Your account.'
      : `You're a ${me.role_label} at ${me.org?.name}. This short tour shows the parts you'll use.` },
    { target: 'nav-dashboard', title: 'Your dashboard', body: 'Open jobs, new applicants, interviews to review and anything that needs you today.' },
    { target: 'nav-jobs', title: 'Jobs', body: hr ? 'Create a job here: paste or import a JD, or let AI write it. Each job has its own applicants board, hiring flow and team.' : 'The jobs you have access to, with their applicants.' },
    { target: 'nav-candidates', title: 'Candidates', body: hr ? 'Every resume in one place. Upload many at once; we read them and match each person to your jobs.' : 'Profiles, resumes and where each person applied.' },
  ]
  if (hr) s.push(
    { target: 'nav-matches', title: 'Match center', body: 'The best candidates for every open job, ranked side by side, with AI reports and a full match report for each.' },
    { target: 'nav-interviews', title: 'AI interviews', body: 'Send a voice interview the AI runs for you, with proctoring, a transcript, a recording and a scored report.' },
    { target: 'nav-drives', title: 'Campus drives', body: 'One registration link and QR code per college, for one or more roles.' },
    { target: 'nav-team', title: 'Your team', body: 'Invite HR colleagues and hiring managers. Managers only see the jobs you assign them.' })
  else s.push({ target: 'nav-my-interviews', title: 'My interviews', body: 'Interviews booked with you, with the candidate details and a place for your feedback.' })
  s.push({ title: "You're all set", body: hr ? 'Start with Jobs > New job. Tip: everything has a Back button and nothing is sent to candidates without you choosing to.' : 'Ask your HR team if you need access to more jobs.' })
  return s
}

export function Shell({ children }: { children: ReactNode }) {
  const { path } = useLocation()
  const [open, setOpen] = useState(false)
  const { me } = useSession()
  return (
    <>
      {me?.user.id && me.org && <Tour uid={me.user.id} steps={tourSteps(me)} auto={path === '/app'} />}
      <aside className="no-print fixed inset-y-0 left-0 z-30 hidden w-64 overflow-y-auto border-r border-slate-200/80 bg-white px-4 py-5 dark:border-ink-700 dark:bg-ink-900 lg:block">
        <Sidebar path={path} />
      </aside>
      <header className="no-print sticky top-0 z-30 flex items-center justify-between border-b border-slate-200/80 bg-white/90 px-4 py-3 backdrop-blur dark:border-ink-700 dark:bg-ink-900/90 lg:hidden">
        <a href="/app"><Logo /></a>
        <button aria-label="Open menu" onClick={() => setOpen(true)} className="grid size-10 place-items-center rounded-xl text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-ink-800"><Menu className="size-5" /></button>
      </header>
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-ink-950/60 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85vw] overflow-y-auto bg-white px-4 py-5 shadow-2xl dark:bg-ink-900 animate-rise">
            <button aria-label="Close menu" onClick={() => setOpen(false)} className="absolute right-3 top-4 rounded-lg p-2 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-ink-800"><X className="size-4" /></button>
            <Sidebar path={path} onNav={() => setOpen(false)} />
          </div>
        </div>
      )}
      <main className="lg:pl-64"><div className="mx-auto max-w-7xl px-4 py-6 sm:px-8 sm:py-8">{children}</div></main>
    </>
  )
}
