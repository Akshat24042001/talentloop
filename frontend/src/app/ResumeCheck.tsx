// Resume check: is the resume consistent, backed up and about this person? Findings with evidence, what was
// confirmed, what couldn't be checked. Run on every upload (file and text); "Run full check" adds GitHub, the
// people-data provider and an AI read of the claims (quotes it can't find in the resume are dropped).
import { CircleAlert, CircleCheck, Code2, ExternalLink, Link2, ShieldCheck, ShieldAlert, TriangleAlert, UserRound } from 'lucide-react'
import { useState } from 'react'
import { Badge, Button, Card, CardBody, CardHeader, cn, toast } from '../components/ui'
import { ScoreRing } from '../components/kit'
import { api } from '../lib/api'
import { when } from '../lib/format'

export interface Finding { severity: 'high' | 'medium' | 'low'; kind: string; title: string; evidence: string; ask: string }
export interface Verification {
  score: number; level: string; findings: Finding[]; facts: string[]; checked: string[]; mode: 'quick' | 'full'; checked_at: number
  links: { linkedin: string[]; github: string[]; other: string[] }; not_checked?: string[]
  sources?: { github?: { user: string; found?: boolean; name?: string; created?: string; own_repos?: number; languages?: Record<string, number>; last_push?: string; error?: string }
    profile?: { configured?: boolean; matched?: boolean; why?: string; name?: string; title?: string; company?: string; location?: string; linkedin?: string; employers?: string[]; schools?: string[]; error?: string } }
}
const SEV = {
  high: { label: 'Serious', cls: 'bg-red-50 text-red-800 ring-red-200 dark:bg-red-500/15 dark:text-red-200 dark:ring-red-500/30', icon: ShieldAlert },
  medium: { label: 'Check', cls: 'bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-500/15 dark:text-amber-200 dark:ring-amber-500/30', icon: TriangleAlert },
  low: { label: 'Minor', cls: 'bg-slate-100 text-slate-700 ring-slate-200 dark:bg-ink-800 dark:text-slate-200 dark:ring-ink-700', icon: CircleAlert },
}
export const LEVEL_TONE: Record<string, 'success' | 'warning' | 'danger'> = { 'Looks consistent': 'success', 'Some things to check': 'warning', 'Needs checking': 'danger' }

/** Small summary for the side column and the match report. */
export function ResumeCheckSummary({ v, onOpen }: { v?: Verification; onOpen?: () => void }) {
  if (!v) return null
  const serious = v.findings.filter(f => f.severity === 'high').length
  return (
    <Card className="p-4">
      <div className="flex items-center gap-3">
        <ScoreRing value={v.score} size={52} label="Resume check" />
        <div className="min-w-0 flex-1"><div className="text-xs text-slate-500 dark:text-slate-400">Resume check</div>
          <Badge tone={LEVEL_TONE[v.level]}>{v.level}</Badge>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{v.findings.length ? `${v.findings.length} finding${v.findings.length === 1 ? '' : 's'}${serious ? `, ${serious} serious` : ''}` : 'No problems found'}</div></div>
      </div>
      {onOpen && <Button size="sm" variant="ghost" className="mt-2 w-full" onClick={onOpen}>See details</Button>}
    </Card>
  )
}

