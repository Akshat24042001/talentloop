// Platform admin > Analytics: who is using TalentLoop right now and how usage moves over time, across every company.
import { Activity, Briefcase, Building2, FileText, Sparkles, Users, Video } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge, Card, CardBody, CardHeader, Stat } from '../components/ui'
import { navigate } from '../lib/router'
import { Ago, CardsSkeleton, ErrorBox, Tabs, useApi } from '../components/kit'
import { ColumnChart, HBarChart } from '../components/charts'

type Range = '7' | '30' | '90'
interface Data {
  days: string[]; tz: string; online_now: number; tracking_since: string | null
  online: { id: string; name: string; email: string; company: string; last_seen_at: number; platform_admin: boolean }[]
  active: { today: number; d7: number; d30: number }
  totals: { companies: number; companies_disabled: number; users: number; resumes: number; sample_resumes: number; applications: number; jobs_open: number; interviews: number; ai_calls: number }
  series: Record<'active_users' | 'active_companies' | 'signups' | 'companies' | 'resumes' | 'applications' | 'interviews' | 'ai_calls', number[]>
  top_resumes: { company: string; n: number }[]; top_active: { company: string; n: number }[]; stages: Record<string, number>
}
const CHARTS: { key: keyof Data['series']; title: string; name: string; sum: boolean }[] = [
  { key: 'active_users', title: 'People using TalentLoop each day', name: 'People', sum: false },
  { key: 'active_companies', title: 'Companies using it each day', name: 'Companies', sum: false },
  { key: 'signups', title: 'New accounts', name: 'Accounts', sum: true },
  { key: 'companies', title: 'New companies', name: 'Companies', sum: true },
  { key: 'resumes', title: 'Resumes added (real, not sample)', name: 'Resumes', sum: true },
  { key: 'applications', title: 'Applications', name: 'Applications', sum: true },
  { key: 'interviews', title: 'AI interviews', name: 'Interviews', sum: true },
  { key: 'ai_calls', title: 'AI requests', name: 'Requests', sum: true },
]
const day = (s: string) => new Date(`${s}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })

export default function PlatformAnalytics() {
  const [range, setRange] = useState<Range>('30')
  const { data: d, error, reload } = useApi<Data>(`/api/admin/analytics?days=${range}`)
  useEffect(() => { const t = setInterval(reload, 60_000); return () => clearInterval(t) }, [reload])   // "online now" stays fresh
  if (error) return <ErrorBox error={error} />
  return (
    <section className="mb-6">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="text-lg font-semibold">Platform analytics</h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">All companies together. Days in {d?.tz || 'India time'}; refreshes every minute.{d?.tracking_since ? ` Daily activity is recorded from ${day(d.tracking_since)}.` : ''}</p></div>
        <Tabs value={range} onChange={setRange} tabs={[{ id: '7', label: '7 days' }, { id: '30', label: '30 days' }, { id: '90', label: '90 days' }]} />
      </div>
      {!d ? <CardsSkeleton n={8} /> : <>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-5">
          <button type="button" className="rounded-2xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500" onClick={() => document.getElementById('online-now')?.scrollIntoView({ behavior: 'smooth', block: 'center' })}>
            <Stat label="Online now" value={<span className="inline-flex items-center gap-2">{d.online_now}{d.online_now > 0 && <i className="size-2 animate-pulse rounded-full bg-emerald-500" aria-hidden />}</span>} sub="active in the last 5 minutes · see who" icon={<Activity />} /></button>
          <Stat label="Active today" value={d.active.today} sub="people who used it today" icon={<Users />} />
          <Stat label="Active this week" value={d.active.d7} sub="last 7 days" icon={<Users />} />
          <Stat label="Active this month" value={d.active.d30} sub="last 30 days" icon={<Users />} />
          <Stat label="Companies" value={d.totals.companies} sub={d.totals.companies_disabled ? `${d.totals.companies_disabled} disabled` : 'all enabled'} icon={<Building2 />} />
          <Stat label="Accounts" value={d.totals.users} sub="staff sign-ins, all companies" icon={<Users />} />
          <Stat label="Resumes" value={d.totals.resumes} sub={d.totals.sample_resumes ? `+ ${d.totals.sample_resumes} sample` : 'no sample data'} icon={<FileText />} />
          <Stat label="Applications" value={d.totals.applications} sub={`${d.totals.jobs_open} open jobs`} icon={<Briefcase />} />
          <Stat label="AI interviews" value={d.totals.interviews} icon={<Video />} />
          <Stat label="AI requests" value={d.totals.ai_calls} icon={<Sparkles />} />
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">{CHARTS.map(c => {
          const v = d.series[c.key]; const total = v.reduce((a, b) => a + b, 0)
          return <Card key={c.key}><CardBody>
            <div className="mb-3 flex items-baseline justify-between gap-2"><span className="text-sm font-semibold">{c.title}</span>
              <span className="whitespace-nowrap text-xs text-slate-500 dark:text-slate-400">{c.sum ? <><b className="text-slate-800 dark:text-slate-100">{total}</b> total</> : <>peak <b className="text-slate-800 dark:text-slate-100">{Math.max(0, ...v)}</b></>}</span></div>
            <ColumnChart values={v} labels={d.days} name={c.name} fmtLabel={day} />
          </CardBody></Card>
        })}</div>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <Card id="online-now"><CardHeader title="Online now" description="Signed-in people active in the last 5 minutes. Click a person to manage their account." /><CardBody>
            {d.online.length ? <ul className="space-y-2 text-sm">{d.online.map(p => (
              <li key={p.email}><button type="button" onClick={() => navigate(`/admin/people/${p.id}`)} className="-mx-2 flex w-[calc(100%+1rem)] items-center justify-between gap-2 rounded-lg px-2 py-1 text-left hover:bg-slate-50 dark:hover:bg-ink-850"><div className="min-w-0"><div className="truncate font-medium">{p.name || p.email} {p.platform_admin && <Badge tone="violet">Admin</Badge>}</div>
                <div className="truncate text-xs text-slate-500 dark:text-slate-400">{p.company || 'no company'} · {p.email}</div></div>
                <span className="shrink-0 text-xs text-slate-500 dark:text-slate-400"><Ago ts={p.last_seen_at} /></span></button></li>))}</ul>
              : <p className="text-sm text-slate-500 dark:text-slate-400">Nobody right now.</p>}
          </CardBody></Card>
          <Card><CardHeader title="Most active companies" description={`Person-days of use, last ${range} days`} /><CardBody>
            <HBarChart valueLabel="Person-days" rows={d.top_active.map(r => ({ key: r.company, label: r.company, value: r.n }))} empty="No activity recorded yet." /></CardBody></Card>
          <Card><CardHeader title="Most resumes added" description={`Real resumes, last ${range} days`} /><CardBody>
            <HBarChart valueLabel="Resumes" rows={d.top_resumes.map(r => ({ key: r.company, label: r.company, value: r.n }))} empty="No resumes in this period." /></CardBody></Card>
        </div>
        <Card className="mt-4"><CardHeader title="Where applications stand" description="Every application on the platform, by pipeline stage" /><CardBody>
          <HBarChart valueLabel="Applications" rows={Object.entries(d.stages).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ key: k, label: k.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase()), value: n }))} />
        </CardBody></Card>
      </>}
    </section>
  )
}
