// Platform console: companies. The list, and one company with everything in it: profile, people, jobs, candidates,
// interviews, messages and audit log, with the actions a platform admin needs (edit, disable, delete, manage people).
import { Ban, CircleCheck, Save, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Field, Input, Modal, Select, Stat, Switch, Textarea, toast } from '../../components/ui'
import { Ago, ErrorBox, Loading, Tabs, useApi } from '../../components/kit'
import { HBarChart } from '../../components/charts'
import { ask } from '../../components/dialogs'
import { api } from '../../lib/api'
import { useLocation, navigate } from '../../lib/router'
import { Audit, Candidates, Interviews, Jobs, Outbox } from './data'
import { FilterBar, Head, SearchBox, Table, go, label } from './parts'

interface OrgRow { id: string; name: string; slug: string; created_at: number; disabled: boolean; owner: string; members: number; jobs: number; open_jobs: number; candidates: number; applications: number; interviews: number; ai_calls: number; last_activity?: number }

export function Companies() {
  const { data } = useApi<OrgRow[]>('/api/admin/orgs')
  const [q, setQ] = useState(''), [st, setSt] = useState('')
  const rows = (data || []).filter(o => (!q || `${o.name} ${o.owner} ${o.slug}`.toLowerCase().includes(q.toLowerCase())) && (!st || (st === 'disabled') === o.disabled))
  return (<>
    <Head title="Companies" sub="Every company on TalentLoop. Open one to see and manage everything in it." />
    <FilterBar>
      <SearchBox value={q} onChange={setQ} placeholder="Company, owner or careers address" />
      <Select aria-label="Status" className="w-full sm:w-40" value={st} onChange={e => setSt(e.target.value)}><option value="">All</option><option value="enabled">Enabled</option><option value="disabled">Disabled</option></Select>
    </FilterBar>
    <Table rows={data ? rows : null} onOpen={o => go(`/admin/companies/${o.id}`)} empty="No companies match." cols={[
      { h: 'Company', cell: o => <><div className="font-semibold">{o.name} {o.disabled && <Badge tone="danger">Disabled</Badge>}</div><div className="text-xs text-slate-500">/{o.slug} · since <Ago ts={o.created_at} /></div></> },
      { h: 'Owner', cell: o => <span className="text-slate-600 dark:text-slate-300">{o.owner || '-'}</span> },
      { h: 'People', cell: o => o.members, className: 'tabular-nums' },
      { h: 'Jobs', cell: o => `${o.jobs} (${o.open_jobs} open)`, className: 'whitespace-nowrap tabular-nums' },
      { h: 'Candidates', cell: o => o.candidates, className: 'tabular-nums' },
      { h: 'Interviews', cell: o => o.interviews, className: 'tabular-nums' },
      { h: 'AI requests', cell: o => o.ai_calls, className: 'tabular-nums' },
      { h: 'Last active', cell: o => <Ago ts={o.last_activity} />, className: 'whitespace-nowrap text-xs text-slate-500' },
    ]} />
  </>)
}

interface Member { id: string; user_id: string; name: string; email: string; role: string; role_label: string; title: string; active: boolean; joined_at: number; last_login_at: number | null; disabled: boolean; email_verified: boolean }
interface OrgFull {
  id: string; name: string; slug: string; disabled: boolean; created_at: number; last_activity: number | null
  settings: { about: string; website: string; industry: string; size: string; country: string; timezone: string; logo_url: string; careers_enabled: boolean }
  members: Member[]; invites: { id: string; email: string; role_label: string; created_at: number; expires_at: number }[]
  counts: Record<'jobs' | 'open_jobs' | 'candidates' | 'sample_candidates' | 'applications' | 'interviews' | 'messages' | 'ai_calls' | 'ai_calls_30d', number>
  stages: Record<string, number>
}
type Tab = 'overview' | 'people' | 'jobs' | 'candidates' | 'interviews' | 'messages' | 'audit' | 'profile'
const ROLES = [['owner', 'Owner'], ['admin', 'Admin'], ['recruiter', 'Recruiter (HR)'], ['hiring_manager', 'Hiring manager'], ['viewer', 'Viewer']]

