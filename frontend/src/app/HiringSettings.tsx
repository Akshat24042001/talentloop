// Company hiring settings: the FAQ the AI interviewer may answer from, mandatory application fields,
// HROne export columns and how long recordings are kept.
import { Download, Plus, Save, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Alert, Button, Card, CardBody, CardHeader, Field, Input, Select, Switch, Textarea, toast } from '../components/ui'
import { Loading, useApi } from '../components/kit'
import { api } from '../lib/api'

const FIELD_LABEL: Record<string, string> = { phone: 'Phone', location: 'Current city', expected_salary: 'Expected salary', notice_days: 'Notice period',
  total_experience_years: 'Total experience', current_company: 'Current company', linkedin: 'LinkedIn' }

export default function HiringSettings() {
  const [s, setS] = useState<Record<string, any> | null>(null), [busy, setBusy] = useState(false)
  const { data: hr } = useApi<{ fields: { id: string; label: string }[]; default_columns: { header: string; field: string }[] }>('/api/hrone/fields')
  useEffect(() => { api('/api/org').then(o => setS(o.settings)) }, [])
  if (!s) return <Loading />
  const set = (k: string, v: unknown) => setS({ ...s, [k]: v })
  const faq: { q: string; a: string }[] = s.faq || [], cols: { header: string; field: string }[] = s.hrone_columns || []
  async function save() {
    setBusy(true)
    try {
      const r = await api('/api/org', { method: 'PATCH', json: { settings: { faq: faq.filter(x => x.q.trim() && x.a.trim()), application_fields: s!.application_fields, hrone_columns: cols.filter(x => x.header.trim()),
        recording_retention_days: s!.recording_retention_days || 0, sender_name: s!.sender_name || '' } } })
      setS(r.settings); toast('Settings saved')
    } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  return (
    <div className="max-w-3xl space-y-5">
      <Card><CardHeader title="Mandatory application details" description="Candidates can't apply from the careers page without these. The talent pool form stays short." />
        <CardBody className="grid gap-3 sm:grid-cols-2">{Object.keys(FIELD_LABEL).map(k => (
          <Switch key={k} id={`af-${k}`} checked={!!s.application_fields?.[k]} onChange={v => set('application_fields', { ...s.application_fields, [k]: v })} label={FIELD_LABEL[k]} />))}</CardBody></Card>

      <Card><CardHeader title="Company FAQ for the AI interviewer" description="When a candidate asks about the company, the AI answers only from these. Anything else: it says the hiring team will follow up." />
        <CardBody className="space-y-3">
          {faq.map((x, i) => (
            <div key={i} className="space-y-2 rounded-xl bg-slate-50 p-3 dark:bg-ink-850">
              <div className="flex gap-2"><Input aria-label={`Question ${i + 1}`} placeholder="Question, e.g. Is the role hybrid?" value={x.q} onChange={e => set('faq', faq.map((y, j) => j === i ? { ...y, q: e.target.value } : y))} />
                <Button variant="ghost" aria-label="Remove question" icon={<Trash2 />} onClick={() => set('faq', faq.filter((_, j) => j !== i))} /></div>
              <Textarea aria-label={`Answer ${i + 1}`} className="min-h-0" rows={2} placeholder="Approved answer" value={x.a} onChange={e => set('faq', faq.map((y, j) => j === i ? { ...y, a: e.target.value } : y))} />
            </div>))}
          {faq.length < 40 && <Button size="sm" icon={<Plus />} onClick={() => set('faq', [...faq, { q: '', a: '' }])}>Add a question</Button>}
          <Alert tone="info">Good topics: work model and location, interview process and timelines, benefits you are happy to state, team size. Avoid salary promises.</Alert>
        </CardBody></Card>

      <Card><CardHeader title="HROne export columns" description="Copy the column headers from your HROne employee import template, in order, and pick the TalentLoop field for each. Leave a field empty to keep the column blank." />
        <CardBody className="space-y-2">
          {!cols.length && <p className="text-sm text-slate-500">No columns yet: the export uses {hr ? hr.default_columns.map(c => c.header).join(', ') : 'a basic set'}.</p>}
          {cols.map((c, i) => (
            <div key={i} className="flex gap-2"><Input aria-label={`HROne header ${i + 1}`} placeholder="Header exactly as in HROne" value={c.header} onChange={e => set('hrone_columns', cols.map((y, j) => j === i ? { ...y, header: e.target.value } : y))} />
              <Select aria-label={`Field for column ${i + 1}`} className="w-56" value={c.field} onChange={e => set('hrone_columns', cols.map((y, j) => j === i ? { ...y, field: e.target.value } : y))}>
                <option value="">(leave empty)</option>{hr?.fields.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}</Select>
              <Button variant="ghost" aria-label="Remove column" icon={<Trash2 />} onClick={() => set('hrone_columns', cols.filter((_, j) => j !== i))} /></div>))}
          <div className="flex flex-wrap gap-2 pt-1"><Button size="sm" icon={<Plus />} onClick={() => set('hrone_columns', [...cols, { header: '', field: '' }])}>Add column</Button>
            <Button size="sm" variant="ghost" icon={<Download />} href="/api/exports/hrone.xlsx">Export selected candidates</Button></div>
        </CardBody></Card>

      <Card><CardHeader title="Messages and recordings" />
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <Field label="Sender name" htmlFor="hs-sender" hint="Shown as the From name on emails."><Input id="hs-sender" value={s.sender_name || ''} onChange={e => set('sender_name', e.target.value)} placeholder="Acme Hiring" /></Field>
          <Field label="Delete recordings after (days)" htmlFor="hs-ret" hint="Videos, test snapshots, uploads and interview recordings of closed candidates (rejected, withdrawn, hired). 0 keeps them.">
            <Input id="hs-ret" type="number" min={0} max={3650} value={s.recording_retention_days || 0} onChange={e => set('recording_retention_days', +e.target.value)} /></Field>
        </CardBody></Card>
      <div className="flex justify-end"><Button variant="primary" loading={busy} onClick={save} icon={<Save />}>Save</Button></div>
    </div>
  )
}
