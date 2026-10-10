import { ArrowLeft, Check, ExternalLink, FileText, FileUp, Languages, Link2, ShieldCheck, Sparkles, TriangleAlert, Wand2 } from 'lucide-react'
import { LanguageChoice } from '../components/LanguageChoice'
import { LANGUAGES } from './flow/types'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Field, Input, Select, Switch, Textarea, cn, toast } from '../components/ui'
import { api } from '../lib/api'
import { TYPE_LABEL } from '../lib/format'
import { PageHeader } from '../components/kit'
import { useHealth } from '../lib/health'
import { useLocation } from '../lib/router'
import { DateTimePicker, Stepper } from '../components/pickers'
import { LinkActions } from '../components/LinkActions'

interface Sample { id: string; role: string; company: string; candidate: string; duration: number; jd: string; resume: string; questions: string }
interface Question { id: string; type: string; ask: string; competency_id?: string; scored: boolean; good_answer_covers?: string[]; max_followups: number; time_budget_sec: number }
interface Plan { duration_min: number; questions: Question[]; competencies?: { id: string; name: string }[]; keyterms?: string[]; resume_claims_to_verify?: string[] }

function Steps({ step, max, onGo }: { step: number; max: number; onGo: (n: number) => void }) {
  const items = ['Candidate & role', 'Review plan', 'Interview rules', 'Send link']
  return (
    <ol className="mb-6 flex flex-wrap items-center gap-2 text-sm">
      {items.map((t, i) => {
        const n = i + 1, state = n < step ? 'done' : n === step ? 'on' : ''
        return (
          <li key={t} className="flex items-center gap-2">
            <button type="button" disabled={n > max} onClick={() => onGo(n)} aria-current={state === 'on' ? 'step' : undefined} className={cn('flex items-center gap-2 rounded-full px-3 py-1.5 font-medium ring-1 ring-inset disabled:cursor-not-allowed',
              state === 'on' ? 'bg-brand-50 text-brand-700 ring-brand-200 dark:bg-brand-500/15 dark:text-brand-200 dark:ring-brand-500/30'
                : state === 'done' ? 'bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/30'
                : 'bg-white text-slate-500 ring-slate-200 dark:bg-ink-900 dark:text-slate-400 dark:ring-ink-700')}>
              <span className={cn('grid size-5 place-items-center rounded-full text-[11px] font-bold', state === 'on' ? 'bg-brand-600 text-white' : state === 'done' ? 'bg-emerald-600 text-white' : 'bg-slate-100 dark:bg-ink-800')}>
                {state === 'done' ? <Check className="size-3" strokeWidth={3} /> : n}</span>{t}
            </button>
            {n < 3 && <span className="hidden h-px w-6 bg-slate-200 dark:bg-ink-700 sm:block" />}
          </li>
        )
      })}
    </ol>
  )
}

