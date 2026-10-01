import { Copy, Mail, Trash2, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Field, Input, Select, copyText, toast } from '../components/ui'
import { Avatar, ErrorBox, Loading, PageHeader, useApi } from '../components/kit'
import { api } from '../lib/api'
import { ago } from '../lib/format'
import { useMe } from '../lib/session'

interface TeamData {
  members: { id: string; user_id: string; name: string; email: string; role: string; role_label: string; title: string; last_login_at?: number; you: boolean }[]
  invites: { id: string; email: string; role_label: string; title: string; expires_at: number }[]
  roles: { id: string; label: string }[]
}
const ROLE_HELP: Record<string, string> = {
  owner: 'Everything, including billing-level settings and other owners.',
  admin: 'Manages the team, settings and every job.',
  recruiter: 'HR: creates and publishes jobs, manages candidates, runs matching and interviews.',
  hiring_manager: 'Sees only the jobs HR assigns, as JD editor or reviewer. E.g. a sales or tech manager.',
  viewer: 'Read-only access to all jobs and candidates.',
}

export default function Team() {
  const me = useMe()
  const { data, error, reload } = useApi<TeamData>('/api/team')
  const [email, setEmail] = useState(''), [role, setRole] = useState('recruiter'), [title, setTitle] = useState(''), [busy, setBusy] = useState(false)
  const [link, setLink] = useState('')
  async function invite() {
    setBusy(true)
    try { const r = await api('/api/team/invites', { json: { email, role, title } }); const url = location.origin + r.path; setLink(url); copyText(url, 'Invite link copied'); setEmail(''); setTitle(''); reload() }
    catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  async function changeRole(mid: string, r: string) { try { await api(`/api/team/members/${mid}`, { method: 'PATCH', json: { role: r } }); toast('Role updated'); reload() } catch (e: any) { toast(e.message) } }
  async function remove(mid: string, name: string) { if (!confirm(`Remove ${name} from ${me.org?.name}?`)) return; try { await api(`/api/team/members/${mid}`, { method: 'DELETE' }); reload() } catch (e: any) { toast(e.message) } }
  async function revoke(id: string) { await api(`/api/team/invites/${id}`, { method: 'DELETE' }); reload() }
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!data) return <Loading />
  return (
    <>
      <PageHeader title="Team" description="Several people can share a role. Hiring managers only see the jobs you assign them." />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-5">
          <Card>
            <CardHeader title={`Members (${data.members.length})`} />
            <CardBody className="pt-3">
              <ul className="divide-y divide-slate-100 dark:divide-ink-800">{data.members.map(m => (
                <li key={m.id} className="flex flex-wrap items-center gap-3 py-3">
                  <Avatar name={m.name || m.email} />
                  <div className="min-w-0 flex-1"><div className="truncate font-medium">{m.name} {m.you && <span className="text-xs text-slate-400">(you)</span>}</div>
                    <div className="truncate text-xs text-slate-500">{m.email}{m.title ? ` · ${m.title}` : ''} · {m.last_login_at ? `active ${ago(m.last_login_at)}` : 'never signed in'}</div></div>
                  {me.can.manage_team && !m.you ? (
                    <Select aria-label="Role" className="w-40 py-1.5 text-[13px]" value={m.role} onChange={e => changeRole(m.id, e.target.value)}>{data.roles.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}</Select>
                  ) : <Badge tone={m.role === 'owner' ? 'violet' : 'neutral'}>{m.role_label}</Badge>}
                  {me.can.manage_team && !m.you && <button aria-label={`Remove ${m.name}`} onClick={() => remove(m.id, m.name || m.email)} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600 dark:hover:bg-ink-800"><Trash2 className="size-4" /></button>}
                </li>))}</ul>
            </CardBody>
          </Card>
          {data.invites.length > 0 && <Card><CardHeader title="Pending invites" /><CardBody className="pt-3"><ul className="divide-y divide-slate-100 dark:divide-ink-800">{data.invites.map(i => (
            <li key={i.id} className="flex items-center gap-3 py-2.5 text-sm"><Mail className="size-4 text-slate-400" /><span className="flex-1">{i.email} <span className="text-slate-500">· {i.role_label}{i.title ? ` · ${i.title}` : ''}</span></span>
              <Button size="sm" variant="ghost" onClick={() => revoke(i.id)}>Revoke</Button></li>))}</ul></CardBody></Card>}
        </div>
        <div className="space-y-5">
          {me.can.manage_team ? (
            <Card><CardHeader title="Invite someone" description="We create a private link; send it by email or chat. It works once and expires in 7 days." /><CardBody className="space-y-3">
              <Field label="Email" htmlFor="inv-email"><Input id="inv-email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="sales.manager@company.com" /></Field>
              <Field label="Role" htmlFor="inv-role" hint={ROLE_HELP[role]}><Select id="inv-role" value={role} onChange={e => setRole(e.target.value)}>{data.roles.filter(r => r.id !== 'owner' || me.role === 'owner').map(r => <option key={r.id} value={r.id}>{r.label}</option>)}</Select></Field>
              <Field label="Job title (optional)" htmlFor="inv-title"><Input id="inv-title" value={title} onChange={e => setTitle(e.target.value)} placeholder="Sales Manager" /></Field>
              <Button variant="primary" className="w-full" disabled={!email} loading={busy} onClick={invite} icon={<UserPlus />}>Create invite link</Button>
              {link && <Alert tone="success" title="Invite link (copied)"><span className="break-all text-xs">{link}</span> <button className="ml-1 inline-flex items-center gap-1 text-xs font-semibold underline" onClick={() => copyText(link)}><Copy className="size-3" />Copy</button></Alert>}
            </CardBody></Card>
          ) : <Alert tone="info">Only owners and admins can invite people or change roles.</Alert>}
          <Card><CardHeader title="Roles" /><CardBody className="space-y-2 pt-3 text-sm">{data.roles.map(r => <div key={r.id}><b>{r.label}</b><p className="text-xs text-slate-500 dark:text-slate-400">{ROLE_HELP[r.id]}</p></div>)}</CardBody></Card>
        </div>
      </div>
    </>
  )
}
