import { useEffect, type ReactNode } from 'react'
import Admin from './admin/Admin'
import CandidateDetail from './app/CandidateDetail'
import Candidates from './app/Candidates'
import Dashboard from './app/Dashboard'
import InterviewReport from './app/InterviewReport'
import Interviews from './app/Interviews'
import JobDetail from './app/JobDetail'
import JobEditor from './app/JobEditor'
import Jobs from './app/Jobs'
import MatchCenter from './app/MatchCenter'
import NewInterview from './app/NewInterview'
import Settings from './app/Settings'
import { Shell } from './app/Shell'
import Team from './app/Team'
import { Button, Logo, Toaster, TooltipProvider } from './components/ui'
import { Loading } from './components/kit'
import { setUnauthorizedHandler } from './lib/api'
import { match, navigate, useLocation } from './lib/router'
import { SessionProvider, useSession } from './lib/session'
import { Invite, Login, Signup } from './site/Auth'
import { CareersPage, PublicJobPage } from './site/Careers'
import Landing from './site/Landing'

type Route = [string, (p: Record<string, string>) => ReactNode, string?]
const APP: Route[] = [
  ['/app', () => <Dashboard />, 'Dashboard'],
  ['/app/jobs', () => <Jobs />, 'Jobs'],
  ['/app/jobs/new', () => <JobEditor />, 'New job'],
  ['/app/jobs/:id', p => <JobDetail key={p.id} id={p.id!} />, 'Job'],
  ['/app/jobs/:id/edit', p => <JobEditor key={p.id} id={p.id} />, 'Edit job'],
  ['/app/candidates', () => <Candidates />, 'Candidates'],
  ['/app/candidates/:id', p => <CandidateDetail key={p.id} id={p.id!} />, 'Candidate'],
  ['/app/matches', () => <MatchCenter />, 'Match center'],
  ['/app/interviews', () => <Interviews />, 'AI interviews'],
  ['/app/interviews/new', () => <NewInterview />, 'New interview'],
  ['/app/interviews/:id', p => <InterviewReport key={p.id} id={p.id!} />, 'Interview report'],
  ['/app/team', () => <Team />, 'Team'],
  ['/app/settings', () => <Settings />, 'Settings'],
  ['/admin', () => <Admin />, 'Platform admin'],
]

function find(routes: Route[], path: string) {
  for (const [pat, render, title] of routes) { const p = match(pat, path); if (p) return { node: render(p), title } }
  return null
}

function Workspace({ path }: { path: string }) {
  const { me } = useSession()
  const hit = find(APP, path)
  useEffect(() => { if (hit?.title) document.title = `${hit.title} · TalentLoop` }, [hit?.title])
  useEffect(() => {
    if (me === null) navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`, { replace: true })
  }, [me])
  if (!me) return <Loading className="min-h-screen" />
  if (!me.org && !(me.platform_admin && path === '/admin')) return <NoCompany />
  if (path === '/admin' && !me.platform_admin) return <Shell><NotFound /></Shell>
  return <Shell>{hit ? hit.node : <NotFound />}</Shell>
}

function NoCompany() {
  return (
    <div className="grid min-h-screen place-items-center p-6 text-center"><div className="max-w-sm">
      <Logo className="justify-center" /><h1 className="mt-6 text-xl font-semibold">You're not part of a company yet</h1>
      <p className="mt-2 text-sm text-slate-500">Ask your company admin for an invite link, or create your own workspace.</p>
      <div className="mt-5 flex justify-center gap-2"><Button href="/signup" variant="primary">Create a workspace</Button><Button onClick={async () => { await fetch('/api/auth/logout', { method: 'POST' }); location.href = '/login' }}>Sign out</Button></div>
    </div></div>
  )
}
function NotFound() {
  return <div className="py-24 text-center"><h1 className="text-xl font-semibold">Page not found</h1><p className="mt-2 text-sm text-slate-500">The link may be old, or you may not have access.</p><Button className="mt-5" href="/app">Go to dashboard</Button></div>
}

function Routes() {
  const { path } = useLocation()
  useEffect(() => { setUnauthorizedHandler(() => { if (path.startsWith('/app') || path.startsWith('/admin')) navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`, { replace: true }) }) }, [path])
  if (path === '/app' || path.startsWith('/app/') || path === '/admin') return <Workspace path={path} />
  let p
  if (path === '/login') return <Login />
  if (path === '/signup') return <Signup />
  if ((p = match('/invite/:token', path))) return <Invite token={p.token!} />
  if ((p = match('/careers/:slug', path))) return <CareersPage slug={p.slug!} />
  if ((p = match('/careers/:slug/jobs/:id', path))) return <PublicJobPage slug={p.slug!} id={p.id!} />
  if (path === '/' || path === '') return <Landing />
  return <div className="min-h-screen"><NotFound /></div>
}

export default function App() {
  return <SessionProvider><TooltipProvider><Routes /><Toaster /></TooltipProvider></SessionProvider>
}
