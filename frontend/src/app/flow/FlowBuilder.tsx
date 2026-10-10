// The job's hiring flow: a block palette, drag-and-drop ordering and the settings of each round.
import { ArrowDown, ArrowUp, BookUser, CalendarPlus, ClipboardList, FileCheck2, FileUp, GripVertical, LayoutTemplate, ListChecks, Mic, MonitorPlay, Plus, Save, ShieldCheck, Trash2, UserCheck, Users, Video, Bot, FileText } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Field, Input, Modal, Select, Switch, Textarea, cn, toast } from '../../components/ui'
import { ErrorBox, Loading, useApi } from '../../components/kit'
import { api } from '../../lib/api'
import { setLeaveGuard } from '../../lib/router'
import { when } from '../../lib/format'
import { LANGUAGES, PASS_LABEL, SHORT_LABEL, newRound, type FlowMeta, type Round, type RoundType, type TeamMember } from './types'
import { DatePicker, MINUTE_PRESETS, Stepper, TimePicker } from '../../components/pickers'
import { LanguageChoice } from '../../components/LanguageChoice'
import { ask } from '../../components/dialogs'

export const ROUND_ICON: Record<RoundType, typeof Bot> = {
  application: ClipboardList, cv_screening: FileCheck2, test: ListChecks, video_intro: Video, role_task: Mic, practical_task: FileUp, live_task: MonitorPlay, reference_check: BookUser,
  ai_interview: Bot, human_interview: Users, manager_approval: UserCheck,
}

