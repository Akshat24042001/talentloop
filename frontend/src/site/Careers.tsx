import { ArrowLeft, Briefcase, Building2, CircleCheck, Clock, FileUp, MapPin, Plus, Search, Send, Trash2, Wallet } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Alert, Badge, Button, Card, Field, Input, Logo, Select, Textarea, cn } from '../components/ui'
import { Loading, TagInput, Ago } from '../components/kit'
import { ApiError } from '../lib/api'

interface Org { name: string; slug: string; about: string; website: string; logo_url: string; brand_color: string; headline: string; industry: string; size: string; country: string }
interface JobItem { id: string; ref: string; title: string; department: string; location: string; workplace_type: string; employment_type: string; experience: string; salary: string; published_at: number }
interface PublicJob { id: string; org: Org; jd: { title: string; company: string; facts: string[]; sections: { title: string; body?: string; items?: string[] }[]; contact?: string }; questions: { id: string; question: string; kind: string; required: boolean }[]; deadline?: string; required_fields?: string[] }

async function getJSON(url: string) { const r = await fetch(url); const d = await r.json().catch(() => ({})); if (!r.ok) throw new ApiError(d.detail || r.statusText, r.status); return d }
async function postForm(url: string, fd: FormData) { const r = await fetch(url, { method: 'POST', body: fd }); const d = await r.json().catch(() => ({})); if (!r.ok) throw new ApiError(d.detail || r.statusText, r.status); return d }

function OrgHeader({ org, children }: { org: Org; children?: ReactNode }) {
  return (
    <header className="text-white" style={{ background: `linear-gradient(135deg, ${org.brand_color || '#2848e6'}, #111827)` }}>
      <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6 sm:py-14">
        <a href={`/careers/${org.slug}`} className="flex items-center gap-3">
          {org.logo_url ? <img src={org.logo_url} alt="" className="size-11 rounded-xl bg-white object-contain p-1" /> : <span className="grid size-11 place-items-center rounded-xl bg-white/15 text-lg font-bold">{org.name.slice(0, 1)}</span>}
          <span className="text-lg font-semibold">{org.name}</span>
        </a>
        {children}
      </div>
    </header>
  )
}
const Foot = () => <footer className="py-10 text-center text-xs text-slate-500"><a href="/" className="inline-flex items-center gap-2">Hiring with <Logo compact /> TalentLoop</a></footer>
function NotFound({ msg }: { msg: string }) { return <div className="grid min-h-screen place-items-center p-6 text-center"><div><Briefcase className="mx-auto size-8 text-slate-500 dark:text-slate-400" /><h1 className="mt-3 text-lg font-semibold">{msg}</h1><a className="mt-2 inline-block text-sm text-brand-600 dark:text-brand-400 hover:underline" href="/">TalentLoop</a></div></div> }

