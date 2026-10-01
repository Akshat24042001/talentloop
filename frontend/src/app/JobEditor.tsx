import { Check, FileUp, Save, Send, Sparkles, Trash2, Wand2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Badge, Button, Card, Field, Input, Select, Switch, Textarea, cn, toast } from '../components/ui'
import { BackLink, ErrorBox, ListInput, Loading, PageHeader, TagInput } from '../components/kit'
import { api } from '../lib/api'
import { navigate } from '../lib/router'
import { useMe } from '../lib/session'

interface FieldDef {
  key: string; label: string; type: string; required?: boolean; required_unless?: Record<string, unknown>; show_if?: Record<string, unknown>
  options?: string[]; placeholder?: string; help?: string; min?: number; max?: number; rows?: number; default?: unknown
}
interface Section { id: string; title: string; description: string; fields: FieldDef[] }
export interface Meta { sections: Section[]; defaults: Record<string, unknown>; required: string[]; skills: string[]; stages: { id: string; label: string }[] }
type Q = { id: string; question: string; kind: string; required: boolean; required_answer?: string | null; min_number?: number | null }

let metaP: Promise<Meta> | null = null
export const loadMeta = () => (metaP ||= api<Meta>('/api/meta/job-fields'))

const visible = (f: FieldDef, v: Record<string, any>) => !f.show_if || Object.entries(f.show_if).every(([k, x]) => v[k] === x)
const isRequired = (f: FieldDef, v: Record<string, any>) => !!f.required || (!!f.required_unless && !Object.entries(f.required_unless).every(([k, x]) => v[k] === x))
const empty = (x: unknown) => x === undefined || x === null || x === '' || (Array.isArray(x) && !x.length)