export default function FlowBuilder({ jobId, canEdit, canManage = false }: { jobId: string; canEdit: boolean; canManage?: boolean }) {
  const { data: meta, error: e1 } = useApi<FlowMeta>('/api/flow-meta')
  const { data, error, reload } = useApi<{ rounds: Round[]; counts: Record<string, number>; team: TeamMember[] }>(`/api/jobs/${jobId}/flow`)
  const [rounds, setRounds] = useState<Round[] | null>(null)
  const [sel, setSel] = useState<string>('')
  const [dirty, setDirty] = useState(false), [busy, setBusy] = useState(false)
  const [drag, setDrag] = useState<{ from?: number; type?: RoundType } | null>(null), [over, setOver] = useState<number | null>(null)
  const [tplOpen, setTplOpen] = useState(false)
  useEffect(() => { if (data && !dirty) { setRounds(data.rounds); setSel(s => s || data.rounds[1]?.id || data.rounds[0]?.id || '') } }, [data])   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault() }
    window.addEventListener('beforeunload', warn)
    setLeaveGuard(async () => await ask('You have unsaved changes to the hiring flow. Leave without saving them?'))
    return () => { window.removeEventListener('beforeunload', warn); setLeaveGuard(null) }
  }, [dirty])
  if (error || e1) return <ErrorBox error={error || e1} retry={reload} />
  if (!data || !meta || !rounds) return <Loading />
  const change = (next: Round[]) => { setRounds(next); setDirty(true) }
  const update = (id: string, patch: Partial<Round>) => change(rounds.map(r => r.id === id ? { ...r, ...patch } : r))
  const add = (type: RoundType, at?: number) => {
    const r = newRound(meta, type), i = at == null ? rounds.length : Math.max(1, at)
    change([...rounds.slice(0, i), r, ...rounds.slice(i)]); setSel(r.id)
  }
  const move = (from: number, to: number) => {
    if (from === 0 || to < 1 || to > rounds.length - 1 || from === to) return
    const next = [...rounds]; const [r] = next.splice(from, 1); next.splice(to, 0, r!); change(next)
  }
  const remove = async (id: string) => {
    const n = data.counts[id] || 0
    if (n && !await ask(`${n} candidate(s) are in this round. They will continue to the round that follows it. Remove it?`)) return
    change(rounds.filter(r => r.id !== id)); if (sel === id) setSel(rounds[0]!.id)
  }
  function drop(at: number) {
    if (!drag) return
    if (drag.type) add(drag.type, at)
    else if (drag.from != null) move(drag.from, at > drag.from ? at - 1 : at)
    setDrag(null); setOver(null)
  }
  async function save() {
    setBusy(true)
    try {
      const r = await api<{ rounds_list: Round[]; removed: number; placed: number }>(`/api/jobs/${jobId}/flow`, { method: 'PUT', json: { rounds } })
      setRounds(r.rounds_list); setDirty(false); reload()
      toast(r.placed ? `Flow saved. ${r.placed} candidate(s) from removed rounds are now in the new rounds, waiting to be started (Applicants tab).` : 'Flow saved')
    } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  const cur = rounds.find(r => r.id === sel)
  const saved = (id: string) => data.rounds.some(r => r.id === id)
  return (
    <div className="grid gap-5 xl:grid-cols-[220px_minmax(0,1fr)_minmax(0,420px)]">
      {canEdit && (
        <Card className="h-fit xl:sticky xl:top-4">
          <CardHeader title="Add a round" description="Drag into the flow, or click." />
          <CardBody className="space-y-1.5">
            {meta.round_types.filter(t => t.type !== 'application').map(t => {
              const Icon = ROUND_ICON[t.type]
              return (
                <button key={t.type} draggable onDragStart={() => setDrag({ type: t.type })} onDragEnd={() => { setDrag(null); setOver(null) }} onClick={() => add(t.type)} title={t.description}
                  className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm ring-1 ring-slate-200 hover:bg-slate-50 hover:ring-brand-300 dark:ring-ink-700 dark:hover:bg-ink-850">
                  <Icon className="size-4 shrink-0 text-brand-500" /><span className="min-w-0 flex-1 truncate font-medium">{SHORT_LABEL[t.type]}</span><Plus className="size-3.5 text-slate-500 dark:text-slate-400" />
                </button>)
            })}
          </CardBody>
        </Card>
      )}
      <div className={cn('space-y-0', !canEdit && 'xl:col-span-2')}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="mr-auto text-[15px] font-semibold">Hiring flow <span className="font-normal text-slate-500">· {rounds.length} rounds</span></h2>
          {canEdit && <Button size="sm" icon={<LayoutTemplate />} onClick={() => setTplOpen(true)}>Templates</Button>}
          {canEdit && <Button size="sm" variant="primary" icon={<Save />} loading={busy} disabled={!dirty} onClick={save}>{dirty ? 'Save flow' : 'Saved'}</Button>}
        </div>
        {dirty && <Alert className="mb-3" tone="info">Unsaved changes. Candidates already past a point are not affected; anyone in a removed round continues to the next one.</Alert>}
        <ol aria-label="Rounds">
          {rounds.map((r, i) => {
            const Icon = ROUND_ICON[r.type]
            return (
              <li key={r.id}>
                {i > 0 && <DropZone active={!!drag && over === i} onOver={() => setOver(i)} onDrop={() => drop(i)} visible={!!drag} />}
                <div draggable={canEdit && i > 0} onDragStart={() => setDrag({ from: i })} onDragEnd={() => { setDrag(null); setOver(null) }}
                  onClick={() => setSel(r.id)} role="button" tabIndex={0} onKeyDown={e => e.key === 'Enter' && setSel(r.id)} aria-pressed={sel === r.id}
                  className={cn('group flex items-center gap-3 rounded-2xl border bg-white p-3 text-left dark:bg-ink-900', sel === r.id ? 'border-brand-400 ring-2 ring-brand-100 dark:ring-brand-500/20' : 'border-slate-200 dark:border-ink-700')}>
                  {canEdit && i > 0 ? <GripVertical className="size-4 shrink-0 cursor-grab text-slate-300" /> : <span className="w-4" />}
                  <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300"><Icon className="size-[18px]" /></span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5"><span className="tabular text-xs text-slate-500 dark:text-slate-400">{i + 1}.</span><span className="truncate font-semibold">{r.name}</span>
                      {!saved(r.id) && <Badge tone="brand">New</Badge>}</span>
                    <span className="block truncate text-xs text-slate-500 dark:text-slate-400">{SHORT_LABEL[r.type]} · {ruleText(r)}{r.deadline_days ? ` · ${r.deadline_days}d deadline` : ''}</span>
                  </span>
                  {(data.counts[r.id] || 0) > 0 && <Badge tone="violet">{data.counts[r.id]} here</Badge>}
                  {canEdit && i > 0 && <span className="flex opacity-60 group-hover:opacity-100">
                    <button aria-label="Move up" disabled={i < 2} onClick={e => { e.stopPropagation(); move(i, i - 1) }} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-ink-800"><ArrowUp className="size-4" /></button>
                    <button aria-label="Move down" disabled={i === rounds.length - 1} onClick={e => { e.stopPropagation(); move(i, i + 1) }} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-ink-800"><ArrowDown className="size-4" /></button>
                    <button aria-label="Remove round" onClick={e => { e.stopPropagation(); remove(r.id) }} className="rounded p-1 text-slate-500 dark:text-slate-400 hover:bg-slate-100 hover:text-red-600 dark:hover:bg-ink-800"><Trash2 className="size-4" /></button>
                  </span>}
                </div>
              </li>)
          })}
          <li><DropZone active={!!drag && over === rounds.length} onOver={() => setOver(rounds.length)} onDrop={() => drop(rounds.length)} visible={!!drag} last /></li>
        </ol>
        <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-500"><ShieldCheck className="size-3.5" />Integrity flags never reject anyone on their own: a flagged result always waits for HR.</p>
      </div>
      {cur && <RoundEditor key={cur.id} r={cur} meta={meta} team={data.team} jobId={jobId} canEdit={canEdit} saved={saved(cur.id) && !dirty}
        onChange={patch => update(cur.id, patch)} />}
      {tplOpen && <Templates canManage={canManage} meta={meta} jobId={jobId} rounds={rounds} dirty={dirty} onClose={() => setTplOpen(false)} onApplied={() => { setDirty(false); setRounds(null); reload() }} />}
    </div>
  )
}

function DropZone({ active, visible, onOver, onDrop, last }: { active: boolean; visible: boolean; onOver: () => void; onDrop: () => void; last?: boolean }) {
  return (
    <div onDragOver={e => { e.preventDefault(); onOver() }} onDrop={e => { e.preventDefault(); onDrop() }}
      className={cn('mx-6 rounded-lg transition-all', visible ? 'my-1 h-8 border-2 border-dashed' : last ? 'h-2' : 'h-2', active ? 'border-brand-400 bg-brand-50 dark:bg-brand-500/10' : 'border-transparent',
        !visible && !last && 'border-l-2 border-slate-200 dark:border-ink-700 ml-[3.1rem] h-3 rounded-none border-dashed')} />
  )
}

