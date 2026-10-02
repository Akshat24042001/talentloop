import { ROLE_HELP } from '../lib/roles'
import { Check, Mail, Pencil, RefreshCw, Trash2, UserPlus, X } from 'lucide-react'
import { useState } from 'react'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Field, Input, Select, copyText, toast } from '../components/ui'
import { Ago, Avatar, ErrorBox, ListSkeleton, PageHeader, useApi } from '../components/kit'
import { api } from '../lib/api'
import { useMe } from '../lib/session'
import { LinkActions } from '../components/LinkActions'
import { ask } from '../components/dialogs'

interface TeamData {
  members: { id: string; user_id: string; name: string; email: string; role: string; role_label: string; title: string; last_login_at?: number; you: boolean; active: boolean }[]
  invites: { id: string; email: string; role_label: string; title: string; expires_at: number; expired: boolean }[]
  roles: { id: string; label: string }[]
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
  async function remove(mid: string, name: string) { if (!await ask(`Remove ${name} from ${me.org?.name}?`)) return; try { await api(`/api/team/members/${mid}`, { method: 'DELETE' }); reload() } catch (e: any) { toast(e.message) } }
  async function revoke(id: string) { if (!await ask('Revoke this invite? The link stops working.')) return; await api(`/api/team/invites/${id}`, { method: 'DELETE' }); toast('Invite revoked'); reload() }
  async function renew(id: string) { try { const r = await api(`/api/team/invites/${id}/renew`, { method: 'POST' }); const url = location.origin + r.path; setLink(url); copyText(url, 'New invite link copied'); reload() } catch (e: any) { toast(e.message) } }
  async function setActive(mid: string, name: string, active: boolean) {
    if (!active && !await ask(`Pause ${name}'s access? They are signed out of ${me.org?.name} now and can't sign in until you turn it back on. Nothing is deleted.`)) return
    try { await api(`/api/team/members/${mid}`, { method: 'PATCH', json: { active } }); toast(active ? `${name} can sign in again` : `${name}'s access paused`); reload() } catch (e: any) { toast(e.message) }
  }
  async function saveTitle(mid: string, title: string) { try { await api(`/api/team/members/${mid}`, { method: 'PATCH', json: { title } }); toast('Saved'); reload() } catch (e: any) { toast(e.message) } }
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!data) return <ListSkeleton rows={4} />
  return (
    <>
      <PageHeader title="Team" description="Several people can share a role. Hiring managers only see the jobs you assign them." />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-5">
          <Card>
            <CardHeader title={`Members (${data.members.length})`} />
            <CardBody className="pt-3">
              <ul className="divide-y divide-slate-100 dark:divide-ink-800">{data.members.map(m => (
                <li key={m.id} className={`flex flex-wrap items-center gap-3 py-3 ${m.active ? '' : 'opacity-60'}`}>
                  <Avatar name={m.name || m.email} />
                  <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2 truncate font-medium">{m.name} {m.you && <span className="text-xs text-slate-400">(you)</span>}{!m.active && <Badge tone="warning">Access paused</Badge>}</div>
                    <div className="truncate text-xs text-slate-500">{m.email} · {m.last_login_at ? <Ago ts={m.last_login_at} prefix="active " /> : 'never signed in'}</div>
                    <TitleEdit value={m.title} editable={me.can.manage_team} onSave={t => saveTitle(m.id, t)} /></div>
                  {me.can.manage_team && !m.you && (
                    <label className="flex items-center gap-2 text-xs text-slate-500" title={m.active ? 'Pause access' : 'Resume access'}>
                      <button type="button" role="switch" aria-checked={m.active} aria-label={`${m.name || m.email} can sign in`} onClick={() => setActive(m.id, m.name || m.email, !m.active)}
                        className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors ${m.active ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-ink-600'}`}>
                        <span className={`absolute top-0.5 size-4 rounded-full bg-white shadow transition-transform ${m.active ? 'translate-x-4.5' : 'translate-x-0.5'}`} /></button>
                      {m.active ? 'Active' : 'Paused'}</label>)}
                  {me.can.manage_team && !m.you ? (
                    <Select aria-label="Role" className="w-40 py-1.5 text-[13px]" value={m.role} onChange={e => changeRole(m.id, e.target.value)}>{data.roles.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}</Select>
                  ) : <Badge tone={m.role === 'owner' ? 'violet' : 'neutral'}>{m.role_label}</Badge>}
                  {me.can.manage_team && !m.you && <button aria-label={`Remove ${m.name}`} onClick={() => remove(m.id, m.name || m.email)} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600 dark:hover:bg-ink-800"><Trash2 className="size-4" /></button>}
                </li>))}</ul>
            </CardBody>
          </Card>
          {data.invites.length > 0 && <Card><CardHeader title="Pending invites" /><CardBody className="pt-3"><ul className="divide-y divide-slate-100 dark:divide-ink-800">{data.invites.map(i => (
            <li key={i.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm"><Mail className="size-4 text-slate-400" /><span className="min-w-0 flex-1">{i.email} <span className="text-slate-500">· {i.role_label}{i.title ? ` · ${i.title}` : ''}</span>
                {i.expired ? <Badge tone="warning" className="ml-2">Link expired</Badge> : <span className="ml-2 text-xs text-slate-400">expires {new Date(i.expires_at * 1000).toLocaleDateString()}</span>}</span>
              <Button size="sm" icon={<RefreshCw />} onClick={() => renew(i.id)}>New link</Button>
              <Button size="sm" variant="ghost" onClick={() => revoke(i.id)}>Revoke</Button></li>))}</ul></CardBody></Card>}
        </div>
        <div className="space-y-5">
          {me.can.manage_team ? (
            <Card><CardHeader title="Invite someone" description="We create a private link; send it by email or chat. It works once and expires in 7 days." /><CardBody className="space-y-3">
              <Field label="Email" htmlFor="inv-email"><Input id="inv-email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="sales.manager@company.com" /></Field>
              <Field label="Role" htmlFor="inv-role" hint={ROLE_HELP[role]}><Select id="inv-role" value={role} onChange={e => setRole(e.target.value)}>{data.roles.filter(r => r.id !== 'owner' || me.role === 'owner').map(r => <option key={r.id} value={r.id}>{r.label}</option>)}</Select></Field>
              <Field label="Job title (optional)" htmlFor="inv-title"><Input id="inv-title" value={title} onChange={e => setTitle(e.target.value)} placeholder="Sales Manager" /></Field>
              <Button variant="primary" className="w-full" disabled={!email} loading={busy} onClick={invite} icon={<UserPlus />}>Create invite link</Button>
              {link && <Alert tone="success" title="Invite link (copied)"><span className="break-all text-xs">{link}</span> <div className="mt-2"><LinkActions url={link} label="Copy" copied="Invite link copied" subject="Join our team on TalentLoop" message="You're invited to join our hiring workspace on TalentLoop. Accept here:" /></div></Alert>}
            </CardBody></Card>
          ) : <Alert tone="info">Only owners and admins can invite people or change roles.</Alert>}
          <Card><CardHeader title="Roles" /><CardBody className="space-y-2 pt-3 text-sm">{data.roles.map(r => <div key={r.id}><b>{r.label}</b><p className="text-xs text-slate-500 dark:text-slate-400">{ROLE_HELP[r.id]}</p></div>)}</CardBody></Card>
        </div>
      </div>
    </>
  )
}

function TitleEdit({ value, editable, onSave }: { value: string; editable: boolean; onSave: (v: string) => void }) {
  const [edit, setEdit] = useState(false), [v, setV] = useState(value)
  if (!edit) return (
    <div className="mt-0.5 flex items-center gap-1 text-xs text-slate-600 dark:text-slate-300">{value || <span className="text-slate-400">{editable ? 'No job title' : ''}</span>}
      {editable && <button aria-label="Edit job title" onClick={() => { setV(value); setEdit(true) }} className="rounded p-0.5 text-slate-400 hover:text-slate-700"><Pencil className="size-3" /></button>}</div>)
  return (
    <form className="mt-1 flex items-center gap-1" onSubmit={e => { e.preventDefault(); onSave(v.trim()); setEdit(false) }}>
      <Input aria-label="Job title" autoFocus className="h-7 max-w-56 py-1 text-xs" value={v} onChange={e => setV(e.target.value)} placeholder="e.g. Sales Manager" />
      <button type="submit" aria-label="Save title" className="rounded p-1 text-emerald-600 hover:bg-emerald-50"><Check className="size-4" /></button>
      <button type="button" aria-label="Cancel" onClick={() => setEdit(false)} className="rounded p-1 text-slate-400 hover:bg-slate-100"><X className="size-4" /></button>
    </form>)
}
