// Platform console: people (accounts). Every account on the platform, and one account with its companies, roles,
// devices and history, plus the fixes support needs: confirm email, reset password, sign out, disable, admin rights.
import { Ban, CircleCheck, KeyRound, LogOut, MailCheck, Save, ShieldCheck, ShieldOff, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Field, Input, Modal, Select, Stat, toast } from '../../components/ui'
import { Ago, ErrorBox, Loading, useApi } from '../../components/kit'
import { ask } from '../../components/dialogs'
import { api } from '../../lib/api'
import { useMe } from '../../lib/session'
import { Audit } from './data'
import { CompanyLink, FilterBar, Head, SearchBox, Table, go } from './parts'

interface UserRow { id: string; email: string; name: string; created_at: number; last_login_at?: number; login_count: number; disabled: boolean; platform_admin: boolean; email_verified?: boolean; memberships: { org: string; role_label: string }[] }

export function People() {
  const { data } = useApi<UserRow[]>('/api/admin/users')
  const [q, setQ] = useState(''), [f, setF] = useState('')
  const rows = (data || []).filter(u => (!q || `${u.name} ${u.email} ${u.memberships.map(m => m.org).join(' ')}`.toLowerCase().includes(q.toLowerCase()))
    && (!f || (f === 'unconfirmed' && u.email_verified === false) || (f === 'disabled' && u.disabled) || (f === 'admins' && u.platform_admin) || (f === 'never' && !u.last_login_at) || (f === 'nocompany' && !u.memberships.length)))
  return (<>
    <Head title="People" sub="Every account on the platform: company staff and platform admins. Open one to manage it." />
    <FilterBar>
      <SearchBox value={q} onChange={setQ} placeholder="Name, email or company" />
      <Select aria-label="Show" className="w-full sm:w-52" value={f} onChange={e => setF(e.target.value)}>
        <option value="">Everyone</option><option value="unconfirmed">Email not confirmed</option><option value="disabled">Disabled</option>
        <option value="admins">Platform admins</option><option value="never">Never signed in</option><option value="nocompany">Not in any company</option></Select>
    </FilterBar>
    <Table rows={data ? rows : null} onOpen={u => go(`/admin/people/${u.id}`)} empty="Nobody matches." cols={[
      { h: 'Person', cell: u => <><div className="font-semibold">{u.name || u.email} {u.platform_admin && <Badge tone="violet">Platform admin</Badge>} {u.email_verified === false && <Badge tone="warning">Email not confirmed</Badge>} {u.disabled && <Badge tone="danger">Disabled</Badge>}</div><div className="text-xs text-slate-500">{u.email}</div></> },
      { h: 'Companies', cell: u => <div className="text-xs">{u.memberships.length ? u.memberships.map((m, i) => <div key={i}>{m.org} <span className="text-slate-500">· {m.role_label}</span></div>) : <span className="text-slate-500">none</span>}</div> },
      { h: 'Sign-ins', cell: u => u.login_count, className: 'tabular-nums' },
      { h: 'Last sign-in', cell: u => u.last_login_at ? <Ago ts={u.last_login_at} /> : 'never', className: 'whitespace-nowrap text-xs text-slate-500' },
      { h: 'Joined', cell: u => <Ago ts={u.created_at} />, className: 'whitespace-nowrap text-xs text-slate-500' },
    ]} />
  </>)
}

interface UserFull {
  id: string; email: string; name: string; created_at: number; last_login_at: number | null; login_count: number; disabled: boolean; platform_admin: boolean; admin_from_env: boolean
  email_verified: boolean; email_verified_at: number | null; active_days: number
  memberships: { id: string; org_id: string; company: string; role: string; role_label: string; title: string; active: boolean; joined_at: number; only_owner?: boolean }[]
  sessions: { id: string; company: string; ip: string; device: string; created_at: number; last_seen_at: number | null; online: boolean }[]
}
const ROLES = [['owner', 'Owner'], ['admin', 'Admin'], ['recruiter', 'Recruiter (HR)'], ['hiring_manager', 'Hiring manager'], ['viewer', 'Viewer']]

