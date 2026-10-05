import { Ban, CircleCheck, Search } from 'lucide-react'
import { useState } from 'react'
import { Badge, Button, Card, Input, toast } from '../components/ui'
import { Ago, Loading, PageHeader, Tabs, useApi } from '../components/kit'
import { api } from '../lib/api'
import { when } from '../lib/format'
import { SampleData, SystemStatus } from './System'
import AIModels from './AIModels'
import PlatformAnalytics from './PlatformAnalytics'
import { ask } from '../components/dialogs'

interface OrgRow { id: string; name: string; slug: string; created_at: number; disabled: boolean; owner: string; members: number; jobs: number; open_jobs: number; candidates: number; applications: number; interviews: number; ai_calls: number; last_activity?: number }
interface UserRow { id: string; email: string; name: string; created_at: number; last_login_at?: number; login_count: number; disabled: boolean; platform_admin: boolean; email_verified?: boolean; memberships: { org: string; role_label: string }[] }

export default function Admin() {
  const [tab, setTab] = useState<'orgs' | 'users'>('orgs')
  const orgs = useApi<OrgRow[]>('/api/admin/orgs')
  const users = useApi<UserRow[]>('/api/admin/users')
  const [q, setQ] = useState('')
  async function toggleOrg(o: OrgRow) { if (!await ask(`${o.disabled ? 'Enable' : 'Disable'} ${o.name}?`)) return; await api(`/api/admin/orgs/${o.id}`, { method: 'PATCH', json: { disabled: !o.disabled } }); toast('Updated'); orgs.reload() }
  async function toggleUser(u: UserRow) {
    if (!await ask(`${u.disabled ? 'Enable' : 'Disable'} ${u.email}?${u.disabled ? '' : ' They are signed out everywhere.'}`)) return
    try { await api(`/api/admin/users/${u.id}`, { method: 'PATCH', json: { disabled: !u.disabled } }); toast('Updated'); users.reload() } catch (e: any) { toast(e.message) }
  }
  async function confirmUser(u: UserRow) {
    if (!await ask(`Mark ${u.email} as confirmed without the emailed code? Only do this if you know the person owns this address.`)) return
    try { await api(`/api/admin/users/${u.id}`, { method: 'PATCH', json: { email_verified: true } }); toast('Marked as confirmed'); users.reload() } catch (e: any) { toast(e.message) }
  }
  const qq = q.toLowerCase()
  return (
    <>
      <PageHeader title="Platform admin" description="Every company and user on this TalentLoop installation." />
      <PlatformAnalytics />
      <div className="mb-5 grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]"><SystemStatus /><SampleData /></div>
      <div className="mb-5"><AIModels /></div>
      <div className="mt-6 flex flex-wrap items-end justify-between gap-3">
        <Tabs className="flex-1" value={tab} onChange={setTab} tabs={[{ id: 'orgs', label: 'Companies', count: orgs.data?.length }, { id: 'users', label: 'Users', count: users.data?.length }]} />
        <div className="relative w-full sm:w-72"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-500 dark:text-slate-400" /><Input type="search" aria-label="Search" className="pl-9" placeholder="Search" value={q} onChange={e => setQ(e.target.value)} /></div>
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
                <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500"><Ago ts={o.last_activity} /></td>
                <td className="px-4 py-3 text-right"><Button size="sm" variant="ghost" icon={o.disabled ? <CircleCheck /> : <Ban />} onClick={() => toggleOrg(o)}>{o.disabled ? 'Enable' : 'Disable'}</Button></td>
              </tr>))}</tbody>
          </table>
        ))}
        {tab === 'users' && (!users.data ? <Loading /> : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500">{['User', 'Companies', 'Sign-ins', 'Last sign-in', 'Joined', ''].map(h => <th key={h} className="whitespace-nowrap px-4 py-3 font-medium">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100 dark:divide-ink-800">{users.data.filter(u => !qq || `${u.name} ${u.email} ${u.memberships.map(m => m.org).join(' ')}`.toLowerCase().includes(qq)).map(u => (
              <tr key={u.id} className={u.disabled ? 'opacity-50' : ''}>
                <td className="px-4 py-3"><div className="font-semibold">{u.name} {u.platform_admin && <Badge tone="violet">Admin</Badge>} {u.email_verified === false && <Badge tone="warning">Email not confirmed</Badge>}</div><div className="text-xs text-slate-500">{u.email}</div></td>
                <td className="px-4 py-3 text-xs">{u.memberships.map((m, i) => <div key={i}>{m.org} <span className="text-slate-500">· {m.role_label}</span></div>)}</td>
                <td className="tabular px-4 py-3">{u.login_count}</td>
                <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">{u.last_login_at ? <Ago ts={u.last_login_at} /> : 'never'}</td>
                <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500"><Ago ts={u.created_at} /></td>
                <td className="whitespace-nowrap px-4 py-3 text-right">{u.email_verified === false && <Button size="sm" variant="ghost" onClick={() => confirmUser(u)}>Mark confirmed</Button>}<Button size="sm" variant="ghost" onClick={() => toggleUser(u)}>{u.disabled ? 'Enable' : 'Disable'}</Button></td>
              </tr>))}</tbody>
          </table>
        ))}
      </Card>
    </>
  )
}
