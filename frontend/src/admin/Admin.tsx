import { Ban, Briefcase, Building2, CircleCheck, FileText, Search, Sparkles, Users, Video } from 'lucide-react'
import { useState } from 'react'
import { Badge, Button, Card, CardBody, CardHeader, Input, Stat, toast } from '../components/ui'
import { ErrorBox, Loading, PageHeader, Tabs, useApi } from '../components/kit'
import { api } from '../lib/api'
import { ago, when } from '../lib/format'

interface Overview { orgs: number; users: number; active_users_7d: number; jobs: number; open_jobs: number; candidates: number; applications: number; interviews: number; ai_calls: number; ai_calls_30d: number; signups_30d: number[]; storage: { s3: boolean; database: string } }
interface OrgRow { id: string; name: string; slug: string; created_at: number; disabled: boolean; owner: string; members: number; jobs: number; open_jobs: number; candidates: number; applications: number; interviews: number; ai_calls: number; last_activity?: number }
interface UserRow { id: string; email: string; name: string; created_at: number; last_login_at?: number; login_count: number; disabled: boolean; platform_admin: boolean; memberships: { org: string; role_label: string }[] }

export default function Admin() {
  const [tab, setTab] = useState<'orgs' | 'users'>('orgs')
  const ov = useApi<Overview>('/api/admin/overview')
  const orgs = useApi<OrgRow[]>('/api/admin/orgs')
  const users = useApi<UserRow[]>('/api/admin/users')
  const [q, setQ] = useState('')
  if (ov.error) return <ErrorBox error={ov.error} />
  const d = ov.data
  const max = Math.max(1, ...(d?.signups_30d || [0]))
  async function toggleOrg(o: OrgRow) { if (!confirm(`${o.disabled ? 'Enable' : 'Disable'} ${o.name}?`)) return; await api(`/api/admin/orgs/${o.id}`, { method: 'PATCH', json: { disabled: !o.disabled } }); toast('Updated'); orgs.reload() }
  async function toggleUser(u: UserRow) {
    if (!confirm(`${u.disabled ? 'Enable' : 'Disable'} ${u.email}?${u.disabled ? '' : ' They are signed out everywhere.'}`)) return
    try { await api(`/api/admin/users/${u.id}`, { method: 'PATCH', json: { disabled: !u.disabled } }); toast('Updated'); users.reload() } catch (e: any) { toast(e.message) }
  }
  const qq = q.toLowerCase()
  return (
    <>
      <PageHeader title="Platform admin" description="Every company and user on this TalentLoop installation." />
      {!d ? <Loading /> : <>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          <Stat label="Companies" value={d.orgs} icon={<Building2 />} />
          <Stat label="Users" value={d.users} sub={`${d.active_users_7d} active this week`} icon={<Users />} />
          <Stat label="Jobs" value={d.jobs} sub={`${d.open_jobs} open`} icon={<Briefcase />} />
          <Stat label="Resumes" value={d.candidates} sub={`${d.applications} applications`} icon={<FileText />} />
          <Stat label="AI interviews" value={d.interviews} icon={<Video />} />
          <Stat label="AI calls" value={d.ai_calls} sub={`${d.ai_calls_30d} in 30 days`} icon={<Sparkles />} />
        </div>
        <Card className="mt-4"><CardHeader title="Sign-ups, last 30 days" description={`Database: ${d.storage.database} · files: ${d.storage.s3 ? 'S3 bucket' : 'local disk'}`} /><CardBody>
          <div className="flex h-20 items-end gap-1">{d.signups_30d.map((n, i) => <span key={i} title={`${n}`} className="flex-1 rounded-t-[3px] bg-[var(--series-1)]" style={{ height: `${Math.max(4, (n / max) * 100)}%`, opacity: n ? 1 : 0.25 }} />)}</div>
        </CardBody></Card>
      </>}
      <div className="mt-6 flex flex-wrap items-end justify-between gap-3">
        <Tabs className="flex-1" value={tab} onChange={setTab} tabs={[{ id: 'orgs', label: 'Companies', count: orgs.data?.length }, { id: 'users', label: 'Users', count: users.data?.length }]} />
        <div className="relative w-full sm:w-72"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" /><Input type="search" aria-label="Search" className="pl-9" placeholder="Search" value={q} onChange={e => setQ(e.target.value)} /></div>
      </div>
      <Card className="mt-4 overflow-x-auto">
        {tab === 'orgs' && (!orgs.data ? <Loading /> : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500">{['Company', 'Owner', 'Users', 'Jobs', 'Resumes', 'Applications', 'Interviews', 'AI calls', 'Last active', ''].map(h => <th key={h} className="whitespace-nowrap px-4 py-3 font-medium">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{orgs.data.filter(o => !qq || `${o.name} ${o.owner} ${o.slug}`.toLowerCase().includes(qq)).map(o => (
              <tr key={o.id} className={o.disabled ? 'opacity-50' : ''}>
                <td className="px-4 py-3"><div className="font-semibold">{o.name}</div><div className="text-xs text-slate-500">/{o.slug} · since {when(o.created_at).split(',')[0]}</div></td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-300">{o.owner}</td>
                {[o.members, `${o.jobs} (${o.open_jobs} open)`, o.candidates, o.applications, o.interviews, o.ai_calls].map((v, i) => <td key={i} className="tabular whitespace-nowrap px-4 py-3">{v}</td>)}
                <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">{o.last_activity ? ago(o.last_activity) : '-'}</td>
                <td className="px-4 py-3 text-right"><Button size="sm" variant="ghost" icon={o.disabled ? <CircleCheck /> : <Ban />} onClick={() => toggleOrg(o)}>{o.disabled ? 'Enable' : 'Disable'}</Button></td>
              </tr>))}</tbody>
          </table>
        ))}
        {tab === 'users' && (!users.data ? <Loading /> : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500">{['User', 'Companies', 'Sign-ins', 'Last sign-in', 'Joined', ''].map(h => <th key={h} className="whitespace-nowrap px-4 py-3 font-medium">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{users.data.filter(u => !qq || `${u.name} ${u.email} ${u.memberships.map(m => m.org).join(' ')}`.toLowerCase().includes(qq)).map(u => (
              <tr key={u.id} className={u.disabled ? 'opacity-50' : ''}>
                <td className="px-4 py-3"><div className="font-semibold">{u.name} {u.platform_admin && <Badge tone="violet">Admin</Badge>}</div><div className="text-xs text-slate-500">{u.email}</div></td>
                <td className="px-4 py-3 text-xs">{u.memberships.map((m, i) => <div key={i}>{m.org} <span className="text-slate-500">· {m.role_label}</span></div>)}</td>
                <td className="tabular px-4 py-3">{u.login_count}</td>
                <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">{u.last_login_at ? ago(u.last_login_at) : 'never'}</td>
                <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">{ago(u.created_at)}</td>
                <td className="px-4 py-3 text-right"><Button size="sm" variant="ghost" onClick={() => toggleUser(u)}>{u.disabled ? 'Enable' : 'Disable'}</Button></td>
              </tr>))}</tbody>
          </table>
        ))}
      </Card>
    </>
  )
}
