// One application in a job's flow: every round's result, test sections, recordings, practical work, integrity
// evidence, HR actions (pass, hold, reject, move, resend, reset, override) and the messages sent.
import * as Dialog from '@radix-ui/react-dialog'
import { Check, Copy, Download, ExternalLink, Flag, Hand, Link2, Mail, MessageCircle, Play, RefreshCw, RotateCcw, Star, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Alert, Badge, Button, Field, Input, Modal, Select, Spinner, Textarea, copyText, toast } from '../../components/ui'
import { ErrorBox, Loading, useApi } from '../../components/kit'
import { api } from '../../lib/api'
import { ago, when } from '../../lib/format'
import { useMe } from '../../lib/session'
import { ROUND_ICON } from './FlowBuilder'
import { ReasonModal } from './Board'
import { REC_TONE, STATUS_TONE, type Round, type RoundSummary } from './types'

interface Msg { id: string; channel: string; to: string; subject: string; body: string; template: string; status: string; error: string; created_at: number; sent_at: number | null }
interface Detail {
  id: string; stage: string; stage_label: string; round_id: string | null; round_status: string | null; permission: string
  candidate: { id: string; ref: string; name: string; email: string; phone?: string; location?: string; headline?: string; years?: number | null; notice_days?: number | null; expected_salary?: number | null; college?: string; has_photo?: boolean }
  job: { id: string; ref: string; title: string }; rounds: { round: Round; result: RoundSummary | null; data: Record<string, any> | null }[]
  answers: Record<string, any>; cover_letter: string; knockout_failed: string[] | null; rating: number | null; notes: string
  human_requested_at: number | null; human_request_note: string; accommodation: Record<string, any> | null; status_link: string; messages: Msg[]
}