export function CareersPage({ slug }: { slug: string }) {
  const [d, setD] = useState<{ org: Org; jobs: JobItem[] } | null>(null), [err, setErr] = useState('')
  const [q, setQ] = useState(''), [dep, setDep] = useState(''), [pool, setPool] = useState(false)
  useEffect(() => { getJSON(`/api/public/orgs/${slug}`).then(x => { setD(x); document.title = `Careers at ${x.org.name}` }).catch(e => setErr(e.message)) }, [slug])
  if (err) return <NotFound msg={err} />
  if (!d) return <Loading className="min-h-screen" />
  const deps = [...new Set(d.jobs.map(j => j.department))].sort()
  const jobs = d.jobs.filter(j => (!dep || j.department === dep) && (!q || `${j.title} ${j.location}`.toLowerCase().includes(q.toLowerCase())))
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-ink-950">
      <OrgHeader org={d.org}>
        <h1 className="mt-8 max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">{d.org.headline || `Join ${d.org.name}`}</h1>
        {d.org.about && <p className="mt-3 max-w-2xl text-white/80">{d.org.about}</p>}
        <div className="mt-4 flex flex-wrap gap-3 text-sm text-white/80">{d.org.industry && <span>{d.org.industry}</span>}{d.org.size && <span>· {d.org.size} people</span>}{d.org.country && <span>· {d.org.country}</span>}
          {d.org.website && <a className="underline" href={d.org.website} target="_blank" rel="noopener">· Website</a>}</div>
      </OrgHeader>
      <main className="mx-auto -mt-6 max-w-4xl px-4 sm:px-6">
        <Card className="p-4">
          <div className="grid gap-2 sm:grid-cols-[2fr_1fr]">
            <div className="relative"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-500 dark:text-slate-400" /><Input type="search" aria-label="Search jobs" className="pl-9" placeholder="Search roles or locations" value={q} onChange={e => setQ(e.target.value)} /></div>
            <Select aria-label="Team" value={dep} onChange={e => setDep(e.target.value)}><option value="">All teams</option>{deps.map(x => <option key={x}>{x}</option>)}</Select>
          </div>
        </Card>
        <h2 className="mb-3 mt-8 text-sm font-semibold text-slate-500">{jobs.length} open role{jobs.length === 1 ? '' : 's'}</h2>
        <div className="space-y-3">
          {jobs.map(j => (
            <a key={j.id} href={`/careers/${slug}/jobs/${j.ref}`} className="block rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200/80 transition hover:shadow-md hover:ring-brand-200 dark:bg-ink-900 dark:ring-ink-700">
              <div className="flex flex-wrap items-start justify-between gap-2"><span className="text-lg font-semibold">{j.title}</span><Badge>{j.department}</Badge></div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500 dark:text-slate-400">
                <span className="inline-flex items-center gap-1"><MapPin className="size-4" />{j.location}</span><span className="inline-flex items-center gap-1"><Clock className="size-4" />{j.employment_type}</span>
                {j.experience && <span className="inline-flex items-center gap-1"><Briefcase className="size-4" />{j.experience}</span>}{j.salary && <span className="inline-flex items-center gap-1"><Wallet className="size-4" />{j.salary}</span>}
                <span>· posted <Ago ts={j.published_at} /></span></div>
            </a>))}
          {!jobs.length && <Card className="p-8 text-center text-sm text-slate-500">No open roles match right now.</Card>}
        </div>
        <Card className="mt-8 p-6 text-center">
          <h3 className="font-semibold">Don't see the right role?</h3>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Join our talent pool and we'll reach out when something fits.</p>
          {pool ? <div className="mt-5 text-left"><ApplyForm url={`/api/public/orgs/${slug}/talent-pool`} orgName={d.org.name} questions={[]} talentPool /></div>
            : <Button className="mt-4" onClick={() => setPool(true)} icon={<Plus />}>Join the talent pool</Button>}
        </Card>
      </main>
      <Foot />
    </div>
  )
}