function ruleText(r: Round): string {
  const m = r.pass_rule.mode
  const rule = m === 'min_score' ? `pass at ${r.pass_rule.value}+` : m === 'top_n' ? `top ${r.pass_rule.value}` : m === 'auto_pass' ? 'everyone passes' : 'HR reviews'
  return `${rule}, ${r.advance === 'auto' ? 'moves on automatically' : 'HR moves on'}`
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <div className="space-y-3 border-t border-slate-100 pt-4 dark:border-ink-800"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>{children}</div>
}

function RoundEditor({ r, meta, team, jobId, canEdit, saved, onChange }: { r: Round; meta: FlowMeta; team: TeamMember[]; jobId: string; canEdit: boolean; saved: boolean; onChange: (p: Partial<Round>) => void }) {
  const c = r.config
  const cfg = (k: string, v: unknown) => onChange({ config: { ...c, [k]: v } })
  const num = (v: string) => v === '' ? 0 : +v
  const isApp = r.type === 'application', scored = !['application', 'manager_approval', 'human_interview'].includes(r.type)
  return (
    <Card className="h-fit xl:sticky xl:top-4">
      <CardHeader title={r.name} description={meta.round_types.find(t => t.type === r.type)?.description} />
      <CardBody>
        <fieldset disabled={!canEdit} className="space-y-4">
          {isApp ? <p className="text-sm text-slate-600 dark:text-slate-300">The application form is always the first round. Its knockout questions are set in the job description, and the mandatory fields in Settings.</p> : <>
            <Field label="Round name" htmlFor="r-name"><Input id="r-name" value={r.name} onChange={e => onChange({ name: e.target.value })} /></Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Pass rule" htmlFor="r-mode"><Select id="r-mode" value={r.pass_rule.mode} onChange={e => onChange({ pass_rule: { ...r.pass_rule, mode: e.target.value as Round['pass_rule']['mode'] } })}>
                {meta.pass_modes.filter(m => scored || ['hr_review', 'auto_pass'].includes(m)).map(m => <option key={m} value={m}>{PASS_LABEL[m]}</option>)}</Select></Field>
              {['min_score', 'top_n'].includes(r.pass_rule.mode) && <Field label={r.pass_rule.mode === 'top_n' ? 'How many pass (N)' : 'Pass mark (0-100)'} htmlFor="r-val">
                <Input id="r-val" type="number" min={0} max={r.pass_rule.mode === 'top_n' ? 10000 : 100} value={r.pass_rule.value} onChange={e => onChange({ pass_rule: { ...r.pass_rule, value: num(e.target.value) } })} /></Field>}
              <Field label="After the result" htmlFor="r-adv" hint={r.advance === 'auto' ? 'Passing candidates move on; below the mark they get a respectful closure message.' : 'Results wait for an HR decision.'}>
                <Select id="r-adv" value={r.advance} onChange={e => onChange({ advance: e.target.value as Round['advance'] })}><option value="auto">Automatic</option><option value="hr">Wait for HR</option></Select></Field>
              {meta.round_types.find(t => t.type === r.type)?.candidate && <Field label="Deadline (days)" htmlFor="r-dl" hint="Empty for no deadline. Reminders go out before it.">
                <Input id="r-dl" type="number" min={1} max={60} value={r.deadline_days ?? ''} onChange={e => onChange({ deadline_days: e.target.value ? +e.target.value : null })} /></Field>}
            </div>
            {r.pass_rule.mode === 'top_n' && <p className="text-xs text-slate-500">Top N is applied by HR from the pipeline once enough candidates have finished ("Pass top N").</p>}
            <Field label="Message to candidates" htmlFor="r-msg" hint="Added to the invitation for this round."><Textarea id="r-msg" className="min-h-0" rows={2} value={r.message} onChange={e => onChange({ message: e.target.value })} /></Field>
          </>}
          {r.type === 'cv_screening' && <Section title="Screening"><Switch id="r-air" checked={c.use_ai_report !== false} onChange={v => cfg('use_ai_report', v)} label="Write an AI report" description="A written fit report per candidate, on top of the instant score (uses AI credits)." /></Section>}
          {r.type === 'test' && <TestConfig c={c} cfg={cfg} meta={meta} />}
          {(r.type === 'video_intro' || r.type === 'role_task') && <Section title="Recording">
            {r.type === 'role_task' && <Field label="Brief the candidate reads first" htmlFor="r-brief" hint="For example the product, the customer and what to pitch."><Textarea id="r-brief" rows={4} value={c.brief || ''} onChange={e => cfg('brief', e.target.value)} /></Field>}
            <Field label="Prompt" htmlFor="r-prompt"><Textarea id="r-prompt" className="min-h-0" rows={3} value={c.prompt || ''} onChange={e => cfg('prompt', e.target.value)} /></Field>
            <div className="grid grid-cols-3 gap-3">
              <Field label="Max seconds" htmlFor="r-max"><Input id="r-max" type="number" min={30} max={600} value={c.max_seconds ?? 120} onChange={e => cfg('max_seconds', num(e.target.value))} /></Field>
              <Field label="Prepare (s)" htmlFor="r-prep"><Input id="r-prep" type="number" min={0} max={600} value={c.prepare_seconds ?? 30} onChange={e => cfg('prepare_seconds', num(e.target.value))} /></Field>
              <Field label="Retakes" htmlFor="r-ret"><Input id="r-ret" type="number" min={0} max={5} value={c.retakes ?? 1} onChange={e => cfg('retakes', num(e.target.value))} /></Field>
            </div>
          </Section>}
          {r.type === 'practical_task' && <PracticalConfig c={c} cfg={cfg} jobId={jobId} roundId={r.id} saved={saved} />}
          {r.type === 'live_task' && <LiveConfig c={c} cfg={cfg} />}
          {r.type === 'reference_check' && <Section title="Referees">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="At least" htmlFor="rc-min"><Stepper id="rc-min" aria-label="Minimum referees" min={1} max={5} step={1} unit="referees" value={c.min_referees ?? 2} onChange={v => { cfg('min_referees', v); if ((c.max_referees ?? 3) < v) cfg('max_referees', v) }} /></Field>
              <Field label="At most" htmlFor="rc-max"><Stepper id="rc-max" aria-label="Maximum referees" min={c.min_referees ?? 2} max={5} step={1} unit="referees" value={c.max_referees ?? 3} onChange={v => cfg('max_referees', v)} /></Field>
            </div>
            <Switch id="rc-mgr" checked={!!c.require_manager} onChange={v => cfg('require_manager', v)} label="Require a former manager" description="At least one referee must have managed the candidate." />
            <p className="text-xs text-slate-500 dark:text-slate-400">Each referee rates quality of work, reliability, communication and teamwork (1 to 5) and answers four short questions. The score is the average rating; AI writes the summary and we flag look-alike references (same network as the candidate, forms filled in seconds).</p>
          </Section>}
          {r.type === 'ai_interview' && <Section title="AI interview">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Default language" htmlFor="r-lang"><Select id="r-lang" value={c.language || 'en'} onChange={e => cfg('language', e.target.value)}>{LANGUAGES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
              <Field label="Channel" htmlFor="r-ch"><Select id="r-ch" value={c.channel || 'web'} onChange={e => cfg('channel', e.target.value)}><option value="web">Browser (video)</option><option value="phone">Phone call</option><option value="both">Candidate chooses</option></Select></Field>
              <Field label="Length (minutes)" htmlFor="r-dur"><Stepper id="r-dur" aria-label="Length" max={60} value={c.duration_min ?? 15} onChange={v => cfg('duration_min', v)} /></Field>
              <Field label="Warnings before it ends" htmlFor="r-warn"><Input id="r-warn" type="number" min={0} max={10} value={c.max_warnings ?? 2} onChange={e => cfg('max_warnings', num(e.target.value))} /></Field>
            </div>
            <Field label="Languages the candidate can choose"><LanguageChoice value={c.languages} onChange={x => cfg('languages', x)} /></Field>
            <Switch id="r-sched" checked={c.allow_scheduling !== false} onChange={v => cfg('allow_scheduling', v)} label="Candidates can book a time"
              description="Besides starting right away, they can pick a 30-minute start time; we send a confirmation, a calendar invite and reminders, and they can change or cancel it." />
            {c.allow_scheduling !== false && <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Earliest start" htmlFor="r-from"><Stepper id="r-from" aria-label="Earliest hour" min={0} max={23} step={1} unit=":00" value={c.day_from ?? 8} onChange={v => cfg('day_from', v)} /></Field>
              <Field label="Latest end" htmlFor="r-to"><Stepper id="r-to" aria-label="Latest hour" min={1} max={24} step={1} unit=":00" value={c.day_to ?? 22} onChange={v => cfg('day_to', v)} /></Field>
              <Field label="Changes allowed" htmlFor="r-chg"><Stepper id="r-chg" aria-label="Changes allowed" min={0} max={10} step={1} unit="changes" value={c.reschedules_allowed ?? 5} onChange={v => cfg('reschedules_allowed', v)} /></Field>
            </div>}
            <Switch id="r-rp" checked={!!c.role_play} onChange={v => cfg('role_play', v)} label="Role-play" description="The AI plays a customer or stakeholder for part of the interview." />
            {c.role_play && <Field label="Role-play brief" htmlFor="r-rpb"><Textarea id="r-rpb" rows={3} value={c.role_play_brief || ''} onChange={e => cfg('role_play_brief', e.target.value)} placeholder="You are a busy clinic owner who thinks the software is too expensive…" /></Field>}
          </Section>}
          {r.type === 'human_interview' && <HumanConfig c={c} cfg={cfg} team={team} jobId={jobId} roundId={r.id} saved={saved} />}
          {r.type === 'manager_approval' && <Section title="Approvers">
            <p className="text-xs text-slate-500">They get a one-page summary and Select / Reject / Hold buttons by email, no login. Empty: the job's hiring managers, else its creator.</p>
            <PeoplePicker team={team} value={c.approvers || []} onChange={v => cfg('approvers', v)} allowEmail />
          </Section>}
        </fieldset>
      </CardBody>
    </Card>
  )
}