export default function AppDrawer({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const me = useMe()
  const { data, error, reload } = useApi<Detail>(`/api/applications/${id}`)
  const [reject, setReject] = useState(false)
  const refresh = () => { reload(); onChanged() }
  async function decide(action: string, extra: Record<string, unknown> = {}) {
    try { await api(`/api/applications/${id}/decide`, { json: { action, ...extra } }); toast('Done'); refresh() } catch (e: any) { toast(e.message) }
  }
  const canEdit = data && data.permission !== 'view'
  const closed = data && ['rejected', 'withdrawn', 'offer', 'hired'].includes(data.stage)
  const cur = data?.rounds.find(r => r.round.id === data.round_id)
  return (
    <Dialog.Root open onOpenChange={o => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink-950/50" />
        <Dialog.Content aria-describedby={undefined} className="fixed inset-y-0 right-0 z-50 flex w-full max-w-2xl flex-col bg-white shadow-2xl focus:outline-none dark:bg-ink-900">
          <header className="flex items-start gap-3 border-b border-slate-100 px-5 py-4 dark:border-ink-800">
            <div className="min-w-0 flex-1">
              <Dialog.Title className="truncate text-lg font-semibold">{data?.candidate.name || 'Application'}</Dialog.Title>
              {data && <p className="truncate text-sm text-slate-500">{[data.candidate.headline, data.candidate.location, data.candidate.notice_days != null ? `${data.candidate.notice_days}d notice` : '', data.candidate.college].filter(Boolean).join(' · ')}</p>}
              {data && <div className="mt-2 flex flex-wrap gap-1.5"><Badge tone={closed ? (['offer', 'hired'].includes(data.stage) ? 'success' : 'danger') : 'brand'}>{data.stage_label}</Badge>
                {cur?.result && <Badge tone={STATUS_TONE[cur.result.status]}>{cur.round.name}: {cur.result.status_label}</Badge>}</div>}
            </div>
            <Dialog.Close className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-ink-800" aria-label="Close"><X className="size-5" /></Dialog.Close>
          </header>
          {error ? <div className="p-5"><ErrorBox error={error} retry={reload} /></div> : !data ? <Loading /> : <>
            {canEdit && !closed && (
              <div className="flex flex-wrap gap-2 border-b border-slate-100 px-5 py-3 dark:border-ink-800">
                {data.round_id && cur?.result?.status === 'pending' ? <>
                  <Button size="sm" variant="primary" icon={<Play />} onClick={() => decide('move', { round_id: cur.round.id })}>Start {cur.round.name}</Button>
                </> : data.round_id ? <>
                  <Button size="sm" variant="primary" icon={<Check />} onClick={() => decide('pass')}>Pass {cur?.round.name || 'round'}</Button>
                  <Button size="sm" icon={<Hand />} onClick={() => decide('hold')}>Hold</Button>
                </> : <Button size="sm" variant="primary" onClick={() => decide('start')}>Start the flow</Button>}
                <Select aria-label="Move to round" className="!h-8 !w-48 !py-0 text-[13px]" value="" onChange={e => e.target.value && decide('move', { round_id: e.target.value })}>
                  <option value="">Move to round…</option>{data.rounds.slice(1).map(r => <option key={r.round.id} value={r.round.id}>{r.round.name}</option>)}</Select>
                <Button size="sm" variant="subtle" onClick={() => confirm(`Select ${data.candidate.name} for ${data.job.title}?`) && decide('select')}>Select</Button>
                <Button size="sm" variant="ghost" className="text-red-600" onClick={() => setReject(true)}>Reject</Button>
              </div>)}
            <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
              <Requests d={data} canEdit={data.permission === 'manage'} onDone={refresh} />
              {data.knockout_failed?.length ? <Alert tone="danger" title="Knockout answers">{data.knockout_failed.join('; ')}</Alert> : null}
              <ol className="space-y-3">{data.rounds.map((r, i) => <RoundBlock key={r.round.id} i={i} r={r} d={data} canEdit={!!canEdit} onChanged={refresh} />)}</ol>
              <Notes d={data} canEdit={me.role !== 'viewer'} onSaved={refresh} />
              <Messages msgs={data.messages} onRetry={reload} />
            </div>
            <footer className="flex flex-wrap gap-2 border-t border-slate-100 px-5 py-3 dark:border-ink-800">
              <Button size="sm" href={`/app/candidates/${data.candidate.ref}`} icon={<ExternalLink />}>Full profile</Button>
              {data.status_link && <Button size="sm" icon={<Link2 />} onClick={() => copyText(data.status_link, 'Status page link copied')}>Candidate status link</Button>}
              {data.permission === 'manage' && <Button size="sm" variant="ghost" className="ml-auto text-red-600" icon={<Trash2 />} onClick={async () => {
                if (!confirm(`Remove ${data.candidate.name} from ${data.job.title}? They stay in your talent pool.`)) return
                try { await api(`/api/applications/${data.id}`, { method: 'DELETE' }); toast('Removed from the job'); onChanged(); onClose() } catch (e: any) { toast(e.message) }
              }}>Remove from job</Button>}
            </footer>
          </>}
          {reject && <ReasonModal title={`Reject ${data?.candidate.name}`} cta="Reject" onClose={() => setReject(false)} onSubmit={(reason, notify) => { setReject(false); decide('reject', { reason, notify }) }} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function H({ children }: { children: ReactNode }) { return <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">{children}</div> }

function RoundBlock({ i, r, d, canEdit, onChanged }: { i: number; r: Detail['rounds'][number]; d: Detail; canEdit: boolean; onChanged: () => void }) {
  const res = r.result, data = r.data || {}, Icon = ROUND_ICON[r.round.type]
  const isCur = d.round_id === r.round.id
  const [open, setOpen] = useState(isCur || (!!res && r.round.type !== 'application'))
  const [score, setScore] = useState<string | null>(null)
  async function act(path: string, msg: string) {
    try { const x = await api(`/api/round-results/${res!.id}/${path}`, { method: 'POST' }); toast(msg); if (x.link) copyText(x.link, `${msg}. New link copied`); onChanged() } catch (e: any) { toast(e.message) }
  }
  async function saveScore() {
    try { await api(`/api/round-results/${res!.id}/score`, { json: { score: +(score || 0) } }); toast('Score changed'); setScore(null); onChanged() } catch (e: any) { toast(e.message) }
  }
  return (
    <li className={`rounded-2xl ring-1 ${isCur ? 'ring-brand-300 dark:ring-brand-500/40' : 'ring-slate-200 dark:ring-ink-700'}`}>
      <button className="flex w-full items-center gap-3 px-3.5 py-3 text-left" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-600 dark:bg-ink-800 dark:text-slate-300"><Icon className="size-4" /></span>
        <span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold">{i + 1}. {r.round.name}</span>
          {res?.decided_by && <span className="block truncate text-xs text-slate-500">{res.decision ? `${res.decision} by ` : ''}{res.decided_by}{res.reason ? `: ${res.reason}` : ''}</span>}</span>
        {res?.flagged && <Badge tone="danger" icon={<Flag />}>Flag</Badge>}
        {data.recommendation_label && <Badge tone={REC_TONE[data.recommendation_label] || 'neutral'}>{data.recommendation_label}</Badge>}
        {res?.score != null && <span className="tabular text-sm font-bold">{Math.round(res.score)}</span>}
        <Badge tone={res ? STATUS_TONE[res.status] : 'neutral'}>{res ? res.status_label : 'Upcoming'}</Badge>
      </button>
      {open && res && (
        <div className="space-y-3 border-t border-slate-100 px-3.5 py-3 text-sm dark:border-ink-800">
          {res.suggestion && ['submitted', 'on_hold'].includes(res.status) && <Alert tone="info">Suggested by the pass rule: <b>{({ pass: 'Pass', fail: 'Not progress', hold: 'Hold' } as Record<string, string>)[res.suggestion] || res.suggestion}</b></Alert>}
          {res.deadline_at && ['invited', 'in_progress', 'pending'].includes(res.status) && <p className="text-xs text-slate-500">Deadline {when(res.deadline_at)}</p>}
          <RoundData type={r.round.type} res={res} data={data} />
          {Object.keys(res.integrity || {}).length > 0 && <Integrity res={res} hasPhoto={!!d.candidate.has_photo} />}
          {data.score_overridden && <p className="text-xs text-slate-500">Score changed from {data.score_overridden.from ?? 'none'} {ago(data.score_overridden.at)}.</p>}
          {canEdit && (
            <div className="flex flex-wrap gap-2 pt-1">
              {res.candidate_link && ['invited', 'in_progress', 'booked', 'expired', 'pending'].includes(res.status) && <Button size="sm" icon={<Copy />} onClick={() => copyText(res.candidate_link, 'Candidate link copied')}>Copy link</Button>}
              {['test', 'video_intro', 'role_task', 'practical_task', 'ai_interview', 'human_interview', 'manager_approval'].includes(r.round.type) && isCur && ['invited', 'in_progress', 'expired', 'pending', 'booked', 'submitted', 'on_hold'].includes(res.status) &&
                <Button size="sm" icon={<RefreshCw />} onClick={() => act('resend', r.round.type === 'manager_approval' ? 'Approval request sent again' : 'Link sent again')}>Resend</Button>}
              {['test', 'video_intro', 'role_task', 'practical_task'].includes(r.round.type) && res.status !== 'invited' && <Button size="sm" icon={<RotateCcw />} onClick={() => confirm('Let the candidate do this round again? The current attempt is kept for reference.') && act('reset', 'Attempt reset')}>Reset attempt</Button>}
              {res.score != null || ['submitted', 'on_hold', 'passed', 'failed'].includes(res.status) ? (score == null ? <Button size="sm" variant="ghost" onClick={() => setScore(String(res.score ?? ''))}>Change score</Button>
                : <span className="flex items-center gap-1.5"><Input aria-label="New score" type="number" min={0} max={100} className="h-8 w-20" value={score} onChange={e => setScore(e.target.value)} /><Button size="sm" variant="primary" onClick={saveScore}>Save</Button><Button size="sm" variant="ghost" onClick={() => setScore(null)}>Cancel</Button></span>) : null}
              {res.manager_link && <Button size="sm" variant="ghost" icon={<Link2 />} onClick={() => copyText(res.manager_link, 'Link copied')}>{r.round.type === 'human_interview' ? 'Interviewer feedback link' : 'Decision link'}</Button>}
            </div>)}
        </div>)}
    </li>
  )
}

function RoundData({ type, res, data }: { type: string; res: RoundSummary; data: Record<string, any> }) {
  if (type === 'cv_screening') return <>
    {data.reasons?.length > 0 && <div><H>Why this score</H><ul className="list-disc space-y-0.5 pl-5">{data.reasons.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></div>}
    {data.stability?.label && <p><span className="text-slate-500">Job stability:</span> <b>{data.stability.label}</b>{data.stability.avg_months ? ` (about ${data.stability.avg_months} months per job)` : ''}</p>}
    {data.ai_report && <div><H>AI report</H><p>{data.ai_report.summary || data.ai_report.verdict}</p>
      {data.ai_report.gaps?.length > 0 && <p className="mt-1 text-slate-500">Gaps: {data.ai_report.gaps.join('; ')}</p>}</div>}
  </>
  if (type === 'test') {
    const r = data.result
    if (!r) return <p className="text-slate-500">{res.status === 'in_progress' ? 'Taking the test now.' : 'Not taken yet.'}</p>
    return <div><H>Sections</H>
      <table className="w-full text-sm"><thead className="text-left text-xs text-slate-500"><tr><th className="py-1">Section</th><th>Score</th><th>Right</th><th>Wrong</th><th>Blank</th><th>Cutoff</th></tr></thead>
        <tbody>{r.sections.map((x: any) => <tr key={x.section} className="border-t border-slate-100 dark:border-ink-800"><td className="py-1">{x.label}</td><td className="tabular font-semibold">{x.pct}%</td><td className="tabular">{x.right}</td><td className="tabular">{x.wrong}</td><td className="tabular">{x.blank}</td>
          <td>{x.cutoff ? <Badge tone={x.passed_cutoff ? 'success' : 'danger'}>{x.cutoff}%</Badge> : '-'}</td></tr>)}</tbody></table>
      <p className="mt-1 text-xs text-slate-500">Overall {r.overall}% · {({ submitted: 'submitted by the candidate', time_up: 'time ran out', auto_submitted_exits: 'submitted automatically after leaving the test too often' } as Record<string, string>)[data.finished_reason] || data.finished_reason}
        {data.resumes?.length ? ` · resumed ${data.resumes.length} time(s)` : ''}</p>
      {data.previous_attempt && <p className="text-xs text-slate-500">An earlier attempt scored {data.previous_score ?? 'n/a'}.</p>}
    </div>
  }
  if (type === 'video_intro' || type === 'role_task') {
    const a = data.assessment || {}
    if (!data.file) return <p className="text-slate-500">{data.media_deleted_at ? `Recording deleted under your retention policy ${ago(data.media_deleted_at)}.` : 'No recording yet.'}</p>
    return <>
      <Player src={`/api/round-results/${res.id}/file`} />
      {data.scoring && data.scoring !== 'done' && <p className="flex items-center gap-1.5 text-slate-500"><Spinner className="size-3.5" />Scoring the recording…</p>}
      {a.dimensions && <div className="grid grid-cols-4 gap-2">{Object.entries(a.dimensions).map(([k, v]) => <div key={k} className="rounded-lg bg-slate-50 p-2 text-center dark:bg-ink-850"><div className="text-xs capitalize text-slate-500">{k}</div><div className="tabular font-bold">{v as number}/5</div></div>)}</div>}
      {a.summary && <p>{a.summary}</p>}
      {(a.strengths?.length > 0 || a.improvements?.length > 0) && <div className="grid gap-2 sm:grid-cols-2">
        {a.strengths?.length > 0 && <div><H>Strengths</H><ul className="list-disc pl-5">{a.strengths.map((x: string) => <li key={x}>{x}</li>)}</ul></div>}
        {a.improvements?.length > 0 && <div><H>To improve</H><ul className="list-disc pl-5">{a.improvements.map((x: string) => <li key={x}>{x}</li>)}</ul></div>}</div>}
      {a.wpm && <p className="text-xs text-slate-500">{a.words} words · {a.wpm} words per minute · {a.fillers} filler words</p>}
      {a.note && <Alert tone="info">{a.note}</Alert>}{a.error && <Alert tone="warning">{a.error}</Alert>}
      {a.transcript && <details><summary className="cursor-pointer text-sm font-medium">Transcript ({a.transcript_source})</summary><p className="mt-1 whitespace-pre-line text-slate-600 dark:text-slate-300">{a.transcript}</p></details>}
    </>
  }
  if (type === 'practical_task') {
    const a = data.assessment || {}
    if (!data.file) return <p className="text-slate-500">{data.media_deleted_at ? `File deleted under your retention policy ${ago(data.media_deleted_at)}.` : 'Nothing uploaded yet.'}</p>
    return <>
      <div className="flex flex-wrap items-center gap-2"><Button size="sm" icon={<Download />} href={`/api/round-results/${res.id}/file`} target="_blank">{data.file_name}</Button>
        {data.uploaded_at && <span className="text-xs text-slate-500">uploaded {ago(data.uploaded_at)}</span>}</div>
      {data.note && <p className="italic text-slate-600 dark:text-slate-300">"{data.note}"</p>}
      {data.scoring && data.scoring !== 'done' && <p className="flex items-center gap-1.5 text-slate-500"><Spinner className="size-3.5" />Reviewing…</p>}
      {a.criteria?.length > 0 && <table className="w-full text-sm"><thead className="text-left text-xs text-slate-500"><tr><th className="py-1">Criterion</th><th>Weight</th><th>Score</th><th>Comment</th></tr></thead>
        <tbody>{a.criteria.map((x: any) => <tr key={x.criterion} className="border-t border-slate-100 align-top dark:border-ink-800"><td className="py-1 pr-2 font-medium">{x.criterion}</td><td className="tabular">{x.weight}</td><td className="tabular font-semibold">{x.score ?? '-'}/10</td><td className="text-slate-600 dark:text-slate-300">{x.comment}</td></tr>)}</tbody></table>}
      {a.summary && <p>{a.summary}</p>}
      {a.concerns?.length > 0 && <Alert tone="warning" title="Concerns">{a.concerns.join('; ')}</Alert>}
      {a.note && <Alert tone="info">{a.note}</Alert>}{a.error && <Alert tone="warning">{a.error}</Alert>}
    </>
  }
  if (type === 'ai_interview') return <>
    {res.status === 'setting_up' && <p className="flex items-center gap-1.5 text-slate-500"><Spinner className="size-3.5" />Preparing the interview…</p>}
    {data.summary && <p>{data.summary}</p>}
    {data.interview_id && <Button size="sm" icon={<Play />} href={`/app/interviews/${data.interview_id}`}>Interview report</Button>}
  </>
  if (type === 'human_interview') {
    const b = data.booking, fb = data.feedback
    return <>
      {b ? <p><b>{when(b.starts_at)}</b>{b.interviewer ? ` with ${b.interviewer}` : ''}{b.location ? ` · ${b.location}` : ''}{b.meeting_url && <> · <a className="text-brand-600 dark:text-brand-400 hover:underline" href={b.meeting_url} target="_blank" rel="noopener">meeting link</a></>}</p>
        : <p className="text-slate-500">{res.status === 'invited' ? 'Waiting for the candidate to pick a slot.' : 'Not booked.'}</p>}
      {data.reschedules ? <p className="text-xs text-slate-500">Rescheduled {data.reschedules} time(s).</p> : null}
      {fb && <div className="rounded-xl bg-slate-50 p-3 dark:bg-ink-850"><H>Feedback from {fb.by}</H>
        <p><Badge tone={fb.decision === 'pass' ? 'success' : fb.decision === 'fail' ? 'danger' : 'warning'}>{({ pass: 'Select', fail: 'Reject', hold: 'Hold' } as Record<string, string>)[fb.decision]}</Badge>{fb.rating ? <span className="ml-2 text-amber-500">{'★'.repeat(fb.rating)}</span> : null}{!fb.attended && <Badge tone="danger">No-show</Badge>}</p>
        {fb.summary?.summary && <p className="mt-1.5">{fb.summary.summary}</p>}
        {fb.notes && <details className="mt-1.5"><summary className="cursor-pointer font-medium">Notes</summary><p className="whitespace-pre-line text-slate-600 dark:text-slate-300">{fb.notes}</p></details>}
        {fb.recording_file && <div className="mt-2"><audio controls preload="none" src={`/api/round-results/${res.id}/file?which=recording`} className="w-full" /></div>}
        {fb.transcript && <details className="mt-1.5"><summary className="cursor-pointer font-medium">Transcript</summary><p className="whitespace-pre-line text-slate-600 dark:text-slate-300">{fb.transcript}</p></details>}
      </div>}
    </>
  }
  if (type === 'manager_approval') return <>
    {data.approvers?.length > 0 && <p className="text-slate-500">Sent to {data.approvers.join(', ')}</p>}
    {data.reason && <p>"{data.reason}"</p>}
  </>
  if (type === 'application' && data.knockouts?.length) return <p className="text-red-600">Knockouts: {data.knockouts.join('; ')}</p>
  return null
}

/** Video with playback speed up to 2x (reviewers skim introductions). */
function Player({ src }: { src: string }) {
  const ref = useRef<HTMLVideoElement>(null), [rate, setRate] = useState(1)
  useEffect(() => { if (ref.current) ref.current.playbackRate = rate }, [rate])
  return (
    <div>
      <video ref={ref} controls preload="metadata" src={src} className="aspect-video w-full rounded-xl bg-black" onLoadedMetadata={e => { (e.target as HTMLVideoElement).playbackRate = rate }} />
      <div className="mt-1.5 flex items-center gap-1 text-xs"><span className="mr-1 text-slate-500">Speed</span>
        {[1, 1.25, 1.5, 1.75, 2].map(x => <button key={x} aria-pressed={rate === x} onClick={() => setRate(x)} className={`rounded-md px-2 py-0.5 font-semibold ${rate === x ? 'bg-slate-900 text-white dark:bg-white dark:text-ink-900' : 'bg-slate-100 dark:bg-ink-800'}`}>{x}×</button>)}</div>
    </div>
  )
}

const INTEG_LABEL: Record<string, string> = { exits: 'Left the screen', copy_paste: 'Copy / paste', no_face: 'No face seen', faces_multi: 'More than one face', phone_seen: 'Phone seen',
  looking_away: 'Looking away', virtual_camera: 'Virtual camera', second_voice: 'Second voice', devtools: 'Developer tools', photo_mismatch: 'Photo mismatch', warnings: 'Warnings' }
function Integrity({ res, hasPhoto }: { res: RoundSummary; hasPhoto: boolean }) {
  const g = res.integrity, snaps: { t: number; reason: string }[] = g.snapshots || []
  const counts = Object.entries(INTEG_LABEL).filter(([k]) => typeof g[k] === 'number' && g[k] > 0)
  const [big, setBig] = useState<string | null>(null)
  const reasons: string[] = (g.reasons || []).map((x: any) => typeof x === 'string' ? x : x?.text || JSON.stringify(x))
  if (!counts.length && !snaps.length && !g.start_photo && !reasons.length && !g.risk) return null
  return (
    <div className={`rounded-xl p-3 ${res.flagged ? 'bg-red-50 dark:bg-red-500/10' : 'bg-slate-50 dark:bg-ink-850'}`}>
      <H>Integrity{g.risk ? ` · ${g.risk} risk` : ''}</H>
      {res.flagged && <p className="mb-1.5 text-red-700 dark:text-red-300">Flagged for review. Flags never reject anyone on their own.</p>}
      {reasons.length > 0 && <ul className="mb-1.5 list-disc pl-5">{reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>}
      {counts.length > 0 && <div className="flex flex-wrap gap-1.5">{counts.map(([k, l]) => <Badge key={k} tone="warning">{l}: {g[k]}</Badge>)}</div>}
      {(g.start_photo || snaps.length > 0) && <div className="mt-2 flex gap-1.5 overflow-x-auto pb-1">
        {hasPhoto && <Thumb src={`/api/round-results/${res.id}/snapshot/registration`} label="Registration photo" onOpen={setBig} />}
        {g.start_photo && <Thumb src={`/api/round-results/${res.id}/snapshot/start`} label="At the start" onOpen={setBig} />}
        {snaps.map((s, i) => <Thumb key={i} src={`/api/round-results/${res.id}/snapshot/${i}`} label={`${new Date(s.t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}${s.reason !== 'routine' ? ` · ${s.reason}` : ''}`} onOpen={setBig} />)}
      </div>}
      {g.events?.length > 0 && <details className="mt-1.5"><summary className="cursor-pointer text-xs font-medium">{g.events.length} events</summary>
        <ul className="mt-1 max-h-40 overflow-y-auto text-xs text-slate-600 dark:text-slate-300">{g.events.map((e: any, i: number) => <li key={i}>{new Date(e.t * 1000).toLocaleTimeString()} · {INTEG_LABEL[e.type] || e.type}{e.detail ? `: ${e.detail}` : ''}</li>)}</ul></details>}
      {big && <Modal open onOpenChange={() => setBig(null)} title="Snapshot"><img src={big} alt="Snapshot" className="mt-3 w-full rounded-lg" /></Modal>}
    </div>
  )
}
function Thumb({ src, label, onOpen }: { src: string; label: string; onOpen: (s: string) => void }) {
  return <button onClick={() => onOpen(src)} className="shrink-0 text-left"><img src={src} alt={label} loading="lazy" className="h-16 w-24 rounded-md bg-slate-200 object-cover dark:bg-ink-700" /><span className="block w-24 truncate text-[10px] text-slate-500">{label}</span></button>
}

function Requests({ d, canEdit, onDone }: { d: Detail; canEdit: boolean; onDone: () => void }) {
  const acc = d.accommodation || {}
  const [pct, setPct] = useState(25)
  async function accDecide(status: string) {
    try { await api(`/api/applications/${d.id}/accommodation`, { json: { status, extra_time_pct: pct } }); toast(status === 'approved' ? 'Approved' : 'Declined'); onDone() } catch (e: any) { toast(e.message) }
  }
  async function human(action: string) {
    try { await api(`/api/applications/${d.id}/human-request`, { json: { action } }); toast(action === 'human' ? 'Moved to a human interview' : 'Reply sent'); onDone() } catch (e: any) { toast(e.message) }
  }
  return <>
    {d.human_requested_at && !acc.human_handled && <Alert tone="warning" title={`Asked for a human interview ${ago(d.human_requested_at)}`}>
      {d.human_request_note && <p>"{d.human_request_note}"</p>}
      {canEdit && <div className="mt-2 flex flex-wrap gap-2"><Button size="sm" variant="primary" onClick={() => human('human')}>Switch to a human interview</Button><Button size="sm" onClick={() => human('keep')}>Keep the AI round and reply</Button></div>}
    </Alert>}
    {acc.request && <Alert tone={acc.status === 'requested' ? 'warning' : 'info'} title={`Accommodation ${acc.status === 'requested' ? 'requested' : acc.status}`}>
      <p>"{acc.request}"</p>{acc.status === 'approved' && acc.extra_time_pct ? <p>{acc.extra_time_pct}% extra time on tests.</p> : null}
      {canEdit && acc.status === 'requested' && <div className="mt-2 flex flex-wrap items-center gap-2"><label className="flex items-center gap-1.5 text-sm">Extra time<Input type="number" aria-label="Extra time percent" className="h-8 w-16" min={0} max={100} value={pct} onChange={e => setPct(+e.target.value)} />%</label>
        <Button size="sm" variant="primary" onClick={() => accDecide('approved')}>Approve</Button><Button size="sm" onClick={() => accDecide('declined')}>Decline</Button></div>}
    </Alert>}
  </>
}

function Notes({ d, canEdit, onSaved }: { d: Detail; canEdit: boolean; onSaved: () => void }) {
  const [rating, setRating] = useState(d.rating || 0), [notes, setNotes] = useState(d.notes || ''), [busy, setBusy] = useState(false)
  const answers = Object.entries(d.answers || {})
  async function save() {
    setBusy(true)
    try { await api(`/api/applications/${d.id}`, { method: 'PATCH', json: { rating: rating || null, notes } }); toast('Saved'); onSaved() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  return (
    <div className="space-y-3">
      {answers.length > 0 && <div><H>Application answers</H><dl className="grid gap-x-4 gap-y-1 sm:grid-cols-2">{answers.map(([k, v]) => <div key={k}><dt className="text-xs text-slate-500">{k}</dt><dd className="font-medium">{String(v)}</dd></div>)}</dl></div>}
      {d.cover_letter && <div><H>Cover letter</H><p className="whitespace-pre-line text-sm">{d.cover_letter}</p></div>}
      <Field label="Your rating"><div className="flex gap-1">{[1, 2, 3, 4, 5].map(n => <button key={n} disabled={!canEdit} aria-label={`${n} stars`} onClick={() => setRating(n === rating ? 0 : n)} className={n <= rating ? 'text-amber-400' : 'text-slate-300 dark:text-ink-600'}><Star className="size-5" fill="currentColor" /></button>)}</div></Field>
      <Field label="Team notes" htmlFor="ad-notes"><Textarea id="ad-notes" className="min-h-0" rows={3} value={notes} disabled={!canEdit} onChange={e => setNotes(e.target.value)} /></Field>
      {canEdit && <Button size="sm" loading={busy} onClick={save} disabled={rating === (d.rating || 0) && notes === (d.notes || '')}>Save notes</Button>}
    </div>
  )
}

export const MSG_TONE: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = { sent: 'success', queued: 'warning', failed: 'danger', not_configured: 'neutral' }
export const MSG_LABEL: Record<string, string> = { sent: 'Sent', queued: 'Queued', failed: 'Failed', not_configured: 'Channel not set up' }
function Messages({ msgs, onRetry }: { msgs: Msg[]; onRetry: () => void }) {
  if (!msgs.length) return null
  async function retry(id: string) { try { await api(`/api/messages/${id}/retry`, { method: 'POST' }); toast('Queued again'); onRetry() } catch (e: any) { toast(e.message) } }
  return (
    <div><H>Messages to the candidate</H>
      <ul className="space-y-1.5">{msgs.map(m => (
        <li key={m.id} className="rounded-xl bg-slate-50 px-3 py-2 dark:bg-ink-850">
          <div className="flex items-center gap-2 text-sm">{m.channel === 'whatsapp' ? <MessageCircle className="size-4 text-emerald-600" /> : <Mail className="size-4 text-slate-400" />}
            <span className="min-w-0 flex-1 truncate font-medium">{m.subject || m.template}</span><Badge tone={MSG_TONE[m.status] || 'neutral'}>{MSG_LABEL[m.status] || m.status}</Badge>
            {['failed', 'not_configured'].includes(m.status) && <button className="text-xs font-semibold text-brand-600 dark:text-brand-400" onClick={() => retry(m.id)}>Retry</button>}</div>
          <div className="text-xs text-slate-500">{m.to} · {ago(m.created_at)}{m.error ? ` · ${m.error}` : ''}</div>
        </li>))}</ul>
    </div>
  )
}