export function PublicJobPage({ slug, id }: { slug: string; id: string }) {
  const [j, setJ] = useState<PublicJob | null>(null), [err, setErr] = useState('')
  const formRef = useRef<HTMLDivElement>(null)
  useEffect(() => { getJSON(`/api/public/orgs/${slug}/jobs/${id}`).then(x => { setJ(x); document.title = `${x.jd.title} at ${x.jd.company}` }).catch(e => setErr(e.message)) }, [slug, id])
  if (err) return <NotFound msg={err} />
  if (!j) return <Loading className="min-h-screen" />
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-ink-950">
      <OrgHeader org={j.org}>
        <a href={`/careers/${slug}`} className="mt-6 inline-flex items-center gap-1 text-sm text-white/80 hover:text-white"><ArrowLeft className="size-4" />All jobs</a>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">{j.jd.title}</h1>
        <div className="mt-3 flex flex-wrap gap-2">{j.jd.facts.map(f => <span key={f} className="rounded-full bg-white/15 px-3 py-1 text-sm">{f}</span>)}</div>
        <Button className="mt-6 bg-white !text-slate-900 hover:bg-slate-100 dark:bg-white dark:hover:bg-slate-100" onClick={() => formRef.current?.scrollIntoView({ behavior: 'smooth' })} icon={<Send />}>Apply now</Button>
      </OrgHeader>
      <main className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
        <Card className="p-6 sm:p-8">
          {j.jd.sections.map(s => (
            <section key={s.title} className="mb-6 last:mb-0">
              <h2 className="text-base font-semibold">{s.title}</h2>
              {s.body && s.body.split('\n').filter(Boolean).map((p, i) => <p key={i} className="mt-2 text-sm leading-relaxed text-slate-700 dark:text-slate-200">{p}</p>)}
              {s.items && <ul className="mt-2 space-y-1.5 text-sm text-slate-700 dark:text-slate-200">{s.items.map((it, i) => <li key={i} className="flex gap-2"><span className="mt-2 size-1.5 shrink-0 rounded-full bg-slate-400" />{it}</li>)}</ul>}
            </section>))}
          {j.jd.contact && <p className="mt-6 text-sm text-slate-500">Questions? {j.jd.contact}</p>}
        </Card>
        <div ref={formRef} className="scroll-mt-6"><Card className="mt-6 p-6 sm:p-8"><h2 className="text-xl font-semibold">Apply for {j.jd.title}</h2>
          {j.deadline && <p className="mt-1 text-sm text-slate-500">Applications close {j.deadline}.</p>}
          <div className="mt-5"><ApplyForm url={`/api/public/orgs/${slug}/jobs/${id}/apply`} orgName={j.jd.company} questions={j.questions} required={j.required_fields} /></div></Card></div>
      </main>
      <Foot />
    </div>
  )
}

