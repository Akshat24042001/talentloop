import { ArrowRight, BadgeCheck, BookUser, Briefcase, Copy, FileText, Gauge, Globe, Lock, MonitorPlay, Scale, ScanSearch, ShieldCheck, Sparkles, Users, Video, Wand2 } from 'lucide-react'
import { Button, Logo } from '../components/ui'
import { useSession } from '../lib/session'

const FEATURES = [
  { icon: FileText, title: 'Job descriptions HR actually finishes', body: 'A complete JD form (pay, location, screening questions, must-haves) where only the essentials are required. One click gives you a clean PDF and a careers page post.' },
  { icon: Users, title: 'Hand a JD to the right manager', body: 'HR creates the role and gives the sales or tech manager edit or review rights to just that job. Everyone else sees only what they should.' },
  { icon: ScanSearch, title: 'Find the best 5 in a sea of resumes', body: 'Every resume is scored against every open job in seconds with skills, experience, location and notice period. No AI tokens spent.' },
  { icon: Sparkles, title: 'AI reports only where they count', body: 'The AI writes a match report for each job’s shortlist only, cached, so thousands of resumes cost cents instead of dollars.' },
  { icon: Video, title: 'AI first-round interviews', body: 'Send a link. A voice interviewer asks your questions, probes the resume, and watches for tab switching and second screens.' },
  { icon: MonitorPlay, title: 'Live tasks with screen sharing', body: 'Candidates code, design or build a sheet while sharing their screen. AI reviews the result and how they got there, against your rubric.' },
  { icon: BookUser, title: 'Reference checks that catch fakes', body: 'Referees answer a 5-minute form, no sign-in. AI summarises with quotes; references from the candidate’s own network are flagged.' },
  { icon: Copy, title: 'Spot copied answers across candidates', body: 'Shared wording in interviews and tasks, the same wrong test options, one phone on two records: found and shown with the evidence.' },
  { icon: Scale, title: 'Check the AI against your team', body: 'See how often your interviewers agree with the AI on every round, and where they disagree most, before you trust a pass mark.' },
  { icon: Globe, title: 'A careers page in minutes', body: 'Candidates apply with a resume or build one in the form. Screening questions screen out the obvious mismatches automatically.' },
]