export default function JobEditor({ id }: { id?: string }) {
  const me = useMe()
  const [meta, setMeta] = useState<Meta | null>(null)
  const [v, setV] = useState<Record<string, any> | null>(null)
  const [status, setStatus] = useState('draft'), [perm, setPerm] = useState('manage')
  const [err, setErr] = useState(''), [saving, setSaving] = useState(''), [touched, setTouched] = useState(false), [aiBusy, setAiBusy] = useState(false)
  const [active, setActive] = useState('basics')
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    loadMeta().then(async m => {
      setMeta(m)
      if (id) {
        const j = await api(`/api/jobs/${id}`)
        setV({ ...m.defaults, ...j.fields }); setStatus(j.status); setPerm(j.permission)
      } else setV({ ...m.defaults, currency: me.org?.settings?.default_currency || 'INR', top_n: me.org?.settings?.match_top_n || 5 })
    }).catch(e => setErr(e.message))
  }, [id])                                                  // eslint-disable-line react-hooks/exhaustive-deps

  const missing = useMemo(() => !meta || !v ? [] : meta.sections.flatMap(s => s.fields).filter(f => isRequired(f, v) && empty(v[f.key]) && !(f.type === 'number' && v[f.key] === 0)), [meta, v])
  const set = (k: string, x: unknown) => setV(o => ({ ...o!, [k]: x }))

  async function save(publish: boolean) {
    setTouched(true); setErr('')
    if (!v?.title) { setErr('A job title is required.'); return }
    if (publish && missing.length) { setErr('Fill in before publishing: ' + missing.map(f => f.label).join(', ')); return }
    setSaving(publish ? 'publish' : 'save')
    try {
      const fields = Object.fromEntries(Object.entries(v).map(([k, x]) => [k, Array.isArray(x) ? x.filter(y => typeof y !== 'string' || y.trim()) : x]))
      let jid = id
      if (id) await api(`/api/jobs/${id}`, { method: 'PATCH', json: { fields, ...(publish && perm === 'manage' ? { status: 'open' } : {}) } })
      else jid = (await api('/api/jobs', { json: { fields, status: publish ? 'open' : 'draft' } })).id
      toast(publish ? 'Job published' : 'Saved')
      navigate(`/app/jobs/${jid}`)
    } catch (e: any) { setErr(e.message) }
    setSaving('')
  }
  async function aiWrite() {
    if (!v?.title) { setErr('Add a job title first.'); return }
    setAiBusy(true); setErr('')
    try {
      let jid = id
      if (!jid) { jid = (await api('/api/jobs', { json: { fields: v, status: 'draft' } })).id; history.replaceState(null, '', `/app/jobs/${jid}/edit`) }
      const out = await api(`/api/jobs/${jid}/ai-write`, { method: 'POST' })
      setV(o => ({ ...o!, ...Object.fromEntries(Object.entries(out).filter(([k, x]) => !empty(x) && empty(o![k]))) }))
      toast('Draft written. Review and edit before publishing.')
      if (!id) navigate(`/app/jobs/${jid}/edit`, { replace: true, keepScroll: true })
    } catch (e: any) { setErr(e.message) }
    setAiBusy(false)
  }
  async function importFile(f: File) {
    const fd = new FormData(); fd.append('file', f)
    try {
      const r = await api('/api/jobs/parse-jd', { method: 'POST', body: fd })
      setV(o => {
        const n = { ...o! }
        for (const [k, x] of Object.entries(r.fields || {})) if (!empty(x) && empty(n[k])) n[k] = x
        return n
      })
      toast('Imported. Check the highlighted required fields.')
    } catch (e: any) { toast(e.message) }
  }

  if (err && !meta) return <ErrorBox error={err} />
  if (!meta || !v) return <Loading />
  return (
    <>
      <PageHeader back={<BackLink href={id ? `/app/jobs/${id}` : '/app/jobs'}>{id ? 'Back to job' : 'All jobs'}</BackLink>}
        title={id ? `Edit: ${v.title || 'job'}` : 'New job'}
        description={<>Only fields marked <span className="text-red-500">*</span> are needed to publish. Everything else makes the post and the matching better.</>}
        actions={<>
          <input ref={fileRef} type="file" accept=".pdf,.docx,.txt" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) importFile(f); e.target.value = '' }} />
          <Button icon={<FileUp />} onClick={() => fileRef.current?.click()}>Import JD file</Button>
          <Button variant="subtle" icon={<Wand2 />} loading={aiBusy} onClick={aiWrite}>Write with AI</Button>
        </>} />
      <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
        <nav className="no-print hidden lg:block">
          <div className="sticky top-6 space-y-1">
            {meta.sections.map(s => {
              const miss = s.fields.filter(f => missing.includes(f)).length
              return <a key={s.id} href={`#sec-${s.id}`} onClick={() => setActive(s.id)} className={cn('flex items-center justify-between rounded-lg px-3 py-2 text-sm', active === s.id ? 'bg-white font-semibold shadow-sm ring-1 ring-slate-200 dark:bg-ink-900 dark:ring-ink-700' : 'text-slate-600 hover:text-slate-900 dark:text-slate-300')}>
                {s.title}{miss ? <span className="grid size-5 place-items-center rounded-full bg-red-100 text-[11px] font-bold text-red-700 dark:bg-red-500/20 dark:text-red-300">{miss}</span> : <Check className="size-3.5 text-emerald-500" />}</a>
            })}
            <div className="mt-4 rounded-xl bg-white p-3 text-xs ring-1 ring-slate-200 dark:bg-ink-900 dark:ring-ink-700">
              {missing.length ? <><b className="text-slate-800 dark:text-slate-100">{missing.length} required left</b><p className="mt-1 text-slate-500">{missing.map(f => f.label).join(', ')}</p></>
                : <span className="flex items-center gap-1.5 font-semibold text-emerald-600"><Check className="size-3.5" />Ready to publish</span>}
            </div>
          </div>
        </nav>
        <div className="min-w-0 space-y-5 pb-28">
          {meta.sections.map(s => (
            <Card key={s.id} id={`sec-${s.id}`} className="scroll-mt-6 p-5 sm:p-6" onFocusCapture={() => setActive(s.id)}>
              <h2 className="text-base font-semibold">{s.title}</h2>
              <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">{s.description}</p>
              <div className="mt-5 grid gap-5 sm:grid-cols-2">
                {s.fields.filter(f => visible(f, v)).map(f => <FieldInput key={f.key} f={f} value={v[f.key]} onChange={x => set(f.key, x)} req={isRequired(f, v)} invalid={touched && missing.includes(f)} skills={meta.skills} />)}
              </div>
            </Card>
          ))}
        </div>
      </div>
      <div className="no-print fixed inset-x-0 bottom-0 z-20 border-t border-slate-200 bg-white/90 backdrop-blur dark:border-ink-700 dark:bg-ink-900/90 lg:left-64">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-8">
          <div className="min-w-0 text-sm">{err ? <span className="text-red-600 dark:text-red-400">{err}</span>
            : <span className="text-slate-500 dark:text-slate-400">{status === 'open' ? <Badge tone="success">Live</Badge> : <Badge>Draft</Badge>} {missing.length ? `${missing.length} required field${missing.length > 1 ? 's' : ''} left` : 'All required fields done'}</span>}</div>
          <div className="flex gap-2">
            <Button icon={<Save />} loading={saving === 'save'} onClick={() => save(false)}>{status === 'open' ? 'Save changes' : 'Save draft'}</Button>
            {perm === 'manage' && status !== 'open' && <Button variant="primary" icon={<Send />} loading={saving === 'publish'} onClick={() => save(true)}>Publish</Button>}
          </div>
        </div>
      </div>
    </>
  )
}

