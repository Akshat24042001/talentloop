// Campus drives: a registration link and QR code per college, a test window, and a results link for the placement officer.
import { Check, Copy, Download, GraduationCap, Plus, QrCode, Trash2 } from 'lucide-react'
import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { Badge, Button, Card, CardBody, Field, Input, Modal, Select, Switch, cn, copyText, toast } from '../components/ui'
import { Empty, ErrorBox, ListSkeleton, Loading, PageHeader, useApi, usePaged } from '../components/kit'
import { api } from '../lib/api'
import { when } from '../lib/format'
import { DateTimePicker } from '../components/pickers'
import { LinkActions } from '../components/LinkActions'
import { ask } from '../components/dialogs'

interface Drive {
  id: string; job_id: string; college: string; code: string; share_code: string; opens_at: number | null; closes_at: number | null; status: 'open' | 'closed'
  settings: { require_photo?: boolean; show_scores?: boolean; placement_officer?: string; officer_email?: string }; created_at: number; link: string; results_link: string; registered?: number
  job?: { id: string; ref: string; title: string } | null
  job_ids?: string[]; jobs?: { id: string; ref: string; title: string; status: string; registered: number }[]
}
type JobOpt = { id: string; title: string; status: string; department?: string }

export default function Drives() {
  const { data, error, reload } = useApi<Drive[]>('/api/drives')
  const { data: jobs } = useApi<JobOpt[]>('/api/jobs')
  const [edit, setEdit] = useState<Partial<Drive> | null>(null)
  const [q, setQ] = useState(''), [st, setSt] = useState('')
  const list = (data || []).filter(d => (!st || d.status === st) && (!q || `${d.college} ${(d.jobs || []).map(j => j.title).join(' ')}`.toLowerCase().includes(q.toLowerCase())))
  const { rows, pager } = usePaged(list, 12, [q, st])
  if (error) return <ErrorBox error={error} retry={reload} />
  return (
    <>
      <PageHeader title="Campus drives" description="One registration link and QR code per college, for one or more roles. Students pick the roles they want, register with a live photo and take each role's flow (usually a proctored test) in your test window."
        actions={jobs && jobs.length > 0 && <Button variant="primary" icon={<Plus />} onClick={() => setEdit({ job_ids: [] })}>New drive</Button>} />
      {!data ? <ListSkeleton rows={3} avatar={false} /> : !data.length ? <Card><Empty icon={<GraduationCap />} title="No campus drives yet">Create a drive per college and pick the roles you're hiring for there (a campus template flow works well).</Empty></Card>
        : <>
          <div className="mb-3 flex flex-wrap gap-2"><Input type="search" aria-label="Search drives" className="max-w-xs" placeholder="Search college or role" value={q} onChange={e => setQ(e.target.value)} />
            <Select aria-label="Status" className="!w-40" value={st} onChange={e => setSt(e.target.value)}><option value="">All drives</option><option value="open">Open</option><option value="closed">Closed</option></Select></div>
          {list.length ? <DriveList drives={rows} onEdit={setEdit} reload={reload} showJob /> : <Card><CardBody><p className="text-sm text-slate-500 dark:text-slate-400">No drives match.</p></CardBody></Card>}
          {pager}</>}
      {edit && <DriveEditor d={edit} jobs={jobs || []} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </>
  )
}

export function JobDrives({ jobId, canManage }: { jobId: string; canManage: boolean }) {
  const { data, error, reload } = useApi<Drive[]>(`/api/jobs/${jobId}/drives`)
  const { data: jobs } = useApi<JobOpt[]>('/api/jobs')
  const [edit, setEdit] = useState<Partial<Drive> | null>(null)
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!data) return <Loading />
  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3"><p className="text-sm text-slate-500">Each college gets its own registration link, QR code, test window and results page.</p>
        {canManage && <Button variant="primary" icon={<Plus />} onClick={() => setEdit({ job_ids: [jobId] })}>New drive</Button>}</div>
      {!data.length ? <Card><Empty icon={<GraduationCap />} title="No drives for this job">Add one per college you are hiring from.</Empty></Card> : <DriveList drives={data} onEdit={canManage ? setEdit : undefined} reload={reload} />}
      {edit && <DriveEditor d={edit} jobs={jobs || []} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </>
  )
}