function TestConfig({ c, cfg, meta }: { c: Record<string, any>; cfg: (k: string, v: unknown) => void; meta: FlowMeta }) {
  const secs: any[] = c.sections || []
  const setSec = (i: number, k: string, v: unknown) => cfg('sections', secs.map((s, j) => j === i ? { ...s, [k]: v } : s))
  const total = secs.reduce((a, s) => a + (+s.minutes || 0), 0)
  return (
    <Section title={`Test sections · ${total} min`}>
      {secs.map((s, i) => (
        <div key={i} className="space-y-2 rounded-xl bg-slate-50 p-3 dark:bg-ink-850">
          <div className="flex gap-2"><Select aria-label="Section" className="min-w-0 flex-1" value={s.section} onChange={e => setSec(i, 'section', e.target.value)}>{meta.sections.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}</Select>
            <Select aria-label="Level" className="!w-28" value={s.difficulty || 'mixed'} onChange={e => setSec(i, 'difficulty', e.target.value)}>{['mixed', 'easy', 'medium', 'hard'].map(x => <option key={x}>{x}</option>)}</Select>
            <Button size="sm" variant="ghost" aria-label="Remove section" icon={<Trash2 />} onClick={() => cfg('sections', secs.filter((_, j) => j !== i))} /></div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <label>Questions<Input type="number" min={1} max={100} value={s.count} onChange={e => setSec(i, 'count', +e.target.value)} /></label>
            <label>Minutes<Input type="number" min={1} max={180} value={s.minutes} onChange={e => setSec(i, 'minutes', +e.target.value)} /></label>
            <label>Cutoff %<Input type="number" min={0} max={100} value={s.cutoff ?? 0} onChange={e => setSec(i, 'cutoff', +e.target.value)} /></label>
          </div>
        </div>))}
      <Button size="sm" icon={<Plus />} onClick={() => cfg('sections', [...secs, { section: 'domain', count: 10, difficulty: 'mixed', minutes: 10, cutoff: 0 }])}>Add section</Button>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Overall pass %" htmlFor="t-oc"><Input id="t-oc" type="number" min={0} max={100} value={c.overall_cutoff ?? 0} onChange={e => cfg('overall_cutoff', +e.target.value)} /></Field>
        <Field label="Negative mark" htmlFor="t-neg" hint="0.25 = a quarter mark"><Input id="t-neg" type="number" min={0} max={1} step={0.25} value={c.negative_marking ?? 0} onChange={e => cfg('negative_marking', +e.target.value)} /></Field>
        <Field label="Exits allowed" htmlFor="t-exit" hint="Then it submits"><Input id="t-exit" type="number" min={0} max={20} value={c.max_exits ?? 3} onChange={e => cfg('max_exits', +e.target.value)} /></Field>
      </div>
      <Switch id="t-cam" checked={c.require_camera !== false} onChange={v => cfg('require_camera', v)} label="Camera snapshots" description="A photo at the start and every few minutes, for HR review." />
      <Switch id="t-shuf" checked={c.shuffle_options !== false} onChange={v => cfg('shuffle_options', v)} label="Shuffle options" />
      <Switch id="t-show" checked={!!c.show_score} onChange={v => cfg('show_score', v)} label="Show candidates their score" />
      <p className="text-xs text-slate-500">Every candidate gets a different random paper from the <a className="font-medium text-brand-600 dark:text-brand-400 hover:underline" href="/app/questions">question bank</a>.</p>
    </Section>
  )
}