export function Company({ id }: { id: string }) {
  const { query } = useLocation()
  const { data: o, error, reload } = useApi<OrgFull>(`/api/console/orgs/${id}`)
  const [tab, setTabState] = useState<Tab>((query.get('tab') as Tab) || 'overview')
  const setTab = (t: Tab) => { setTabState(t); navigate(`/admin/companies/${id}?tab=${t}`, { replace: true, keepScroll: true }) }
  const [del, setDel] = useState(false), [typed, setTyped] = useState('')
  if (error) return <ErrorBox error={error} retry={reload} />
  if (!o) return <Loading />
  async function toggle() {
    if (!await ask(o!.disabled ? `Enable ${o!.name}? Its people can sign in again.` : `Disable ${o!.name}? Nobody in it can sign in or use it until you enable it again. Nothing is deleted.`, { confirm: o!.disabled ? 'Enable' : 'Disable' })) return
    try { await api(`/api/console/orgs/${id}`, { method: 'PATCH', json: { disabled: !o!.disabled } }); toast('Updated'); reload() } catch (e: any) { toast(e.message) }
  }
  async function remove() {
    try { const r = await api(`/api/console/orgs/${id}`, { method: 'DELETE', json: { confirm: typed } }); toast(`${o!.name} deleted with ${r.candidates} candidates`); navigate('/admin/companies') } catch (e: any) { toast(e.message) }
  }
  const c = o.counts
  return (<>
    <button type="button" className="mb-2 text-sm text-slate-500 hover:underline" onClick={() => go('/admin/companies')}>← All companies</button>
    <Head title={<span className="flex flex-wrap items-center gap-2">{o.name} {o.disabled ? <Badge tone="danger">Disabled</Badge> : <Badge tone="success">Active</Badge>}</span>}
      sub={<>/{o.slug} · created <Ago ts={o.created_at} /> · last active <Ago ts={o.last_activity} /></>}>
      <Button icon={o.disabled ? <CircleCheck /> : <Ban />} onClick={toggle}>{o.disabled ? 'Enable company' : 'Disable company'}</Button>
      <Button variant="danger" icon={<Trash2 />} onClick={() => { setTyped(''); setDel(true) }}>Delete</Button>
    </Head>
    <Tabs className="mb-5" value={tab} onChange={setTab} tabs={[
      { id: 'overview', label: 'Overview' }, { id: 'people', label: 'People', count: o.members.length }, { id: 'jobs', label: 'Jobs', count: c.jobs },
      { id: 'candidates', label: 'Candidates', count: c.candidates }, { id: 'interviews', label: 'AI interviews', count: c.interviews },
      { id: 'messages', label: 'Outbox', count: c.messages }, { id: 'audit', label: 'Audit log' }, { id: 'profile', label: 'Company profile' }]} />
    {tab === 'overview' && <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="People" value={o.members.length} sub={`${o.invites.length} invite(s) pending`} />
        <Stat label="Jobs" value={c.jobs} sub={`${c.open_jobs} open`} />
        <Stat label="Candidates" value={c.candidates} sub={c.sample_candidates ? `${c.sample_candidates} of them sample` : 'no sample data'} />
        <Stat label="Applications" value={c.applications} />
        <Stat label="AI interviews" value={c.interviews} />
        <Stat label="Messages" value={c.messages} />
        <Stat label="AI requests" value={c.ai_calls} sub={`${c.ai_calls_30d} in 30 days`} />
        <Stat label="Careers page" value={o.settings.careers_enabled ? 'On' : 'Off'} sub={<a className="text-brand-600 hover:underline dark:text-brand-300" href={`/careers/${o.slug}`} target="_blank" rel="noopener">/careers/{o.slug}</a>} />
      </div>
      <Card className="mt-4"><CardHeader title="Where applications stand" /><CardBody>
        <HBarChart valueLabel="Applications" rows={Object.entries(o.stages).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ key: k, label: label(k), value: n }))} empty="No applications yet." />
      </CardBody></Card>
    </>}
    {tab === 'people' && <People o={o} reload={reload} />}
    {tab === 'jobs' && <Jobs org={id} />}
    {tab === 'candidates' && <Candidates org={id} />}
    {tab === 'interviews' && <Interviews org={id} />}
    {tab === 'messages' && <Outbox org={id} />}
    {tab === 'audit' && <Audit org={id} />}
    {tab === 'profile' && <Profile o={o} reload={reload} />}
    <Modal open={del} onOpenChange={setDel} title={`Delete ${o.name}?`} description="Every job, candidate, resume, interview, recording, message and audit entry of this company is deleted for good. People's accounts stay. This cannot be undone."
      footer={<><Button onClick={() => setDel(false)}>Keep it</Button><Button variant="danger" disabled={typed !== o.name} onClick={remove}>Delete for good</Button></>}>
      <Field className="mt-4" label={<>Type <b>{o.name}</b> to confirm</>} htmlFor="del-name"><Input id="del-name" value={typed} onChange={e => setTyped(e.target.value)} autoComplete="off" /></Field>
    </Modal>
  </>)
}

