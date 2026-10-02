import { Suspense, lazy, useEffect, type ComponentType, type ReactNode } from 'react'
import { Shell } from './app/Shell'
import { Button, Logo, Toaster, TooltipProvider } from './components/ui'
import { Loading, PageSkeleton } from './components/kit'
import { DialogHost } from './components/dialogs'
import { setUnauthorizedHandler } from './lib/api'
import { match, navigate, useLocation } from './lib/router'
import { SessionProvider, useSession } from './lib/session'
import { Invite, Login, Signup } from './site/Auth'

// Every page is its own chunk: the careers page or a candidate link never downloads the HR workspace.
function named<T extends Record<string, unknown>>(load: () => Promise<T>, key: keyof T) {
  return lazy(() => load().then(m => ({ default: m[key] as ComponentType<any> })))
}
const Admin = lazy(() => import('./admin/Admin'))
const CandidateDetail = lazy(() => import('./app/CandidateDetail'))
const Candidates = lazy(() => import('./app/Candidates'))
const Dashboard = lazy(() => import('./app/Dashboard'))
const Drives = lazy(() => import('./app/Drives'))
const MyInterviews = named(() => import('./app/Inbox'), 'MyInterviews'), Outbox = named(() => import('./app/Inbox'), 'Outbox'), Requests = named(() => import('./app/Inbox'), 'Requests')
const QuestionBank = lazy(() => import('./app/QuestionBank'))
const AuditLog = named(() => import('./app/Reports'), 'AuditLog'), Reports = named(() => import('./app/Reports'), 'Reports')
const InterviewReport = lazy(() => import('./app/InterviewReport'))
const Interviews = lazy(() => import('./app/Interviews'))
const JobDetail = lazy(() => import('./app/JobDetail'))
const JobEditor = lazy(() => import('./app/JobEditor'))
const MatchReport = lazy(() => import('./app/MatchReport'))
const Jobs = lazy(() => import('./app/Jobs'))
const MatchCenter = lazy(() => import('./app/MatchCenter'))
const NewInterview = lazy(() => import('./app/NewInterview'))
const Settings = lazy(() => import('./app/Settings'))
const Account = lazy(() => import('./app/Account'))
const Team = lazy(() => import('./app/Team'))
const CareersPage = named(() => import('./site/Careers'), 'CareersPage'), PublicJobPage = named(() => import('./site/Careers'), 'PublicJobPage')
const Landing = lazy(() => import('./site/Landing'))
const RoundPage = lazy(() => import('./portal/RoundPage'))
const DecidePage = named(() => import('./portal/Pages'), 'DecidePage'), RefereePage = named(() => import('./portal/Pages'), 'RefereePage'), DrivePage = named(() => import('./portal/Pages'), 'DrivePage'), FeedbackPage = named(() => import('./portal/Pages'), 'FeedbackPage'), ResultsPage = named(() => import('./portal/Pages'), 'ResultsPage'), StatusPage = named(() => import('./portal/Pages'), 'StatusPage')

type Need = 'manage_jobs' | 'manage_team'
type Route = [string, (p: Record<string, string>) => ReactNode, string?, Need?]
const APP: Route[] = [
  ['/app', () => <Dashboard />, 'Dashboard'],
  ['/app/jobs', () => <Jobs />, 'Jobs'],
  ['/app/jobs/new', () => <JobEditor />, 'New job', 'manage_jobs'],
  ['/app/jobs/:id', p => <JobDetail key={p.id} id={p.id!} />, 'Job'],
  ['/app/jobs/:id/edit', p => <JobEditor key={p.id} id={p.id} />, 'Edit job'],
  ['/app/jobs/:id/match/:cid', p => <MatchReport key={p.id + p.cid} jobId={p.id!} candId={p.cid!} />, 'Match report'],
  ['/app/candidates', () => <Candidates />, 'Candidates'],
  ['/app/candidates/:id', p => <CandidateDetail key={p.id} id={p.id!} />, 'Candidate'],
  ['/app/matches', () => <MatchCenter />, 'Match center'],
  ['/app/interviews', () => <Interviews />, 'AI interviews'],
  ['/app/interviews/new', () => <NewInterview />, 'New interview'],
  ['/app/interviews/:id', p => <InterviewReport key={p.id} id={p.id!} />, 'Interview report'],
  ['/app/questions', () => <QuestionBank />, 'Question bank', 'manage_jobs'],
  ['/app/drives', () => <Drives />, 'Campus drives', 'manage_jobs'],
  ['/app/requests', () => <Requests />, 'Candidate requests', 'manage_jobs'],
  ['/app/outbox', () => <Outbox />, 'Outbox', 'manage_jobs'],
  ['/app/my-interviews', () => <MyInterviews />, 'My interviews'],
  ['/app/reports', () => <Reports />, 'Reports', 'manage_jobs'],
  ['/app/audit', () => <AuditLog />, 'Audit log', 'manage_team'],
  ['/app/team', () => <Team />, 'Team'],
  ['/app/settings', () => <Settings />, 'Settings', 'manage_team'],
  ['/app/account', () => <Account />, 'Your account'],
  ['/admin', () => <Admin />, 'Platform admin'],
]

function find(routes: Route[], path: string) {
  for (const [pat, render, title, need] of routes) { const p = match(pat, path); if (p) return { node: render(p), title, need } }
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
  if (hit?.need && !me.can[hit.need]) return <Shell><NoAccess /></Shell>
  return <Shell><Suspense fallback={<PageSkeleton />}>{hit ? hit.node : <NotFound />}</Suspense></Shell>
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
function NoAccess() {
  return <div className="py-24 text-center"><h1 className="text-xl font-semibold">Not available for your role</h1><p className="mt-2 text-sm text-slate-500">Ask an owner or HR if you need access to this page.</p><Button className="mt-5" href="/app">Go to dashboard</Button></div>
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
  if ((p = match('/r/:token', path))) return <RoundPage token={p.token!} />
  if ((p = match('/status/:token', path))) return <StatusPage token={p.token!} />
  if ((p = match('/decide/:token', path))) return <DecidePage token={p.token!} />
  if ((p = match('/ref/:token', path))) return <RefereePage token={p.token!} />
  if ((p = match('/feedback/:token', path))) return <FeedbackPage token={p.token!} />
  if ((p = match('/drive/:code', path))) return <DrivePage code={p.code!} />
  if ((p = match('/results/:code', path))) return <ResultsPage code={p.code!} />
  if (path === '/' || path === '') return <Landing />
  return <div className="min-h-screen"><NotFound /></div>
}

export default function App() {
  return <SessionProvider><TooltipProvider><Suspense fallback={<Loading className="min-h-screen" />}><Routes /></Suspense><Toaster /><DialogHost /></TooltipProvider></SessionProvider>
}
