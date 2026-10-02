// Pipeline board for one job: a column per round (kanban) or a list, filters, bulk actions and the application drawer.
import { Check, CheckCheck, Columns3, Flag, Hand, List, MessageSquare, Search, Send, SlidersHorizontal, Trophy, Users, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Badge, Button, Card, Field, Input, Modal, Select, Spinner, Textarea, cn, toast } from '../../components/ui'
import { Avatar, BoardSkeleton, Empty, ErrorBox, ScoreBar, useApi } from '../../components/kit'
import { api } from '../../lib/api'
import { ago } from '../../lib/format'
import { navigate, useLocation } from '../../lib/router'
import AppDrawer from './AppDrawer'
import { STATUS_TONE, type Round, type RoundSummary } from './types'
import { ask } from '../../components/dialogs'
import { Stepper } from '../../components/pickers'

export interface PipeItem {
  id: string; ref?: string; stage: string; stage_label: string; round_id: string | null; round_status: string | null; created_at: number; updated_at: number; rating: number | null
  source: string; college: string; match_score: number | null; human_requested: boolean; accommodation: string | null; knockout_failed: string[] | null
  candidate: { id: string; ref: string; name: string; email: string; location?: string; headline?: string; years?: number | null; notice_days?: number | null; expected_salary?: number | null; college?: string }
  current: RoundSummary | null; scores: Record<string, number>; flags: string[]
}
interface Pipe { rounds: Round[]; items: PipeItem[]; permission: string; statuses: Record<string, string> }
type Col = { id: string; title: string; round?: Round; items: PipeItem[] }

const CLOSED = ['rejected', 'withdrawn'], DONE = ['offer', 'hired']