function PracticalConfig({ c, cfg, jobId, roundId, saved }: { c: Record<string, any>; cfg: (k: string, v: unknown) => void; jobId: string; roundId: string; saved: boolean }) {
  const [busy, setBusy] = useState(false), [uploaded, setUploaded] = useState('')
  const fileName = uploaded || c.attachment?.name
  async function upload(f: File) {
    setBusy(true)
    try { const fd = new FormData(); fd.append('file', f); const r = await api(`/api/jobs/${jobId}/rounds/${roundId}/attachment`, { body: fd }); setUploaded(r.name); toast('Task file uploaded') } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  return (
    <Section title="Task">
      <Field label="Instructions" htmlFor="p-ins"><Textarea id="p-ins" rows={4} value={c.instructions || ''} onChange={e => cfg('instructions', e.target.value)} /></Field>
      <Field label="Task file (optional)" hint={saved ? 'Candidates download it from their task page (max 15 MB).' : 'Save the flow first, then upload the file.'}>
        <div className="flex items-center gap-2">{fileName && <Badge icon={<FileText />}>{fileName}</Badge>}
          <label className={cn('inline-flex', !saved && 'pointer-events-none opacity-50')}><span className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg px-3 text-[13px] font-semibold ring-1 ring-slate-200 hover:bg-slate-50 dark:ring-ink-700">{busy ? 'Uploading…' : fileName ? 'Replace' : 'Upload'}</span>
            <input type="file" className="sr-only" onChange={e => { const f = e.target.files?.[0]; if (f) upload(f) }} /></label></div>
      </Field>
      <Field label="Accepted file types" htmlFor="p-ft"><Input id="p-ft" value={c.file_types || ''} onChange={e => cfg('file_types', e.target.value)} placeholder=".xlsx,.pdf" /></Field>
      <Rubric c={c} cfg={cfg} />
    </Section>
  )
}

function Rubric({ c, cfg }: { c: Record<string, any>; cfg: (k: string, v: unknown) => void }) {
  const rub: { criterion: string; weight: number }[] = c.rubric || []
  return <>
    <div className="text-sm font-semibold">Rubric</div>
    {rub.map((x, i) => (
      <div key={i} className="flex gap-2"><Input aria-label="Criterion" className="flex-1" value={x.criterion} onChange={e => cfg('rubric', rub.map((y, j) => j === i ? { ...y, criterion: e.target.value } : y))} />
        <Input aria-label="Weight" type="number" className="w-20" min={1} max={100} value={x.weight} onChange={e => cfg('rubric', rub.map((y, j) => j === i ? { ...y, weight: +e.target.value } : y))} />
        <Button variant="ghost" aria-label="Remove criterion" icon={<Trash2 />} onClick={() => cfg('rubric', rub.filter((_, j) => j !== i))} /></div>))}
    <Button size="sm" icon={<Plus />} onClick={() => cfg('rubric', [...rub, { criterion: '', weight: 25 }])}>Add criterion</Button>
  </>
}

function LiveConfig({ c, cfg }: { c: Record<string, any>; cfg: (k: string, v: unknown) => void }) {
  return (
    <Section title="Live task">
      <Alert tone="info">The candidate shares their entire screen and works in any tool (code editor, Figma, Excel). We keep a screenshot every {c.snapshot_every_sec || 30} seconds; AI reviews the result and how they got there against your rubric.</Alert>
      <Field label="Task" htmlFor="l-ins" hint="Exactly what to build or solve. Include inputs, constraints and what 'done' looks like."><Textarea id="l-ins" rows={5} value={c.instructions || ''} onChange={e => cfg('instructions', e.target.value)}
        placeholder="Write a function that groups a list of orders by customer and returns the top 3 customers by spend. Handle empty input." /></Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Time" htmlFor="l-min"><Stepper id="l-min" aria-label="Time" max={180} value={c.minutes ?? 30} onChange={v => cfg('minutes', v)} presets={MINUTE_PRESETS} /></Field>
        <Field label="What they hand in" htmlFor="l-del"><Select id="l-del" value={c.deliverable || 'code'} onChange={e => cfg('deliverable', e.target.value)}>
          <option value="code">Code (typed or pasted on the page)</option><option value="text">Written answer</option><option value="file">A file (design, sheet, zip)</option><option value="none">Nothing: judge from the screen only</option></Select></Field>
        {c.deliverable !== 'file' && c.deliverable !== 'none' && <Field label={c.deliverable === 'text' ? 'Format hint' : 'Language'} htmlFor="l-lang"><Input id="l-lang" value={c.language || ''} onChange={e => cfg('language', e.target.value)} placeholder={c.deliverable === 'text' ? 'Bullet points' : 'Python'} /></Field>}
        <Field label="Screenshot every" htmlFor="l-snap"><Stepper id="l-snap" aria-label="Screenshot interval" min={15} max={120} step={15} unit="s" value={c.snapshot_every_sec ?? 30} onChange={v => cfg('snapshot_every_sec', v)} /></Field>
      </div>
      <Rubric c={c} cfg={cfg} />
    </Section>
  )
}

function PeoplePicker({ team, value, onChange, allowEmail }: { team: TeamMember[]; value: string[]; onChange: (v: string[]) => void; allowEmail?: boolean }) {
  const [email, setEmail] = useState('')
  const name = (id: string) => { const m = team.find(t => t.id === id); return m ? (m.name || m.email) : id }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">{value.map(v => <Badge key={v} tone="violet">{name(v)}<button aria-label={`Remove ${name(v)}`} onClick={() => onChange(value.filter(x => x !== v))} className="ml-0.5">×</button></Badge>)}</div>
      <Select aria-label="Add a team member" value="" onChange={e => e.target.value && onChange([...value, e.target.value])}><option value="">Add a team member…</option>
        {team.filter(t => !value.includes(t.id)).map(t => <option key={t.id} value={t.id}>{t.name || t.email}{t.title ? ` (${t.title})` : ''}</option>)}</Select>
      {allowEmail && <div className="flex gap-2"><Input aria-label="Approver email" type="email" placeholder="or an email (no login needed)" value={email} onChange={e => setEmail(e.target.value)} />
        <Button disabled={!/^\S+@\S+\.\S+$/.test(email)} onClick={() => { onChange([...value, email.trim().toLowerCase()]); setEmail('') }}>Add</Button></div>}
    </div>
  )
}

