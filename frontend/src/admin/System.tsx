// Platform admin only: server configuration and sample data.
import { CircleCheck, Database, Server, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { Alert, Button, Card, CardBody, CardHeader, toast } from '../components/ui'
import { Loading } from '../components/kit'
import { api } from '../lib/api'
import { healthProblems, useHealth } from '../lib/health'
import { useMe } from '../lib/session'

export function SampleData() {
  const me = useMe()
  const [busy, setBusy] = useState('')
  async function run(kind: 'seed' | 'clear') {
    if (kind === 'clear' && !confirm(`Remove all sample jobs and candidates from ${me.org?.name}? Real data is kept.`)) return
    setBusy(kind)
    try { const r = await api(kind === 'seed' ? '/api/demo/seed' : '/api/demo/clear', { method: 'POST' }); toast(kind === 'seed' ? `Added ${r.jobs} jobs and ${r.candidates} candidates to ${me.org?.name}` : `Removed ${r.jobs} jobs and ${r.candidates} candidates`) }
    catch (e: any) { toast(e.message) }
    setBusy('')
  }
  if (!me.org) return null
  return (
    <Card><CardHeader title="Sample data" description={`For demos: 6 jobs and 40 realistic resumes, loaded into the workspace you're in now (${me.org.name}). Company users can only remove it.`} />
      <CardBody className="flex flex-wrap gap-2"><Button variant="primary" icon={<Database />} loading={busy === 'seed'} onClick={() => run('seed')}>Load sample data</Button>
        <Button loading={busy === 'clear'} onClick={() => run('clear')}>Remove sample data</Button></CardBody></Card>
  )
}

export function SystemStatus() {
  const h = useHealth()
  if (!h) return <Loading />
  const problems = healthProblems(h)
  const rows: [string, boolean, string][] = [
    ['AI model', h.mock || !!h.llm_key_set, h.mock ? 'Demo AI (LLM_MOCK=1)' : `${h.fast_model} / ${h.smart_model}`],
    ['Database', !!h.platform?.persistent_db, h.platform ? (h.platform.database === 'postgres' ? 'Postgres (DATABASE_URL)' : 'SQLite on local disk') : '-'],
    ['File storage (resumes, recordings)', !!(h.storage?.s3 || h.storage?.persistent_disk), h.storage?.s3 ? 'S3-compatible bucket' : h.storage?.persistent_disk ? 'Persistent disk' : 'Temporary disk'],
    ['Voice interviews (Vapi)', !!h.vapi_key_set && !!h.public_url, h.public_url || 'PUBLIC_URL not set'],
    ['Live interviewer, last hour', !h.live_turns?.turns || h.live_turns.failed / h.live_turns.turns <= 0.2, h.live_turns?.turns ? `${h.live_turns.turns} turns · ${h.live_turns.failed} failed · ${(h.live_turns.avg_ms / 1000).toFixed(1)} s average` : 'No interviews yet'],
    ['Video processing (ffmpeg)', !!h.ffmpeg, h.ffmpeg ? 'Available' : 'Missing'],
  ]
  return (
    <Card><CardHeader title="System status" description="Server configuration, visible to platform admins only. Change it in the hosting environment variables." /><CardBody>
      {problems.length > 0 && <div className="mb-4 space-y-2">{problems.map(p => <Alert key={p} tone="warning" icon={<TriangleAlert />}>{p}</Alert>)}</div>}
      <ul className="divide-y divide-slate-100 dark:divide-ink-800">{rows.map(([k, ok, v]) => (
        <li key={k} className="flex items-center justify-between gap-3 py-3 text-sm"><span className="flex items-center gap-2">{ok ? <CircleCheck className="size-4 text-emerald-500" /> : <TriangleAlert className="size-4 text-amber-500" />}{k}</span><span className="truncate text-right text-slate-500">{v}</span></li>))}</ul>
      <p className="mt-4 flex items-center gap-2 text-xs text-slate-500"><Server className="size-3.5" />See DEPLOY.md for every environment variable.</p>
    </CardBody></Card>
  )
}
