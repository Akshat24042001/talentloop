import { CircleCheck, Download, Gauge, Link2, Plus, Search, Send, ShieldAlert, Sparkles, ThumbsUp, TriangleAlert, UserX } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { SplitBar } from '../components/charts'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Input, Select, Spinner, Stat, Tip, copyText, useInterval } from '../components/ui'
import { api, withKey } from '../lib/api'
import { REC_LABEL, REC_TONE, STATUS_LABEL, STATUS_TONE, ago, initials, when } from '../lib/format'
import { AppShell, PageHeader, healthProblems, useHealth } from './shell'

interface Row {
  id: string; created_at: number; status: string; candidate?: string; role?: string; company?: string; email?: string
  recommendation?: string; overall?: number | null; risk?: 'low' | 'medium' | 'high'; decision?: string; ended_early: boolean
  disqualified: boolean; warnings: number
}
interface Calib { pairs: number; within_1?: number; exact?: number; ai_minus_hr_avg?: number }

export default function Dashboard() {
  const health = useHealth()
  const [rows, setRows] = useState<Row[] | null>(null)
  const [cal, setCal] = useState<Calib | null>(null)
  const [err, setErr] = useState('')
  const [q, setQ] = useState(''), [fs, setFs] = useState(''), [fr, setFr] = useState(''), [role, setRole] = useState(''), [sort, setSort] = useState('new')
  const base = (health?.public_url || location.origin).replace(/\/$/, '')

  const load = useCallback(async () => {
    try { const [r, c] = await Promise.all([api<Row[]>('/api/interviews'), api<Calib>('/api/calibration')]); setRows(r); setCal(c); setErr('') }
    catch (e: any) { setErr(e.message) }
  }, [])
  useEffect(() => { load() }, [load])
  useInterval(useCallback(() => { if (!document.hidden) load() }, [load]), 30000)

  const all = rows || []
  const roles = useMemo(() => [...new Set(all.map(r => r.role).filter(Boolean) as string[])].sort(), [all])
  const filtered = useMemo(() => {
    const qq = q.toLowerCase().trim(), rank = { high: 3, medium: 2, low: 1 } as Record<string, number>
    const out = all.filter(r => (!fs || r.status === fs) && (!role || r.role === role) && (!fr || (fr === 'dq' ? r.disqualified : r.risk === fr)) &&
      (!qq || [r.candidate, r.role, r.company, r.email].join(' ').toLowerCase().includes(qq)))
    if (sort === 'score') out.sort((a, b) => (b.overall ?? -1) - (a.overall ?? -1))
    if (sort === 'risk') out.sort((a, b) => (+b.disqualified - +a.disqualified) || (rank[b.risk || ''] || 0) - (rank[a.risk || ''] || 0))
    if (sort === 'name') out.sort((a, b) => String(a.candidate || '').localeCompare(String(b.candidate || '')))
    return out
  }, [all, q, fs, fr, role, sort])

  const n = (s: string) => all.filter(r => r.status === s).length
  const done = all.filter(r => ['completed', 'scored', 'incomplete'].includes(r.status)).length
  const scores = all.map(r => r.overall).filter((x): x is number => typeof x === 'number')
  const avg = scores.length ? (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1) : '-'
  const rc = (k: string) => all.filter(r => r.recommendation === k).length
  const rk = (k: string) => all.filter(r => r.risk === k).length
  const problems = health ? healthProblems(health) : []

  return (
    <AppShell active="dashboard">
      <PageHeader title="Interviews" description="Every AI interview you've sent, with results and integrity at a glance."
        actions={<><Button href={withKey('/api/interviews.csv')} icon={<Download />}>Export CSV</Button>
          <Button variant="primary" href="/hr.html" icon={<Plus />}>New interview</Button></>} />
      {(health?.mock || problems.length > 0) && (
        <div className="mb-6 space-y-2">
          {health?.mock && <Alert tone="info" icon={<Sparkles />} title="Demo mode">The AI is simulated (LLM_MOCK=1). Good for trying the flow; turn it off for real candidates.</Alert>}
          {problems.map(p => <Alert key={p} tone="danger" icon={<TriangleAlert />}>{p}</Alert>)}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Sent" value={all.length} sub={`${n('created')} not started yet`} icon={<Send />} />
        <Stat label="Completed" value={done} sub={`${n('in_progress')} in progress now`} icon={<CircleCheck />} />
        <Stat label="Average AI score" value={avg} sub={scores.length ? `out of 5, across ${scores.length}` : 'nothing scored yet'} icon={<Gauge />} />
        <Stat label="Recommended" value={rc('yes') + rc('strong_yes')} sub="AI says yes or strong yes" icon={<ThumbsUp />} />
        <Stat label="High integrity risk" value={rk('high')} sub="watch the recording" icon={<ShieldAlert />} tone="warning" />
        <Stat label="Disqualified" value={all.filter(r => r.disqualified).length} sub="left after final warning" icon={<UserX />} tone="danger" />
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Card><CardHeader title="AI recommendations" /><CardBody>
          <SplitBar parts={[{ label: 'Strong yes', n: rc('strong_yes'), color: '#0b7a55' }, { label: 'Yes', n: rc('yes'), color: '#35b27f' },
            { label: 'Maybe', n: rc('maybe'), color: 'var(--status-warn)' }, { label: 'No', n: rc('no'), color: 'var(--status-critical)' }]} />
        </CardBody></Card>
        <Card><CardHeader title="Integrity risk" /><CardBody>
          <SplitBar parts={[{ label: 'Low', n: rk('low'), color: 'var(--status-good)' }, { label: 'Medium', n: rk('medium'), color: 'var(--status-serious)' },
            { label: 'High', n: rk('high'), color: 'var(--status-critical)' }]} />
        </CardBody></Card>
      </div>

      <Card className="mt-4 overflow-hidden">
        <div className="grid gap-2 border-b border-slate-100 p-4 dark:border-ink-800 md:grid-cols-[2fr_repeat(4,1fr)]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
            <Input id="q" type="search" className="pl-9" placeholder="Search candidate, role, company or email" value={q} onChange={e => setQ(e.target.value)} />
          </div>
          <Select aria-label="Status" value={fs} onChange={e => setFs(e.target.value)}><option value="">All statuses</option>{Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
          <Select aria-label="Role" value={role} onChange={e => setRole(e.target.value)}><option value="">All roles</option>{roles.map(r => <option key={r}>{r}</option>)}</Select>
          <Select aria-label="Integrity" value={fr} onChange={e => setFr(e.target.value)}><option value="">Any integrity</option><option value="high">High risk</option><option value="medium">Medium risk</option><option value="low">Low risk</option><option value="dq">Disqualified</option></Select>
          <Select aria-label="Sort" value={sort} onChange={e => setSort(e.target.value)}><option value="new">Newest first</option><option value="score">Best AI score</option><option value="risk">Highest risk</option><option value="name">Name A-Z</option></Select>
        </div>
        {cal && <p className="border-b border-slate-100 px-5 py-2.5 text-xs text-slate-500 dark:border-ink-800 dark:text-slate-400">
          {cal.pairs ? <>AI vs your scores: within ±1 on <b className="text-slate-700 dark:text-slate-200">{cal.within_1}%</b> of {cal.pairs} answers · exact {cal.exact}% · AI minus HR {cal.ai_minus_hr_avg}</>
            : 'Tip: add your own scores on a report to measure how closely the AI agrees with your team.'}</p>}
        {err ? <div className="p-5"><Alert tone="danger" icon={<TriangleAlert />}>{err}</Alert></div>
          : !rows ? <div className="grid place-items-center p-16"><Spinner className="size-6 text-brand-500" /></div>
          : !filtered.length ? (all.length ? <p className="p-10 text-center text-sm text-slate-500">No interviews match the filters.</p> : <Empty />)
          : (<>
            <ul className="divide-y divide-slate-100 dark:divide-ink-800 md:hidden">
              {filtered.map(r => (
                <li key={r.id}>
                  <a href={`/report.html?id=${encodeURIComponent(r.id)}`} className="flex gap-3 px-4 py-3.5 active:bg-slate-50 dark:active:bg-ink-850">
                    <span className="grid size-10 shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-100 to-violet-100 text-xs font-bold text-brand-700 dark:from-brand-500/25 dark:to-violet-500/25 dark:text-brand-200">{initials(r.candidate)}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2"><span className="truncate font-semibold text-slate-900 dark:text-white">{r.candidate || 'Candidate'}</span><span className="shrink-0 text-xs text-slate-400">{ago(r.created_at)}</span></div>
                      <div className="truncate text-xs text-slate-500 dark:text-slate-400">{r.role}{r.company ? ` · ${r.company}` : ''}</div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <Badge tone={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status] || r.status}</Badge>
                        {r.recommendation && <Badge tone={REC_TONE[r.recommendation]}>{REC_LABEL[r.recommendation]}{typeof r.overall === 'number' ? ` · ${r.overall.toFixed(1)}` : ''}</Badge>}
                        {r.disqualified ? <Badge tone="danger" icon={<UserX />}>Disqualified</Badge> : r.risk && r.risk !== 'low' && <Badge tone={r.risk === 'high' ? 'danger' : 'warning'}>{r.risk} risk</Badge>}
                      </div>
                    </div>
                  </a>
                </li>
              ))}
            </ul>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-xs font-medium text-slate-500 dark:text-slate-400">
                  {['Candidate', 'Role', 'Status', 'AI verdict', 'Score', 'Integrity', 'HR', 'Created', ''].map((h, i) =>
                    <th key={i} className={`whitespace-nowrap px-4 py-3 font-medium ${[1, 6, 7].includes(i) ? 'hidden lg:table-cell' : ''}`}>{h}</th>)}
                </tr></thead>
                <tbody className="divide-y divide-slate-100 dark:divide-ink-800">
                  {filtered.map(r => (
                    <tr key={r.id} className="cursor-pointer transition-colors hover:bg-slate-50/80 dark:hover:bg-ink-850" onClick={e => { if (!(e.target as HTMLElement).closest('a,button')) location.href = `/report.html?id=${encodeURIComponent(r.id)}` }}>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-100 to-violet-100 text-xs font-bold text-brand-700 dark:from-brand-500/25 dark:to-violet-500/25 dark:text-brand-200">{initials(r.candidate)}</span>
                          <div className="min-w-0"><div className="truncate font-semibold text-slate-900 dark:text-white">{r.candidate || 'Candidate'}</div><div className="truncate text-xs text-slate-500 dark:text-slate-400">{r.email}</div></div>
                        </div>
                      </td>
                      <td className="hidden max-w-[240px] px-4 py-3 lg:table-cell"><div className="truncate text-slate-800 dark:text-slate-100" title={r.role}>{r.role}</div><div className="truncate text-xs text-slate-500 dark:text-slate-400">{r.company}</div></td>
                      <td className="px-4 py-3"><Badge tone={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status] || r.status}</Badge></td>
                      <td className="px-4 py-3">{r.recommendation ? <Badge tone={REC_TONE[r.recommendation]}>{REC_LABEL[r.recommendation]}</Badge> : <span className="text-slate-400">-</span>}</td>
                      <td className="px-4 py-3">{typeof r.overall === 'number'
                        ? <span className="flex items-center gap-2 font-semibold tabular"><span>{r.overall.toFixed(1)}</span><span className="relative h-1.5 w-14 rounded-r-full bg-[var(--track)]"><i className="absolute inset-y-0 left-0 rounded-r-full bg-[var(--series-1)]" style={{ width: `${(r.overall / 5) * 100}%` }} /></span></span>
                        : <span className="text-slate-400">-</span>}</td>
                      <td className="px-4 py-3">
                        {r.disqualified ? <Badge tone="danger" icon={<UserX />}>Disqualified</Badge>
                          : r.risk ? <Badge tone={r.risk === 'high' ? 'danger' : r.risk === 'medium' ? 'warning' : 'success'}>{r.risk[0]!.toUpperCase() + r.risk.slice(1)}</Badge> : <span className="text-slate-400">-</span>}
                        {r.warnings > 0 && !r.disqualified && <div className="mt-1 text-xs text-amber-600 dark:text-amber-300">{r.warnings} warning{r.warnings > 1 ? 's' : ''}</div>}
                      </td>
                      <td className="hidden px-4 py-3 capitalize text-slate-700 dark:text-slate-200 lg:table-cell">{(r.decision || '').replace('_', ' ') || <span className="text-slate-400">-</span>}</td>
                      <td className="hidden whitespace-nowrap px-4 py-3 text-xs text-slate-500 dark:text-slate-400 lg:table-cell" title={when(r.created_at)}>{ago(r.created_at)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        <Button size="sm" href={`/report.html?id=${encodeURIComponent(r.id)}`}>Report</Button>
                        <Tip label="Copy candidate link"><button className="ml-1 rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-ink-800 dark:hover:text-white" aria-label="Copy candidate link"
                          onClick={() => copyText(`${base}/interview.html?id=${r.id}`, 'Candidate link copied')}><Link2 className="size-4" /></button></Tip>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>)}
      </Card>
    </AppShell>
  )
}

function Empty() {
  return (
    <div className="px-6 py-16 text-center">
      <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300"><Sparkles className="size-6" /></div>
      <h3 className="mt-4 text-base font-semibold text-slate-900 dark:text-white">No interviews yet</h3>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Create your first AI interview. Seven sample roles are ready to try.</p>
      <Button variant="primary" href="/hr.html" icon={<Plus />} className="mt-5">New interview</Button>
    </div>
  )
}