function FieldInput({ f, value, onChange, req, invalid, skills }: { f: FieldDef; value: any; onChange: (v: any) => void; req: boolean; invalid: boolean; skills: string[] }) {
  const id = `f-${f.key}`
  const wide = ['textarea', 'list', 'questions', 'multiselect', 'skills', 'tags'].includes(f.type) || f.key === 'title'
  const label = <>{f.label}{req && <span className="text-red-500"> *</span>}</>
  const ring = invalid ? 'ring-2 ring-red-400' : ''
  let input
  switch (f.type) {
    case 'select':
      input = <Select id={id} className={ring} value={value ?? ''} onChange={e => onChange(e.target.value)}><option value="">Select…</option>{f.options!.map(o => <option key={o}>{o}</option>)}</Select>; break
    case 'number':
      input = <Input id={id} className={ring} type="number" inputMode="decimal" min={f.min} max={f.max} placeholder={f.placeholder} value={value ?? ''} onChange={e => onChange(e.target.value === '' ? '' : +e.target.value)} />; break
    case 'date':
      input = <Input id={id} type="date" value={value ?? ''} onChange={e => onChange(e.target.value)} />; break
    case 'textarea':
      input = <Textarea id={id} rows={f.rows || 3} className={cn('min-h-0', ring)} placeholder={f.placeholder} value={value ?? ''} onChange={e => onChange(e.target.value)} />; break
    case 'toggle':
      return <div className="sm:col-span-2"><Switch id={id} checked={!!value} onChange={onChange} label={f.label} description={f.help} /></div>
    case 'tags': case 'skills':
      input = <div className={cn('rounded-xl', ring)}><TagInput id={id} value={value || []} onChange={onChange} placeholder={f.placeholder || (f.type === 'skills' ? 'Type a skill and press Enter' : 'Type and press Enter')} suggestions={f.type === 'skills' ? skills : undefined} /></div>; break
    case 'list':
      input = <ListInput value={value || []} onChange={onChange} placeholder={f.placeholder} />; break
    case 'multiselect':
      input = <div className="flex flex-wrap gap-2">{f.options!.map(o => { const on = (value || []).includes(o); return (
        <button type="button" key={o} onClick={() => onChange(on ? value.filter((x: string) => x !== o) : [...(value || []), o])}
          className={cn('rounded-full px-3 py-1.5 text-[13px] font-medium ring-1 ring-inset transition-colors', on ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white text-slate-600 ring-slate-200 hover:bg-slate-50 dark:bg-ink-850 dark:text-slate-300 dark:ring-ink-700')}>{on && <Check className="mr-1 inline size-3" />}{o}</button>) })}</div>; break
    case 'questions':
      input = <Questions value={value || []} onChange={onChange} />; break
    default:
      input = <Input id={id} className={ring} placeholder={f.placeholder} maxLength={f.max} value={value ?? ''} onChange={e => onChange(e.target.value)} />
  }
  return <Field className={wide ? 'sm:col-span-2' : ''} label={label} htmlFor={id} hint={f.help}>{input}</Field>
}

function Questions({ value, onChange }: { value: Q[]; onChange: (v: Q[]) => void }) {
  const upd = (i: number, p: Partial<Q>) => onChange(value.map((q, j) => j === i ? { ...q, ...p } : q))
  const presets = [
    { question: 'Are you legally authorised to work in this country?', kind: 'yes_no', required_answer: 'yes' },
    { question: 'Are you comfortable working from our office on the required days?', kind: 'yes_no', required_answer: 'yes' },
    { question: 'What is your notice period in days?', kind: 'number' },
    { question: 'Why are you interested in this role?', kind: 'text' },
  ]
  return (
    <div className="space-y-3">
      {value.map((q, i) => (
        <div key={i} className="rounded-xl p-3 ring-1 ring-slate-200 dark:ring-ink-700">
          <div className="flex gap-2">
            <Input aria-label="Question" value={q.question} onChange={e => upd(i, { question: e.target.value })} placeholder="Question for the candidate" />
            <Button type="button" variant="ghost" aria-label="Remove question" onClick={() => onChange(value.filter((_, j) => j !== i))} icon={<Trash2 />} />
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-[13px]">
            <Select aria-label="Answer type" className="w-auto py-1.5" value={q.kind} onChange={e => upd(i, { kind: e.target.value, required_answer: null, min_number: null })}>
              <option value="yes_no">Yes / No</option><option value="number">Number</option><option value="text">Short text</option></Select>
            {q.kind === 'yes_no' && <label className="flex items-center gap-2">Screen out unless answer is
              <Select className="w-auto py-1.5" value={q.required_answer || ''} onChange={e => upd(i, { required_answer: e.target.value || null })}><option value="">(any answer)</option><option value="yes">Yes</option><option value="no">No</option></Select></label>}
            {q.kind === 'number' && <label className="flex items-center gap-2">Minimum<Input type="number" className="w-24 py-1.5" value={q.min_number ?? ''} onChange={e => upd(i, { min_number: e.target.value === '' ? null : +e.target.value })} /></label>}
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={q.required} onChange={e => upd(i, { required: e.target.checked })} />Required</label>
          </div>
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" onClick={() => onChange([...value, { id: `q${Date.now() % 100000}`, question: '', kind: 'yes_no', required: true }])}>+ Add question</Button>
        {presets.filter(p => !value.some(q => q.question === p.question)).slice(0, 3).map(p => (
          <Button key={p.question} type="button" size="sm" variant="ghost" icon={<Sparkles />} onClick={() => onChange([...value, { id: `q${Date.now() % 100000}`, required: true, ...p }])}>{p.question.length > 34 ? p.question.slice(0, 32) + '…' : p.question}</Button>
        ))}
      </div>
      {value.some(q => q.required_answer) && <Alert tone="info">Candidates who give a screening-out answer are still saved and marked "Rejected" so you can review them.</Alert>}
    </div>
  )
}
