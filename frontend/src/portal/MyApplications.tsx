// /me: candidates sign in with their email and a one-time code, and see every application they made with that email:
// stage, the current step, interview times, and links to take a step or change an interview time.
import { CalendarCheck, LogOut, Mail } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Alert, Badge, Button, Card, Field, Input } from '../components/ui'
import { fullWhen } from '../components/SlotPicker'
import { when } from '../lib/format'
import { ask as confirm } from '../components/dialogs'
import { Frame, PageState, getJSON, send, type Brand } from './common'

interface Step { name: string; type: string; status: string; status_label: string; link: string | null; deadline_at: number | null; booking: { starts_at: number; ends_at: number; interviewer: string } | null }
interface DriveRow { college: string; org: Brand; roles: string[]; results_link: string; register_link: string; opens_at: number | null; registered: number }
interface App { id: string; org: Brand; job: string; stage: string; stage_label: string; applied_at: number; status_link: string; step: Step | null }
const ACTION: Record<string, string> = { human_interview: 'Pick an interview time', ai_interview: 'Start or schedule the interview', test: 'Take the test', video_intro: 'Record your introduction',
  role_task: 'Do the task', practical_task: 'Submit your work', live_task: 'Start the live task', reference_check: 'Add your referees' }

export default function MyApplications() {
  const [state, setState] = useState<{ email: string; applications: App[]; drives?: DriveRow[] } | null | 'out'>(null)
  const [email, setEmail] = useState(''), [code, setCode] = useState(''), [sent, setSent] = useState(false), [busy, setBusy] = useState(false), [err, setErr] = useState('')
  const load = () => getJSON<{ email: string; applications: App[]; drives?: DriveRow[] }>('/api/me').then(setState).catch(() => setState('out'))
  useEffect(() => { document.title = 'My applications'; load() }, [])
  async function ask(e: FormEvent) {
    e.preventDefault(); setBusy(true); setErr('')
    try { await send('/api/me/code', { email }); setSent(true) } catch (x: any) { setErr(x.message) }
    setBusy(false)
  }
  async function verify(e: FormEvent) {
    e.preventDefault(); setBusy(true); setErr('')
    try { await send('/api/me/verify', { email, code }); await load() } catch (x: any) { setErr(x.message) }
    setBusy(false)
  }
  if (state === null) return <PageState loading />
  if (state === 'out') return (
    <Frame>
      <h1 className="text-2xl font-semibold tracking-tight">Your applications</h1>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">Candidates: sign in with the email you applied with. Placement officers: use the email the company has on file for your campus drive. We'll send you a 6-digit code; no password needed.</p>
      <Card className="mt-5 p-5">
        {!sent ? <form onSubmit={ask} className="space-y-3">
          <Field label="Email" htmlFor="me-email"><Input id="me-email" type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} /></Field>
          {err && <Alert tone="danger">{err}</Alert>}
          <Button type="submit" variant="primary" icon={<Mail />} loading={busy} disabled={!/^\S+@\S+\.\S+$/.test(email)}>Email me a code</Button>
        </form> : <form onSubmit={verify} className="space-y-3">
          <Alert tone="info">If {email} has applications with us, a code is on its way. Check spam too. It works for about 10 minutes.</Alert>
          <Field label="6-digit code" htmlFor="me-code"><Input id="me-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))} /></Field>
          {err && <Alert tone="danger">{err}</Alert>}
          <div className="flex flex-wrap gap-2"><Button type="submit" variant="primary" loading={busy} disabled={code.length !== 6}>Sign in</Button>
            <Button onClick={() => { setSent(false); setCode(''); setErr('') }}>Use another email</Button></div>
        </form>}
      </Card>
    </Frame>
  )
  return (
    <Frame>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div><h1 className="text-2xl font-semibold tracking-tight">{state.applications.length || !state.drives?.length ? 'Your applications' : 'Your campus drives'}</h1><p className="text-sm text-slate-500 dark:text-slate-400">{state.email}</p></div>
        <Button size="sm" variant="ghost" icon={<LogOut />} onClick={async () => { if (!await confirm('Sign out? You will need a new code from your email to sign in again.', { confirm: 'Sign out', danger: false })) return; await send('/api/me/logout'); setState('out'); setSent(false); setCode('') }}>Sign out</Button>
      </div>
      {!!state.drives?.length && <div className="mt-5 space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Campus drives you coordinate</h2>
        {state.drives.map(d => (
          <Card key={d.results_link} className="flex flex-wrap items-center justify-between gap-3 p-5">
            <div className="min-w-0"><div className="font-semibold">{d.college}</div><div className="text-sm text-slate-500 dark:text-slate-400">{d.org.name} · {d.roles.join(', ')} · {d.registered} registered</div></div>
            <div className="flex flex-wrap gap-2"><Button size="sm" variant="primary" href={d.results_link}>Live results</Button><Button size="sm" href={d.register_link}>Student registration page</Button></div>
          </Card>))}
      </div>}
      {!state.applications.length && !state.drives?.length && <Card className="mt-5 p-6 text-sm text-slate-600 dark:text-slate-300">No applications with this email yet.</Card>}
      <div className="mt-5 space-y-3">{state.applications.map(a => (
        <Card key={a.id} className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0"><div className="font-semibold">{a.job}</div><div className="text-sm text-slate-500 dark:text-slate-400">{a.org.name} · applied {when(a.applied_at)}</div></div>
            <Badge tone={a.stage === 'rejected' ? 'danger' : ['offer', 'hired'].includes(a.stage) ? 'success' : 'brand'}>{a.stage_label}</Badge>
          </div>
          {a.step && <div className="mt-3 rounded-xl bg-slate-50 p-3 text-sm dark:bg-ink-850">
            <div className="text-xs text-slate-500 dark:text-slate-400">Now: {a.step.name} · {a.step.status_label}</div>
            {a.step.booking && <div className="mt-1 flex items-center gap-1.5 font-semibold"><CalendarCheck className="size-4 text-emerald-600 dark:text-emerald-400" />{fullWhen(a.step.booking.starts_at)}{a.step.booking.interviewer ? <span className="font-normal text-slate-500 dark:text-slate-400"> with {a.step.booking.interviewer}</span> : null}</div>}
            {!a.step.booking && a.step.deadline_at && <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">Please complete by {when(a.step.deadline_at)}</div>}
          </div>}
          <div className="mt-3 flex flex-wrap gap-2">
            {a.step?.link && <Button size="sm" variant="primary" href={a.step.link}>{a.step.booking ? 'Details, change or cancel' : ACTION[a.step.type] || 'Open'}</Button>}
            {a.status_link && <Button size="sm" href={a.status_link}>Status and help</Button>}
          </div>
        </Card>))}</div>
    </Frame>
  )
}