type Exp = { title: string; company: string; start: string; end: string; description: string }
const STEPS = ['Resume', 'About you', 'Experience', 'Finish'] as const
const AUTH = ['Citizen / permanent resident', 'Have a valid work permit', 'Will need visa sponsorship']
// The application in four short steps (resume, about you, experience and preferences, questions and review), so
// nobody faces one endless page. Each step checks its own required fields; the server checks everything again.
function ApplyForm({ url, orgName, questions, talentPool, required = [] }: { url: string; orgName: string; questions: PublicJob['questions']; talentPool?: boolean; required?: string[] }) {
  const rq = (k: string) => required.includes(k), star = (label: string, k: string) => rq(k) ? `${label} *` : label
  const [step, setStep] = useState(0)
  const [mode, setMode] = useState<'upload' | 'build'>('upload')
  const [f, setF] = useState({ name: '', email: '', phone: '', location: '', preferred_location: '', headline: '', current_company: '', total_experience_years: '', notice_days: '',
    current_salary: '', expected_salary: '', linkedin: '', portfolio: '', github: '', work_authorization: '', summary: '', cover_letter: '', how_heard: '', referral: '' })
  const [skills, setSkills] = useState<string[]>([]), [langs, setLangs] = useState<string[]>([]), [certs, setCerts] = useState<string[]>([])
  const [exp, setExp] = useState<Exp[]>([{ title: '', company: '', start: '', end: '', description: '' }])
  const [edu, setEdu] = useState({ degree: '', field: '', school: '', year: '', grade: '' })
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [file, setFile] = useState<File | null>(null), [consent, setConsent] = useState(false), [relocate, setRelocate] = useState(false)
  const [busy, setBusy] = useState(false), [err, setErr] = useState(''), [done, setDone] = useState(false), [parsing, setParsing] = useState(false)
  const errRef = useRef<HTMLDivElement>(null), topRef = useRef<HTMLDivElement>(null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF(v => ({ ...v, [k]: e.target.value }))
  async function onFile(x: File) {
    setFile(x); setParsing(true)
    try {
      const fd = new FormData(); fd.append('resume', x)
      const p = await postForm('/api/public/parse-resume', fd)
      setF(v => ({ ...v, name: v.name || p.name || '', email: v.email || p.email || '', phone: v.phone || p.phone || '', location: v.location || p.location || '',
        headline: v.headline || p.headline || '', linkedin: v.linkedin || p.linkedin || '',
        total_experience_years: v.total_experience_years || (p.total_experience_years ?? '').toString(), notice_days: v.notice_days || (p.notice_days ?? '').toString() }))
      if (p.skills?.length && !skills.length) setSkills(p.skills.slice(0, 25))
    } catch { /* prefill is optional */ }
    setParsing(false)
  }
  const show = (m: string) => { setErr(m); requestAnimationFrame(() => errRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })) }
  // What's still missing on a step (labels), so Next can say exactly what to fill in.
  function missing(i: number): string[] {
    const need = (ok: unknown, label: string) => ok ? [] : [label]
    if (i === 0) return mode === 'upload' ? need(file, 'your resume (or switch to "Build my resume")')
      : [...need(f.summary.trim() || exp.some(x => x.title || x.company), 'a summary or at least one job'), ...(rq('resume') ? [] : [])]
    if (i === 1) return [...need(f.name.trim(), 'Full name'), ...need(/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email.trim()), 'a valid email'),
      ...(rq('phone') ? need(f.phone.trim(), 'Phone') : []), ...(rq('location') ? need(f.location.trim(), 'Current city') : []), ...(rq('linkedin') ? need(f.linkedin.trim(), 'LinkedIn') : [])]
    if (i === 2) return [...(rq('current_company') ? need(f.current_company.trim(), 'Current company') : []), ...(rq('total_experience_years') ? need(f.total_experience_years !== '', 'Total experience') : []),
      ...(rq('notice_days') ? need(f.notice_days !== '', 'Notice period') : []), ...(rq('expected_salary') ? need(f.expected_salary !== '', 'Expected salary') : [])]
    return [...questions.filter(q => q.required && !(answers[q.id] || '').trim()).map(q => q.question), ...need(consent, 'the consent checkbox')]
  }
  function go(i: number) {
    if (i > step) for (let k = step; k < i; k++) { const m = missing(k); if (m.length) { setStep(k); show(`Please fill in: ${m.join(', ')}.`); return } }
    setErr(''); setStep(i); requestAnimationFrame(() => topRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (step < STEPS.length - 1) { go(step + 1); return }
    for (let k = 0; k < STEPS.length; k++) { const m = missing(k); if (m.length) { setStep(k); show(`Please fill in: ${m.join(', ')}.`); return } }
    setErr(''); setBusy(true)
    const data = { ...f, skills, languages: langs, certifications: certs, consent, willing_to_relocate: relocate, answers,
      education: edu.degree || edu.school ? [edu] : [], ...(mode === 'build' ? { experience: exp.filter(x => x.title || x.company) } : {}) }
    const fd = new FormData(); fd.append('data', JSON.stringify(data)); if (mode === 'upload' && file) fd.append('resume', file)
    try { await postForm(url, fd); setDone(true); requestAnimationFrame(() => topRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })) }
    catch (e: any) { show(e.message || 'Your application could not be sent. Please try again.') }
    setBusy(false)
  }
  if (done) return <div ref={topRef}><Alert tone="success" icon={<CircleCheck />} title={talentPool ? "You're in our talent pool" : 'Application sent'}>Thank you, {f.name.split(' ')[0]}. {orgName} will be in touch if there's a fit. We've emailed you a link to follow your application.</Alert></div>
  const last = step === STEPS.length - 1
  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <div ref={topRef} className="scroll-mt-6">
        <ol className="grid grid-cols-4 gap-1.5" aria-label="Application steps">{STEPS.map((s, i) => (
          <li key={s}><button type="button" onClick={() => go(i)} aria-current={i === step ? 'step' : undefined} className="w-full text-left">
            <span className={cn('block h-1.5 rounded-full transition-colors', i <= step ? 'bg-brand-600' : 'bg-slate-200 dark:bg-ink-700')} />
            <span className={cn('mt-1.5 block truncate text-xs font-medium', i === step ? 'text-brand-700 dark:text-brand-300' : 'text-slate-500 dark:text-slate-400')}>{i + 1}. {s}</span></button></li>))}</ol>
      </div>

      {step === 0 && <div className="space-y-4">
        <div className="inline-flex rounded-xl bg-slate-100 p-1 text-sm dark:bg-ink-850">
          {(['upload', 'build'] as const).map(m => <button type="button" key={m} onClick={() => setMode(m)} className={`rounded-lg px-4 py-1.5 font-medium ${mode === m ? 'bg-white shadow-sm dark:bg-ink-700 dark:text-white' : 'text-slate-500 dark:text-slate-400'}`}>{m === 'upload' ? 'Upload resume' : 'Build my resume'}</button>)}
        </div>
        {mode === 'upload' ? (
          <label className="flex cursor-pointer items-center gap-3 rounded-2xl border-2 border-dashed border-slate-200 p-5 hover:border-brand-300 dark:border-ink-700">
            <FileUp className="size-6 text-brand-500" />
            <span className="min-w-0 flex-1 text-sm"><span className="block font-semibold">{file ? file.name : 'Attach your resume'}</span><span className="text-slate-500 dark:text-slate-400">{parsing ? 'Reading it to fill the form for you…' : 'PDF, DOCX or TXT, max 10 MB. We fill in the next steps from it.'}</span></span>
            <input type="file" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.webp" className="sr-only" onChange={e => { const x = e.target.files?.[0]; if (x) onFile(x) }} />
          </label>
        ) : (
          <div className="space-y-4 rounded-2xl bg-slate-50 p-4 dark:bg-ink-850">
            <Field label="Professional summary" htmlFor="ap-sum"><Textarea id="ap-sum" className="min-h-0" rows={3} value={f.summary} onChange={set('summary')} placeholder="Two or three lines about what you do best" /></Field>
            <div className="text-sm font-semibold">Work experience</div>
            {exp.map((x, i) => (
              <div key={i} className="grid gap-2 rounded-xl bg-white p-3 ring-1 ring-slate-200 dark:bg-ink-900 dark:ring-ink-700 sm:grid-cols-2">
                <Input aria-label="Job title" placeholder="Job title" value={x.title} onChange={e => setExp(a => a.map((y, j) => j === i ? { ...y, title: e.target.value } : y))} />
                <Input aria-label="Company" placeholder="Company" value={x.company} onChange={e => setExp(a => a.map((y, j) => j === i ? { ...y, company: e.target.value } : y))} />
                <Input aria-label="Start" placeholder="Start (e.g. Jan 2021)" value={x.start} onChange={e => setExp(a => a.map((y, j) => j === i ? { ...y, start: e.target.value } : y))} />
                <Input aria-label="End" placeholder="End (or leave empty if current)" value={x.end} onChange={e => setExp(a => a.map((y, j) => j === i ? { ...y, end: e.target.value } : y))} />
                <Textarea aria-label="What you did" className="min-h-0 sm:col-span-2" rows={3} placeholder="What you did and achieved, one point per line" value={x.description} onChange={e => setExp(a => a.map((y, j) => j === i ? { ...y, description: e.target.value } : y))} />
                {exp.length > 1 && <Button type="button" size="sm" variant="ghost" icon={<Trash2 />} onClick={() => setExp(a => a.filter((_, j) => j !== i))}>Remove</Button>}
              </div>))}
            <Button type="button" size="sm" onClick={() => setExp(a => [...a, { title: '', company: '', start: '', end: '', description: '' }])} icon={<Plus />}>Add experience</Button>
            <p className="text-xs text-slate-500 dark:text-slate-400">We turn this into a clean PDF resume for the hiring team. Education and skills come in the next steps.</p>
          </div>
        )}
      </div>}

      {step === 1 && <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Full name *" htmlFor="ap-name"><Input id="ap-name" autoComplete="name" value={f.name} onChange={set('name')} /></Field>
        <Field label="Email *" htmlFor="ap-email"><Input id="ap-email" type="email" autoComplete="email" value={f.email} onChange={set('email')} /></Field>
        <Field label={star('Phone', 'phone')} htmlFor="ap-phone"><Input id="ap-phone" type="tel" autoComplete="tel" value={f.phone} onChange={set('phone')} /></Field>
        <Field label={star('Current city', 'location')} htmlFor="ap-loc"><Input id="ap-loc" autoComplete="address-level2" value={f.location} onChange={set('location')} /></Field>
        <Field label="Preferred work location" htmlFor="ap-pref"><Input id="ap-pref" value={f.preferred_location} onChange={set('preferred_location')} placeholder="e.g. Pune, or remote" /></Field>
        <Field label="Work authorisation" htmlFor="ap-auth"><Select id="ap-auth" value={f.work_authorization} onChange={set('work_authorization')}><option value="">Select…</option>{AUTH.map(x => <option key={x}>{x}</option>)}</Select></Field>
        <Field label={star('LinkedIn', 'linkedin')} htmlFor="ap-li"><Input id="ap-li" value={f.linkedin} onChange={set('linkedin')} placeholder="linkedin.com/in/…" /></Field>
        <Field label="Portfolio or GitHub" htmlFor="ap-pf"><Input id="ap-pf" value={f.portfolio} onChange={set('portfolio')} placeholder="https://…" /></Field>
      </div>}

      {step === 2 && <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Current job title" htmlFor="ap-title"><Input id="ap-title" value={f.headline} onChange={set('headline')} /></Field>
          <Field label={star('Current company', 'current_company')} htmlFor="ap-co"><Input id="ap-co" value={f.current_company} onChange={set('current_company')} /></Field>
          <Field label={star('Total experience (years)', 'total_experience_years')} htmlFor="ap-yrs"><Input id="ap-yrs" type="number" min={0} step="0.5" value={f.total_experience_years} onChange={set('total_experience_years')} /></Field>
          <Field label={star('Notice period (days)', 'notice_days')} htmlFor="ap-notice"><Input id="ap-notice" type="number" min={0} value={f.notice_days} onChange={set('notice_days')} /></Field>
          <Field label="Current salary (per year)" htmlFor="ap-cur"><Input id="ap-cur" type="number" min={0} value={f.current_salary} onChange={set('current_salary')} /></Field>
          <Field label={star('Expected salary (per year)', 'expected_salary')} htmlFor="ap-sal"><Input id="ap-sal" type="number" min={0} value={f.expected_salary} onChange={set('expected_salary')} /></Field>
          <Field className="sm:col-span-2" label="Skills" hint="Press Enter after each one."><TagInput value={skills} onChange={setSkills} placeholder="e.g. Excel, Zendesk, SQL" /></Field>
        </div>
        <div>
          <div className="mb-2 text-sm font-semibold">Highest education</div>
          <div className="grid gap-2 sm:grid-cols-2">
            <Input aria-label="Degree" placeholder="Degree (e.g. B.Tech)" value={edu.degree} onChange={e => setEdu({ ...edu, degree: e.target.value })} />
            <Input aria-label="Field" placeholder="Field of study" value={edu.field} onChange={e => setEdu({ ...edu, field: e.target.value })} />
            <Input aria-label="School" placeholder="College / university" value={edu.school} onChange={e => setEdu({ ...edu, school: e.target.value })} />
            <div className="grid grid-cols-2 gap-2"><Input aria-label="Year" placeholder="Year" value={edu.year} onChange={e => setEdu({ ...edu, year: e.target.value })} /><Input aria-label="Grade" placeholder="CGPA / %" value={edu.grade} onChange={e => setEdu({ ...edu, grade: e.target.value })} /></div>
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Languages"><TagInput value={langs} onChange={setLangs} placeholder="e.g. English, Hindi" /></Field>
          <Field label="Certifications"><TagInput value={certs} onChange={setCerts} placeholder="e.g. AWS Practitioner" /></Field>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={relocate} onChange={e => setRelocate(e.target.checked)} />I'm open to relocating</label>
      </div>}

      {last && <div className="space-y-5">
        {questions.length > 0 && <div className="space-y-3">
          <div className="text-sm font-semibold">A few questions</div>
          {questions.map(q => (
            <Field key={q.id} label={<>{q.question}{q.required && <span className="text-red-500"> *</span>}</>} htmlFor={`q-${q.id}`}>
              {q.kind === 'yes_no' ? <Select id={`q-${q.id}`} value={answers[q.id] || ''} onChange={e => setAnswers(a => ({ ...a, [q.id]: e.target.value }))}><option value="">Select…</option><option value="yes">Yes</option><option value="no">No</option></Select>
                : <Input id={`q-${q.id}`} type={q.kind === 'number' ? 'number' : 'text'} value={answers[q.id] || ''} onChange={e => setAnswers(a => ({ ...a, [q.id]: e.target.value }))} />}
            </Field>))}
        </div>}
        {!talentPool && <Field label="Cover letter (optional)" htmlFor="ap-cl"><Textarea id="ap-cl" className="min-h-0" rows={4} value={f.cover_letter} onChange={set('cover_letter')} placeholder="Why this role, in a few lines" /></Field>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="How did you hear about us?" htmlFor="ap-how"><Select id="ap-how" value={f.how_heard} onChange={set('how_heard')}><option value="">Select…</option>{['LinkedIn', 'Company website', 'Referral', 'Job board', 'Social media', 'Campus', 'Other'].map(x => <option key={x}>{x}</option>)}</Select></Field>
          {f.how_heard === 'Referral' && <Field label="Who referred you?" htmlFor="ap-ref"><Input id="ap-ref" value={f.referral} onChange={set('referral')} placeholder="Name or email" /></Field>}
        </div>
        <div className="rounded-2xl bg-slate-50 p-4 text-sm ring-1 ring-slate-200/70 dark:bg-ink-850 dark:ring-ink-700">
          <div className="mb-2 font-semibold">Review</div>
          <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">{([
            ['Resume', mode === 'upload' ? (file?.name || 'none') : 'Built here', 0], ['Name', f.name, 1], ['Email', f.email, 1], ['Phone', f.phone, 1], ['City', f.location, 1],
            ['Experience', f.total_experience_years ? `${f.total_experience_years} years` : '', 2], ['Notice', f.notice_days ? `${f.notice_days} days` : '', 2], ['Expected salary', f.expected_salary, 2],
            ['Skills', skills.slice(0, 6).join(', '), 2]] as [string, string, number][]).map(([k, v, s]) => (
            <div key={k} className="flex justify-between gap-3"><dt className="text-slate-500 dark:text-slate-400">{k}</dt><dd className="truncate text-right">{v || <button type="button" className="text-brand-600 underline dark:text-brand-400" onClick={() => go(s)}>add</button>}</dd></div>))}</dl>
        </div>
        <label className="flex items-start gap-2 text-sm text-slate-600 dark:text-slate-300"><input type="checkbox" className="mt-1" checked={consent} onChange={e => setConsent(e.target.checked)} required />
          <span>I agree that {orgName} may store and process my details to consider me for roles, including automated matching. I can ask for them to be deleted at any time.</span></label>
      </div>}

      <div ref={errRef} aria-live="assertive">{err && <Alert tone="danger" title={last ? (talentPool ? 'Not sent yet' : 'Your application was not sent') : 'A few details are missing'}>{err}</Alert>}</div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4 dark:border-ink-800">
        {step > 0 ? <Button type="button" variant="ghost" icon={<ArrowLeft />} onClick={() => go(step - 1)}>Back</Button> : <span />}
        {last ? <Button variant="primary" size="lg" type="submit" loading={busy} icon={talentPool ? <Building2 /> : <Send />}>{talentPool ? 'Join talent pool' : 'Submit application'}</Button>
          : <Button variant="primary" size="lg" type="submit">Next: {STEPS[step + 1]}</Button>}
      </div>
    </form>
  )
}