export default function Board({ jobId, jobRef }: { jobId: string; jobRef?: string }) {
  const { query } = useLocation()
  const { data, error, reload, setData } = useApi<Pipe>(`/api/jobs/${jobId}/pipeline`)
  const [moving, setMoving] = useState<Set<string>>(new Set())
  const [topRound, setTopRound] = useState<Round | null>(null)
  const [view, setView] = useState<'board' | 'list'>((localStorage.getItem('tl.pipeView') as 'board' | 'list') || 'board')
  const [f, setF] = useState({ q: '', minScore: '', location: '', maxNotice: '', college: '', status: '', flagged: false, closed: false })
  const [showFilters, setShowFilters] = useState(false)
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [open, setOpen] = useState<string | null>(query.get('app'))
  const [dragId, setDragId] = useState<string | null>(null), [overCol, setOverCol] = useState<string | null>(null)
  const [bulk, setBulk] = useState<null | 'reject' | 'message' | 'move'>(null)
  const items = useMemo(() => (data?.items || []).filter(a => {
    const c = a.candidate, sc = a.current?.score ?? a.match_score
    if (f.q && !`${c.name} ${c.email} ${c.headline || ''}`.toLowerCase().includes(f.q.toLowerCase())) return false
    if (f.minScore && (sc == null || sc < +f.minScore)) return false
    if (f.location && !(c.location || '').toLowerCase().includes(f.location.toLowerCase())) return false
    if (f.maxNotice && (c.notice_days == null || c.notice_days > +f.maxNotice)) return false
    if (f.college && a.college !== f.college) return false
    if (f.status && a.round_status !== f.status) return false
    if (f.flagged && !a.flags.length) return false
    return true
  }), [data, f])
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!data) return <BoardSkeleton />
  const canEdit = data.permission !== 'view'
  const colleges = [...new Set(data.items.map(a => a.college).filter(Boolean))].sort()
  const cols: Col[] = [
    ...(items.some(a => !a.round_id && !CLOSED.includes(a.stage) && !DONE.includes(a.stage)) ? [{ id: '_none', title: 'Not in the flow yet', items: items.filter(a => !a.round_id && !CLOSED.includes(a.stage) && !DONE.includes(a.stage)) }] : []),
    ...data.rounds.map(r => ({ id: r.id, title: r.name, round: r, items: items.filter(a => a.round_id === r.id && !CLOSED.includes(a.stage) && !DONE.includes(a.stage)) }))
      .filter(c => c.round.type !== 'application' || c.items.length > 0),
    { id: '_selected', title: 'Selected', items: items.filter(a => DONE.includes(a.stage)) },
    ...(f.closed ? [{ id: '_closed', title: 'Not progressed', items: items.filter(a => CLOSED.includes(a.stage)) }] : []),
  ]
  const orphan = items.filter(a => a.round_id && !data.rounds.some(r => r.id === a.round_id) && !CLOSED.includes(a.stage) && !DONE.includes(a.stage))
  if (orphan.length) cols.splice(cols.length - (f.closed ? 2 : 1), 0, { id: '_removed', title: 'In a removed round', items: orphan })
  const listItems = items.filter(a => f.closed || !CLOSED.includes(a.stage))
  const toggle = (id: string) => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const openApp = (id: string | null) => { setOpen(id); const ref = id && (items.find(a => a.id === id)?.ref || id); navigate(`/app/jobs/${jobRef || jobId}?tab=pipeline${ref ? `&app=${ref}` : ''}`, { replace: true, keepScroll: true }) }
  async function runBulk(action: string, extra: Record<string, unknown> = {}) {
    try {
      const r = await api<{ done: number; errors: { id: string; error: string }[] }>('/api/applications/bulk', { json: { ids: [...sel], action, ...extra } })
      toast(`${r.done} updated${r.errors.length ? `, ${r.errors.length} skipped: ${r.errors[0]!.error}` : ''}`); setSel(new Set()); setBulk(null); reload()
    } catch (e: any) { toast(e.message) }
  }
  // Show a move at once (the card jumps to its new column marked "Moving…"), then confirm it with the server;
  // a refused move puts the card back. A card that is moving can't be moved again.
  const optimistic = (id: string, patch: Partial<PipeItem>) =>
    setData(d => d && { ...d, items: d.items.map(x => x.id === id ? { ...x, ...patch, round_status: 'moving', current: x.current ? { ...x.current, status: 'moving', status_label: 'Moving…' } : x.current } : x) })
  async function dropOn(col: Col) {
    const a = data!.items.find(x => x.id === dragId); setDragId(null); setOverCol(null)
    if (!a || !canEdit || moving.has(a.id)) return
    let action = 'move'
    if (col.id === '_selected') action = 'select'
    else if (col.id === '_closed') action = 'reject'
    else if (!col.round || col.round.id === a.round_id) return
    if (action === 'select' && !await ask(`Select ${a.candidate.name} for the job?`)) return
    if (action === 'reject') { setSel(new Set([a.id])); setBulk('reject'); return }
    setMoving(m => new Set(m).add(a.id))
    optimistic(a.id, action === 'select' ? { stage: 'selected' } : { round_id: col.round!.id })
    try { await api(`/api/applications/${a.id}/decide`, { json: { action, round_id: col.round?.id } }); toast(`${a.candidate.name} → ${col.title}`) }
    catch (e: any) { toast(e.message) }
    await reload(); setMoving(m => { const n = new Set(m); n.delete(a.id); return n })
  }
  async function startWaiting(col: Col) {
    const ids = col.items.filter(a => a.current?.status === 'pending').map(a => a.id)
    if (!await ask(`Start "${col.title}" for ${ids.length} candidate(s)? Their invitations go out now.`)) return
    try { const r = await api<{ done: number; errors: { error: string }[] }>('/api/applications/bulk', { json: { ids, action: 'move', round_id: col.round!.id } }); toast(`${r.done} started${r.errors.length ? `, ${r.errors.length} skipped` : ''}`); reload() } catch (e: any) { toast(e.message) }
  }
  const topN = (r: Round) => setTopRound(r)

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-48 flex-1 sm:max-w-xs"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-500 dark:text-slate-400" />
          <Input type="search" aria-label="Search applicants" className="pl-9" placeholder="Search name or email" value={f.q} onChange={e => setF({ ...f, q: e.target.value })} /></div>
        <Button icon={<SlidersHorizontal />} onClick={() => setShowFilters(x => !x)} aria-expanded={showFilters}>Filters{Object.entries(f).filter(([k, v]) => k !== 'q' && k !== 'closed' && v).length ? ` (${Object.entries(f).filter(([k, v]) => k !== 'q' && k !== 'closed' && v).length})` : ''}</Button>
        <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={f.closed} onChange={e => setF({ ...f, closed: e.target.checked })} />Show not progressed</label>
        <span className="ml-auto inline-flex rounded-xl bg-slate-100 p-1 dark:bg-ink-850">
          {(['board', 'list'] as const).map(v => <button key={v} aria-pressed={view === v} onClick={() => { setView(v); try { localStorage.setItem('tl.pipeView', v) } catch { /* private mode */ } }}
            className={cn('flex items-center gap-1.5 rounded-lg px-3 py-1 text-sm font-medium', view === v ? 'bg-white shadow-sm dark:bg-ink-700' : 'text-slate-500')}>{v === 'board' ? <Columns3 className="size-4" /> : <List className="size-4" />}{v === 'board' ? 'Board' : 'List'}</button>)}
        </span>
      </div>
      {showFilters && (
        <Card className="mb-3 grid gap-3 p-4 sm:grid-cols-3 lg:grid-cols-6">
          <Field label="Min score" htmlFor="f-sc"><Input id="f-sc" type="number" min={0} max={100} value={f.minScore} onChange={e => setF({ ...f, minScore: e.target.value })} /></Field>
          <Field label="Location" htmlFor="f-loc"><Input id="f-loc" value={f.location} onChange={e => setF({ ...f, location: e.target.value })} /></Field>
          <Field label="Notice up to (days)" htmlFor="f-np"><Input id="f-np" type="number" min={0} value={f.maxNotice} onChange={e => setF({ ...f, maxNotice: e.target.value })} /></Field>
          <Field label="College" htmlFor="f-col"><Select id="f-col" value={f.college} onChange={e => setF({ ...f, college: e.target.value })}><option value="">Any</option>{colleges.map(c => <option key={c}>{c}</option>)}</Select></Field>
          <Field label="Round status" htmlFor="f-st"><Select id="f-st" value={f.status} onChange={e => setF({ ...f, status: e.target.value })}><option value="">Any</option>{Object.entries(data.statuses).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
          <div className="flex flex-col justify-end gap-2"><label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={f.flagged} onChange={e => setF({ ...f, flagged: e.target.checked })} />Integrity flags only</label>
            <button className="text-left text-sm font-medium text-brand-600 dark:text-brand-400" onClick={() => setF({ q: f.q, minScore: '', location: '', maxNotice: '', college: '', status: '', flagged: false, closed: f.closed })}>Clear filters</button></div>
        </Card>
      )}
      {sel.size > 0 && canEdit && (
        <div className="sticky top-2 z-20 mb-3 flex flex-wrap items-center gap-2 rounded-xl bg-slate-900 px-3 py-2 text-sm text-white shadow-lg dark:bg-white dark:text-ink-900">
          <span className="font-semibold">{sel.size} selected</span>
          <Button size="sm" variant="ghost" className="text-inherit" icon={<CheckCheck />} onClick={() => runBulk('pass')}>Pass round</Button>
          <Button size="sm" variant="ghost" className="text-inherit" icon={<Hand />} onClick={() => runBulk('hold')}>Hold</Button>
          <Button size="sm" variant="ghost" className="text-inherit" onClick={() => setBulk('move')}>Move to…</Button>
          <Button size="sm" variant="ghost" className="text-inherit" icon={<Trophy />} onClick={async () => await ask(`Select ${sel.size} candidate(s) for the job?`) && runBulk('select')}>Select</Button>
          <Button size="sm" variant="ghost" className="text-inherit" icon={<MessageSquare />} onClick={() => setBulk('message')}>Message</Button>
          <Button size="sm" variant="ghost" className="text-red-300 dark:text-red-600" onClick={() => setBulk('reject')}>Reject</Button>
          <button aria-label="Clear selection" className="ml-auto rounded p-1 hover:bg-white/10" onClick={() => setSel(new Set())}><X className="size-4" /></button>
        </div>
      )}
      {!data.items.length ? <Card><Empty icon={<Users />} title="No applicants yet">Share the public job link, register a campus drive, or shortlist people from Best matches.</Empty></Card>
        : view === 'board' ? (
          <div className="-mx-4 overflow-x-auto px-4 pb-3 sm:-mx-6 sm:px-6"><div className="flex min-w-max gap-3">
            {cols.map(col => (
              <section key={col.id} aria-label={col.title} onDragOver={e => { if (dragId) { e.preventDefault(); setOverCol(col.id) } }} onDragLeave={() => setOverCol(null)} onDrop={() => dropOn(col)}
                className={cn('flex w-72 shrink-0 flex-col rounded-2xl bg-slate-100/70 p-2 dark:bg-ink-850', overCol === col.id && 'ring-2 ring-brand-400')}>
                <header className="flex items-center gap-2 px-1.5 pb-2 pt-1">
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold" title={col.title}>{col.title}</span>
                  <span className="tabular rounded-full bg-white px-1.5 text-xs font-semibold text-slate-600 dark:bg-ink-800 dark:text-slate-300">{col.items.length}</span>
                  {canEdit && col.round && col.items.some(a => a.current?.status === 'pending') && <Button size="sm" variant="subtle" onClick={() => startWaiting(col)}>Start {col.items.filter(a => a.current?.status === 'pending').length}</Button>}
                  {data.permission === 'manage' && col.round?.pass_rule.mode === 'top_n' && col.items.some(a => a.round_status === 'submitted') && <Button size="sm" variant="subtle" icon={<Trophy />} onClick={() => topN(col.round!)}>Choose the best…</Button>}
                </header>
                <div className="flex max-h-[65vh] flex-col gap-2 overflow-y-auto">
                  {col.items.map(a => <CardItem key={a.id} a={a} checked={sel.has(a.id)} onCheck={canEdit ? () => toggle(a.id) : undefined} onOpen={() => openApp(a.id)} draggable={canEdit} onDrag={() => setDragId(a.id)} />)}
                  {!col.items.length && <p className="px-2 py-6 text-center text-xs text-slate-500 dark:text-slate-400">Nobody here</p>}
                </div>
              </section>))}
          </div></div>
        ) : (
          <Card className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-ink-800"><tr>
                {canEdit && <th className="w-10 px-4 py-2.5"><input type="checkbox" aria-label="Select all" checked={listItems.length > 0 && listItems.every(a => sel.has(a.id))} onChange={e => setSel(e.target.checked ? new Set(listItems.map(a => a.id)) : new Set())} /></th>}
                <th className="px-3 py-2.5">Candidate</th><th className="px-3 py-2.5">Round</th><th className="px-3 py-2.5">Score</th><th className="px-3 py-2.5">Location</th><th className="px-3 py-2.5">Notice</th><th className="px-3 py-2.5">College</th><th className="px-3 py-2.5">Applied</th></tr></thead>
              <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{listItems.map(a => (
                <tr key={a.id} className="hover:bg-slate-50 dark:hover:bg-ink-850">
                  {canEdit && <td className="px-4 py-2.5"><input type="checkbox" aria-label={`Select ${a.candidate.name}`} checked={sel.has(a.id)} onChange={() => toggle(a.id)} /></td>}
                  <td className="px-3 py-2.5"><button className="text-left font-semibold hover:underline" onClick={() => openApp(a.id)}>{a.candidate.name}</button>
                    <div className="flex items-center gap-1 text-xs text-slate-500">{a.candidate.headline}{a.flags.length > 0 && <Flag className="size-3 text-red-500" aria-label="Integrity flag" />}</div></td>
                  <td className="px-3 py-2.5"><div className="text-xs text-slate-500">{roundName(data.rounds, a)}</div><StatusBadge a={a} /></td>
                  <td className="px-3 py-2.5"><ScoreBar value={a.current?.score ?? a.match_score} /></td>
                  <td className="px-3 py-2.5">{a.candidate.location || '-'}</td><td className="tabular px-3 py-2.5">{a.candidate.notice_days != null ? `${a.candidate.notice_days}d` : '-'}</td>
                  <td className="px-3 py-2.5">{a.college || '-'}</td><td className="px-3 py-2.5 text-slate-500">{ago(a.created_at)}</td>
                </tr>))}</tbody>
            </table>
            {!listItems.length && <p className="p-8 text-center text-sm text-slate-500">Nobody matches these filters.</p>}
          </Card>
        )}
      {open && <AppDrawer id={open} onClose={() => openApp(null)} onChanged={reload} onMoving={(id, roundId) => optimistic(id, roundId ? { round_id: roundId } : {})} />}
      {topRound && <TopNDialog jobId={jobId} round={topRound} items={data.items.filter(a => a.round_id === topRound.id && !CLOSED.includes(a.stage) && !DONE.includes(a.stage))}
        next={data.rounds[data.rounds.findIndex(r => r.id === topRound.id) + 1]?.name} onClose={() => setTopRound(null)} onDone={() => { setTopRound(null); reload() }} />}
      {bulk === 'reject' && <ReasonModal title={`Reject ${sel.size} candidate(s)`} cta="Reject" onClose={() => setBulk(null)} onSubmit={(reason, notify) => runBulk('reject', { reason, notify })} />}
      {bulk === 'message' && <MessageModal n={sel.size} onClose={() => setBulk(null)} onSubmit={(subject, text) => runBulk('message', { subject, text })} />}
      {bulk === 'move' && (
        <Modal open onOpenChange={o => !o && setBulk(null)} title={`Move ${sel.size} candidate(s)`} description="They start the chosen round now (invitations go out).">
          <div className="mt-4 space-y-2">{data.rounds.slice(1).map(r => <Button key={r.id} className="w-full justify-start" onClick={() => runBulk('move', { round_id: r.id })}>{r.name}</Button>)}</div>
        </Modal>)}
    </>
  )
}

