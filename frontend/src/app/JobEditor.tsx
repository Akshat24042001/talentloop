import { Check, ChevronLeft, ChevronRight, FileUp, Plus, Save, Send, Sparkles, Trash2, Wand2, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Badge, Button, Card, Field, Input, Select, Switch, Textarea, cn, toast } from '../components/ui'
import { BackLink, ErrorBox, ListInput, Loading, PageHeader, TagInput } from '../components/kit'
import { api } from '../lib/api'
import { navigate } from '../lib/router'
import { useMe, useSession } from '../lib/session'
import { DatePicker } from '../components/pickers'
import { ask } from '../components/dialogs'

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
  // One section at a time (tabs), so the form never turns into one long scroll.
  const go = (sid: string) => { setActive(sid); window.scrollTo({ top: 0, behavior: 'smooth' }) }

  async function save(publish: boolean) {
    setTouched(true); setErr('')
    if (!v?.title) { setErr('A job title is required.'); return }
    if (publish && missing.length) {
      setErr('Fill in before publishing: ' + missing.map(f => f.label).join(', '))
      const first = meta?.sections.find(sec => sec.fields.some(f => missing.includes(f))); if (first) go(first.id)
      return
    }
    setSaving(publish ? 'publish' : 'save')
    try {
      const fields = Object.fromEntries(Object.entries(v).map(([k, x]) => [k, Array.isArray(x) ? x.filter(y => typeof y !== 'string' || y.trim()) : x]))
      let jid = id
      if (id) jid = (await api(`/api/jobs/${id}`, { method: 'PATCH', json: { fields, ...(publish && perm === 'manage' ? { status: 'open' } : {}) } })).ref
      else jid = (await api('/api/jobs', { json: { fields, status: publish ? 'open' : 'draft' } })).ref
      toast(publish ? 'Job published' : 'Saved')
      navigate(`/app/jobs/${jid}`)
    } catch (e: any) { setErr(e.message) }
    setSaving('')
  }
  async function aiWrite() {
    if (!v?.title) { setErr('Add a job title first.'); return }
    setAiBusy(true); setErr('')
    try {
      // The AI works from what is on screen now (unsaved edits included); nothing is saved until you press Save.
      const out = await api<Record<string, unknown>>(id ? `/api/jobs/${id}/ai-write` : '/api/jobs/ai-write', { json: { fields: v } })
      const label = (k: string) => (meta?.sections || []).flatMap(x => x.fields).find(f => f.key === k)?.label || k
      const filled = Object.keys(out).filter(k => !empty(out[k]) && !empty(v[k]))
      let replace = false
      if (filled.length) replace = await ask(`Replace what you wrote in ${filled.map(label).join(', ')} with the AI draft? Choose "Keep mine" to fill only the empty fields.`,
        { title: 'Replace your text?', confirm: 'Replace with AI draft', cancel: 'Keep mine', danger: false })
      const take = Object.keys(out).filter(k => !empty(out[k]) && (replace || empty(v[k])))
      if (take.length) {
        setV(o => ({ ...o!, ...Object.fromEntries(take.map(k => [k, out[k]])) }))
        toast(`AI wrote ${take.map(label).join(', ')}. Review it, then Save.`)
      } else toast('Nothing changed: those fields already have your text.')
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
              return <button type="button" key={s.id} aria-current={active === s.id ? 'step' : undefined}
                onClick={() => go(s.id)} className={cn('flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm', active === s.id ? 'bg-white font-semibold text-slate-900 shadow-sm ring-1 ring-slate-200 dark:bg-ink-900 dark:text-white dark:ring-ink-700' : 'text-slate-600 hover:bg-white/60 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-ink-900/60 dark:hover:text-white')}>
                {s.title}{miss ? <span className="grid size-5 place-items-center rounded-full bg-red-100 text-[11px] font-bold text-red-700 dark:bg-red-500/20 dark:text-red-300">{miss}</span> : <Check className="size-3.5 text-emerald-500" />}</button>
            })}
            <div className="mt-4 rounded-xl bg-white p-3 text-xs ring-1 ring-slate-200 dark:bg-ink-900 dark:ring-ink-700">
              {missing.length ? <><b className="text-slate-800 dark:text-slate-100">{missing.length} required left</b><p className="mt-1 text-slate-500">{missing.map(f => f.label).join(', ')}</p></>
                : <span className="flex items-center gap-1.5 font-semibold text-emerald-600"><Check className="size-3.5" />Ready to publish</span>}
            </div>
          </div>
        </nav>
        <div className="min-w-0 pb-28">
          <div className="no-print -mx-1 mb-4 flex gap-1.5 overflow-x-auto px-1 pb-1 lg:hidden" role="tablist" aria-label="Sections">
            {meta.sections.map(s => { const miss = s.fields.filter(f => missing.includes(f)).length
              return <button key={s.id} type="button" role="tab" aria-selected={active === s.id} onClick={() => go(s.id)}
                className={cn('flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-medium ring-1 ring-inset', active === s.id ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white text-slate-600 ring-slate-200 dark:bg-ink-850 dark:text-slate-300 dark:ring-ink-700')}>
                {s.title}{miss > 0 && <span className={cn('grid size-4 place-items-center rounded-full text-[10px] font-bold', active === s.id ? 'bg-white/25' : 'bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-300')}>{miss}</span>}</button> })}
          </div>
          {meta.sections.map((s, i) => s.id !== active ? null : (
            <Card key={s.id} id={`sec-${s.id}`} className="p-5 sm:p-6 animate-rise">
              <div className="flex items-start justify-between gap-3"><div>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Step {i + 1} of {meta.sections.length}</div>
                <h2 className="mt-1 text-base font-semibold">{s.title}</h2>
                <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">{s.description}</p></div></div>
              <div className="mt-5 grid gap-5 sm:grid-cols-2">
                {s.fields.filter(f => visible(f, v)).map(f => <FieldInput key={f.key} f={f} value={v[f.key]} onChange={x => set(f.key, x)} req={isRequired(f, v)} invalid={touched && missing.includes(f)} skills={meta.skills} />)}
              </div>
              <div className="mt-6 flex items-center justify-between border-t border-slate-100 pt-4 dark:border-ink-800">
                {i > 0 ? <Button variant="ghost" icon={<ChevronLeft />} onClick={() => go(meta.sections[i - 1].id)}>{meta.sections[i - 1].title}</Button> : <span />}
                {i < meta.sections.length - 1 && <Button variant="primary" onClick={() => go(meta.sections[i + 1].id)}>Next: {meta.sections[i + 1].title}<ChevronRight className="size-4" /></Button>}
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
  const wide = ['textarea', 'list', 'questions', 'multiselect', 'skills', 'tags', 'benefits'].includes(f.type) || f.key === 'title'
  const label = <>{f.label}{req && <span className="text-red-500"> *</span>}</>
  const ring = invalid ? 'ring-2 ring-red-400' : ''
  let input
  switch (f.type) {
    case 'select':
      input = <Select id={id} className={ring} value={value ?? ''} onChange={e => onChange(e.target.value)}><option value="">Select…</option>{f.options!.map(o => <option key={o}>{o}</option>)}</Select>; break
    case 'number':
      input = <Input id={id} className={ring} type="number" inputMode="decimal" min={f.min} max={f.max} placeholder={f.placeholder} value={value ?? ''} onChange={e => onChange(e.target.value === '' ? '' : +e.target.value)} />; break
    case 'date':
      input = <DatePicker id={id} value={value ?? ''} onChange={v => onChange(v)} />; break
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
    case 'benefits':
      input = <Benefits value={value || []} onChange={onChange} />; break
    default:
      input = <Input id={id} className={ring} placeholder={f.placeholder} maxLength={f.max} value={value ?? ''} onChange={e => onChange(e.target.value)} />
  }
  return <Field className={wide ? 'sm:col-span-2' : ''} label={label} htmlFor={id} hint={f.help}>{input}</Field>
}

/** The company's own benefits list: pick the ones this job offers, add new ones (saved for the company), remove old ones. */
function Benefits({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const me = useMe(), { refresh } = useSession()
  const [list, setList] = useState<string[]>(me.org?.settings?.benefits || []), [text, setText] = useState(''), [busy, setBusy] = useState(false)
  const canManage = me.can.manage_jobs
  const all = [...list, ...value.filter(x => !list.some(y => y.toLowerCase() === x.toLowerCase()))]
  const on = (x: string) => value.some(y => y.toLowerCase() === x.toLowerCase())
  async function add() {
    const x = text.trim().replace(/\s+/g, ' ')
    if (!x) return
    if (!on(x)) onChange([...value, x])
    setText('')
    if (!canManage || list.some(y => y.toLowerCase() === x.toLowerCase())) return
    setBusy(true)
    try { const r = await api('/api/org/benefits', { json: { add: x } }); setList(r.benefits); refresh() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  async function remove(x: string) {
    if (!await ask(`Remove "${x}" from your company's benefits list? Jobs that already list it keep it until you edit them.`)) return
    try { const r = await api('/api/org/benefits', { json: { remove: x } }); setList(r.benefits); refresh() } catch (e: any) { toast(e.message) }
  }
  return (
    <div className="space-y-2.5">
      {all.length ? <div className="flex flex-wrap gap-2">{all.map(x => (
        <span key={x} className={cn('inline-flex items-center rounded-full text-[13px] font-medium ring-1 ring-inset transition-colors',
          on(x) ? 'bg-brand-600 text-white ring-brand-600 dark:bg-brand-500 dark:ring-brand-400' : 'bg-white text-slate-700 ring-slate-200 hover:bg-slate-50 dark:bg-ink-850 dark:text-slate-200 dark:ring-ink-700 dark:hover:bg-ink-800')}>
          <button type="button" aria-pressed={on(x)} onClick={() => onChange(on(x) ? value.filter(y => y.toLowerCase() !== x.toLowerCase()) : [...value, x])} className="py-1.5 pl-3 pr-2">
            {on(x) && <Check className="mr-1 inline size-3" />}{x}</button>
          {canManage && list.includes(x) && <button type="button" aria-label={`Remove ${x} from the company list`} onClick={() => remove(x)}
            className={cn('mr-1.5 grid size-5 place-items-center rounded-full', on(x) ? 'hover:bg-white/20' : 'text-slate-400 hover:bg-slate-200 hover:text-slate-700 dark:hover:bg-ink-700 dark:hover:text-white')}><X className="size-3" /></button>}
        </span>))}</div>
        : <p className="text-sm text-slate-500 dark:text-slate-400">No benefits yet. Add the ones your company offers; they're saved for your other jobs.</p>}
      <div className="flex gap-2">
        <Input aria-label="New benefit" placeholder="Add a benefit, e.g. Health insurance" value={text} maxLength={80} onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add() } }} />
        <Button type="button" icon={<Plus />} loading={busy} disabled={!text.trim()} onClick={add}>Add</Button>
      </div>
    </div>
  )
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
