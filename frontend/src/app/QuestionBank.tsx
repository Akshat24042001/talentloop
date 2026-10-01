// Question bank for proctored tests: add and edit questions, import from Excel, review AI drafts before saving.
import { Download, FileUp, Library, Pencil, Plus, Sparkles, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Alert, Badge, Button, Card, Field, Input, Modal, Select, Switch, Textarea, toast } from '../components/ui'
import { Empty, ErrorBox, Loading, PageHeader, Pager, useApi } from '../components/kit'
import { api } from '../lib/api'
import { useMe } from '../lib/session'

interface Q { id?: string; section: string; section_label?: string; difficulty: string; kind: 'single' | 'multiple' | 'numeric'; text: string; options: string[]; answer: number[]; marks: number; explanation: string; active?: boolean; tags?: string[] }
interface List { total: number; items: Q[]; stats: Record<string, Record<string, number>>; sections: { id: string; label: string }[] }
const LETTERS = 'ABCDEF'
const blank = (section = 'quantitative'): Q => ({ section, difficulty: 'medium', kind: 'single', text: '', options: ['', '', '', ''], answer: [], marks: 1, explanation: '' })

export default function QuestionBank() {
  const me = useMe()
  const [f, setF] = useState({ section: '', difficulty: '', q: '' }), [page, setPage] = useState(1)
  const qs = new URLSearchParams({ ...f, page: String(page), limit: '50' }).toString()
  const { data, error, reload } = useApi<List>(`/api/questions?${qs}`)
  const [edit, setEdit] = useState<Q | null>(null), [draft, setDraft] = useState(false), [imp, setImp] = useState(false)
  const canEdit = me.can.manage_jobs
  if (error) return <ErrorBox error={error} retry={reload} />
  async function toggle(q: Q) { try { await api(`/api/questions/${q.id}`, { method: 'PATCH', json: { active: !q.active } }); reload() } catch (e: any) { toast(e.message) } }
  async function del(q: Q) { if (!confirm('Delete this question? Papers already given keep their copy of the score.')) return; try { await api(`/api/questions/${q.id}`, { method: 'DELETE' }); reload() } catch (e: any) { toast(e.message) } }
  async function sample() { try { const r = await api('/api/questions/sample', { method: 'POST' }); toast(`${r.created} starter questions added`); reload() } catch (e: any) { toast(e.message) } }
  const sections = data?.sections || []
  const totals = Object.entries(data?.stats || {})
  return (
    <>
      <PageHeader title="Question bank" description="Tests draw a different random paper for each candidate from the active questions here, by section and difficulty."
        actions={canEdit && <>
          <Button icon={<Download />} href="/api/questions/template.xlsx">Excel template</Button>
          <Button icon={<FileUp />} onClick={() => setImp(true)}>Import</Button>
          <Button icon={<Sparkles />} onClick={() => setDraft(true)}>Draft with AI</Button>
          <Button variant="primary" icon={<Plus />} onClick={() => setEdit(blank(f.section || 'quantitative'))}>Add question</Button></>} />
      {totals.length > 0 && <div className="mb-4 flex flex-wrap gap-2">{totals.map(([sec, n]) => (
        <button key={sec} onClick={() => { setF({ ...f, section: f.section === sec ? '' : sec }); setPage(1) }} className={`rounded-xl px-3 py-2 text-left text-sm ring-1 ${f.section === sec ? 'bg-brand-50 ring-brand-300 dark:bg-brand-500/15' : 'bg-white ring-slate-200 dark:bg-ink-900 dark:ring-ink-700'}`}>
          <div className="font-semibold">{sections.find(s => s.id === sec)?.label || sec}</div><div className="text-xs text-slate-500">{n.easy} easy · {n.medium} medium · {n.hard} hard</div></button>))}</div>}
      <Card className="mb-3 flex flex-wrap gap-2 p-3">
        <Input type="search" aria-label="Search questions" className="min-w-48 flex-1" placeholder="Search question text" value={f.q} onChange={e => { setF({ ...f, q: e.target.value }); setPage(1) }} />
        <Select aria-label="Section" className="w-48" value={f.section} onChange={e => { setF({ ...f, section: e.target.value }); setPage(1) }}><option value="">All sections</option>{sections.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}</Select>
        <Select aria-label="Difficulty" className="w-36" value={f.difficulty} onChange={e => { setF({ ...f, difficulty: e.target.value }); setPage(1) }}><option value="">Any level</option>{['easy', 'medium', 'hard'].map(d => <option key={d}>{d}</option>)}</Select>
      </Card>
      {!data ? <Loading /> : !data.items.length ? (
        <Card><Empty icon={<Library />} title={data.total || f.q || f.section || f.difficulty ? 'No questions match' : 'Your question bank is empty'}
          action={canEdit && !f.q && !f.section && !f.difficulty && <Button variant="primary" onClick={sample}>Load about 60 starter questions</Button>}>
          Import your own from Excel, draft some with AI, or start with the starter set (quantitative, logical, English, IT hardware, sales awareness).</Empty></Card>
      ) : <>
        <ul className="space-y-2">{data.items.map(q => (
          <Card key={q.id} className={`p-4 ${q.active === false ? 'opacity-60' : ''}`}>
            <div className="flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex flex-wrap gap-1.5"><Badge>{q.section_label}</Badge><Badge tone={q.difficulty === 'hard' ? 'danger' : q.difficulty === 'easy' ? 'success' : 'warning'}>{q.difficulty}</Badge>
                  {q.kind !== 'single' && <Badge tone="violet">{q.kind === 'multiple' ? 'Several answers' : 'Number answer'}</Badge>}{q.active === false && <Badge>Inactive</Badge>}</div>
                <p className="whitespace-pre-line text-sm font-medium">{q.text}</p>
                {q.kind === 'numeric' ? <p className="mt-1 text-sm text-emerald-700 dark:text-emerald-400">Answer: {q.answer[0]}</p> : (
                  <ol className="mt-1.5 grid gap-1 text-sm sm:grid-cols-2">{q.options.map((o, i) => <li key={i} className={q.answer.includes(i) ? 'font-semibold text-emerald-700 dark:text-emerald-400' : 'text-slate-600 dark:text-slate-300'}>{LETTERS[i]}. {o}</li>)}</ol>)}
              </div>
              {canEdit && <div className="flex items-center gap-1">
                <Switch id={`qa-${q.id}`} checked={q.active !== false} onChange={() => toggle(q)} label={<span className="sr-only">Active</span>} />
                <Button size="sm" variant="ghost" aria-label="Edit question" icon={<Pencil />} onClick={() => setEdit(q)} />
                <Button size="sm" variant="ghost" aria-label="Delete question" icon={<Trash2 />} onClick={() => del(q)} /></div>}
            </div>
          </Card>))}</ul>
        <Pager page={page} total={data.total} limit={50} onPage={setPage} />
      </>}
      {edit && <Editor q={edit} sections={sections} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
      {draft && <Drafter sections={sections} onClose={() => setDraft(false)} onSaved={() => { setDraft(false); reload() }} />}
      {imp && <Importer onClose={() => setImp(false)} onDone={reload} />}
    </>
  )
}

function QuestionFields({ q, set, sections }: { q: Q; set: (q: Q) => void; sections: { id: string; label: string }[] }) {
  const toggleAns = (i: number) => set({ ...q, answer: q.kind === 'single' ? [i] : q.answer.includes(i) ? q.answer.filter(x => x !== i) : [...q.answer, i].sort() })
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <Field label="Section" htmlFor="qe-s"><Select id="qe-s" value={q.section} onChange={e => set({ ...q, section: e.target.value })}>{sections.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          {!sections.some(s => s.id === q.section) && <option value={q.section}>{q.section}</option>}</Select></Field>
        <Field label="Level" htmlFor="qe-d"><Select id="qe-d" value={q.difficulty} onChange={e => set({ ...q, difficulty: e.target.value })}>{['easy', 'medium', 'hard'].map(d => <option key={d}>{d}</option>)}</Select></Field>
        <Field label="Type" htmlFor="qe-k"><Select id="qe-k" value={q.kind} onChange={e => set({ ...q, kind: e.target.value as Q['kind'], answer: [] })}><option value="single">One answer</option><option value="multiple">Several answers</option><option value="numeric">Number</option></Select></Field>
      </div>
      <Field label="Question" htmlFor="qe-t"><Textarea id="qe-t" rows={3} value={q.text} onChange={e => set({ ...q, text: e.target.value })} /></Field>
      {q.kind === 'numeric' ? <Field label="Correct answer" htmlFor="qe-n"><Input id="qe-n" type="number" step="any" value={q.answer[0] ?? ''} onChange={e => set({ ...q, answer: e.target.value === '' ? [] : [+e.target.value] })} /></Field> : (
        <div className="space-y-1.5"><div className="text-sm font-medium">Options <span className="font-normal text-slate-500">(tick the correct {q.kind === 'single' ? 'one' : 'ones'})</span></div>
          {q.options.map((o, i) => <div key={i} className="flex items-center gap-2">
            <input type={q.kind === 'single' ? 'radio' : 'checkbox'} name="qe-ans" aria-label={`Option ${LETTERS[i]} is correct`} checked={q.answer.includes(i)} onChange={() => toggleAns(i)} />
            <span className="w-4 text-sm font-semibold">{LETTERS[i]}</span><Input aria-label={`Option ${LETTERS[i]}`} value={o} onChange={e => set({ ...q, options: q.options.map((x, j) => j === i ? e.target.value : x) })} />
            {q.options.length > 2 && <Button size="sm" variant="ghost" aria-label="Remove option" icon={<Trash2 />} onClick={() => set({ ...q, options: q.options.filter((_, j) => j !== i), answer: q.answer.filter(x => x !== i).map(x => x > i ? x - 1 : x) })} />}</div>)}
          {q.options.length < 6 && <Button size="sm" icon={<Plus />} onClick={() => set({ ...q, options: [...q.options, ''] })}>Add option</Button>}
        </div>)}
      <div className="grid grid-cols-[100px_1fr] gap-2">
        <Field label="Marks" htmlFor="qe-m"><Input id="qe-m" type="number" min={0.25} max={10} step={0.25} value={q.marks} onChange={e => set({ ...q, marks: +e.target.value })} /></Field>
        <Field label="Explanation (for your team)" htmlFor="qe-x"><Input id="qe-x" value={q.explanation} onChange={e => set({ ...q, explanation: e.target.value })} /></Field>
      </div>
    </div>
  )
}

function Editor({ q: init, sections, onClose, onSaved }: { q: Q; sections: { id: string; label: string }[]; onClose: () => void; onSaved: () => void }) {
  const [q, setQ] = useState<Q>(init), [busy, setBusy] = useState(false)
  async function save() {
    setBusy(true)
    try { await api(init.id ? `/api/questions/${init.id}` : '/api/questions', { method: init.id ? 'PATCH' : 'POST', json: q }); toast('Question saved'); onSaved() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  return (
    <Modal open onOpenChange={o => !o && onClose()} title={init.id ? 'Edit question' : 'Add a question'}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save}>Save</Button></>}>
      <div className="mt-4 max-h-[65vh] overflow-y-auto pr-1"><QuestionFields q={q} set={setQ} sections={sections} /></div>
    </Modal>
  )
}

function Drafter({ sections, onClose, onSaved }: { sections: { id: string; label: string }[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ section: 'domain', topic: '', difficulty: 'medium', count: 5, role: '' })
  const [items, setItems] = useState<(Q & { keep: boolean })[] | null>(null), [busy, setBusy] = useState(false), [err, setErr] = useState('')
  async function run() {
    setBusy(true); setErr('')
    try {
      const r = await api<{ items: any[] }>('/api/questions/draft', { json: f })
      setItems(r.items.map(x => ({ ...blank(f.section), ...x, section: f.section, answer: Array.isArray(x.answer) ? x.answer : [x.answer], keep: true })))
    } catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  async function save() {
    setBusy(true)
    try { const r = await api('/api/questions', { json: { questions: items!.filter(x => x.keep).map(({ keep: _k, ...q }) => q) } }); toast(`${r.created} question(s) saved`); onSaved() } catch (e: any) { setErr(e.message) }
    setBusy(false)
  }
  return (
    <Modal open onOpenChange={o => !o && onClose()} title="Draft questions with AI" description="Nothing is saved until you review the drafts. Check every answer: AI can be wrong."
      footer={items ? <><Button onClick={() => setItems(null)}>Back</Button><Button variant="primary" loading={busy} disabled={!items.some(x => x.keep)} onClick={save}>Save {items.filter(x => x.keep).length} question(s)</Button></>
        : <><Button onClick={onClose}>Cancel</Button><Button variant="primary" icon={<Sparkles />} loading={busy} onClick={run}>Draft</Button></>}>
      <div className="mt-4 max-h-[65vh] space-y-3 overflow-y-auto pr-1">
        {err && <Alert tone="danger">{err}</Alert>}
        {!items ? <>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Section" htmlFor="dq-s"><Select id="dq-s" value={f.section} onChange={e => setF({ ...f, section: e.target.value })}>{sections.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}</Select></Field>
            <Field label="Level" htmlFor="dq-d"><Select id="dq-d" value={f.difficulty} onChange={e => setF({ ...f, difficulty: e.target.value })}>{['easy', 'medium', 'hard'].map(d => <option key={d}>{d}</option>)}</Select></Field>
            <Field label="How many" htmlFor="dq-n"><Input id="dq-n" type="number" min={1} max={15} value={f.count} onChange={e => setF({ ...f, count: +e.target.value })} /></Field>
            <Field label="For the role (optional)" htmlFor="dq-r"><Input id="dq-r" value={f.role} onChange={e => setF({ ...f, role: e.target.value })} /></Field>
          </div>
          <Field label="Topic" htmlFor="dq-t"><Input id="dq-t" value={f.topic} onChange={e => setF({ ...f, topic: e.target.value })} placeholder="e.g. percentages and profit & loss, or basic networking" /></Field>
        </> : items.map((q, i) => (
          <div key={i} className="rounded-xl p-3 ring-1 ring-slate-200 dark:ring-ink-700">
            <label className="mb-2 flex items-center gap-2 text-sm font-semibold"><input type="checkbox" checked={q.keep} onChange={e => setItems(items.map((x, j) => j === i ? { ...x, keep: e.target.checked } : x))} />Keep draft {i + 1}</label>
            {q.keep && <QuestionFields q={q} set={nq => setItems(items.map((x, j) => j === i ? { ...x, ...nq } : x))} sections={sections} />}
          </div>))}
      </div>
    </Modal>
  )
}

function Importer({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [res, setRes] = useState<{ created: number; errors: string[] } | null>(null), [busy, setBusy] = useState(false)
  async function upload(file: File) {
    setBusy(true)
    try { const fd = new FormData(); fd.append('file', file); const r = await api('/api/questions/import', { body: fd }); setRes(r); onDone() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  return (
    <Modal open onOpenChange={o => !o && onClose()} title="Import questions" description="Excel (.xlsx) or CSV with the template's columns: section, difficulty, type, question, option a-f, answer (A, or A,C), marks, explanation."
      footer={<Button onClick={onClose}>Close</Button>}>
      <div className="mt-4 space-y-3">
        <Button icon={<Download />} href="/api/questions/template.xlsx">Download the template</Button>
        <label className="flex cursor-pointer items-center gap-3 rounded-2xl border-2 border-dashed border-slate-200 p-5 hover:border-brand-300 dark:border-ink-700">
          <FileUp className="size-6 text-brand-500" /><span className="text-sm font-semibold">{busy ? 'Importing…' : 'Choose a file'}</span>
          <input type="file" accept=".xlsx,.xlsm,.csv" className="sr-only" onChange={e => { const x = e.target.files?.[0]; if (x) upload(x) }} /></label>
        {res && <Alert tone={res.errors.length ? 'warning' : 'success'} title={`${res.created} question(s) imported`}>
          {res.errors.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs">{res.errors.map((x, i) => <li key={i}>{x}</li>)}</ul>}</Alert>}
      </div>
    </Modal>
  )
}