function UploadLink({ onText, resume, jd, onParsed }: { onText: (t: string) => void; resume?: boolean; jd?: boolean; onParsed?: (p: { name?: string; email?: string; title?: string }) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  return (
    <>
      <button type="button" className="inline-flex items-center gap-1 text-[13px] font-semibold text-brand-600 hover:text-brand-700 dark:text-brand-300" onClick={() => ref.current?.click()}>
        <FileUp className="size-3.5" />{busy ? 'Reading...' : 'Upload'}
      </button>
      <input ref={ref} type="file" accept=".pdf,.txt,.docx" className="hidden" onChange={async e => {
        const f = e.target.files?.[0]; if (!f) return
        const fd = new FormData(); fd.append('file', f); setBusy(true)
        try {
          const r = await api<{ text: string; parsed?: { name?: string; email?: string; title?: string } }>(`/api/extract${resume ? '?kind=resume' : jd ? '?kind=jd' : ''}`, { method: 'POST', body: fd })
          onText(r.text); if (r.parsed) onParsed?.(r.parsed)
        } catch (err: any) { toast(err.message) }
        setBusy(false); e.target.value = ''
      }} />
    </>
  )
}

export default function NewInterview() {
  const health = useHealth()
  const [samples, setSamples] = useState<Sample[] | null>(null)
  const [sampleId, setSampleId] = useState('')
  const [f, setF] = useState({ company: '', role: '', cand: '', email: '', dur: '15', jd: '', cv: '', qs: '' })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF(v => ({ ...v, [k]: e.target.value }))
  const [hist, setHist] = useState<string[]>([])
  const [plan, setPlan] = useState<Plan | null>(null)
  const [inputs, setInputs] = useState<Record<string, unknown> | null>(null)
  const [planWarn, setPlanWarn] = useState<string[]>([])
  const [json, setJson] = useState('')
  const [gen, setGen] = useState(false), [err1, setErr1] = useState('')
  const [st, setSt] = useState({ focus: true, maxW: '2', mon: true, share: false, face: true, room: true, ears: true, strictRoom: true, vision: '120', snap: true, rejoin: '90', openAt: '', validH: '72', opening: 'pick' as 'pick' | 'now' | 'fixed', invite: true, language: 'en', languages: undefined as string[] | undefined })
  const [creating, setCreating] = useState(false), [err2, setErr2] = useState('')
  const [link, setLink] = useState<{ url: string; report: string; path: string; warnings: string[]; code: string; invited: boolean } | null>(null)
  const base = (health?.app_url || health?.public_url || location.origin).replace(/\/$/, '')
  const { query } = useLocation()
  const link_ = { job_id: query.get('job') || '', candidate_id: query.get('candidate') || '', application_id: query.get('application') || '' }
  const [fromJob, setFromJob] = useState('')

  useEffect(() => {   // opened from a job's matches or pipeline: fill in the JD, resume and the job's interview questions
    if (!link_.job_id) return
    Promise.all([api(`/api/jobs/${link_.job_id}`), api(`/api/jobs/${link_.job_id}/jd`), link_.candidate_id ? api(`/api/candidates/${link_.candidate_id}`) : null]).then(([job, jd, cand]) => {
      const jdText = [jd.title, jd.facts.join(' | '), ...jd.sections.map((s: any) => `${s.title}\n${s.body || ''}\n${(s.items || []).map((x: string) => '- ' + x).join('\n')}`)].join('\n\n')
      const qs: string[] = job.fields.ai_interview_questions || []
      setF(v => ({ ...v, company: jd.company, role: job.title, jd: jdText, cand: cand?.name || v.cand, email: cand?.email || v.email, cv: cand?.resume_text || v.cv, qs: qs.join('\n') || v.qs }))
      setFromJob(job.title)
      if (cand?.email) checkHistory(cand.email)
    }).catch((e: any) => toast(e.message))
  }, [link_.job_id, link_.candidate_id])                   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {   // public static file: load it first, independent of the admin key and health check
    fetch('/samples/index.json', { cache: 'no-cache' }).then(r => r.ok ? r.json() : []).then((s: Sample[]) => { setSamples(s); setSampleId(s[0]?.id || '') }).catch(() => setSamples([]))
  }, [])

  async function loadSample() {
    const s = samples?.find(x => x.id === sampleId); if (!s) return
    const [jd, cv, qs] = await Promise.all([s.jd, s.resume, s.questions].map(p => fetch('/samples/' + p).then(r => r.text())))
    const email = s.candidate.toLowerCase().replace(/[^a-z]+/g, '.') + '@example.com'
    setF({ company: s.company, role: s.role, cand: s.candidate, email, dur: String(s.duration || 15), jd: jd!, cv: cv!, qs: qs!.trim() })
    toast(`Loaded sample: ${s.role}`); checkHistory(email)
  }
  async function checkHistory(email = f.email) {
    setHist([]); if (!email.trim()) return
    try { setHist((await api<{ warnings: string[] }>('/api/candidates/history?email=' + encodeURIComponent(email.trim()))).warnings || []) } catch { /* optional */ }
  }
  async function generate() {
    setErr1('')
    const inp = { company: f.company, role: f.role, candidate_name: f.cand, duration_min: +f.dur, jd: f.jd, resume: f.cv,
      questions: f.qs.split('\n').map(s => s.trim()).filter(Boolean) }
    if (!inp.jd.trim() || !inp.resume.trim()) return setErr1('The job description and the resume are required.')
    setGen(true)
    try {
      const r = await api<{ plan: Plan; warnings: string[] }>('/api/plan', { json: inp })
      const p: any = r.plan
      const notes = p.source === 'template' ? [`${p.fallback_reason || 'The AI was slow.'} This is a template plan built from the JD, resume and your questions. Review it, or press "Generate interview plan" again to retry with AI.`] : []
      setPlan(r.plan); setJson(JSON.stringify(r.plan, null, 2)); setPlanWarn([...notes, ...(r.warnings || [])]); setInputs(inp); setLink(null)
      toast(p.source === 'template' ? 'Template plan ready (AI was slow)' : `Plan ready in ${Math.max(1, Math.round((p.generated_ms || 0) / 1000))} s`)
      go(2)
    } catch (e: any) { setErr1(e.message) }
    setGen(false)
  }
  async function create() {
    setErr2(''); setCreating(true)
    try {
      const settings = { candidate_email: f.email.trim(), require_screen_share: st.share, reconnect_window_sec: +st.rejoin || 90,
        opening: st.opening, available_from: st.opening === 'fixed' && st.openAt ? new Date(st.openAt).getTime() / 1000 : null, face_detection: st.face, snapshots: st.snap, room_scan: st.room, ear_check: st.ears, strict_room: st.strictRoom, vision_check_sec: Number(st.vision),
        enforce_focus: st.focus, max_warnings: +st.maxW, block_multi_monitor: st.mon, language: st.language, ...(st.languages ? { languages: st.languages } : {}) }
      const r = await api<{ candidate_path: string; report_path: string; warnings: string[]; access_code: string; invited: boolean }>('/api/interviews', { json: { plan, inputs, expires_hours: +st.validH || 72, settings, send_invite: st.invite && !!f.email.trim(), ...Object.fromEntries(Object.entries(link_).filter(([, x]) => x)) } })
      setLink({ url: base + r.candidate_path, report: r.report_path, path: r.candidate_path, warnings: r.warnings || [], code: r.access_code, invited: r.invited })
      go(4)
    } catch (e: any) { setErr2(e.message) }
    setCreating(false)
  }

  const [view, setView] = useState(1)
  const maxStep = link ? 4 : plan ? 3 : 1
  const go = (n: number) => { setView(n); window.scrollTo({ top: 0, behavior: 'smooth' }) }
  const comps = Object.fromEntries((plan?.competencies || []).map(c => [c.id, c.name]))
  const budget = plan ? plan.questions.reduce((a, q) => a + q.time_budget_sec, 0) : 0

  return (
    <>
      <PageHeader title="New AI interview" description={fromJob ? <>For <b>{f.cand || 'the candidate'}</b> · {fromJob}. The JD, resume and the job's interview questions are filled in. Review, then generate the plan.</> : 'Job description + resume + your questions → a plan you approve → a link for the candidate.'} />
      <Steps step={view} max={maxStep} onGo={go} />
      {health && (
        <div className="mb-4 flex flex-wrap gap-2">
          {health.mock ? <Badge tone="warning">Demo mode: simulated AI</Badge> : health.detail && <Badge tone="neutral">Interviewer: {health.fast_model} · Plan and scoring: {health.smart_model}</Badge>}
          {health.free_models && <Badge tone="warning">Free AI models: slower, rate-limited, may train on data</Badge>}
          {health.model_note && <Badge tone="warning">{health.model_note}</Badge>}
        </div>
      )}

      {view === 1 && <Card>
        <CardHeader title="Candidate & role" description="The length is used to plan the questions. The candidate is never told the length or the number of questions." />
        <CardBody className="space-y-5">
          {!fromJob && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl bg-gradient-to-r from-brand-50 to-violet-50 p-3 ring-1 ring-brand-100 dark:from-brand-500/10 dark:to-violet-500/10 dark:ring-brand-500/20">
            <span className="flex items-center gap-2 text-sm font-semibold text-brand-800 dark:text-brand-200"><Sparkles className="size-4" />Try a sample role</span>
            <Select id="sampleSel" aria-label="Sample role" className="min-w-0 flex-1 basis-60" value={sampleId} onChange={e => setSampleId(e.target.value)}>
              {samples === null ? <option>Loading samples...</option> : samples.length ? samples.map(s => <option key={s.id} value={s.id}>{s.role} · {s.candidate}</option>) : <option value="">No samples available</option>}
            </Select>
            <Button id="sampleBtn" variant="primary" size="sm" disabled={!samples?.length} onClick={loadSample}>Load sample</Button>
          </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <Field label="Company" htmlFor="company"><Input id="company" placeholder="RAC IT Solutions" value={f.company} onChange={set('company')} /></Field>
            <Field label="Role" htmlFor="role"><Input id="role" placeholder="Java Backend Developer" value={f.role} onChange={set('role')} /></Field>
            <Field label="Candidate name" htmlFor="cand"><Input id="cand" placeholder="Full name" value={f.cand} onChange={set('cand')} /></Field>
            <Field label="Candidate email" htmlFor="email"><Input id="email" type="email" placeholder="name@example.com" value={f.email} onChange={set('email')} onBlur={() => checkHistory()} /></Field>
            <Field label="Interview length" htmlFor="dur"><Stepper id="dur" aria-label="Interview length" max={60} value={+f.dur} onChange={v => setF(x => ({ ...x, dur: String(v) }))} presets={[10, 15, 20, 30, 45, 60]} /></Field>
          </div>
          {hist.map(w => <Alert key={w} tone="danger" icon={<TriangleAlert />}>{w}</Alert>)}
          <div className="grid gap-4 lg:grid-cols-2">
            <Field label="Job description" htmlFor="jd" action={<UploadLink jd onText={t => setF(v => ({ ...v, jd: t }))} onParsed={pp => setF(v => ({ ...v, role: v.role || pp.title || '' }))} />}>
              <Textarea id="jd" className="min-h-56" placeholder="Paste the JD, or upload a PDF, TXT or DOCX" value={f.jd} onChange={set('jd')} /></Field>
            <Field label="Resume" htmlFor="cv" action={<UploadLink resume onText={t => setF(v => ({ ...v, cv: t }))} onParsed={pp => setF(v => ({ ...v, cand: v.cand || pp.name || '', email: v.email || pp.email || '' }))} />}>
              <Textarea id="cv" className="min-h-56" placeholder="Paste the resume, or upload a PDF, TXT or DOCX" value={f.cv} onChange={set('cv')} /></Field>
          </div>
          <Field label="Your questions" htmlFor="qs" hint="One per line. Every one of them will be asked.">
            <Textarea id="qs" className="min-h-24" placeholder={'Why are you looking for a change?\nWhat is your notice period?'} value={f.qs} onChange={set('qs')} /></Field>
          {err1 && <Alert tone="danger" icon={<TriangleAlert />}>{err1}</Alert>}
          <Button id="genBtn" variant="primary" size="lg" icon={<Wand2 />} loading={gen} onClick={generate}>{gen ? 'Generating the plan (usually under 20 s)...' : plan ? 'Generate a new plan' : 'Generate interview plan'}</Button>
          {plan && !gen && <Button size="lg" className="ml-2" onClick={() => go(2)}>Keep the current plan</Button>}
        </CardBody>
      </Card>}

      {plan && view === 2 && (
          <Card id="planCard">
            <CardHeader title="Review the plan" description={<>This is exactly what the AI will ask, in order. Your approval is the control point. · {plan.questions.length} questions · about {Math.round(budget / 60)} of {plan.duration_min} min</>} />
            <CardBody className="space-y-3">
              {planWarn.map(w => <Alert key={w} icon={<TriangleAlert />}>{w}</Alert>)}
              <ol className="space-y-2.5">
                {plan.questions.map((q, i) => (
                  <li key={q.id + i} className="rounded-xl p-4 ring-1 ring-slate-200 dark:ring-ink-700">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="grid size-6 place-items-center rounded-full bg-brand-600 text-[11px] font-bold text-white">{i + 1}</span>
                      <Badge tone={q.type === 'hr_mandatory' ? 'brand' : q.type === 'warmup' ? 'neutral' : 'violet'}>{TYPE_LABEL[q.type] || q.type}</Badge>
                      {comps[q.competency_id || ''] && <Badge>{comps[q.competency_id || '']}</Badge>}
                      <Badge>{q.time_budget_sec}s</Badge><Badge>follow-ups ≤ {q.max_followups}</Badge>{!q.scored && <Badge>not scored</Badge>}
                    </div>
                    <p className="mt-2 font-semibold text-slate-900 dark:text-white">{q.ask}</p>
                    {!!q.good_answer_covers?.length && <p className="mt-1 text-[13px] text-slate-500 dark:text-slate-400">A good answer covers: {q.good_answer_covers.join(' · ')}</p>}
                  </li>
                ))}
              </ol>
              <p className="text-xs text-slate-500 dark:text-slate-400">Speech recognition key terms: {(plan.keyterms || []).join(', ') || 'none'}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">Resume claims to verify: {(plan.resume_claims_to_verify || []).join(' · ') || 'none'}</p>
              <details className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200/70 dark:bg-ink-850 dark:ring-ink-700">
                <summary className="cursor-pointer text-sm font-medium text-slate-700 dark:text-slate-200">Edit plan JSON (wording, time budgets, follow-ups)</summary>
                <Textarea className="mt-3 min-h-80 font-mono text-xs" value={json} onChange={e => setJson(e.target.value)} />
                <Button className="mt-3" size="sm" onClick={() => { try { const p = JSON.parse(json); setPlan(p); toast('Plan updated') } catch (e: any) { toast('Invalid JSON: ' + e.message) } }}>Apply JSON edits</Button>
              </details>
            </CardBody>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-4 dark:border-ink-800">
              <Button variant="ghost" icon={<ArrowLeft />} onClick={() => go(1)}>Candidate & role</Button>
              <Button id="toRules" variant="primary" onClick={() => go(3)}>Next: interview rules</Button>
            </div>
          </Card>
      )}

      {plan && view === 3 && (
          <Card>
            <CardHeader title="Interview rules" description="How strict the interview is, and how the link behaves." />
            <CardBody className="grid gap-6 lg:grid-cols-2">
              <Group title="Language" icon={<Languages />}>
                <Field label="Language the plan is written in" htmlFor="ivLang"><Select id="ivLang" value={st.language} onChange={e => setSt(s => ({ ...s, language: e.target.value }))}>{LANGUAGES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
                <Field label="Languages the candidate can choose"><LanguageChoice value={st.languages} onChange={x => setSt(s => ({ ...s, languages: x }))} /></Field>
              </Group>
              <Group title="Integrity" icon={<ShieldCheck />}>
                <Switch id="focusOn" checked={st.focus} onChange={v => setSt(s => ({ ...s, focus: v }))} label="Warn when the candidate leaves the interview" description="Switching tabs, windows or apps. The AI interviewer says the warning out loud and repeats the question." />
                <div className={cn('pb-3', !st.focus && 'opacity-50')}>
                  <Field label="Warnings before the interview is stopped" htmlFor="maxW">
                    <Select id="maxW" disabled={!st.focus} value={st.maxW} onChange={e => setSt(s => ({ ...s, maxW: e.target.value }))}>
                      <option value="0">None: stop the first time</option><option value="1">1 warning</option><option value="2">2 warnings</option><option value="3">3 warnings</option>
                    </Select></Field>
                </div>
                <Switch id="monOn" checked={st.mon} onChange={v => setSt(s => ({ ...s, mon: v }))} label="One screen only" description="A second monitor blocks the start; connecting one mid-interview counts as leaving." />
                <Switch id="reqShare" checked={st.share} onChange={v => setSt(s => ({ ...s, share: v }))} label="Require entire-screen sharing" description="HR sees the screen, with a screenshot whenever the candidate switches away. Laptops and desktops only." />
                <Switch id="faceOn" checked={st.face} onChange={v => setSt(s => ({ ...s, face: v }))} label="Camera checks" description="Face in view; other people anywhere in the room; phones and other screens. Checked every 2 seconds on the candidate's device." />
                {st.face && <>
                  <Switch id="roomOn" checked={st.room} onChange={v => setSt(s => ({ ...s, room: v }))} label="Room scan before the start" description="The candidate turns the camera around the room for 12 seconds. Someone else seen blocks the start." />
                  <Switch id="earsOn" checked={st.ears} onChange={v => setSt(s => ({ ...s, ears: v }))} label="Earphone check before the start" description="Photos of both ears from the head turn, checked by the AI vision model (Platform admin > AI models). Earbuds seen block the start." />
                  <Switch id="strictRoomOn" checked={st.strictRoom} onChange={v => setSt(s => ({ ...s, strictRoom: v }))} label="Strict: someone else, a phone or earphones count as warnings" description="Off: the interviewer only reminds the candidate; it is still flagged in the report." />
                  <Field label="AI photo check during the interview" htmlFor="visionEvery"><Select id="visionEvery" value={st.vision} onChange={e => setSt(s => ({ ...s, vision: e.target.value }))}>
                    <option value="0">Off</option><option value="60">About every minute</option><option value="120">About every 2 minutes</option><option value="300">About every 5 minutes</option></Select></Field>
                </>}
                <Switch id="snapOn" checked={st.snap} onChange={v => setSt(s => ({ ...s, snap: v }))} label="Snapshots" description="Camera every minute, and the screen when shared." />
              </Group>
              <Group title="Link" icon={<Link2 />}>
                <div className="grid gap-4 py-3">
                  <Field label="Rejoin window after a dropped call" htmlFor="rejoin" hint="Seconds (10 to 900)."><Input id="rejoin" type="number" min={10} max={900} value={st.rejoin} onChange={e => setSt(s => ({ ...s, rejoin: e.target.value }))} /></Field>
                  <Field label="When does the candidate take it?" htmlFor="opening">
                    <Select id="opening" value={st.opening} onChange={e => setSt(s => ({ ...s, opening: e.target.value as typeof s.opening }))}>
                      <option value="pick">The candidate picks a time (recommended)</option>
                      <option value="now">Any time, starting now</option>
                      <option value="fixed">At a time I choose</option>
                    </Select></Field>
                  {st.opening === 'fixed' && <Field label="Opens at" htmlFor="openAt"><DateTimePicker id="openAt" aria-label="Link opens" value={st.openAt} onChange={v => setSt(s => ({ ...s, openAt: v }))} /></Field>}
                  <Field label={st.opening === 'pick' ? 'The candidate can book a time within' : 'Link valid for'} htmlFor="validH" hint="Hours (72 = 3 days)."><Input id="validH" type="number" min={1} max={720} value={st.validH} onChange={e => setSt(s => ({ ...s, validH: e.target.value }))} /></Field>
                  <Switch id="inviteOn" checked={st.invite} onChange={v => setSt(s => ({ ...s, invite: v }))} label="Email the invitation to the candidate"
                    description={f.email.trim() ? `To ${f.email.trim()}: the link${st.opening === 'pick' ? ' to pick a time' : ''}, then the access code in a separate email.` : 'Add the candidate\'s email in step 1 to send it.'} />
                </div>
              </Group>
            </CardBody>
            <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 px-5 py-4 dark:border-ink-800">
              <Button variant="ghost" icon={<ArrowLeft />} onClick={() => go(2)}>Review plan</Button>
              <Button id="createBtn" className="ml-auto" variant="primary" size="lg" icon={<Link2 />} loading={creating} onClick={create}>{st.invite && f.email.trim() ? 'Create and email the invitation' : 'Create candidate link'}</Button>
              {err2 && <span className="w-full text-sm text-red-600 dark:text-red-300">{err2}</span>}
            </div>
          </Card>
      )}

      {link && view === 4 && (
        <div>
          <Card id="linkOut" className="ring-2 ring-emerald-500/30">
            <CardHeader title={<span className="flex items-center gap-2"><span className="grid size-6 place-items-center rounded-full bg-emerald-500 text-white"><Check className="size-3.5" strokeWidth={3} /></span>Link ready</span>}
              description={link.invited ? `Emailed to ${f.email.trim()}: the invitation${st.opening === 'pick' ? ' (they pick a time)' : ''}, and the access code separately. You'll find the interview on the Interviews page.`
                : 'Send this link and the access code to the candidate, separately if you can. You\'ll find the interview on the Interviews page.'} />
            <CardBody className="space-y-4">
              {link.warnings.map(w => <Alert key={w} tone="danger" icon={<TriangleAlert />}>{w}</Alert>)}
              <div className="flex flex-wrap items-center gap-3 rounded-xl bg-slate-50 px-4 py-3 ring-1 ring-slate-200 dark:bg-ink-850 dark:ring-ink-700">
                <ShieldCheck className="size-5 text-brand-600 dark:text-brand-300" />
                <div className="text-sm">Access code <b id="accessCodeOut" className="ml-1 font-mono text-lg tracking-widest">{link.code}</b>
                  <div className="text-xs text-slate-500 dark:text-slate-400">The link opens nothing without it. Also shown on the interview's page, where you can issue a new one.</div></div>
              </div>
              <div className="flex gap-2"><Input id="candLink" readOnly value={link.url} onFocus={e => e.target.select()} /><LinkActions size="md" url={link.url} label="Copy" copied="Candidate link copied" to={{ email: f.email, name: f.cand }} subject={`Your interview for ${f.role}`}
                message={`Hi ${f.cand.split(' ')[0] || 'there'}, here is the link to your AI interview for ${f.role} at ${f.company}. Use a laptop with a camera and a quiet room:`} /></div>
              <div className="flex flex-wrap gap-2">
                <Button href={link.report} icon={<FileText />}>Open report page</Button>
                <Button href={link.path} target="_blank" icon={<ExternalLink />}>Preview candidate page</Button>
                <Button variant="ghost" href="/app/interviews" icon={<ArrowLeft />}>Back to all interviews</Button>
              </div>
            </CardBody>
          </Card>
        </div>
      )}
    </>
  )
}

function Group({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white [&_svg]:size-4 [&_svg]:text-brand-600 dark:[&_svg]:text-brand-300">{icon}{title}</h3>
      <div className="divide-y divide-slate-100 dark:divide-ink-800">{children}</div>
    </div>
  )
}
