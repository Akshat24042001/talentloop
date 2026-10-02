// Your account: who you are in this company, how the app looks, your profile, password and companies.
// Company-wide settings live in Settings (owners and admins only).
import { Check, KeyRound, Monitor, Moon, Save, ShieldCheck, Sun } from 'lucide-react'
import { useState } from 'react'
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, cn, toast } from '../components/ui'
import { Avatar, PageHeader } from '../components/kit'
import { api } from '../lib/api'
import { ROLE_CAN, ROLE_HELP } from '../lib/roles'
import { useMe, useSession } from '../lib/session'
import { useTheme, type Theme } from '../lib/theme'

const THEMES: { id: Theme; label: string; icon: typeof Sun; hint: string }[] = [
  { id: 'system', label: 'System', icon: Monitor, hint: 'Follows your device' },
  { id: 'light', label: 'Light', icon: Sun, hint: 'Always light' },
  { id: 'dark', label: 'Dark', icon: Moon, hint: 'Always dark' },
]

export default function Account() {
  const me = useMe()
  const { setMe } = useSession()
  const [theme, setTheme] = useTheme()
  const [name, setName] = useState(me.user.name), [cur, setCur] = useState(''), [nw, setNw] = useState('')
  const mine = me.memberships.find(m => m.org_id === me.org?.id)
  async function saveName() { try { setMe(await api('/api/auth/profile', { method: 'PATCH', json: { name } })); toast('Saved') } catch (e: any) { toast(e.message) } }
  async function savePw() { try { await api('/api/auth/password', { json: { current: cur, new: nw } }); setCur(''); setNw(''); toast('Password changed. Other devices were signed out.') } catch (e: any) { toast(e.message) } }
  return (
    <>
      <PageHeader title="Your account" description="Who you are here, how TalentLoop looks for you, and your sign-in." />
      <div className="grid max-w-4xl gap-5">
        <Card><CardBody className="flex flex-wrap items-start gap-4">
          <Avatar name={me.user.name || me.user.email} size="lg" />
          <div className="min-w-0 flex-1">
            <div className="text-lg font-semibold">{me.user.name || me.user.email}</div>
            <div className="text-sm text-slate-500 dark:text-slate-400">{me.user.email}</div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {me.role && <Badge tone="brand">{me.role_label}</Badge>}
              {me.org && <span className="text-sm text-slate-600 dark:text-slate-300">at <b>{me.org.name}</b>{mine?.title ? ` · ${mine.title}` : ''}</span>}
              {me.platform_admin && <Badge tone="warning" icon={<ShieldCheck />}>Platform admin</Badge>}
            </div>
            {me.role && <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{ROLE_HELP[me.role]}</p>}
            {me.role && <ul className="mt-3 flex flex-wrap gap-1.5">{(ROLE_CAN[me.role] || []).map(x => (
              <li key={x} className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200"><Check className="size-3" />{x}</li>))}</ul>}
            {me.platform_admin && <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">As platform admin you also see every company, system status and sample data in Platform admin.</p>}
            {me.role && !me.can.manage_team && <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">Need more access? Ask an owner or admin of {me.org?.name} to change your role on the Team page.</p>}
          </div>
        </CardBody></Card>

        <Card><CardHeader title="Appearance" description="Saved in this browser." /><CardBody>
          <div role="radiogroup" aria-label="Theme" className="grid gap-2 sm:grid-cols-3">{THEMES.map(t => (
            <button key={t.id} type="button" role="radio" aria-checked={theme === t.id} onClick={() => setTheme(t.id)}
              className={cn('flex items-center gap-3 rounded-xl p-3 text-left ring-1 transition-colors',
                theme === t.id ? 'bg-brand-50 ring-2 ring-brand-500 dark:bg-brand-500/15' : 'ring-slate-200 hover:bg-slate-50 dark:ring-ink-700 dark:hover:bg-ink-800')}>
              <span className={cn('grid size-9 place-items-center rounded-lg', theme === t.id ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-600 dark:bg-ink-800 dark:text-slate-300')}><t.icon className="size-4" /></span>
              <span><span className="block text-sm font-semibold">{t.label}</span><span className="block text-xs text-slate-500 dark:text-slate-400">{t.hint}</span></span>
            </button>))}</div>
        </CardBody></Card>

        <div className="grid gap-5 md:grid-cols-2">
          <Card><CardHeader title="Profile" /><CardBody className="space-y-3">
            <Field label="Name" htmlFor="a-name"><Input id="a-name" value={name} onChange={e => setName(e.target.value)} /></Field>
            <Field label="Email" hint="Your sign-in. It can't be changed here."><Input value={me.user.email} disabled /></Field>
            <div className="flex justify-end"><Button variant="primary" disabled={!name.trim() || name === me.user.name} onClick={saveName} icon={<Save />}>Save</Button></div>
          </CardBody></Card>
          <Card><CardHeader title="Password" /><CardBody className="space-y-3">
            <Field label="Current password" htmlFor="a-cur"><Input id="a-cur" type="password" autoComplete="current-password" value={cur} onChange={e => setCur(e.target.value)} /></Field>
            <Field label="New password" htmlFor="a-new" hint="At least 8 characters. Other devices are signed out."><Input id="a-new" type="password" autoComplete="new-password" value={nw} onChange={e => setNw(e.target.value)} /></Field>
            <div className="flex justify-end"><Button variant="primary" disabled={!cur || nw.length < 8} onClick={savePw} icon={<KeyRound />}>Change password</Button></div>
          </CardBody></Card>
        </div>

        <Card><CardHeader title="Your companies" description="Switch between them from the menu at the top of the sidebar." /><CardBody className="pt-1">
          <ul className="divide-y divide-slate-100 dark:divide-ink-800">{me.memberships.map(m => (
            <li key={m.org_id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
              <span><span className="font-medium">{m.name}</span>{m.title ? <span className="text-slate-500 dark:text-slate-400"> · {m.title}</span> : null}
                {m.org_id === me.org?.id && <span className="ml-2 text-xs text-emerald-700 dark:text-emerald-300">current</span>}</span>
              <Badge>{m.role_label || m.role}</Badge>
            </li>))}</ul>
        </CardBody></Card>
      </div>
    </>
  )
}
