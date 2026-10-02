import {
  ArrowLeft, Download, FileJson, FileText, Link2, Play, Printer, Sparkles, Trash2, TriangleAlert, UserX, XCircle,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { HBarChart, TimelineChart, type BarRow } from '../components/charts'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Select, Spinner, Textarea, cn, toast } from '../components/ui'
import { api, mediaUrl, withKey } from '../lib/api'
import { REC_DETAIL, REC_LABEL, REC_TONE, STATUS_LABEL, STATUS_TONE, TYPE_LABEL, initials, mb, mmss, norm, short, when } from '../lib/format'
import { LinkActions } from '../components/LinkActions'
import { ask } from '../components/dialogs'

let iid = ''
const REASON_LABEL: Record<string, string> = { reference: 'Start of interview', periodic: 'Routine', tab_hidden: 'Left the interview tab', window_blur: 'Switched to another window',
  tab_hidden_away: 'Still away from the interview', window_blur_away: 'Still in another window', tab_return: 'Came back', multi_monitor: 'Second screen connected',
  no_face: 'No face on camera', multiple_faces: 'More than one face', share_stopped: 'Screen sharing stopped', voice_while_muted: 'Voice while muted' }
const WARN_LABEL: Record<string, string> = { tab_hidden: 'Left the interview tab', window_blur: 'Switched to another window', multi_monitor: 'Second screen connected' }

