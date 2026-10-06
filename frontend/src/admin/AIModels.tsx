// Platform admin > AI models: which provider and models each job uses. Providers without a key on the server are
// shown but can't be picked. Saved choices apply at once, no restart. Keys stay in the server's environment.
import { CircleCheck, CircleX, FlaskConical, Plus, RotateCcw, Save, Sparkles, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Input, Select, Switch, cn, toast } from '../components/ui'
import { Loading, useApi } from '../components/kit'
import { api } from '../lib/api'
import { ask } from '../components/dialogs'

type Role = 'fast' | 'smart' | 'vision'
interface Provider { id: string; label: string; available: boolean; env: string; note: string; site: string }
interface State { providers: Provider[]; config: Record<Role, { provider: string; models: string[] }>; source: 'admin' | 'environment'; suggest: Record<string, Record<Role, string[]>>; note: string; mock: boolean; backup: { on: boolean; targets: { provider: string; model: string }[]; last: { provider: string; model: string; at: number; because: string } | null; blocked: Record<string, string> } }
interface Model { id: string; name: string; free: boolean; vision: boolean | null; context?: number }
const ROLES: { id: Role; title: string; help: string }[] = [
  { id: 'fast', title: 'Fast: live interviews and plans', help: 'Answers every turn of an AI interview, so speed matters most. Pick small, quick models.' },
  { id: 'smart', title: 'Smart: scoring, reports, resume reads', help: 'Scores interviews and writes reports. Quality matters more than speed.' },
  { id: 'vision', title: 'Vision: photo resumes and screenshots (optional)', help: 'Reads photo or scanned resumes and live-task screenshots. Must accept images. Leave empty to switch these off.' },
]