function DriveList({ drives, onEdit, reload }: { drives: Drive[]; onEdit?: (d: Drive) => void; reload: () => void; showJob?: boolean }) {
  const [qr, setQr] = useState<Drive | null>(null)
  async function setStatus(d: Drive, status: string) { if (status === 'closed' && !await ask(`Close the ${d.college} drive? Students can no longer register with its link or code. You can reopen it later.`, { confirm: 'Close drive' })) return; try { await api(`/api/drives/${d.id}`, { method: 'PATCH', json: { status } }); reload() } catch (e: any) { toast(e.message) } }
  async function del(d: Drive) { if (!await ask(`Delete the ${d.college} drive?`)) return; try { await api(`/api/drives/${d.id}`, { method: 'DELETE' }); reload() } catch (e: any) { toast(e.message) } }
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {drives.map(d => (
        <Card key={d.id}><CardBody className="space-y-3">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{d.college}</span><Badge tone={d.status === 'open' ? 'success' : 'neutral'}>{d.status === 'open' ? 'Open' : 'Closed'}</Badge></div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs"><span className="font-medium text-slate-600 dark:text-slate-300">{d.jobs?.length || 1} role{(d.jobs?.length || 1) > 1 ? 's' : ''}:</span>
                {(d.jobs || (d.job ? [{ ...d.job, status: 'open', registered: d.registered || 0 }] : [])).map(j => <a key={j.id} href={`/app/jobs/${j.ref}?tab=pipeline`} className="rounded-md bg-brand-50 px-1.5 py-0.5 font-medium text-brand-800 hover:underline dark:bg-brand-500/15 dark:text-brand-200">{j.title}<span className="font-normal text-brand-600/80 dark:text-brand-300/80"> · {j.registered}</span></a>)}</div>
              <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{d.registered ?? 0} student{d.registered === 1 ? '' : 's'} registered · test window {d.opens_at ? when(d.opens_at) : 'any time'} to {d.closes_at ? when(d.closes_at) : 'open-ended'}</div></div>
            <Button size="sm" icon={<QrCode />} onClick={() => setQr(d)}>QR code</Button>
          </div>
          <div className="flex flex-wrap gap-2">
            <LinkActions url={d.link} label="Registration link" copied="Registration link copied" to={{ email: d.settings?.officer_email, name: d.settings?.placement_officer }}
              subject={`Campus hiring at ${d.college}: registration`} message={`Students of ${d.college} can register for our campus hiring drive here:`} />
            <LinkActions url={d.results_link} label="Results link (placement officer)" copied="Results link copied" to={{ email: d.settings?.officer_email, name: d.settings?.placement_officer }}
              subject={`Campus hiring at ${d.college}: results`} message={`Live results of our campus drive at ${d.college}:`} />
            {onEdit && <><Button size="sm" variant="ghost" onClick={() => onEdit(d)}>Edit</Button>
              <Button size="sm" variant="ghost" onClick={() => setStatus(d, d.status === 'open' ? 'closed' : 'open')}>{d.status === 'open' ? 'Close' : 'Reopen'}</Button>
              {!d.registered && <Button size="sm" variant="ghost" aria-label="Delete drive" icon={<Trash2 />} onClick={() => del(d)} />}</>}
          </div>
        </CardBody></Card>))}
      {qr && <QrModal d={qr} onClose={() => setQr(null)} />}
    </div>
  )
}

function QrModal({ d, onClose }: { d: Drive; onClose: () => void }) {
  const [src, setSrc] = useState('')
  useEffect(() => { QRCode.toDataURL(d.link, { width: 640, margin: 2, errorCorrectionLevel: 'M' }).then(setSrc) }, [d.link])
  return (
    <Modal open onOpenChange={o => !o && onClose()} title={`${d.college}: registration`} description="Show it on the projector or print it. Students scan it with their phone camera.">
      <div className="mt-4 text-center">{src ? <img src={src} alt={`QR code for ${d.link}`} className="mx-auto w-64 rounded-lg bg-white p-2" /> : <Loading />}
        <p className="mt-2 break-all text-xs text-slate-500">{d.link}</p>
        <div className="mt-3 flex justify-center gap-2"><Button icon={<Download />} href={src} download>Download PNG</Button><Button icon={<Copy />} onClick={() => copyText(d.link, 'Link copied')}>Copy link</Button></div></div>
    </Modal>
  )
}