export default function Landing() {
  const { me } = useSession()
  return (
    <div className="min-h-screen bg-white text-slate-900 dark:bg-ink-950 dark:text-slate-100">
      <header className="sticky top-0 z-30 border-b border-slate-100 bg-white/85 backdrop-blur dark:border-ink-800 dark:bg-ink-950/85">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <a href="/"><Logo /></a>
          <nav className="flex items-center gap-2">
            <a href="#features" className="hidden rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white sm:block">Features</a>
            <a href="#how" className="hidden rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white sm:block">How it works</a>
            {me ? <Button variant="primary" size="sm" href="/app">Open workspace</Button>
              : <><Button variant="ghost" size="sm" href="/login">Sign in</Button><Button variant="primary" size="sm" href="/signup">Start free</Button></>}
          </nav>
        </div>
      </header>

      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 -z-0 bg-[radial-gradient(60rem_30rem_at_50%_-10%,rgba(59,99,243,.16),transparent),radial-gradient(40rem_20rem_at_90%_10%,rgba(139,92,246,.12),transparent)]" />
        <div className="relative mx-auto max-w-6xl px-4 pb-16 pt-16 text-center sm:px-6 sm:pt-24">
          <span className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700 ring-1 ring-brand-100 dark:bg-brand-500/15 dark:text-brand-200 dark:ring-brand-500/25"><Sparkles className="size-3.5" />Your AI recruiting teammate</span>
          <h1 className="mx-auto mt-5 max-w-4xl text-4xl font-semibold tracking-tight sm:text-6xl">From job description to <span className="bg-gradient-to-r from-brand-600 to-violet-600 bg-clip-text text-transparent">shortlist</span>, without the busywork</h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg text-slate-600 dark:text-slate-300">Write the JD, open a careers page, drop in thousands of resumes. TalentLoop ranks every candidate for every job, writes AI match reports for the top few, and runs the first interview for you.</p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Button variant="primary" size="lg" href={me ? '/app' : '/signup'} icon={<ArrowRight />}>{me ? 'Open your workspace' : 'Create your free workspace'}</Button>
            <Button size="lg" href="#how">See how it works</Button>
          </div>
          <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">Free while in launch. No credit card. Sample jobs and resumes in one click.</p>
          <ProductShot />
        </div>
      </section>

      <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-16 sm:px-6">
        <h2 className="text-center text-3xl font-semibold tracking-tight">Everything a small hiring team needs</h2>
        <p className="mx-auto mt-3 max-w-2xl text-center text-slate-600 dark:text-slate-300">Built the way HR works: a recruiter owns the process, managers own the details of their roles, and the AI does the reading.</p>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(f => (
            <div key={f.title} className="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-[0_1px_2px_rgba(16,24,40,.04)] dark:border-ink-700 dark:bg-ink-900">
              <span className="grid size-10 place-items-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300"><f.icon className="size-5" /></span>
              <h3 className="mt-4 font-semibold">{f.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-600 dark:text-slate-400">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="how" className="scroll-mt-20 border-y border-slate-100 bg-slate-50/70 py-16 dark:border-ink-800 dark:bg-ink-900/50">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <h2 className="text-center text-3xl font-semibold tracking-tight">How it works</h2>
          <div className="mt-10 grid gap-6 md:grid-cols-4">
            {[[Briefcase, 'Create the job', 'Fill the essentials, let the AI draft the rest, assign the hiring manager.'],
              [Users, 'Collect candidates', 'Careers page applications, bulk resume upload, and a talent pool.'],
              [Gauge, 'Get the shortlist', 'Instant keyword and skills ranking, then AI reports for the top 3 to 10.'],
              [Video, 'Interview with AI', 'One link per candidate. Scored report with integrity signals.']].map(([I, t, b], i) => {
              const Icon = I as typeof Briefcase
              return (
                <div key={t as string} className="relative">
                  <span className="tabular text-xs font-bold text-brand-600 dark:text-brand-300">STEP {i + 1}</span>
                  <div className="mt-2 flex items-center gap-2"><Icon className="size-5 text-slate-500 dark:text-slate-400" /><h3 className="font-semibold">{t as string}</h3></div>
                  <p className="mt-1.5 text-sm text-slate-600 dark:text-slate-400">{b as string}</p>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div className="grid gap-4 md:grid-cols-3">
          {[[Lock, 'Private by default', 'Each company’s data is separate. Roles decide who sees which job and candidate.'],
            [ShieldCheck, 'Fair by design', 'Match reports judge only resume evidence and never infer age, gender or background.'],
            [BadgeCheck, 'You stay in control', 'AI suggests. People decide. Every change to a job is in its activity log.']].map(([I, t, b]) => {
            const Icon = I as typeof Lock
            return <div key={t as string} className="flex gap-3"><Icon className="mt-0.5 size-5 shrink-0 text-emerald-600" /><div><h3 className="font-semibold">{t as string}</h3><p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{b as string}</p></div></div>
          })}
        </div>
        <div className="mt-14 overflow-hidden rounded-3xl bg-gradient-to-br from-brand-600 to-violet-600 px-6 py-12 text-center text-white sm:px-12">
          <h2 className="text-3xl font-semibold tracking-tight">Hire your next person faster</h2>
          <p className="mx-auto mt-2 max-w-xl text-brand-100">Set up your workspace in two minutes: add a job, upload resumes and see your shortlist right away.</p>
          <Button size="lg" href={me ? '/app' : '/signup'} className="mt-6 bg-white !text-brand-700 hover:bg-brand-50 dark:bg-white dark:hover:bg-brand-50" icon={<Wand2 />}>{me ? 'Open workspace' : 'Start free'}</Button>
        </div>
      </section>

      <footer className="border-t border-slate-100 py-8 text-center text-xs text-slate-500 dark:border-ink-800 dark:text-slate-400">
        <Logo className="justify-center" compact /> <p className="mt-2">© {new Date().getFullYear()} TalentLoop</p>
      </footer>
    </div>
  )
}

function ProductShot() {
  const rows = [['Anita Sharma', 'Senior Backend Engineer · 6 yrs · Bengaluru', 91, 'Strong'], ['Neha Gupta', 'Backend Developer · 5 yrs · Bengaluru', 84, 'Strong'],
    ['Karan Singh', 'Full-stack Developer · 4 yrs · Bangalore', 72, 'Good'], ['Vikram Rao', 'Java Developer · 3 yrs · Pune', 58, 'Possible']] as const
  return (
    <div className="mx-auto mt-14 max-w-4xl rounded-2xl border border-slate-200 bg-white p-2 text-left shadow-2xl shadow-brand-900/10 dark:border-ink-700 dark:bg-ink-900">
      <div className="rounded-xl bg-slate-50 p-4 dark:bg-ink-850 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><div className="text-xs font-medium text-slate-500">Shortlist · top 4 of 1,284 resumes</div><div className="mt-0.5 text-lg font-semibold">Senior Backend Engineer</div></div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-100 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/20"><Sparkles className="size-3" />4 AI reports · 0.6 s ranking</span>
        </div>
        <div className="mt-4 divide-y divide-slate-200/70 rounded-xl bg-white ring-1 ring-slate-200/70 dark:divide-ink-700 dark:bg-ink-900 dark:ring-ink-700">
          {rows.map(([n, s, sc, v], i) => (
            <div key={n} className="flex items-center gap-3 px-4 py-3">
              <span className="tabular w-5 text-sm font-semibold text-slate-500 dark:text-slate-400">{i + 1}</span>
              <span className="grid size-8 place-items-center rounded-full bg-gradient-to-br from-brand-100 to-violet-100 text-[11px] font-bold text-brand-700">{n.split(' ').map(w => w[0]).join('')}</span>
              <div className="min-w-0 flex-1"><div className="truncate text-sm font-semibold">{n}</div><div className="truncate text-xs text-slate-500">{s}</div></div>
              <span className="hidden rounded-full bg-brand-50 px-2 py-0.5 text-xs font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-200 sm:inline">{v}</span>
              <span className="tabular w-8 text-right text-sm font-bold text-emerald-600">{sc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