function roundName(rounds: Round[], a: PipeItem) {
  if (DONE.includes(a.stage)) return 'Selected'
  if (CLOSED.includes(a.stage)) return a.stage_label
  return rounds.find(r => r.id === a.round_id)?.name || (a.round_id ? 'Removed round' : 'Not in flow')
}

export function StatusBadge({ a }: { a: PipeItem }) {
  if (a.round_status === 'moving') return <Badge tone="brand" icon={<Spinner />}>Moving…</Badge>
  if (CLOSED.includes(a.stage) || DONE.includes(a.stage)) return <Badge tone={DONE.includes(a.stage) ? 'success' : 'danger'}>{a.stage_label}</Badge>
  if (!a.current) return <Badge>{a.stage_label}</Badge>
  return <Badge tone={STATUS_TONE[a.current.status] || 'neutral'}>{a.current.status_label}</Badge>
}

function CardItem({ a, checked, onCheck, onOpen, draggable, onDrag }: { a: PipeItem; checked: boolean; onCheck?: () => void; onOpen: () => void; draggable: boolean; onDrag: () => void }) {
  const c = a.candidate, sc = a.current?.score
  return (
    <article draggable={draggable} onDragStart={onDrag} className={cn('rounded-xl bg-white p-2.5 shadow-sm ring-1 ring-slate-200 dark:bg-ink-900 dark:ring-ink-700', checked && 'ring-2 ring-brand-400', draggable && 'cursor-grab')}>
      <div className="flex items-start gap-2">
        {onCheck && <input type="checkbox" className="mt-1" aria-label={`Select ${c.name}`} checked={checked} onChange={onCheck} />}
        <button className="min-w-0 flex-1 text-left" onClick={onOpen}>
          <div className="flex items-center gap-1.5"><Avatar name={c.name} size="sm" /><span className="truncate text-sm font-semibold">{c.name}</span></div>
          <div className="mt-0.5 truncate text-xs text-slate-500">{[c.location, c.notice_days != null ? `${c.notice_days}d notice` : '', a.college].filter(Boolean).join(' · ') || c.headline}</div>
        </button>
        {sc != null && <span className="tabular text-sm font-bold text-slate-700 dark:text-slate-200">{Math.round(sc)}</span>}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1">
        <StatusBadge a={a} />
        {a.current?.suggestion && ['submitted', 'on_hold'].includes(a.current.status) && <Badge tone="violet">Suggested: {({ pass: 'pass', fail: 'not progress', hold: 'hold' } as Record<string, string>)[a.current.suggestion] || a.current.suggestion}</Badge>}
        {a.flags.length > 0 && <Badge tone="danger" icon={<Flag />}>Flag</Badge>}
        {a.human_requested && <Badge tone="warning">Wants human</Badge>}
        {a.accommodation === 'requested' && <Badge tone="warning">Accommodation</Badge>}
      </div>
    </article>
  )
}