export default function ResumeCheck({ cid, v, canRun, onDone }: { cid: string; v?: Verification; canRun: boolean; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  async function run() {
    setBusy(true)
    try { await api(`/api/candidates/${cid}/verify`, { method: 'POST' }); toast('Full check done'); onDone() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  if (!v) return <Card><CardBody><p className="text-sm text-slate-600 dark:text-slate-300">No resume check yet. It runs when a resume is uploaded.</p>
    {canRun && <Button className="mt-3" loading={busy} icon={<ShieldCheck />} onClick={run}>Run the check</Button>}</CardBody></Card>
  const gh = v.sources?.github, pf = v.sources?.profile
  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-4">
          <ScoreRing value={v.score} size={72} label="Resume check score" />
          <div className="min-w-0 flex-1">
            <Badge tone={LEVEL_TONE[v.level]}>{v.level}</Badge>
            <p className="mt-1.5 text-sm text-slate-600 dark:text-slate-300">{v.mode === 'full' ? 'Full check' : 'Quick check (file and text)'} · {when(v.checked_at)}. Findings are reasons to ask, never proof: people change jobs, freelance, and write modestly or boldly.</p>
          </div>
          {canRun && <Button variant={v.mode === 'full' ? 'secondary' : 'primary'} icon={<ShieldCheck />} loading={busy} onClick={run}>{v.mode === 'full' ? 'Run again' : 'Run full check'}</Button>}
        </div>
        {(v.links.linkedin.length + v.links.github.length + v.links.other.length) > 0 && <div className="mt-4 flex flex-wrap gap-2">
          {v.links.linkedin.map(u => <Button key={u} size="sm" icon={<UserRound />} href={u} target="_blank">{u.replace(/^https?:\/\/(www\.)?/, '')}</Button>)}
          {v.links.github.map(u => <Button key={u} size="sm" icon={<Code2 />} href={u} target="_blank">{u.replace(/^https?:\/\//, '')}</Button>)}
          {v.links.other.map(u => <Button key={u} size="sm" icon={<Link2 />} href={u.startsWith('http') ? u : `https://${u}`} target="_blank">{u.replace(/^https?:\/\/(www\.)?/, '').slice(0, 40)}</Button>)}
        </div>}
      </Card>

      <Card><CardHeader title="Findings" description={v.findings.length ? 'Most serious first. Each has the evidence and a question to ask.' : undefined} />
        <CardBody className="pt-1">{!v.findings.length ? <p className="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-300"><CircleCheck className="size-4" />Nothing inconsistent found in what was checked.</p> : (
          <ul className="space-y-3">{v.findings.map((f, i) => { const s = SEV[f.severity]; return (
            <li key={i} className="rounded-xl p-3 ring-1 ring-slate-200 dark:ring-ink-700">
              <div className="flex flex-wrap items-center gap-2"><span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset', s.cls)}><s.icon className="size-3.5" />{s.label}</span>
                <span className="text-sm font-semibold">{f.title}</span></div>
              {f.evidence && <p className="mt-1.5 break-words rounded-lg bg-slate-50 px-2.5 py-1.5 font-mono text-xs text-slate-700 dark:bg-ink-850 dark:text-slate-200">{f.evidence}</p>}
              {f.ask && <p className="mt-1.5 text-xs text-slate-600 dark:text-slate-300"><b>Ask:</b> {f.ask}</p>}
            </li>) })}</ul>)}</CardBody></Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card><CardHeader title="Confirmed" /><CardBody className="pt-1">
          {v.facts.length ? <ul className="space-y-1.5 text-sm">{v.facts.map((x, i) => <li key={i} className="flex gap-2"><CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />{x}</li>)}</ul>
            : <p className="text-sm text-slate-500 dark:text-slate-400">Nothing confirmed from outside sources yet{v.mode === 'quick' ? ': run the full check' : ''}.</p>}
        </CardBody></Card>
        <Card><CardHeader title="What was checked" /><CardBody className="pt-1 text-sm">
          <ul className="space-y-1 text-slate-600 dark:text-slate-300">{v.checked.map(x => <li key={x}>· {x}</li>)}</ul>
          {!!v.not_checked?.length && <><div className="mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Not checked</div>
            <ul className="mt-1 space-y-1 text-slate-500 dark:text-slate-400">{v.not_checked.map(x => <li key={x}>· {x}</li>)}</ul></>}
        </CardBody></Card>
      </div>

      {(gh || pf?.matched) && <div className="grid gap-4 md:grid-cols-2">
        {gh && <Card><CardHeader title="GitHub" /><CardBody className="pt-1 text-sm">{gh.error ? <p className="text-slate-500">{gh.error}</p> : !gh.found ? <p>No such profile: github.com/{gh.user}</p> : <>
          <p><b>{gh.name || gh.user}</b> · joined {gh.created} · {gh.own_repos} own repositories · last push {gh.last_push || 'never'}</p>
          {gh.languages && Object.keys(gh.languages).length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{Object.entries(gh.languages).map(([k, n]) => <Badge key={k}>{k} · {n}</Badge>)}</div>}
          <Button className="mt-3" size="sm" variant="ghost" icon={<ExternalLink />} href={`https://github.com/${gh.user}`} target="_blank">Open profile</Button></>}</CardBody></Card>}
        {pf?.matched && <Card><CardHeader title="Public professional profile" description="From the people-data provider, very likely the same person" /><CardBody className="pt-1 text-sm space-y-1">
          <p><b>{pf.name}</b>{pf.title ? ` · ${pf.title}` : ''}{pf.company ? ` at ${pf.company}` : ''}{pf.location ? ` · ${pf.location}` : ''}</p>
          {!!pf.employers?.length && <p className="text-slate-600 dark:text-slate-300">Employers: {pf.employers.join(', ')}</p>}
          {!!pf.schools?.length && <p className="text-slate-600 dark:text-slate-300">Education: {pf.schools.join(', ')}</p>}
          {pf.linkedin && <Button size="sm" variant="ghost" icon={<UserRound />} href={pf.linkedin.startsWith('http') ? pf.linkedin : `https://${pf.linkedin}`} target="_blank">LinkedIn</Button>}
        </CardBody></Card>}
      </div>}
    </div>
  )
}