export default function AIModels() {
  const { data, error, reload } = useApi<State>('/api/platform/llm')
  const [cfg, setCfg] = useState<State['config'] | null>(null), [busy, setBusy] = useState(false)
  useEffect(() => { if (data) setCfg(JSON.parse(JSON.stringify(data.config))) }, [data])
  if (error) return <Alert tone="danger">{error}</Alert>
  if (!data || !cfg) return <Card><CardBody><Loading /></CardBody></Card>
  const dirty = JSON.stringify(cfg) !== JSON.stringify(data.config)
  async function save() {
    setBusy(true)
    try { await api('/api/platform/llm', { method: 'PUT', json: cfg }); toast('AI models saved. They apply now.'); reload() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  async function reset() {
    if (!await ask('Go back to the server settings? Your saved model choice is removed and the environment variables decide again.', { confirm: 'Reset' })) return
    try { await api('/api/platform/llm', { method: 'DELETE' }); toast('Using the server settings'); reload() } catch (e: any) { toast(e.message) }
  }
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Sparkles className="size-4 text-brand-600 dark:text-brand-400" />AI models</span>}
        description="Pick the provider and models for each job. First model = main, the rest are fallbacks in order. Applies at once, no restart."
        action={<Badge tone={data.source === 'admin' ? 'brand' : 'neutral'}>{data.source === 'admin' ? 'Set here' : 'From server settings'}</Badge>} />
      <CardBody className="space-y-5">
        {data.mock && <Alert tone="warning">LLM_MOCK is on: the app uses fake answers and ignores these settings.</Alert>}
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Providers</div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{data.providers.map(p => (
            <div key={p.id} className={cn('rounded-xl p-3 text-sm ring-1', p.available ? 'ring-emerald-200 dark:ring-emerald-500/30' : 'opacity-75 ring-slate-200 dark:ring-ink-700')}>
              <div className="flex items-center justify-between gap-2"><b>{p.label}</b>{p.available ? <Badge tone="success" icon={<CircleCheck />}>Ready</Badge> : <Badge icon={<CircleX />}>No key</Badge>}</div>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{p.note}</p>
              {!p.available && <p className="mt-1 text-xs">Add <code className="rounded bg-slate-100 px-1 dark:bg-ink-800">{p.env}</code> on Render{p.site ? <> (<a className="text-brand-600 hover:underline dark:text-brand-400" href={p.site} target="_blank" rel="noopener">get a key</a>)</> : ''}, then redeploy.</p>}
            </div>))}</div>
        </div>
        {data.note && <Alert tone="info">{data.note}</Alert>}
        {Object.entries(data.backup.blocked).map(([k, why]) => <Alert key={k} tone="warning" title={`${k} is refusing requests right now`}>{why}. The app stops asking it for a few minutes so it doesn't use up what is left.</Alert>)}
        <Alert tone={data.backup.on && data.backup.targets.length ? 'success' : 'info'} title="Backup provider">
          {data.backup.on && data.backup.targets.length
            ? <>If the main provider fails a one-off job (match reports, scoring, resume reads, JD writing), the app asks <b>{data.backup.targets.map(t => `${t.provider} (${t.model})`).join(' or ')}</b> instead. That uses the paid key on this server, one small request per job. Live interview turns never use it. Switch it off with <code>LLM_BACKUP=off</code> on Render.</>
            : data.backup.on ? <>No second provider has a key, so there is nothing to fall back to. Add <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code> or <code>GEMINI_API_KEY</code> (with a model chosen above) and failed reports are retried there automatically.</>
            : <>Backup is switched off (<code>LLM_BACKUP=off</code>).</>}
          {data.backup.last && <div className="mt-1 text-xs">Last used: {data.backup.last.provider} ({data.backup.last.model}) {new Date(data.backup.last.at * 1000).toLocaleString()}.</div>}
        </Alert>
        {ROLES.map(r => <RoleEditor key={r.id} role={r} providers={data.providers} suggest={data.suggest} value={cfg[r.id]}
          onChange={v => setCfg({ ...cfg, [r.id]: v })} saved={JSON.stringify(cfg[r.id]) === JSON.stringify(data.config[r.id])} />)}
        <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4 dark:border-ink-800">
          <Button variant="primary" icon={<Save />} loading={busy} disabled={!dirty} onClick={save}>Save</Button>
          {dirty && <Button onClick={() => setCfg(JSON.parse(JSON.stringify(data.config)))}>Discard changes</Button>}
          {data.source === 'admin' && <Button variant="ghost" icon={<RotateCcw />} onClick={reset}>Use server settings</Button>}
        </div>
      </CardBody>
    </Card>
  )
}

function RoleEditor({ role, providers, suggest, value, onChange, saved }: { role: typeof ROLES[number]; providers: Provider[]; suggest: State['suggest']; value: { provider: string; models: string[] }; onChange: (v: { provider: string; models: string[] }) => void; saved: boolean }) {
  const [models, setModels] = useState<Model[] | null>(null), [err, setErr] = useState(''), [freeOnly, setFreeOnly] = useState(true), [typed, setTyped] = useState('')
  const [test, setTest] = useState<any>(null), [testing, setTesting] = useState(false)
  const prov = providers.find(p => p.id === value.provider)
  useEffect(() => {
    setModels(null); setErr('')
    if (!prov?.available && value.provider !== 'openrouter') return
    api<{ models: Model[] }>(`/api/platform/llm/models?provider=${value.provider}`).then(r => setModels(r.models)).catch(e => setErr(e.message))
  }, [value.provider]) // eslint-disable-line react-hooks/exhaustive-deps
  const choices = useMemo(() => (models || []).filter(m => !value.models.includes(m.id) && (!freeOnly || value.provider !== 'openrouter' || m.free) && (role.id !== 'vision' || m.vision !== false)), [models, value, freeOnly, role.id])
  const add = (id: string) => id && !value.models.includes(id) && value.models.length < 4 && onChange({ ...value, models: [...value.models, id] })
  const move = (i: number, d: number) => { const m = [...value.models]; const j = i + d; if (j < 0 || j >= m.length) return; [m[i], m[j]] = [m[j]!, m[i]!]; onChange({ ...value, models: m }) }
  async function runTest() {
    setTesting(true); setTest(null)
    try { setTest(await api('/api/platform/llm/test', { json: { role: role.id } })) } catch (e: any) { setTest({ ok: false, error: e.message }) }
    setTesting(false)
  }
  const info = (id: string) => models?.find(m => m.id === id)
  return (
    <div className="rounded-xl p-4 ring-1 ring-slate-200 dark:ring-ink-700">
      <div className="flex flex-wrap items-start justify-between gap-2"><div><div className="font-semibold">{role.title}</div><p className="text-xs text-slate-500 dark:text-slate-400">{role.help}</p></div>
        <Button size="sm" icon={<FlaskConical />} loading={testing} disabled={!saved || (!value.models.length)} onClick={runTest} title={saved ? 'Send one tiny real request' : 'Save first'}>Test</Button></div>
      {test && <Alert className="mt-3" tone={test.ok ? 'success' : 'danger'}>{test.ok ? `Works: ${test.model} answered in ${test.seconds}s.` : `Failed${test.model ? ` (${test.model})` : ''}: ${test.error}`}</Alert>}
      <div className="mt-3 grid gap-3 sm:grid-cols-[220px_minmax(0,1fr)]">
        <Select aria-label={`${role.title} provider`} value={value.provider} onChange={e => onChange({ provider: e.target.value, models: e.target.value === value.provider ? value.models : (suggest[e.target.value]?.[role.id] || []) })}>
          {providers.map(p => <option key={p.id} value={p.id} disabled={!p.available}>{p.label}{p.available ? '' : ' (no key)'}</option>)}</Select>
        <div className="min-w-0 space-y-2">
          {value.models.length ? <ol className="space-y-1.5">{value.models.map((m, i) => { const mi = info(m); return (
            <li key={m} className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 px-2.5 py-1.5 text-sm dark:bg-ink-850">
              <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">{i === 0 ? 'Main' : `Fallback ${i}`}</span>
              <code className="min-w-0 flex-1 truncate text-xs">{m}</code>
              {mi?.free && <Badge tone="success">Free</Badge>}{mi?.vision && <Badge>Images</Badge>}{models && !mi && <Badge tone="warning">Not in the provider's list</Badge>}
              <button type="button" aria-label="Move up" className="rounded px-1 text-slate-500 hover:bg-slate-200 disabled:opacity-30 dark:hover:bg-ink-700" disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
              <button type="button" aria-label={`Remove ${m}`} className="rounded p-0.5 text-slate-500 hover:bg-slate-200 dark:hover:bg-ink-700" onClick={() => onChange({ ...value, models: value.models.filter(x => x !== m) })}><X className="size-3.5" /></button>
            </li>) })}</ol> : <p className="text-sm text-slate-500 dark:text-slate-400">{role.id === 'vision' ? 'Off: no vision model.' : 'No model picked yet.'}</p>}
          {value.models.length < 4 && <div className="space-y-2">
            {err ? <Alert tone="warning">{err}</Alert> : !models ? (prov?.available || value.provider === 'openrouter' ? <p className="text-xs text-slate-500">Loading the provider's models…</p> : null) : (
              <div className="flex flex-wrap items-center gap-3">
                <Select searchable aria-label="Add a model" className="min-w-0 flex-1" value="" onChange={e => add(e.target.value)}>
                  <option value="">{`Add a model (${choices.length} available)`}</option>
                  {choices.slice(0, 400).map(m => <option key={m.id} value={m.id}>{m.id}{m.free ? '  · free' : ''}{m.vision ? '  · images' : ''}</option>)}</Select>
                {value.provider === 'openrouter' && <Switch id={`free-${role.id}`} checked={freeOnly} onChange={setFreeOnly} label="Free only" />}
              </div>)}
            <div className="flex gap-2"><Input aria-label="Model id" placeholder="Or type a model id" value={typed} onChange={e => setTyped(e.target.value)} />
              <Button icon={<Plus />} disabled={!typed.trim()} onClick={() => { add(typed.trim()); setTyped('') }}>Add</Button></div>
          </div>}
        </div>
      </div>
    </div>
  )
}