export function Person({ id }: { id: string }) {
  const me = useMe()
  const { data: u, error, reload } = useApi<UserFull>(`/api/console/users/${id}`)
  const [f, setF] = useState({ name: '', email: '' }), [del, setDel] = useState(false), [typed, setTyped] = useState('')
  useEffect(() => { if (u) setF({ name: u.name, email: u.email }) }, [u])
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!u) return <Loading />
  const self = u.id === me.user.id
  async function patch(body: Record<string, unknown>, q: string, danger = true) {
    if (!await ask(q, { danger })) return
    try { await api(`/api/console/users/${id}`, { method: 'PATCH', json: body }); toast('Updated'); reload() } catch (e: any) { toast(e.message) }
  }
  async function post(path: string, q: string, done: string, danger = false) {
    if (!await ask(q, { danger })) return
    try { await api(`/api/console/users/${id}/${path}`, { method: 'POST' }); toast(done); reload() } catch (e: any) { toast(e.message) }
  }
  async function membership(mid: string, body: Record<string, unknown> | null, q: string) {
    if (!await ask(q)) return
    try { await api(`/api/console/memberships/${mid}`, body ? { method: 'PATCH', json: body } : { method: 'DELETE' }); toast('Updated'); reload() } catch (e: any) { toast(e.message) }
  }
  const online = u.sessions.some(s => s.online)
  return (<>
    <button type="button" className="mb-2 text-sm text-slate-500 hover:underline" onClick={() => go('/admin/people')}>← All people</button>
    <Head title={<span className="flex flex-wrap items-center gap-2">{u.name || u.email} {online && <Badge tone="success">Online now</Badge>} {u.platform_admin && <Badge tone="violet">Platform admin</Badge>} {u.disabled && <Badge tone="danger">Disabled</Badge>}</span>}
      sub={<>{u.email} · joined <Ago ts={u.created_at} /> · {u.email_verified ? <>email confirmed <Ago ts={u.email_verified_at} /></> : 'email NOT confirmed'}</>} />
    {self && <Alert className="mb-4" tone="info">This is your own account. You can't disable it or change your own admin rights here.</Alert>}
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Stat label="Sign-ins" value={u.login_count} sub={u.last_login_at ? <>last <Ago ts={u.last_login_at} /></> : 'never'} />
      <Stat label="Days active" value={u.active_days} sub="since tracking began" />
      <Stat label="Companies" value={u.memberships.length} />
      <Stat label="Signed-in devices" value={u.sessions.length} sub={online ? 'online now' : 'not online'} />
    </div>
    <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="space-y-4">
        <Card><CardHeader title="Companies and roles" /><CardBody>
          {u.memberships.length ? <ul className="divide-y divide-slate-100 dark:divide-ink-800">{u.memberships.map(m => (
            <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
              <div className="min-w-0"><CompanyLink id={m.org_id} name={m.company} /> {!m.active && <Badge tone="warning">Paused</Badge>} {m.only_owner && <Badge tone="violet">Only owner</Badge>}<div className="text-xs text-slate-500">joined <Ago ts={m.joined_at} />{m.title ? ` · ${m.title}` : ''}</div></div>
              <div className="flex items-center gap-1">
                <Select aria-label={`Role in ${m.company}`} className="w-44 py-1.5 text-[13px]" value={m.role} onChange={e => membership(m.id, { role: e.target.value }, `Change ${u.email}'s role in ${m.company} to ${ROLES.find(r => r[0] === e.target.value)?.[1]}?`)}>
                  {ROLES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>
                <Button size="sm" variant="ghost" onClick={() => membership(m.id, { active: !m.active }, m.active ? `Pause ${u.email}'s access to ${m.company}?` : `Restore ${u.email}'s access to ${m.company}?`)}>{m.active ? 'Pause' : 'Restore'}</Button>
                <Button size="sm" variant="ghost" className="text-red-600" onClick={() => membership(m.id, null, `Remove ${u.email} from ${m.company}? Their account stays.`)}>Remove</Button>
              </div></li>))}</ul> : <p className="text-sm text-slate-500">Not in any company.</p>}
        </CardBody></Card>
        <Card><CardHeader title="Signed-in devices" description="Each is a browser or API client that can act as this person until it signs out or expires." /><CardBody>
          {u.sessions.length ? <ul className="divide-y divide-slate-100 text-sm dark:divide-ink-800">{u.sessions.map(s => (
            <li key={s.id} className="flex flex-wrap justify-between gap-2 py-2"><div className="min-w-0"><div className="truncate">{s.device || 'Unknown device'}</div><div className="text-xs text-slate-500">{s.ip} · {s.company || 'no company'} · since <Ago ts={s.created_at} /></div></div>
              <span className="text-xs text-slate-500">{s.online ? <Badge tone="success">Online</Badge> : <>seen <Ago ts={s.last_seen_at} /></>}</span></li>))}</ul> : <p className="text-sm text-slate-500">Not signed in anywhere.</p>}
        </CardBody></Card>
        <div><h2 className="mb-2 font-semibold">What they did</h2><Audit user={id} /></div>
      </div>
      <div className="space-y-4">
        <Card><CardHeader title="Fix things" /><CardBody className="flex flex-col gap-2">
          {!u.email_verified && <Button icon={<MailCheck />} onClick={() => patch({ email_verified: true }, `Mark ${u.email} as confirmed without the emailed code? Only if you know they own this address.`, false)}>Mark email as confirmed</Button>}
          <Button icon={<KeyRound />} onClick={() => post('reset-password', `Email ${u.email} a password reset code? You never see or set their password.`, 'Reset code sent')}>Email a password reset code</Button>
          <Button icon={<LogOut />} disabled={!u.sessions.length} onClick={() => post('signout', `Sign ${u.email} out of all ${u.sessions.length} device(s)?`, 'Signed out everywhere', true)}>Sign out everywhere</Button>
          {!self && <Button icon={u.disabled ? <CircleCheck /> : <Ban />} variant={u.disabled ? 'secondary' : 'danger'} onClick={() => patch({ disabled: !u.disabled }, u.disabled ? `Enable ${u.email}? They can sign in again.` : `Disable ${u.email}? They are signed out everywhere and can't sign in. Nothing is deleted.`, !u.disabled)}>{u.disabled ? 'Enable account' : 'Disable account'}</Button>}
          {!self && <Button icon={u.platform_admin ? <ShieldOff /> : <ShieldCheck />} disabled={u.platform_admin && u.admin_from_env}
            onClick={() => patch({ platform_admin: !u.platform_admin }, u.platform_admin ? `Remove ${u.email}'s platform admin rights?` : `Make ${u.email} a platform admin? They will see and control every company on TalentLoop.`)}>
            {u.platform_admin ? 'Remove platform admin' : 'Make platform admin'}</Button>}
          {!self && <Button variant="ghost" className="text-red-600" icon={<Trash2 />} onClick={() => { setTyped(''); setDel(true) }}>Delete account</Button>}
          {u.platform_admin && u.admin_from_env && <p className="text-xs text-slate-500">Admin because this email is in PLATFORM_ADMIN_EMAILS on the server. Remove it there to take the rights away.</p>}
        </CardBody></Card>
        <Card><CardHeader title="Account details" /><CardBody className="space-y-3">
          <Field label="Name" htmlFor="u-name"><Input id="u-name" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Email" htmlFor="u-email" hint="Changing it means they must confirm the new address."><Input id="u-email" type="email" value={f.email} onChange={e => setF({ ...f, email: e.target.value })} /></Field>
          <Button variant="primary" icon={<Save />} disabled={f.name === u.name && f.email === u.email} onClick={() => patch(f, `Save the new account details for ${u.email}?`, false)}>Save</Button>
        </CardBody></Card>
      </div>
    </div>
    <Modal open={del} onOpenChange={setDel} title={`Delete ${u.email}?`} description="The account, its sign-ins and its company memberships are deleted for good. What they did stays in the audit log without their name."
      footer={<><Button onClick={() => setDel(false)}>Keep it</Button><Button variant="danger" disabled={typed.trim().toLowerCase() !== u.email} onClick={async () => {
        try { const r = await api(`/api/console/users/${id}`, { method: 'DELETE', json: { confirm: typed } }); toast(r.companies_deleted?.length ? `Account deleted, with ${r.companies_deleted.join(', ')}` : 'Account deleted'); go('/admin/people') } catch (e: any) { toast(e.message) } }}>Delete for good</Button></>}>
      {u.memberships.some(m => m.only_owner) ? <Alert className="mt-4" tone="danger" title="These companies are deleted too, with everything in them">
          They have no other owner: {u.memberships.filter(m => m.only_owner).map(m => m.company).join(', ')}. All their jobs, candidates, resumes, interviews, recordings and messages go, and their other members lose access.</Alert>
        : u.memberships.length > 0 && <Alert className="mt-4" tone="info">Their companies stay: each has another owner. This person just leaves them.</Alert>}
      <Field className="mt-4" label={<>Type <b>{u.email}</b> to confirm</>} htmlFor="del-email"><Input id="del-email" value={typed} onChange={e => setTyped(e.target.value)} autoComplete="off" /></Field>
    </Modal>
  </>)
}