type Rec = any
let PARTS: any[] = []
/** Jump every video part to the moment `ts` (server time, seconds) and play the camera part. Also used by tests. */
function jump(ts?: number | null) {
  if (!ts || !PARTS.length) return
  const cams = PARTS.filter(p => p.kind === 'candidate_video')
  const pick = (list: any[]) => { let best: any = null; for (const p of list) if (p.started_at <= ts + 1 && (!best || p.started_at > best.started_at)) best = p; return best || list[0] }
  const c = pick(cams.length ? cams : PARTS)
  document.querySelectorAll<HTMLVideoElement>('video[data-file]').forEach(v => {
    const p = PARTS.find(x => x.file === v.dataset.file); if (!p) return
    if (p === c || (p.kind === 'screen_video' && p.session === c.session)) { v.currentTime = Math.max(0, ts - p.started_at - 1); if (p === c) v.play().catch(() => {}) }
  })
  document.getElementById('recordings')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
;(window as any).jump = jump

function T({ ts, children }: { ts?: number | null; children: ReactNode }) {
  if (!ts) return <>{children}</>
  return <button type="button" onClick={() => jump(ts)} title="Play the recording from here" className="tabular inline-flex items-center gap-1 whitespace-nowrap font-medium text-brand-600 hover:underline dark:text-brand-300">{children}</button>
}
function Section({ id, title, description, action, children, className }: { id?: string; title: ReactNode; description?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return <Card id={id} className={cn('scroll-mt-24', className)}><CardHeader title={title} description={description} action={action} /><CardBody>{children}</CardBody></Card>
}

export default function Report({ id }: { id: string }) {
  const [rec, setRec] = useState<Rec | null>(null)
  const [err, setErr] = useState('')
  const timer = useRef<number>(undefined)
  const load = useCallback(async () => {
    try {
      const r = await api<Rec>(`/api/interviews/${encodeURIComponent(id)}`); iid = r.id; setRec(r); setErr('')
      clearTimeout(timer.current)
      const sc = r.scoring || {}
      if (sc.state === 'running' || r.status === 'in_progress' || (['completed', 'incomplete'].includes(r.status) && !r.report && sc.state !== 'failed'))
        timer.current = window.setTimeout(load, r.status === 'in_progress' ? 6000 : 5000)
    } catch (e: any) { setErr(e.message) }
  }, [id])
  useEffect(() => { load(); return () => clearTimeout(timer.current) }, [load])

  return (
    <>
      <a href="/app/interviews" className="no-print mb-4 inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"><ArrowLeft className="size-4" />All interviews</a>
      {err ? <Alert tone="danger" icon={<TriangleAlert />}>{err}</Alert> : !rec ? <div className="grid place-items-center py-24"><Spinner className="size-7 text-brand-500" /></div> : <ReportBody rec={rec} reload={load} />}
    </>
  )
}

function ReportBody({ rec, reload }: { rec: Rec; reload: () => void }) {
  const p = rec.plan, rep = rec.report, st = rec.state || { log: [], notes: {} }, pr = rec.proctoring, stats = rec.stats || {}
  const hr = rec.hr || {}, set = rec.settings || {}, start: number | null = rec.started_at
  const dq = rec.disqualified, warns: any[] = rec.warnings || []
  PARTS = (rec.media || []).filter((m: any) => m.kind === 'candidate_video' || m.kind === 'screen_video').sort((a: any, b: any) => (a.started_at || 0) - (b.started_at || 0))
  const Q = useMemo(() => Object.fromEntries(p.questions.map((q: any, i: number) => [q.id, { ...q, n: i + 1 }])), [p])
  const qRef = (qid?: string, n = 60) => { const q = qid && Q[qid]; return q ? `Q${q.n} · ${short(q.ask, n)}` : '-' }
  const qres: Record<string, any> = Object.fromEntries(((rep && rep.questions) || []).map((q: any) => [q.q_id, q]))
  const qstat: Record<string, any> = Object.fromEntries((stats.per_question || []).map((x: any) => [x.q_id, x]))
  const [hrs, setHrs] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(hr.scores || {}).map(([k, v]) => [k, String(v)])))
  const [decision, setDecision] = useState(hr.decision || ''), [notes, setNotes] = useState(hr.notes || '')
  const [busy, setBusy] = useState('')
  const c = rep?.computed || {}
  const overall: number | null = typeof c.overall === 'number' ? c.overall : null

  async function act(kind: 'score' | 'close' | 'delete' | 'save') {
    try {
      if (kind === 'score') { setBusy('score'); await api(`/api/interviews/${iid}/score`, { method: 'POST' }); toast('Scoring started'); setTimeout(reload, 1500) }
      if (kind === 'close') { if (!await ask('Close this interview? The candidate will not be able to continue.')) return; await api(`/api/interviews/${iid}/close`, { method: 'POST' }); reload() }
      if (kind === 'delete') {
        if (!await ask('Permanently delete this interview, its transcript, report, snapshots and recordings from this server and its storage? Vapi and the AI provider keep their own copies under their retention policies.')) return
        await api(`/api/interviews/${iid}`, { method: 'DELETE' }); location.href = '/app/interviews'
      }
      if (kind === 'save') {
        setBusy('save')
        const scores = Object.fromEntries(Object.entries(hrs).filter(([, v]) => v).map(([k, v]) => [k, +v]))
        await api(`/api/interviews/${iid}/hr`, { json: { scores, decision, notes } }); toast('HR review saved'); reload()
      }
    } catch (e: any) { toast(e.message) } finally { setBusy('') }
  }

  // ---- chart rows
  const scoreRows: BarRow[] = p.questions.filter((q: any) => q.scored).map((q: any) => {
    const r = qres[q.id] || {}, n = Q[q.id].n
    return { key: q.id, label: `Q${n} · ${TYPE_LABEL[q.type] || q.type}`, sub: q.ask, value: r.score ?? null, marker: hrs[q.id] ? +hrs[q.id]! : null,
      display: r.score != null ? `${r.score}/5` : '-', tip: <><b>Q{n}.</b> {q.ask}<div className="mt-1 text-slate-300">AI score: {r.score ?? 'not scored'}{hrs[q.id] ? ` · Your score: ${hrs[q.id]}` : ''}</div></> }
  })
  const byComp: Record<string, number[]> = {}
  ;((rep && rep.questions) || []).forEach((qr: any) => { const q = Q[qr.q_id]; if (q && q.scored && qr.score != null) (byComp[q.competency_id] ||= []).push(qr.score) })
  const compRows: BarRow[] = (p.competencies || []).map((cc: any) => {
    const v = byComp[cc.id], avg = v ? v.reduce((a, b) => a + b, 0) / v.length : null
    return { key: cc.id, label: cc.name, sub: `weight ${Math.round((cc.weight || 0) * 100)}%`, value: avg, display: avg != null ? avg.toFixed(1) : '-',
      tip: <><b>{cc.name}</b><div className="mt-1 text-slate-300">{v ? `${v.length} scored answer${v.length > 1 ? 's' : ''}, average ${avg!.toFixed(1)}/5` : 'No scored answers'} · weight {Math.round((cc.weight || 0) * 100)}%</div></> }
  })
  const timeRows: BarRow[] = (stats.per_question || []).map((x: any) => {
    const q = Q[x.q_id] || { n: '?', ask: '' }
    return { key: x.q_id, label: `Q${q.n}`, sub: q.ask, value: x.seconds, display: mmss(x.seconds),
      tip: <><b>Q{q.n}.</b> {q.ask}<div className="mt-1 text-slate-300">{mmss(x.seconds)} · {x.answer_words} words · {x.followups} follow-up{x.followups === 1 ? '' : 's'}{x.repeats ? ` · asked to repeat ${x.repeats}×` : ''}</div></> }
  })

  // ---- flagged moments: screen as it was + camera photo from the same moment
  const imgs = [...(rec.images || [])].sort((a: any, b: any) => a.at - b.at)
  const routineReasons = ['periodic', 'reference', 'tab_return']
  const used = new Set<string>(), moments: { at: number; reason: string; scr?: any; cam?: any }[] = []
  imgs.filter(s => !routineReasons.includes(s.reason)).forEach(s => {
    if (used.has(s.file)) return; used.add(s.file)
    const partner = imgs.find(o => !used.has(o.file) && (o.source || 'camera') !== (s.source || 'camera') && Math.abs(o.at - s.at) < 4 && o.reason.replace('_away', '') === s.reason.replace('_away', ''))
    if (partner) used.add(partner.file)
    const both = [s, partner].filter(Boolean)
    moments.push({ at: s.at, reason: s.reason, scr: both.find((x: any) => x.source === 'screen'), cam: both.find((x: any) => (x.source || 'camera') === 'camera') })
  })
  const routine = imgs.filter(s => routineReasons.includes(s.reason))

  // ---- transcript with the interviewer's warnings merged in
  const lines = useMemo(() => {
    const log = (st.log || []).map((e: any) => ({ ...e }))
    for (const w of warns) {
      const prev = log.filter((e: any) => (e.ts || 0) <= w.at)
      log.push({ role: 'ai', text: w.say, q_id: w.q_id, ts: w.at, t: prev.length ? prev[prev.length - 1].t : 0, action: w.action === 'terminate' ? 'integrity_termination' : 'integrity_warning' })
    }
    return log.sort((a: any, b: any) => (a.ts || 0) - (b.ts || 0))
  }, [st.log, warns])
  const logTs = (st.log || []).filter((e: any) => e.role === 'candidate')
  const media: any[] = rec.media || []
  const sc = rec.scoring || {}
  const nav = [['overview', 'Overview'], ['integrity', 'Integrity'], ['recordings', 'Recordings'], ['answers', 'Answers'], ['transcript', 'Transcript']]

  return (
    <div className="space-y-5">
      {/* header */}
      <Card className="p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div className="flex min-w-0 items-center gap-4">
            <span className="grid size-14 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-violet-500 text-lg font-bold text-white shadow-lg shadow-brand-600/20">{initials(p.candidate_name)}</span>
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">{p.candidate_name || 'Candidate'}</h1>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                <span className="font-medium text-slate-700 dark:text-slate-200">{p.role}</span>{p.company && <span>· {p.company}</span>}{set.candidate_email && <span>· {set.candidate_email}</span>}
                <Badge tone={STATUS_TONE[rec.status]}>{STATUS_LABEL[rec.status] || rec.status}</Badge>
                {dq ? <Badge tone="danger" icon={<UserX />}>Disqualified</Badge> : rec.ended_early ? <Badge tone="warning">Ended early</Badge> : null}
              </div>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{start ? `Interviewed ${when(start)}` : `Created ${when(rec.created_at)} · link expires ${when(rec.expires_at)}`}</p>
            </div>
          </div>
          <div className="no-print flex flex-wrap gap-2">
            <Button variant="primary" href={withKey(`/api/interviews/${iid}/report.pdf`)} icon={<Download />}>Download PDF report</Button>
            <Button href={withKey(`/api/interviews/${iid}/bundle.zip`)} icon={<Download />}>Download everything (ZIP)</Button>
          </div>
        </div>
        <div className="no-print mt-5 flex flex-wrap gap-1.5 border-t border-slate-100 pt-4 dark:border-ink-800">
          <Button size="sm" variant="ghost" href={withKey(`/api/interviews/${iid}/transcript.txt`)} icon={<FileText />}>Transcript (TXT)</Button>
          <Button size="sm" variant="ghost" href={withKey(`/api/interviews/${iid}/export.json`)} icon={<FileJson />}>Data (JSON)</Button>
          <Button size="sm" variant="ghost" icon={<Printer />} onClick={() => print()}>Print</Button>
          <Button size="sm" variant="ghost" icon={<Sparkles />} disabled={!rec.state} loading={busy === 'score'} onClick={() => act('score')}>{rep ? 'Re-score with AI' : 'Score now'}</Button>
          {['in_progress', 'created'].includes(rec.status) && <Button size="sm" variant="ghost" icon={<XCircle />} onClick={() => act('close')}>Close interview</Button>}
          <LinkActions url={`${location.origin}/interview.html?id=${iid}`} icon={<Link2 className="size-3.5" />} label="Candidate link" copied="Candidate link copied"
            to={{ email: rec.settings?.candidate_email, name: rec.plan?.candidate_name }} subject={`Your interview${rec.plan?.role ? ` for ${rec.plan.role}` : ''}`}
            message={`Hi ${(rec.plan?.candidate_name || '').split(' ')[0] || 'there'}, here is the link to your AI interview${rec.plan?.role ? ` for ${rec.plan.role}` : ''}. Use a laptop with a camera and a quiet room:`} />
          <Button size="sm" variant="ghost" className="text-red-600 hover:bg-red-50 hover:text-red-700 dark:text-red-300 dark:hover:bg-red-500/10" icon={<Trash2 />} onClick={() => act('delete')}>Delete all data</Button>
        </div>
        {sc.state === 'running' && <p className="mt-3 flex items-center gap-2 text-sm text-slate-500"><Spinner className="size-4" />AI scoring in progress. This page updates by itself.</p>}
        {sc.state === 'failed' && <Alert className="mt-3" tone="danger" icon={<TriangleAlert />}>AI scoring failed: {sc.error}. Click "Score now" to retry. The integrity report and recordings don't depend on it.</Alert>}
      </Card>

      <nav className="no-print sticky top-[61px] z-20 -mx-1 flex gap-1 overflow-x-auto rounded-2xl bg-slate-50/90 p-1 backdrop-blur dark:bg-ink-950/90 lg:top-2">
        {nav.map(([id, label]) => <a key={id} href={`#${id}`} className="whitespace-nowrap rounded-xl px-3.5 py-2 text-sm font-medium text-slate-600 hover:bg-white hover:text-slate-900 hover:shadow-sm dark:text-slate-300 dark:hover:bg-ink-850 dark:hover:text-white">{label}</a>)}
      </nav>

      {dq ? (
        <div className="dq flex gap-4 rounded-2xl bg-red-50 p-5 ring-1 ring-red-200 dark:bg-red-500/10 dark:ring-red-500/25">
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-red-100 text-red-600 dark:bg-red-500/20 dark:text-red-300"><UserX className="size-5" /></span>
          <div className="min-w-0">
            <h2 className="font-semibold text-red-800 dark:text-red-200">Interview stopped: rules broken after {Math.max(0, warns.length - 1)} warning{warns.length - 1 === 1 ? '' : 's'}</h2>
            <p className="mt-1 text-sm text-red-900/80 dark:text-red-100/80">{dq.reason}</p>
            <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm text-slate-700 dark:text-slate-200">
              {warns.map((w, i) => <li key={i}><T ts={w.at}>{mmss(start ? w.at - start : null)}</T> · {WARN_LABEL[w.type] || w.type}{w.q_id && <> during <i>{qRef(w.q_id, 50)}</i></>}: <span className="text-slate-500 dark:text-slate-400">"{w.say}"</span></li>)}
            </ol>
          </div>
        </div>
      ) : warns.length > 0 && <Alert icon={<TriangleAlert />}>The interviewer warned the candidate {warns.length} time{warns.length > 1 ? 's' : ''} for leaving the interview. See the flagged moments below.</Alert>}

      {/* overview */}
      <div id="overview" className="grid scroll-mt-24 gap-5 lg:grid-cols-3">
        <Card className="p-6">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">AI recommendation <span className="normal-case tracking-normal font-normal">(HR decides)</span></div>
          {rep ? <><div className={cn('mt-2 text-4xl font-bold tracking-tight', REC_TONE[rep.recommendation] === 'success' ? 'text-emerald-600 dark:text-emerald-400' : REC_TONE[rep.recommendation] === 'danger' ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400')}>{REC_LABEL[rep.recommendation] || rep.recommendation}</div>
            <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{REC_DETAIL[rep.recommendation] ? `AI grade: ${REC_DETAIL[rep.recommendation]} · ` : ''}Confidence: {rep.confidence || '-'}</div></>
            : <div className="mt-2 text-xl font-semibold text-slate-500 dark:text-slate-400">{rec.status === 'in_progress' ? 'Interview in progress' : rec.status === 'created' ? 'Not taken yet' : 'Not scored yet'}</div>}
          <div className="mt-6 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Overall score</div>
          <div className="tabular mt-1 text-5xl font-bold tracking-tight text-slate-900 dark:text-white">{overall != null ? overall.toFixed(1) : '-'}<span className="text-xl font-semibold text-slate-500 dark:text-slate-400"> / 5</span></div>
          <div className="relative mt-3 h-2 rounded-r-full bg-[var(--track)]" role="img" aria-label={`Overall ${overall ?? 'not scored'} out of 5`}><i className="absolute inset-y-0 left-0 rounded-r-full bg-[var(--series-1)]" style={{ width: `${overall != null ? (overall / 5) * 100 : 0}%` }} /></div>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">Weighted by competency, computed from the per-question scores.</p>
        </Card>
        <Card className="p-6">
          <h3 className="text-[15px] font-semibold text-slate-900 dark:text-white">Interview facts</h3>
          <dl className="mt-4 space-y-2.5 text-sm">
            {([['Questions answered', `${c.questions_asked ?? (stats.per_question || []).length} of ${c.questions_planned ?? p.questions.length}`], ['Evidence quotes verified', c.evidence_verified ?? '-'],
              ['Active time', stats.active_minutes != null ? `${stats.active_minutes} min` : '-'], ['Candidate talk share', stats.candidate_talk_share != null ? `${stats.candidate_talk_share}%` : '-'],
              ['Average answer', stats.avg_answer_words != null ? `${stats.avg_answer_words} words` : '-'], ['AI turn time', c.avg_turn_latency_ms != null ? `${c.avg_turn_latency_ms} ms` : '-'],
              ['Reconnects', stats.reconnects ?? 0]] as [string, ReactNode][]).map(([k, v]) =>
              <div key={k} className="flex justify-between gap-3"><dt className="text-slate-500 dark:text-slate-400">{k}</dt><dd className="tabular font-semibold text-slate-900 dark:text-white">{v}</dd></div>)}
          </dl>
        </Card>
        <Card className="p-6">
          <h3 className="text-[15px] font-semibold text-slate-900 dark:text-white">Integrity</h3>
          {pr ? <>
            <div className={cn('mt-3 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-bold',
              pr.risk === 'high' ? 'bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300' : pr.risk === 'medium' ? 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300' : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300')}>
              {pr.risk !== 'low' && <TriangleAlert className="size-4" />}{pr.risk.toUpperCase()} RISK</div>
            <ul className="mt-3 list-disc space-y-1 pl-4 text-sm text-slate-600 dark:text-slate-300">
              {pr.reasons.slice(0, 4).map((r: string) => <li key={r}>{r}</li>)}{!pr.reasons.length && <li className="list-none -ml-4 text-emerald-600 dark:text-emerald-400">No integrity concerns detected.</li>}
            </ul>
            {pr.reasons.length > 4 && <p className="mt-2 text-xs text-slate-500">+{pr.reasons.length - 4} more under Integrity</p>}
          </> : <p className="mt-3 text-sm text-slate-500">Available once the interview starts.</p>}
        </Card>
      </div>

      {rep && (
        <Section title="Summary">
          <p className="text-[15px] leading-relaxed text-slate-700 dark:text-slate-200">{rep.summary}</p>
          {!!rep.human_review_reasons?.length && <div className="mt-4 space-y-2">{rep.human_review_reasons.map((r: string) => <Alert key={r} tone={/^DISQUALIFIED/.test(r) ? 'danger' : 'warning'} icon={<TriangleAlert />}>{r}</Alert>)}</div>}
          <div className="mt-5 grid gap-5 md:grid-cols-2">
            <div><h4 className="text-sm font-semibold text-emerald-700 dark:text-emerald-400">Strengths</h4><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700 dark:text-slate-200">{(rep.strengths || []).map((s: string) => <li key={s}>{s}</li>)}{!rep.strengths?.length && <li className="text-slate-500 dark:text-slate-400">None noted</li>}</ul></div>
            <div><h4 className="text-sm font-semibold text-amber-700 dark:text-amber-400">Concerns</h4><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700 dark:text-slate-200">
              {(rep.concerns || []).map((s: string) => <li key={s}>{s}</li>)}{(rep.red_flags || []).map((s: string) => <li key={s} className="text-red-600 dark:text-red-400"><b>Red flag:</b> {s}</li>)}
              {!rep.concerns?.length && !rep.red_flags?.length && <li className="text-slate-500 dark:text-slate-400">None noted</li>}</ul></div>
          </div>
        </Section>
      )}

      {(rep || timeRows.length > 0) && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Section title="Score by question" description="1 to 5">
            {rep ? <HBarChart rows={scoreRows} max={5} valueLabel="AI score" markerLabel={Object.values(hrs).some(Boolean) ? 'Your score' : null} /> : <p className="text-sm text-slate-500">Appears once the AI has scored the interview.</p>}
          </Section>
          <Section title="Competencies" description="Average of the scored answers">
            {rep ? <HBarChart rows={compRows} max={5} /> : <p className="text-sm text-slate-500">Appears once the AI has scored the interview.</p>}
            <h4 className="mb-3 mt-6 text-sm font-semibold text-slate-900 dark:text-white">Time spent per question</h4>
            <HBarChart rows={timeRows} empty="No answers yet." />
          </Section>
        </div>
      )}

      {pr && <Integrity pr={pr} rec={rec} start={start} warns={warns} moments={moments} routine={routine} qRef={qRef} Q={Q} stats={stats} />}

      <Section id="recordings" title="Recordings" description="The camera recording includes the candidate's microphone and the interviewer's voice, and keeps recording while the candidate is muted.">
        {!media.length && <p className="text-sm text-slate-500">No recordings yet.</p>}
        <div className="grid gap-4 md:grid-cols-2">
          {media.filter(m => m.kind !== 'call_audio').map(m => (
            <div key={m.file}>
              <div className="mb-2 flex flex-wrap items-center gap-2 text-sm"><b className="text-slate-800 dark:text-slate-100">{m.kind === 'candidate_video' ? 'Candidate camera + both voices' : m.kind === 'screen_video' ? 'Candidate screen' : m.kind === 'call_video' ? 'Vapi cloud video' : m.kind}</b>
                {m.session && <Badge>session {m.session}</Badge>}{m.duration_sec && <Badge>{mmss(m.duration_sec)}</Badge>}
                {!m.finalized && <Badge tone="warning">still uploading</Badge>}{m.finalized && m.playable === false && <Badge tone="warning">download to play</Badge>}</div>
              <video controls preload="metadata" data-file={m.file} src={mediaUrl(iid, m.file)} className="aspect-video w-full rounded-xl bg-black" />
              <a className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline dark:text-brand-300" href={mediaUrl(iid, m.file, true)}><Download className="size-3.5" />Download {mb(m.bytes)}</a>
            </div>
          ))}
        </div>
        {media.filter(m => m.kind === 'call_audio').map(m => (
          <div key={m.file} className="mt-4"><div className="mb-1 text-sm font-semibold">Call audio from Vapi <span className="font-normal text-slate-500">{mb(m.bytes)}</span></div><audio controls preload="none" src={mediaUrl(iid, m.file)} className="w-full" /></div>
        ))}
      </Section>

      <Section id="answers" title="Answers" description="Add your own score per question to measure how closely the AI agrees with your team.">
        <div className="space-y-4">
          {p.questions.map((q: any, i: number) => {
            const r = qres[q.id] || {}, noteList: string[] = (st.notes || {})[q.id] || [], qs = qstat[q.id] || {}
            const flags = pr?.per_question?.[q.id], firstAsk = (st.log || []).find((e: any) => e.role === 'ai' && e.q_id === q.id)
            const skipped = (stats.skipped || []).includes(q.id)
            return (
              <div key={q.id} className="rounded-2xl p-5 ring-1 ring-slate-200 dark:ring-ink-700">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0 flex-1 basis-72">
                    <div className="text-xs font-semibold uppercase tracking-wider text-brand-600 dark:text-brand-300">Question {i + 1} · {TYPE_LABEL[q.type] || q.type}{q.scored ? '' : ' · not scored'}</div>
                    <p className="mt-1.5 text-base font-semibold text-slate-900 dark:text-white">{q.ask}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      {qs.seconds != null && <Badge>{mmss(qs.seconds)} · {qs.answer_words} words · {qs.followups} follow-up{qs.followups === 1 ? '' : 's'}</Badge>}
                      {skipped && <Badge tone="warning">skipped for time</Badge>}{qs.seconds == null && !skipped && rec.state && <Badge>not reached</Badge>}
                      {firstAsk && <T ts={firstAsk.ts}><Play className="size-3.5" />Watch this answer</T>}
                    </div>
                  </div>
                  <div className="w-36 shrink-0">
                    <div className="tabular text-3xl font-bold text-slate-900 dark:text-white">{r.score ?? '-'}<span className="text-sm font-medium text-slate-500 dark:text-slate-400"> / 5 AI</span></div>
                    {q.scored && <Select aria-label="Your score" className="mt-2 py-1.5" value={hrs[q.id] || ''} onChange={e => setHrs(h => ({ ...h, [q.id]: e.target.value }))}>
                      <option value="">Your score</option>{[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}</option>)}</Select>}
                  </div>
                </div>
                {(r.evidence || []).map((e: any, k: number) => {
                  const hit = logTs.find((x: any) => norm(x.text).includes(norm(e.quote).slice(0, 40)))
                  return <blockquote key={k} className={cn('mt-3 border-l-[3px] py-1 pl-3 text-sm text-slate-700 dark:text-slate-200', e.verified === 'unverified' ? 'border-red-400' : e.verified === 'other_question' ? 'border-amber-400' : 'border-emerald-400')}>
                    "{e.quote}" <span className="ml-1 text-xs text-slate-500">{hit ? <T ts={hit.ts}>[{e.t}]</T> : `[${e.t}]`} {e.verified === 'unverified' ? <b className="text-red-600">not found in transcript</b> : e.verified === 'other_question' ? <b className="text-amber-600">said in a different answer</b> : 'verified'}</span>
                  </blockquote>
                })}
                {r.rationale && <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{r.rationale}</p>}
                {!!r.missed_points?.length && <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">Missed: {r.missed_points.join(' · ')}</p>}
                {noteList.length > 0 && <p className="mt-2 text-xs text-slate-500">Interviewer notes: {noteList.join(' | ')}</p>}
                {flags && <p className="mt-2 text-xs font-medium text-red-600 dark:text-red-400">Integrity during this question: {Object.entries(flags.types).map(([k, v]) => `${k} ×${v}`).join(', ')}</p>}
              </div>
            )
          })}
        </div>
        <div className="mt-6 grid gap-4 rounded-2xl bg-slate-50 p-5 dark:bg-ink-850 md:grid-cols-[220px_1fr]">
          <div><label htmlFor="decision" className="mb-1.5 block text-[13px] font-semibold">Your decision</label>
            <Select id="decision" value={decision} onChange={e => setDecision(e.target.value)}><option value="">Undecided</option><option value="next_round">Next round</option><option value="hold">Hold</option><option value="reject">Reject</option></Select></div>
          <div><label htmlFor="notes" className="mb-1.5 block text-[13px] font-semibold">Notes</label><Textarea id="notes" className="min-h-11" value={notes} onChange={e => setNotes(e.target.value)} /></div>
          <div className="md:col-span-2"><Button id="saveHr" variant="primary" loading={busy === 'save'} onClick={() => act('save')}>Save HR review</Button></div>
        </div>
      </Section>

      {!!rep?.resume_claims?.length && (
        <Section title="Resume claims">
          <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-xs text-slate-500"><th className="py-2 pr-4 font-medium">Claim</th><th className="py-2 pr-4 font-medium">Status</th><th className="py-2 font-medium">Note</th></tr></thead>
            <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{rep.resume_claims.map((r: any, i: number) => <tr key={i}><td className="py-2.5 pr-4">{r.claim}</td>
              <td className="py-2.5 pr-4"><Badge tone={r.status === 'supported' ? 'success' : r.status === 'contradicted' ? 'danger' : r.status === 'weak' ? 'warning' : 'neutral'}>{String(r.status || '').replace('_', ' ')}</Badge></td><td className="py-2.5 text-slate-600 dark:text-slate-300">{r.note}</td></tr>)}</tbody></table></div>
        </Section>
      )}

      <Section title="Sessions, device and consent">
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[180px_1fr]">
          <dt className="text-slate-500">Consent</dt><dd>{rec.consent ? `Given ${when(rec.consent.at)} from ${rec.consent.ip}` : <span className="text-red-600">Not recorded</span>}</dd>
          {(rec.sessions || []).map((s: any) => [<dt key={`k${s.n}`} className="text-slate-500">Session {s.n}</dt>, <dd key={`v${s.n}`} className="break-words">{when(s.at)} · IP {s.ip} · {(s.ua || '').slice(0, 100)}</dd>])}
          {Object.entries(rec.device || {}).map(([k, v]) => [<dt key={`k${k}`} className="capitalize text-slate-500">{k.replace(/_/g, ' ')}</dt>, <dd key={`v${k}`} className="break-words">{String(v)}</dd>])}
          <dt className="text-slate-500">Candidate feedback</dt><dd>{rec.feedback ? `${'★'.repeat(rec.feedback.rating)} ${rec.feedback.comment || ''}` : '-'}</dd>
          <dt className="text-slate-500">Settings</dt><dd>Warnings {set.enforce_focus === false ? 'off' : `on (${set.max_warnings ?? 2} before stopping)`} · one screen {set.block_multi_monitor === false ? 'not enforced' : 'enforced'} · screen share {set.require_screen_share ? 'required' : 'optional'} · rejoin window {rec.reconnect_window_sec}s · face check {set.face_detection === false ? 'off' : 'on'}</dd>
        </dl>
      </Section>

      <Card id="transcript" className="scroll-mt-24">
        <details open={!rep} className="group">
          <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4"><span className="text-[15px] font-semibold">Transcript <span className="ml-1 text-sm font-normal text-slate-500">({(st.log || []).length} turns, click a time to watch)</span></span></summary>
          <div className="max-h-[640px] space-y-1 overflow-y-auto px-5 pb-5 text-sm">
            {!lines.length && <p className="text-slate-500">No transcript yet.</p>}
            {(() => { let last: string | null = null; return lines.map((e: any, i: number) => {
              const head = e.role === 'ai' && e.q_id !== last && ['open', 'resume', 'next_question'].includes(e.action) && Q[e.q_id]
              if (head) last = e.q_id
              const warn = /^integrity/.test(e.action || '')
              return <div key={i}>
                {head && <div className="mb-1 mt-4 rounded-lg bg-brand-50 px-3 py-2 text-[13px] font-semibold text-brand-800 dark:bg-brand-500/10 dark:text-brand-200">Question {Q[e.q_id].n}: {Q[e.q_id].ask}</div>}
                <div className={cn('grid grid-cols-[56px_1fr] gap-2 rounded-lg px-1 py-1.5', warn && 'bg-red-50 dark:bg-red-500/10')}>
                  <T ts={e.ts}>[{mmss(e.t)}]</T>
                  <span><b className={e.role === 'ai' ? 'text-slate-500 dark:text-slate-400' : 'text-slate-900 dark:text-white'}>{e.role === 'ai' ? 'Interviewer' : 'Candidate'}:</b> {e.text}
                    {warn && <Badge tone="danger" className="ml-1.5">{e.action === 'integrity_termination' ? 'interview stopped' : 'warning'}</Badge>}{e.fallback && <Badge tone="warning" className="ml-1.5">fallback</Badge>}</span>
                </div>
              </div>
            }) })()}
          </div>
        </details>
      </Card>
    </div>
  )
}

function Integrity({ pr, rec, start, warns, moments, routine, qRef, Q, stats }: any) {
  const d = pr.durations || {}, cnt = pr.counts || {}, set = rec.settings || {}, dq = rec.disqualified
  const tiles: [string, string][] = [
    ['Interviewer warnings', set.enforce_focus === false ? 'off' : dq ? `${warns.length - 1} · then stopped` : `${warns.length} (limit ${set.max_warnings ?? 2})`],
    ['Left the tab', `${cnt.tab_hidden || 0}× · ${d.tab_hidden || 0}s`], ['Other window focused', `${cnt.window_blur || 0}× · ${d.window_blur || 0}s`],
    ['Second screen', `${cnt.multi_monitor || 0}×`], ['No face on camera', `${cnt.face_missing_start || 0}× · ${d.face_missing_start || 0}s`],
    ['Multiple faces', `${cnt.multiple_faces || 0}×`], ['Muted', `${cnt.mute_on || 0}× · ${d.mute_on || 0}s`], ['Paste / copy', `${cnt.paste || 0} / ${cnt.copy || 0}`],
    ['Screen share stopped', `${cnt.screen_share_stopped || 0}× · ${d.screen_share_stopped || 0}s`], ['Full screen exits', `${cnt.fullscreen_exit || 0}`],
    ['Connection lost', `${cnt.network_offline || 0}× · ${d.network_offline || 0}s`], ['Reconnects', `${stats.reconnects || 0}`]]
  const flagged = pr.timeline.filter((x: any) => x.severity !== 'info' && x.t != null && !['integrity_warning', 'disqualified'].includes(x.type))
  const ends = [...(rec.state?.log || []).map((e: any) => e.ts || 0), ...pr.timeline.map((x: any) => x.at || 0)]
  const duration = start && ends.length ? Math.max(...ends) - start : 0
  // The warning records the question on screen at that moment; fall back to the nearest logged event.
  const qAt = (at: number) => warns.find((w: any) => Math.abs(w.at - at) < 6 && w.q_id)?.q_id
    || pr.timeline.find((x: any) => x.at && Math.abs(x.at - at) < 5 && x.q_id)?.q_id
  return (
    <Section id="integrity" title="Integrity and proctoring" description="Signals, not proof. Click a time to watch that moment in the recording.">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
        {tiles.map(([k, v]) => <div key={k} className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200/70 dark:bg-ink-850 dark:ring-ink-700"><div className="text-[11px] font-medium text-slate-500 dark:text-slate-400">{k}</div><div className="tabular mt-1 text-[15px] font-semibold text-slate-900 dark:text-white">{v}</div></div>)}
      </div>
      <h4 className="mb-3 mt-6 text-sm font-semibold text-slate-900 dark:text-white">When it happened</h4>
      <TimelineChart duration={duration} events={flagged.map((x: any) => ({ t: x.t, severity: x.severity === 'high' ? 'high' : 'medium', label: x.label + (x.duration ? ` (${x.duration}s)` : ''), q: x.q_id ? qRef(x.q_id) : '', detail: x.detail }))}
        markers={warns.map((w: any) => ({ t: start ? w.at - start : 0, label: `Interviewer warning ${w.n}${w.action === 'terminate' ? ' (interview stopped)' : ''}` }))} />
      {pr.reasons.length ? <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-slate-700 dark:text-slate-200">{pr.reasons.map((r: string) => <li key={r}>{r}</li>)}</ul>
        : <p className="mt-4 text-sm text-emerald-600 dark:text-emerald-400">No integrity concerns detected.</p>}

      {moments.length > 0 && <>
        <h4 className="mt-7 text-sm font-semibold text-slate-900 dark:text-white">Flagged moments <span className="font-normal text-slate-500">({moments.length})</span></h4>
        <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">What was on the candidate's screen at that moment, with the camera photo taken at the same time.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {moments.map((m: any, i: number) => { const main = m.scr || m.cam, q = qAt(m.at)
            return (
              <figure key={i} className="moment overflow-hidden rounded-2xl bg-slate-50 ring-1 ring-slate-200 dark:bg-ink-850 dark:ring-ink-700">
                <div className="relative aspect-[16/10] bg-black">
                  <a href={mediaUrl(iid, main.file)} target="_blank" rel="noopener"><img src={mediaUrl(iid, main.file)} alt={REASON_LABEL[m.reason] || m.reason} className={cn('size-full', m.scr ? 'object-contain' : 'object-cover')} /></a>
                  {m.scr && m.cam && <a href={mediaUrl(iid, m.cam.file)} target="_blank" rel="noopener" className="absolute bottom-2 right-2 w-[32%] overflow-hidden rounded-lg shadow-xl ring-2 ring-white"><img src={mediaUrl(iid, m.cam.file)} alt="Camera at the same moment" className="w-full" /></a>}
                </div>
                <figcaption className="px-3.5 py-2.5 text-[13px]"><div className="font-semibold text-slate-900 dark:text-white">{REASON_LABEL[m.reason] || m.reason.replace(/_/g, ' ')}</div>
                  <div className="mt-0.5 text-slate-500 dark:text-slate-400"><T ts={m.at}>{mmss(start ? m.at - start : null)}</T>{q && <> · {qRef(q, 40)}</>}</div></figcaption>
              </figure>
            ) })}
        </div>
      </>}
      {routine.length > 0 && (
        <details className="mt-6"><summary className="cursor-pointer text-sm font-semibold text-slate-900 dark:text-white">Routine snapshots <span className="font-normal text-slate-500">({routine.length})</span></summary>
          <div className="snaps mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-6">
            {routine.map((s: any) => <figure key={s.file}><a href={mediaUrl(iid, s.file)} target="_blank" rel="noopener"><img loading="lazy" src={mediaUrl(iid, s.file)} alt="" className="aspect-[4/3] w-full rounded-lg bg-black object-cover" /></a>
              <figcaption className="mt-1 text-[11px] text-slate-500">{s.source === 'screen' ? 'Screen' : 'Camera'} · {REASON_LABEL[s.reason] || s.reason} · <T ts={s.at}>{mmss(start ? s.at - start : null)}</T></figcaption></figure>)}
          </div>
        </details>
      )}
      <details open={pr.timeline.some((x: any) => x.severity !== 'info')} className="mt-6">
        <summary className="cursor-pointer text-sm font-semibold text-slate-900 dark:text-white">Event timeline <span className="font-normal text-slate-500">({pr.timeline.length})</span></summary>
        <div className="mt-3 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-xs text-slate-500"><th className="py-2 pr-4 font-medium">When</th><th className="py-2 pr-4 font-medium">During question</th><th className="py-2 pr-4 font-medium">Event</th><th className="py-2 font-medium">Detail</th></tr></thead>
          <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{pr.timeline.map((x: any, i: number) => <tr key={i}>
            <td className="py-2 pr-4"><T ts={x.at}>{mmss(x.t)}</T></td>
            <td className="qref max-w-72 py-2 pr-4 text-[13px] text-slate-600 dark:text-slate-300" title={Q[x.q_id]?.ask || ''}>{qRef(x.q_id, 50)}</td>
            <td className={cn('py-2 pr-4', x.severity === 'high' ? 'font-semibold text-red-600 dark:text-red-400' : x.severity === 'medium' ? 'text-amber-700 dark:text-amber-400' : 'text-slate-700 dark:text-slate-200')}>{x.label}{x.duration ? ` (${x.duration}s)` : ''}</td>
            <td className="py-2 text-xs text-slate-500">{x.detail}</td></tr>)}</tbody></table></div>
      </details>
    </Section>
  )
}
