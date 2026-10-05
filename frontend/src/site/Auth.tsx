import { ArrowRight, Building2, KeyRound, Mail, UserRound } from 'lucide-react'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Alert, Button, Field, Input, Logo } from '../components/ui'
import { Loading } from '../components/kit'
import { api } from '../lib/api'
import { navigate, useLocation } from '../lib/router'
import { useSession, type Me } from '../lib/session'

function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="flex flex-col px-4 py-8 sm:px-10">
        <a href="/"><Logo /></a>
        <div className="mx-auto my-auto w-full max-w-sm py-10">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1.5 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
          <div className="mt-7">{children}</div>
          {footer && <div className="mt-6 text-center text-sm text-slate-500 dark:text-slate-400">{footer}</div>}
        </div>
      </div>
      <div className="relative hidden overflow-hidden bg-gradient-to-br from-brand-600 via-brand-700 to-violet-700 lg:block">
        <div className="absolute inset-0 bg-[radial-gradient(40rem_25rem_at_80%_10%,rgba(255,255,255,.18),transparent)]" />
        <div className="relative flex h-full flex-col justify-end p-12 text-white">
          <p className="max-w-md text-2xl font-medium leading-snug">From a thousand resumes to a shortlist of five, each with a written reason.</p>
          <ul className="mt-6 space-y-2 text-sm text-brand-100">
            <li>• Detailed job descriptions and a careers page</li>
            <li>• Instant ranking of every resume for every job</li>
            <li>• AI match reports and AI first-round interviews</li>
          </ul>
        </div>
      </div>
    </div>
  )
}

const nextUrl = (q: URLSearchParams) => { const n = q.get('next') || '/app'; return n.startsWith('/') && !n.startsWith('//') ? n : '/app' }

