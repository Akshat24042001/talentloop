// Campus drives: a registration link and QR code per college, a test window, and a results link for the placement officer.
import { Copy, Download, GraduationCap, Plus, QrCode, Trash2 } from 'lucide-react'
import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { Badge, Button, Card, CardBody, Field, Input, Modal, Select, Switch, copyText, toast } from '../components/ui'
import { Empty, ErrorBox, Loading, PageHeader, useApi } from '../components/kit'
import { api } from '../lib/api'
import { when } from '../lib/format'

interface Drive {
  id: string; job_id: string; college: string; code: string; share_code: string; opens_at: number | null; closes_at: number | null; status: 'open' | 'closed'
  settings: { require_photo?: boolean; show_scores?: boolean; placement_officer?: string; officer_email?: string }; created_at: number; link: string; results_link: string; registered?: number
  job?: { id: string; ref: string; title: string }
}

export default function Drives() {
  const { data, error, reload } = useApi<Drive[]>('/api/drives')
  const { data: jobs } = useApi<{ id: string; title: string; status: string }[]>('/api/jobs')
  const [jobId, setJobId] = useState('')
  const [edit, setEdit] = useState<Partial<Drive> | null>(null)
  if (error) return <ErrorBox error={error} retry={reload} />
  return (
    <>
      <PageHeader title="Campus drives" description="One registration link and QR code per college. Students register with a live photo and take the job's flow (usually a proctored test) in your test window."
        actions={jobs && jobs.length > 0 && <div className="flex gap-2"><Select aria-label="Job" value={jobId} onChange={e => setJobId(e.target.value)}><option value="">Choose a job…</option>{jobs.map(j => <option key={j.id} value={j.id}>{j.title}</option>)}</Select>
          <Button variant="primary" icon={<Plus />} disabled={!jobId} onClick={() => setEdit({ job_id: jobId })}>New drive</Button></div>} />
      {!data ? <Loading /> : !data.length ? <Card><Empty icon={<GraduationCap />} title="No campus drives yet">Pick a job above (a campus template flow works well), then add a drive per college.</Empty></Card>
        : <DriveList drives={data} onEdit={setEdit} reload={reload} showJob />}
      {edit && <DriveEditor d={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </>
  )
}

export function JobDrives({ jobId, canManage }: { jobId: string; canManage: boolean }) {
  const { data, error, reload } = useApi<Drive[]>(`/api/jobs/${jobId}/drives`)
  const [edit, setEdit] = useState<Partial<Drive> | null>(null)
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!data) return <Loading />
  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3"><p className="text-sm text-slate-500">Each college gets its own registration link, QR code, test window and results page.</p>
        {canManage && <Button variant="primary" icon={<Plus />} onClick={() => setEdit({ job_id: jobId })}>New drive</Button>}</div>
      {!data.length ? <Card><Empty icon={<GraduationCap />} title="No drives for this job">Add one per college you are hiring from.</Empty></Card> : <DriveList drives={data} onEdit={canManage ? setEdit : undefined} reload={reload} />}
      {edit && <DriveEditor d={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload() }} />}
    </>
  )
}

function DriveList({ drives, onEdit, reload, showJob }: { drives: Drive[]; onEdit?: (d: Drive) => void; reload: () => void; showJob?: boolean }) {
  const [qr, setQr] = useState<Drive | null>(null)
  async function setStatus(d: Drive, status: string) { try { await api(`/api/drives/${d.id}`, { method: 'PATCH', json: { status } }); reload() } catch (e: any) { toast(e.message) } }
  async function del(d: Drive) { if (!confirm(`Delete the ${d.college} drive?`)) return; try { await api(`/api/drives/${d.id}`, { method: 'DELETE' }); reload() } catch (e: any) { toast(e.message) } }
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {drives.map(d => (
        <Card key={d.id}><CardBody className="space-y-3">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{d.college}</span><Badge tone={d.status === 'open' ? 'success' : 'neutral'}>{d.status === 'open' ? 'Open' : 'Closed'}</Badge></div>
              {showJob && d.job && <a href={`/app/jobs/${d.job.ref}?tab=pipeline`} className="text-sm text-brand-600 hover:underline">{d.job.title}</a>}
              <div className="text-xs text-slate-500">{d.registered ?? 0} registered · test window {d.opens_at ? when(d.opens_at) : 'any time'} to {d.closes_at ? when(d.closes_at) : 'open-ended'}</div></div>
            <Button size="sm" icon={<QrCode />} onClick={() => setQr(d)}>QR code</Button>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" icon={<Copy />} onClick={() => copyText(d.link, 'Registration link copied')}>Registration link</Button>
            <Button size="sm" icon={<Copy />} onClick={() => copyText(d.results_link, 'Results link copied')}>Results link (placement officer)</Button>
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

function DriveEditor({ d, onClose, onSaved }: { d: Partial<Drive>; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ college: d.college || '', opens_at: toLocal(d.opens_at), closes_at: toLocal(d.closes_at), ...{ require_photo: d.settings?.require_photo !== false, show_scores: !!d.settings?.show_scores, placement_officer: d.settings?.placement_officer || '', officer_email: d.settings?.officer_email || '' } })
  const [busy, setBusy] = useState(false)
  async function save() {
    setBusy(true)
    const body = { college: f.college, opens_at: fromLocal(f.opens_at) || 0, closes_at: fromLocal(f.closes_at) || 0,
      settings: { require_photo: f.require_photo, show_scores: f.show_scores, placement_officer: f.placement_officer, officer_email: f.officer_email } }
    try { await api(d.id ? `/api/drives/${d.id}` : `/api/jobs/${d.job_id}/drives`, { method: d.id ? 'PATCH' : 'POST', json: body }); toast(d.id ? 'Drive saved' : 'Drive created'); onSaved() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  return (
    <Modal open onOpenChange={o => !o && onClose()} title={d.id ? 'Edit drive' : 'New campus drive'}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!f.college.trim()} onClick={save}>{d.id ? 'Save' : 'Create drive'}</Button></>}>
      <div className="mt-4 space-y-3">
        <Field label="College" htmlFor="dr-c"><Input id="dr-c" value={f.college} onChange={e => setF({ ...f, college: e.target.value })} placeholder="e.g. PSG College of Technology" /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Test opens" htmlFor="dr-o"><Input id="dr-o" type="datetime-local" value={f.opens_at} onChange={e => setF({ ...f, opens_at: e.target.value })} /></Field>
          <Field label="Test closes" htmlFor="dr-e"><Input id="dr-e" type="datetime-local" value={f.closes_at} onChange={e => setF({ ...f, closes_at: e.target.value })} /></Field>
          <Field label="Placement officer" htmlFor="dr-po"><Input id="dr-po" value={f.placement_officer} onChange={e => setF({ ...f, placement_officer: e.target.value })} /></Field>
          <Field label="Their email" htmlFor="dr-pe"><Input id="dr-pe" type="email" value={f.officer_email} onChange={e => setF({ ...f, officer_email: e.target.value })} /></Field>
        </div>
        <Switch id="dr-ph" checked={f.require_photo} onChange={v => setF({ ...f, require_photo: v })} label="Live photo at registration" description="Taken with the camera and shown next to test snapshots so your team can compare." />
        <Switch id="dr-sc" checked={f.show_scores} onChange={v => setF({ ...f, show_scores: v })} label="Show test scores on the results page" description="Off: the placement officer sees who took the test and progressed, without scores." />
      </div>
    </Modal>
  )
}