function People({ o, reload }: { o: OrgFull; reload: () => void }) {
  async function patch(m: Member, body: Record<string, unknown>, q: string) {
    if (!await ask(q, { danger: body.active === false })) return
    try { await api(`/api/console/memberships/${m.id}`, { method: 'PATCH', json: body }); toast('Updated'); reload() } catch (e: any) { toast(e.message) }
  }
  async function remove(m: Member) {
    if (!await ask(`Remove ${m.email} from ${o.name}? They lose access to it at once. Their account stays.`, { confirm: 'Remove' })) return
    try { await api(`/api/console/memberships/${m.id}`, { method: 'DELETE' }); toast('Removed'); reload() } catch (e: any) { toast(e.message) }
  }
  return (<>
    <Table rows={o.members} onOpen={m => go(`/admin/people/${m.user_id}`)} cols={[
      { h: 'Person', cell: m => <><div className="font-semibold">{m.name || m.email} {!m.email_verified && <Badge tone="warning">Email not confirmed</Badge>} {m.disabled && <Badge tone="danger">Account disabled</Badge>}</div><div className="text-xs text-slate-500">{m.email}{m.title ? ` · ${m.title}` : ''}</div></> },
      { h: 'Role', cell: m => <div onClick={e => e.stopPropagation()}><Select aria-label={`Role of ${m.email}`} className="w-44 py-1.5 text-[13px]" value={m.role}
          onChange={e => patch(m, { role: e.target.value }, `Change ${m.email}'s role in ${o.name} to ${ROLES.find(r => r[0] === e.target.value)?.[1]}?`)}>{ROLES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></div> },
      { h: 'Access', cell: m => m.active ? <Badge tone="success">Active</Badge> : <Badge tone="warning">Paused</Badge> },
      { h: 'Last sign-in', cell: m => <Ago ts={m.last_login_at} />, className: 'whitespace-nowrap text-xs text-slate-500' },
      { h: '', className: 'whitespace-nowrap text-right', cell: m => <div onClick={e => e.stopPropagation()} className="flex justify-end gap-1">
          <Button size="sm" variant="ghost" onClick={() => patch(m, { active: !m.active }, m.active ? `Pause ${m.email}'s access to ${o.name}? They are signed out of it now.` : `Restore ${m.email}'s access to ${o.name}?`)}>{m.active ? 'Pause' : 'Restore'}</Button>
          <Button size="sm" variant="ghost" className="text-red-600" onClick={() => remove(m)}>Remove</Button></div> },
    ]} />
    {o.invites.length > 0 && <Card className="mt-4"><CardHeader title="Pending invites" /><CardBody><ul className="space-y-1 text-sm">{o.invites.map(i => <li key={i.id} className="flex justify-between gap-2"><span>{i.email} · {i.role_label}</span><span className="text-xs text-slate-500">sent <Ago ts={i.created_at} /></span></li>)}</ul></CardBody></Card>}
  </>)
}

function Profile({ o, reload }: { o: OrgFull; reload: () => void }) {
  const init = { name: o.name, slug: o.slug, ...o.settings }
  const [f, setF] = useState(init), [busy, setBusy] = useState(false)
  useEffect(() => setF({ name: o.name, slug: o.slug, ...o.settings }), [o])   // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })
  async function save() {
    if (!await ask(`Save changes to ${o.name}'s profile? The company sees them at once.`, { confirm: 'Save', danger: false })) return
    setBusy(true)
    try { await api(`/api/console/orgs/${o.id}`, { method: 'PATCH', json: f }); toast('Saved'); reload() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  const dirty = JSON.stringify(f) !== JSON.stringify(init)
  return (
    <Card><CardBody className="grid gap-4 md:grid-cols-2">
      <Field label="Company name" htmlFor="o-name"><Input id="o-name" value={f.name} onChange={set('name')} /></Field>
      <Field label="Careers address" htmlFor="o-slug" hint={`/careers/${f.slug}. Changing it breaks links already shared.`}><Input id="o-slug" value={f.slug} onChange={set('slug')} /></Field>
      <Field label="Website" htmlFor="o-web"><Input id="o-web" value={f.website} onChange={set('website')} /></Field>
      <Field label="Industry" htmlFor="o-ind"><Input id="o-ind" value={f.industry} onChange={set('industry')} /></Field>
      <Field label="Size" htmlFor="o-size"><Input id="o-size" value={f.size} onChange={set('size')} /></Field>
      <Field label="Country" htmlFor="o-country"><Input id="o-country" value={f.country} onChange={set('country')} /></Field>
      <Field label="Time zone" htmlFor="o-tz"><Input id="o-tz" value={f.timezone} onChange={set('timezone')} /></Field>
      <Field label="Logo URL" htmlFor="o-logo"><Input id="o-logo" value={f.logo_url} onChange={set('logo_url')} /></Field>
      <Field className="md:col-span-2" label="About" htmlFor="o-about"><Textarea id="o-about" rows={4} value={f.about} onChange={set('about')} /></Field>
      <Switch id="o-careers" checked={!!f.careers_enabled} onChange={v => setF({ ...f, careers_enabled: v })} label="Careers page is public" />
      <div className="flex items-center justify-end gap-2 md:col-span-2">
        {dirty && <Button onClick={() => setF(init)}>Discard</Button>}
        <Button variant="primary" icon={<Save />} loading={busy} disabled={!dirty} onClick={save}>Save changes</Button></div>
      {o.disabled && <Alert className="md:col-span-2" tone="warning">This company is disabled: its people can't sign in.</Alert>}
    </CardBody></Card>
  )
}