export function ReasonModal({ title, cta, onClose, onSubmit }: { title: string; cta: string; onClose: () => void; onSubmit: (reason: string, notify: boolean) => void }) {
  const [reason, setReason] = useState(''), [notify, setNotify] = useState(true)
  return (
    <Modal open onOpenChange={o => !o && onClose()} title={title} description="The reason is kept for your team. Candidates get a respectful closure message without it."
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="danger" onClick={() => onSubmit(reason, notify)}>{cta}</Button></>}>
      <div className="mt-4 space-y-3"><Field label="Reason" htmlFor="rm-r"><Textarea id="rm-r" className="min-h-0" rows={3} value={reason} onChange={e => setReason(e.target.value)} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={notify} onChange={e => setNotify(e.target.checked)} />Send the closure message</label></div>
    </Modal>
  )
}

function MessageModal({ n, onClose, onSubmit }: { n: number; onClose: () => void; onSubmit: (subject: string, text: string) => void }) {
  const [subject, setSubject] = useState('An update on your application'), [text, setText] = useState('')
  return (
    <Modal open onOpenChange={o => !o && onClose()} title={`Message ${n} candidate(s)`} description="Sent by email, and WhatsApp where it is set up. Each message includes their status link."
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" icon={<Send />} disabled={!text.trim()} onClick={() => onSubmit(subject, text)}>Send</Button></>}>
      <div className="mt-4 space-y-3"><Field label="Subject" htmlFor="mm-s"><Input id="mm-s" value={subject} onChange={e => setSubject(e.target.value)} /></Field>
        <Field label="Message" htmlFor="mm-t"><Textarea id="mm-t" rows={5} value={text} onChange={e => setText(e.target.value)} /></Field></div>
    </Modal>
  )
}