function HumanConfig({ c, cfg, team, jobId, roundId, saved }: { c: Record<string, any>; cfg: (k: string, v: unknown) => void; team: TeamMember[]; jobId: string; roundId: string; saved: boolean }) {
  return (
    <Section title="Interview">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Length (minutes)" htmlFor="h-dur"><Stepper id="h-dur" aria-label="Length" value={c.duration_min ?? 45} onChange={v => cfg('duration_min', v)} presets={MINUTE_PRESETS} /></Field>
        <Field label="Mode" htmlFor="h-mode"><Select id="h-mode" value={c.mode || 'video'} onChange={e => cfg('mode', e.target.value)}><option value="video">Video call</option><option value="in_person">In person</option><option value="phone">Phone</option></Select></Field>
        <Field label="Changes the candidate can make" htmlFor="h-res" hint="Reschedules or cancellations from their link."><Stepper id="h-res" aria-label="Changes allowed" min={0} max={10} step={1} unit="changes" value={c.reschedules_allowed ?? 3} onChange={v => cfg('reschedules_allowed', v)} /></Field>
        <Field label="Changes allowed until" htmlFor="h-cut" hint="Hours before the interview. After that they contact you."><Stepper id="h-cut" aria-label="Change cutoff" min={0} max={48} step={1} unit="hours before" value={c.change_cutoff_hours ?? 2} onChange={v => cfg('change_cutoff_hours', v)} /></Field>
      </div>
      {c.mode !== 'in_person' ? <Field label="Meeting link" htmlFor="h-url" hint="Used for every slot unless a slot has its own."><Input id="h-url" value={c.meeting_url || ''} onChange={e => cfg('meeting_url', e.target.value)} placeholder="https://meet.google.com/…" /></Field>
        : <Field label="Address" htmlFor="h-loc"><Input id="h-loc" value={c.location || ''} onChange={e => cfg('location', e.target.value)} /></Field>}
      <Field label="Interviewers"><PeoplePicker team={team} value={c.interviewers || []} onChange={v => cfg('interviewers', v)} /></Field>
      {saved ? <Slots jobId={jobId} roundId={roundId} team={team} interviewers={c.interviewers || []} minutes={c.duration_min || 45} /> : <p className="text-xs text-slate-500">Save the flow to add interview slots.</p>}
    </Section>
  )
}