export function Login() {
  const { query } = useLocation()
  const { setMe, me } = useSession()
  const [email, setEmail] = useState(''), [pw, setPw] = useState(''), [err, setErr] = useState(''), [busy, setBusy] = useState(false)
  useEffect(() => { if (me) navigate(nextUrl(query), { replace: true }) }, [me])     // eslint-disable-line react-hooks/exhaustive-deps
  async function submit(e: FormEvent) {
    e.preventDefault(); setErr(''); setBusy(true)
    try { const m = await api<Me>('/api/auth/login', { json: { email, password: pw }, quiet401: true }); setMe(m); navigate(m.org ? nextUrl(query) : m.platform_admin ? '/admin' : '/app', { replace: true }) }
    catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  return (
    <AuthLayout title="Welcome back" subtitle="Sign in to your hiring workspace." footer={<>New to TalentLoop? <a href="/signup" className="font-semibold text-brand-600 hover:underline dark:text-brand-300">Create a workspace</a></>}>
      <form onSubmit={submit} className="space-y-4">
        {err && <Alert tone="danger">{err}</Alert>}
        <Field label="Work email" htmlFor="email"><Input id="email" type="email" autoComplete="email" required autoFocus value={email} onChange={e => setEmail(e.target.value)} /></Field>
        <Field label="Password" htmlFor="password"><Input id="password" type="password" autoComplete="current-password" required value={pw} onChange={e => setPw(e.target.value)} /></Field>
        <Button variant="primary" className="w-full" type="submit" loading={busy} icon={<KeyRound />}>Sign in</Button>
        <p className="text-center text-sm"><a href={`/forgot${email ? `?email=${encodeURIComponent(email)}` : ''}`} className="font-medium text-brand-600 hover:underline dark:text-brand-300">Forgot your password?</a></p>
      </form>
    </AuthLayout>
  )
}

export function Forgot() {
  const { query } = useLocation()
  const [email, setEmail] = useState(query.get('email') || ''), [code, setCode] = useState(''), [pw, setPw] = useState('')
  const [step, setStep] = useState<'ask' | 'reset' | 'done'>('ask'), [err, setErr] = useState(''), [busy, setBusy] = useState(false)
  async function ask(e: FormEvent) {
    e.preventDefault(); setErr(''); setBusy(true)
    try { await api('/api/auth/forgot', { json: { email }, quiet401: true }); setStep('reset') } catch (x: any) { setErr(x.message) }
    setBusy(false)
  }
  async function reset(e: FormEvent) {
    e.preventDefault(); setErr(''); setBusy(true)
    try { await api('/api/auth/reset', { json: { email, code, password: pw }, quiet401: true }); setStep('done') } catch (x: any) { setErr(x.message) }
    setBusy(false)
  }
  return (
    <AuthLayout title="Reset your password" subtitle={step === 'ask' ? "We'll email you a 6-digit code." : step === 'reset' ? `If ${email} has an account, a code is on its way. Check spam too.` : undefined}
      footer={<a href="/login" className="font-semibold text-brand-600 hover:underline dark:text-brand-300">Back to sign in</a>}>
      {step === 'done' ? <Alert tone="success" title="Password changed">You were signed out on every device. <a className="font-semibold underline" href={`/login`}>Sign in</a> with the new password.</Alert>
        : step === 'ask' ? <form onSubmit={ask} className="space-y-4">
          {err && <Alert tone="danger">{err}</Alert>}
          <Field label="Email" htmlFor="f-email"><Input id="f-email" type="email" autoComplete="email" required autoFocus value={email} onChange={e => setEmail(e.target.value)} /></Field>
          <Button variant="primary" className="w-full" type="submit" loading={busy} icon={<Mail />}>Email me a code</Button>
        </form>
        : <form onSubmit={reset} className="space-y-4">
          {err && <Alert tone="danger">{err}</Alert>}
          <Field label="6-digit code" htmlFor="f-code"><Input id="f-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))} /></Field>
          <Field label="New password" htmlFor="f-pw" hint="At least 8 characters."><Input id="f-pw" type="password" autoComplete="new-password" required value={pw} onChange={e => setPw(e.target.value)} /></Field>
          <Button variant="primary" className="w-full" type="submit" loading={busy} disabled={code.length !== 6 || pw.length < 8} icon={<KeyRound />}>Set new password</Button>
          <button type="button" className="w-full text-center text-sm text-slate-500 hover:underline dark:text-slate-400" onClick={() => { setStep('ask'); setCode('') }}>Send a new code</button>
        </form>}
    </AuthLayout>
  )
}

export function Signup() {
  const { setMe, me } = useSession()
  const [f, setF] = useState({ name: '', email: '', company: '', password: '' })
  const [err, setErr] = useState(''), [busy, setBusy] = useState(false)
  useEffect(() => { if (me?.org) navigate('/app', { replace: true }) }, [me])
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF(v => ({ ...v, [k]: e.target.value }))
  async function submit(e: FormEvent) {
    e.preventDefault(); setErr(''); setBusy(true)
    try { const m = await api<Me>('/api/auth/signup', { json: f, quiet401: true }); setMe(m); navigate('/app?welcome=1', { replace: true }) }
    catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  return (
    <AuthLayout title="Create your workspace" subtitle="You'll be the owner. Invite HR and hiring managers next."
      footer={<>Already have an account? <a href="/login" className="font-semibold text-brand-600 hover:underline dark:text-brand-300">Sign in</a></>}>
      <form onSubmit={submit} className="space-y-4">
        {err && <Alert tone="danger">{err}</Alert>}
        <Field label="Your name" htmlFor="name"><Input id="name" required autoComplete="name" value={f.name} onChange={set('name')} /></Field>
        <Field label="Work email" htmlFor="email"><Input id="email" type="email" required autoComplete="email" value={f.email} onChange={set('email')} /></Field>
        <Field label="Company name" htmlFor="company" hint="Used for your careers page address. You can change it later."><Input id="company" required autoComplete="organization" value={f.company} onChange={set('company')} /></Field>
        <Field label="Password" htmlFor="password" hint="At least 8 characters."><Input id="password" type="password" required minLength={8} autoComplete="new-password" value={f.password} onChange={set('password')} /></Field>
        <Button variant="primary" className="w-full" type="submit" loading={busy} icon={<ArrowRight />}>Create workspace</Button>
        <p className="text-center text-xs text-slate-500 dark:text-slate-400">Joining an existing company? Ask its admin for an invite link.</p>
      </form>
    </AuthLayout>
  )
}

export function Invite({ token }: { token: string }) {
  const { setMe } = useSession()
  const [info, setInfo] = useState<{ org: string; email: string; role_label: string; title: string; has_account: boolean } | null>(null)
  const [err, setErr] = useState(''), [loadErr, setLoadErr] = useState('')
  const [name, setName] = useState(''), [pw, setPw] = useState(''), [busy, setBusy] = useState(false)
  useEffect(() => { api(`/api/invites/${token}`, { quiet401: true }).then(setInfo).catch(e => setLoadErr(e.message)) }, [token])
  async function submit(e: FormEvent) {
    e.preventDefault(); setErr(''); setBusy(true)
    try { const m = await api<Me>(`/api/invites/${token}/accept`, { json: { name, password: pw }, quiet401: true }); setMe(m); navigate('/app', { replace: true }) }
    catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  if (loadErr) return <AuthLayout title="Invite link problem"><Alert tone="danger">{loadErr}</Alert><Button className="mt-4" href="/login">Go to sign in</Button></AuthLayout>
  if (!info) return <Loading className="min-h-screen" />
  return (
    <AuthLayout title={`Join ${info.org}`} subtitle={<>You've been invited as <b>{info.role_label}</b>{info.title ? ` (${info.title})` : ''}.</>}>
      <form onSubmit={submit} className="space-y-4">
        {err && <Alert tone="danger">{err}</Alert>}
        <Field label="Email" htmlFor="email"><div className="relative"><Mail className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-500 dark:text-slate-400" /><Input id="email" className="pl-9" value={info.email} disabled /></div></Field>
        {!info.has_account && <Field label="Your name" htmlFor="name"><div className="relative"><UserRound className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-500 dark:text-slate-400" /><Input id="name" className="pl-9" required value={name} onChange={e => setName(e.target.value)} /></div></Field>}
        <Field label={info.has_account ? 'Your existing password' : 'Choose a password'} htmlFor="password" hint={info.has_account ? 'You already have a TalentLoop account; this company is added to it.' : 'At least 8 characters.'}>
          <Input id="password" type="password" required minLength={8} value={pw} onChange={e => setPw(e.target.value)} autoComplete={info.has_account ? 'current-password' : 'new-password'} /></Field>
        <Button variant="primary" className="w-full" type="submit" loading={busy} icon={<Building2 />}>Join {info.org}</Button>
      </form>
    </AuthLayout>
  )
}