const toLocal = (ts: number | null | undefined) => ts ? new Date(ts * 1000 - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : ''
const fromLocal = (v: string) => v ? new Date(v).getTime() / 1000 : null

function DriveEditor({ d, jobs, onClose, onSaved }: { d: Partial<Drive>; jobs: JobOpt[]; onClose: () => void; onSaved: () => void }) {
  const [roles, setRoles] = useState<string[]>(d.job_ids || (d.job_id ? [d.job_id] : []))
  const pickable = jobs.filter(j => j.status !== 'closed' || roles.includes(j.id))
  const [f, setF] = useState({ college: d.college || '', opens_at: toLocal(d.opens_at), closes_at: toLocal(d.closes_at), ...{ require_photo: d.settings?.require_photo !== false, show_scores: !!d.settings?.show_scores, placement_officer: d.settings?.placement_officer || '', officer_email: d.settings?.officer_email || '' } })
  const [busy, setBusy] = useState(false)
  async function save() {
    setBusy(true)
    const body = { college: f.college, job_ids: roles, opens_at: fromLocal(f.opens_at) || 0, closes_at: fromLocal(f.closes_at) || 0,
      settings: { require_photo: f.require_photo, show_scores: f.show_scores, placement_officer: f.placement_officer, officer_email: f.officer_email } }
    try { await api(d.id ? `/api/drives/${d.id}` : '/api/drives', { method: d.id ? 'PATCH' : 'POST', json: body }); toast(d.id ? 'Drive saved' : 'Drive created'); onSaved() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  return (
    <Modal open onOpenChange={o => !o && onClose()} title={d.id ? 'Edit drive' : 'New campus drive'}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!f.college.trim() || !roles.length} onClick={save}>{d.id ? 'Save' : 'Create drive'}</Button></>}>
      <div className="mt-4 space-y-3">
        <Field label="College" htmlFor="dr-c"><Input id="dr-c" value={f.college} onChange={e => setF({ ...f, college: e.target.value })} placeholder="e.g. PSG College of Technology" /></Field>
        <Field label={`Roles at this campus (${roles.length})`} hint="Students choose one or more of these on the same registration link.">
          <div role="group" aria-label="Roles" className="flex max-h-44 flex-wrap gap-1.5 overflow-y-auto">{pickable.map(j => { const on = roles.includes(j.id); return (
            <button key={j.id} type="button" aria-pressed={on} onClick={() => setRoles(r => on ? r.filter(x => x !== j.id) : [...r, j.id])}
              className={cn('inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-[13px] font-medium ring-1 ring-inset transition-colors', on ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white text-slate-700 ring-slate-200 hover:bg-slate-50 dark:bg-ink-850 dark:text-slate-200 dark:ring-ink-700 dark:hover:bg-ink-800')}>
              {on && <Check className="size-3.5" />}{j.title}{j.status !== 'open' && <span className="opacity-70">({j.status})</span>}</button>) })}
            {!pickable.length && <p className="text-sm text-slate-500 dark:text-slate-400">No open jobs yet. Create and publish a job first.</p>}</div></Field>
        <div className="grid gap-3">
          <Field label="Test opens" htmlFor="dr-o"><DateTimePicker id="dr-o" aria-label="Test opens" value={f.opens_at} onChange={v => setF({ ...f, opens_at: v })} /></Field>
          <Field label="Test closes" htmlFor="dr-e"><DateTimePicker id="dr-e" aria-label="Test closes" value={f.closes_at} onChange={v => setF({ ...f, closes_at: v })} /></Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Placement officer" htmlFor="dr-po"><Input id="dr-po" value={f.placement_officer} onChange={e => setF({ ...f, placement_officer: e.target.value })} /></Field>
          <Field label="Their email" htmlFor="dr-pe" hint="They can sign in at /me with this email to see live results."><Input id="dr-pe" type="email" value={f.officer_email} onChange={e => setF({ ...f, officer_email: e.target.value })} /></Field>
        </div>
        <Switch id="dr-ph" checked={f.require_photo} onChange={v => setF({ ...f, require_photo: v })} label="Live photo at registration" description="Taken with the camera and shown next to test snapshots so your team can compare." />
        <Switch id="dr-sc" checked={f.show_scores} onChange={v => setF({ ...f, show_scores: v })} label="Show test scores on the results page" description="Off: the placement officer sees who took the test and progressed, without scores." />
      </div>
    </Modal>
  )
}