// "Pass the best N" as a real dialog: how many finished, who would pass (by score), and what happens to the rest.
function TopNDialog({ jobId, round, items, next, onClose, onDone }: { jobId: string; round: Round; items: PipeItem[]; next?: string; onClose: () => void; onDone: () => void }) {
  const done = items.filter(a => a.round_status === 'submitted').sort((x, y) => (y.current?.score ?? -1) - (x.current?.score ?? -1))
  const [n, setN] = useState(Math.min(done.length, Math.max(1, Number(round.pass_rule.value) || 10)))
  const [rest, setRest] = useState<'wait' | 'reject'>('wait')
  const [busy, setBusy] = useState(false)
  async function run() {
    setBusy(true)
    try { const x = await api(`/api/jobs/${jobId}/rounds/${round.id}/top-n`, { json: { n, reject_rest: rest === 'reject' } }); toast(`${x.passed} passed${x.failed ? `, ${x.failed} not progressed` : ''}`); onDone() }
    catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  return (
    <Modal open onOpenChange={o => !o && onClose()} title={`Pass the best in ${round.name}`}
      description={`${done.length} candidate${done.length === 1 ? ' has' : 's have'} finished this round. The highest scores move on${next ? ` to ${next}` : ''}.`}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!done.length} onClick={run} icon={<Trophy />}>Pass {Math.min(n, done.length)}</Button></>}>
      <div className="mt-4 space-y-4">
        <Field label="How many pass" htmlFor="topn-n"><Stepper id="topn-n" aria-label="How many pass" min={1} max={Math.max(1, done.length)} step={1} unit={n === 1 ? 'candidate' : 'candidates'} value={n} onChange={setN}
          presets={[5, 10, 25, 50].filter(x => x < done.length)} /></Field>
        <div className="max-h-48 overflow-y-auto rounded-xl ring-1 ring-slate-200 dark:ring-ink-700">
          <ol className="divide-y divide-slate-100 text-sm dark:divide-ink-800">{done.map((a, i) => (
            <li key={a.id} className={cn('flex items-center gap-3 px-3 py-2', i < n ? 'bg-emerald-50/70 dark:bg-emerald-500/10' : 'text-slate-400 dark:text-slate-500')}>
              <span className="tabular w-5 text-xs font-semibold">{i + 1}</span><span className="min-w-0 flex-1 truncate">{a.candidate.name}</span>
              <span className="tabular font-semibold">{a.current?.score != null ? Math.round(a.current.score) : '-'}</span>
              {i < n ? <Check className="size-4 text-emerald-600" /> : <span className="w-4" />}</li>))}</ol>
        </div>
        <fieldset className="space-y-1.5 text-sm"><legend className="mb-1 text-[13px] font-semibold">Everyone else who finished</legend>
          <label className="flex items-center gap-2"><input type="radio" name="topn-rest" checked={rest === 'wait'} onChange={() => setRest('wait')} />Keep them waiting in this round</label>
          <label className="flex items-center gap-2"><input type="radio" name="topn-rest" checked={rest === 'reject'} onChange={() => setRest('reject')} />Mark them as not progressed (they get a polite closure message)</label>
        </fieldset>
      </div>
    </Modal>
  )
}