interface Slot { id: string; starts_at: number; ends_at: number; interviewer: string; booked: boolean; meeting_url: string; location: string; candidate?: { name: string; ref: string } | null; status?: string }
function Slots({ jobId, roundId, team, interviewers, minutes }: { jobId: string; roundId: string; team: TeamMember[]; interviewers: string[]; minutes: number }) {
  const { data, reload } = useApi<Slot[]>(`/api/jobs/${jobId}/rounds/${roundId}/slots`)
  const [open, setOpen] = useState(false)
  const today = new Date(Date.now() + 86400000).toISOString().slice(0, 10)
  const [f, setF] = useState({ date: today, from: '10:00', to: '13:00', minutes, gap: 15, days: 1, interviewer: interviewers[0] || '' })
  const [busy, setBusy] = useState(false)
  async function create() {
    setBusy(true)
    try {
      let made = 0, skipped = 0, told = 0
      for (let d = 0; d < Math.max(1, f.days); d++) {
        const base = new Date(`${f.date}T00:00`); base.setDate(base.getDate() + d)
        if (f.days > 1 && (base.getDay() === 0 || base.getDay() === 6)) continue
        const at = (hm: string) => { const [h, m] = hm.split(':').map(Number); const x = new Date(base); x.setHours(h!, m!, 0, 0); return x.getTime() / 1000 }
        const r = await api(`/api/jobs/${jobId}/rounds/${roundId}/slots`, { json: { series: { start: at(f.from), end: at(f.to), minutes: f.minutes, gap_minutes: f.gap }, interviewer_id: f.interviewer || undefined } })
        made += r.created; skipped += r.skipped_overlaps || 0; told += r.candidates_told || 0
      }
      toast(`${made} slot(s) added${skipped ? `, ${skipped} skipped (the interviewer already has a slot then)` : ''}${told ? `. ${told} waiting candidate(s) emailed` : ''}`); setOpen(false); reload()
    } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  async function del(id: string) { if (!await ask('Delete this free slot? Candidates can no longer book it.')) return; try { await api(`/api/slots/${id}`, { method: 'DELETE' }); reload() } catch (e: any) { toast(e.message) } }
  const free = (data || []).filter(s => !s.booked).length
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between"><span className="text-sm font-semibold">Slots <span className="font-normal text-slate-500">· {free} free of {data?.length ?? 0}</span></span>
        <Button size="sm" icon={<CalendarPlus />} onClick={() => setOpen(true)}>Add slots</Button></div>
      <ul className="max-h-56 space-y-1 overflow-y-auto text-sm">{(data || []).map(s => (
        <li key={s.id} className="flex items-center gap-2 rounded-lg bg-slate-50 px-2.5 py-1.5 dark:bg-ink-850">
          <span className="tabular flex-1">{when(s.starts_at)}{s.interviewer ? <span className="text-slate-500"> · {s.interviewer}</span> : null}</span>
          {s.booked ? <Badge tone="violet">{s.candidate?.name || 'Booked'}</Badge> : <button aria-label="Delete slot" onClick={() => del(s.id)} className="text-slate-500 dark:text-slate-400 hover:text-red-600"><Trash2 className="size-3.5" /></button>}
        </li>))}</ul>
      <Modal open={open} onOpenChange={setOpen} title="Add interview slots" description="Candidates pick one of these times themselves (at least an hour ahead)."
        footer={<><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" loading={busy} onClick={create}>Add slots</Button></>}>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <Field label="First day" htmlFor="sl-d"><DatePicker id="sl-d" min={today} value={f.date} onChange={v => setF({ ...f, date: v })} /></Field>
          <Field label="Working days" htmlFor="sl-n" hint="Skips weekends"><Input id="sl-n" type="number" min={1} max={14} value={f.days} onChange={e => setF({ ...f, days: +e.target.value })} /></Field>
          <Field label="From" htmlFor="sl-f"><TimePicker id="sl-f" value={f.from} onChange={v => setF({ ...f, from: v })} /></Field>
          <Field label="To" htmlFor="sl-t"><TimePicker id="sl-t" value={f.to} onChange={v => setF({ ...f, to: v })} /></Field>
          <Field className="col-span-2" label="Interview length" htmlFor="sl-m"><Stepper id="sl-m" aria-label="Interview length" value={f.minutes} onChange={v => setF({ ...f, minutes: v })} presets={MINUTE_PRESETS} /></Field>
          <Field className="col-span-2" label="Break between interviews" htmlFor="sl-g"><Stepper id="sl-g" aria-label="Break between interviews" min={0} max={60} value={f.gap} onChange={v => setF({ ...f, gap: v })} presets={[0, 5, 10, 15, 30]} /></Field>
          <Field className="col-span-2" label="Interviewer" htmlFor="sl-i"><Select id="sl-i" value={f.interviewer} onChange={e => setF({ ...f, interviewer: e.target.value })}><option value="">Me</option>
            {team.map(t => <option key={t.id} value={t.id}>{t.name || t.email}</option>)}</Select></Field>
        </div>
      </Modal>
    </div>
  )
}

function Templates({ canManage, meta, jobId, rounds, dirty, onClose, onApplied }: { canManage: boolean; meta: FlowMeta; jobId: string; rounds: Round[]; dirty: boolean; onClose: () => void; onApplied: () => void }) {
  const [name, setName] = useState(''), [desc, setDesc] = useState(''), [busy, setBusy] = useState('')
  const [list, setList] = useState(meta.templates)
  async function apply(id: string) {
    if (!await ask('Replace this job\'s flow with the template? Candidates already in a round continue from their position.')) return
    setBusy(id)
    try {
      const r = await api(`/api/jobs/${jobId}/flow/template`, { json: { template: id } })
      toast(r.placed ? `Template applied. ${r.placed} candidate(s) are in the new rounds, waiting to be started (Applicants tab).` : 'Template applied'); onApplied(); onClose()
    } catch (e: any) { toast(e.message) }
    setBusy('')
  }
  async function saveAs() {
    setBusy('save')
    try { const r = await api('/api/flow-templates', { json: { name, description: desc, rounds } }); setList(l => [...l, { id: r.id, name: r.name, description: desc, rounds: rounds.length, custom: true }]); setName(''); setDesc(''); toast('Saved as a template') } catch (e: any) { toast(e.message) }
    setBusy('')
  }
  async function del(id: string) {
    if (!await ask('Delete this template? Jobs that used it keep their flow.')) return
    try { await api(`/api/flow-templates/${id}`, { method: 'DELETE' }); setList(l => l.filter(t => t.id !== id)) } catch (e: any) { toast(e.message) }
  }
  return (
    <Modal open onOpenChange={o => !o && onClose()} title="Flow templates" description="Start from a ready flow, or save this one to reuse on other jobs.">
      <div className="mt-4 max-h-[55vh] space-y-2 overflow-y-auto pr-1">
        {dirty && <Alert tone="warning">Applying a template discards your unsaved changes.</Alert>}
        {list.map(t => (
          <div key={t.id} className="flex items-center gap-3 rounded-xl p-3 ring-1 ring-slate-200 dark:ring-ink-700">
            <div className="min-w-0 flex-1"><div className="flex items-center gap-2 font-semibold">{t.name}{t.custom && <Badge tone="violet">Yours</Badge>}</div><div className="text-xs text-slate-500">{t.description || `${t.rounds} rounds`}</div></div>
            {t.custom && canManage && <Button size="sm" variant="ghost" aria-label={`Delete ${t.name}`} icon={<Trash2 />} onClick={() => del(t.id)} />}
            <Button size="sm" aria-label={`Use ${t.name}`} loading={busy === t.id} onClick={() => apply(t.id)}>Use</Button>
          </div>))}
        {canManage && <div className="space-y-2 border-t border-slate-100 pt-3 dark:border-ink-800">
          <div className="text-sm font-semibold">Save the current flow as a template</div>
          <Input aria-label="Template name" placeholder="Template name" value={name} onChange={e => setName(e.target.value)} />
          <Input aria-label="Template description" placeholder="Description (optional)" value={desc} onChange={e => setDesc(e.target.value)} />
          <Button variant="primary" disabled={!name.trim()} loading={busy === 'save'} onClick={saveAs} icon={<Save />}>Save template</Button>
        </div>}
      </div>
    </Modal>
  )
}
