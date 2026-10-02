import { Copy, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button, Card, CardBody, CardHeader, Field, Input, Select, Switch, Textarea, copyText, toast } from '../components/ui'
import { Loading, PageHeader, Tabs, TagInput, useApi } from '../components/kit'
import { api } from '../lib/api'
import { navigate, useLocation } from '../lib/router'
import { useMe, useSession } from '../lib/session'
import HiringSettings from './HiringSettings'

type Tab = 'company' | 'careers' | 'hiring' | 'matching' | 'data'
const W_LABEL: Record<string, string> = { skills: 'Skills', experience: 'Experience', relevance: 'Keyword relevance', location: 'Location', logistics: 'Notice & salary' }

export default function Settings() {
  const me = useMe()
  const { query } = useLocation()
  const q = query.get('tab')
  useEffect(() => { if (q === 'account') navigate('/app/account', { replace: true }); else if (q === 'system') navigate(me.platform_admin ? '/admin' : '/app/settings', { replace: true }) }, [q])
  const tab = (q as Tab) || 'company'
  const { data: orgInfo, reload: reloadOrg } = useApi<{ has_sample_data: boolean }>('/api/org')
  const samples = !!orgInfo?.has_sample_data
  const setTab = (t: Tab) => navigate(`/app/settings?tab=${t}`, { replace: true, keepScroll: true })
  const tabs = [...(me.can.manage_team ? [{ id: 'company' as Tab, label: 'Company' }, { id: 'careers' as Tab, label: 'Careers page' }, { id: 'hiring' as Tab, label: 'Hiring' }, { id: 'matching' as Tab, label: 'Matching & AI' }, ...(samples ? [{ id: 'data' as Tab, label: 'Sample data' }] : [])] : [])]
  return (
    <>
      <PageHeader title="Settings" description={me.org?.name} />
      <Tabs className="mb-5" tabs={tabs} value={tab} onChange={setTab} />
      {['company', 'careers', 'matching'].includes(tab) && me.can.manage_team && <OrgSettings tab={tab} />}
      {tab === 'hiring' && me.can.manage_team && <HiringSettings />}
      {tab === 'data' && me.can.manage_team && <DataTab onDone={() => { reloadOrg(); setTab('company') }} />}
    </>
  )
}

function OrgSettings({ tab }: { tab: string }) {
  const { refresh } = useSession()
  const [org, setOrg] = useState<{ name: string; slug: string; settings: Record<string, any> } | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api('/api/org').then(setOrg) }, [])
  if (!org) return <Loading />
  const s = org.settings
  const set = (k: string, v: unknown) => setOrg(o => ({ ...o!, settings: { ...o!.settings, [k]: v } }))
  async function save() {
    setBusy(true)
    try { const r = await api('/api/org', { method: 'PATCH', json: { name: org!.name, slug: org!.slug, settings: org!.settings } }); setOrg(r); await refresh(); toast('Settings saved') } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  const careers = `${location.origin}/careers/${org.slug}`
  return (
    <Card className="max-w-3xl">
      <CardBody className="space-y-5">
        {tab === 'company' && <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Company name" htmlFor="s-name"><Input id="s-name" value={org.name} onChange={e => setOrg({ ...org, name: e.target.value })} /></Field>
            <Field label="Website" htmlFor="s-web"><Input id="s-web" value={s.website || ''} onChange={e => set('website', e.target.value)} placeholder="https://" /></Field>
            <Field label="Industry" htmlFor="s-ind"><Input id="s-ind" value={s.industry || ''} onChange={e => set('industry', e.target.value)} /></Field>
            <Field label="Company size" htmlFor="s-size"><Select id="s-size" value={s.size || ''} onChange={e => set('size', e.target.value)}><option value="">Select…</option>{['1-10', '11-50', '51-200', '201-500', '501-1000', '1000+'].map(x => <option key={x}>{x}</option>)}</Select></Field>
            <Field label="Country" htmlFor="s-country"><Input id="s-country" value={s.country || ''} onChange={e => set('country', e.target.value)} /></Field>
            <Field label="Default currency" htmlFor="s-cur"><Select id="s-cur" value={s.default_currency || 'INR'} onChange={e => set('default_currency', e.target.value)}>{['INR', 'USD', 'EUR', 'GBP', 'AED', 'SGD', 'AUD', 'CAD'].map(x => <option key={x}>{x}</option>)}</Select></Field>
          </div>
          <Field label="About the company" htmlFor="s-about" hint="Shown on your careers page and at the end of every job description."><Textarea id="s-about" value={s.about || ''} onChange={e => set('about', e.target.value)} /></Field>
          <Field label="Benefits you offer" htmlFor="s-ben" hint="Your own list, picked per job in the job description editor. Removing one here doesn't change jobs that already list it.">
            <TagInput id="s-ben" value={s.benefits || []} onChange={v => set('benefits', v)} placeholder="Type a benefit and press Enter" /></Field>
          <Field label="Equal opportunity statement" htmlFor="s-eeo"><Textarea id="s-eeo" className="min-h-0" rows={2} value={s.eeo_statement || ''} onChange={e => set('eeo_statement', e.target.value)} /></Field>
        </>}
        {tab === 'careers' && <>
          <Switch id="s-careers" checked={s.careers_enabled !== false} onChange={v => set('careers_enabled', v)} label="Public careers page" description="Lists your open jobs and lets candidates apply or join your talent pool." />
          <Field label="Careers page address" htmlFor="s-slug" hint={careers}><div className="flex gap-2"><Input id="s-slug" value={org.slug} onChange={e => setOrg({ ...org, slug: e.target.value })} /><Button icon={<Copy />} onClick={() => copyText(careers, 'Link copied')}>Copy</Button></div></Field>
          <Field label="Headline" htmlFor="s-head"><Input id="s-head" value={s.careers_headline || ''} onChange={e => set('careers_headline', e.target.value)} placeholder="Build the future of payments with us" /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Logo URL" htmlFor="s-logo"><Input id="s-logo" value={s.logo_url || ''} onChange={e => set('logo_url', e.target.value)} placeholder="https://…/logo.png" /></Field>
            <Field label="Brand color" htmlFor="s-color"><div className="flex gap-2"><input type="color" aria-label="Pick color" value={s.brand_color || '#2848e6'} onChange={e => set('brand_color', e.target.value)} className="h-10 w-12 rounded-lg" /><Input id="s-color" value={s.brand_color || ''} onChange={e => set('brand_color', e.target.value)} /></div></Field>
          </div>
          <Button href={`/careers/${org.slug}`} target="_blank">Preview careers page</Button>
        </>}
        {tab === 'matching' && <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Default shortlist size per job" htmlFor="s-topn" hint="New jobs start with this. Each job can override it."><Input id="s-topn" type="number" min={1} max={50} value={s.match_top_n} onChange={e => set('match_top_n', +e.target.value)} /></Field>
            <Field label="Best-fit minimum score" htmlFor="s-fit" hint="A candidate's Best-fit jobs tab lists only open jobs they score at least this on (0 to 100). Below it, no job is shown."><Input id="s-fit" type="number" min={0} max={100} value={s.best_fit_min_score ?? 55} onChange={e => set('best_fit_min_score', +e.target.value)} /></Field>
            <Field label="AI reports per run (cost cap)" htmlFor="s-budget" hint="The most AI match reports one click can write. 0 turns AI reports off."><Input id="s-budget" type="number" min={0} max={500} value={s.ai_reports_per_run} onChange={e => set('ai_reports_per_run', +e.target.value)} /></Field>
          </div>
          <div>
            <div className="text-sm font-semibold">Ranking weights</div>
            <p className="text-xs text-slate-500 dark:text-slate-400">How much each signal counts in the free first-stage ranking. They are relative to each other.</p>
            <div className="mt-3 space-y-3">{Object.keys(W_LABEL).map(k => (
              <label key={k} className="grid grid-cols-[150px_1fr_40px] items-center gap-3 text-sm"><span>{W_LABEL[k]}</span>
                <input type="range" min={0} max={60} value={s.match_weights?.[k] ?? 0} onChange={e => set('match_weights', { ...s.match_weights, [k]: +e.target.value })} className="accent-brand-600" />
                <span className="tabular text-right font-semibold">{s.match_weights?.[k] ?? 0}</span></label>))}</div>
          </div>
          <Field label="Delete interview data after (days)" htmlFor="s-ret" hint="0 keeps everything. Applies to AI interview recordings."><Input id="s-ret" type="number" min={0} value={s.retention_days || 0} onChange={e => set('retention_days', +e.target.value)} /></Field>
        </>}
        <div className="flex justify-end border-t border-slate-100 pt-4 dark:border-ink-800"><Button variant="primary" loading={busy} onClick={save} icon={<Save />}>Save</Button></div>
      </CardBody>
    </Card>
  )
}

function DataTab({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  async function clear() {
    if (!confirm('Remove all sample jobs and sample candidates? Your own data is kept.')) return
    setBusy(true)
    try { const r = await api('/api/demo/clear', { method: 'POST' }); toast(`Removed ${r.jobs} jobs and ${r.candidates} candidates`); onDone() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  return (
    <Card className="max-w-3xl"><CardHeader title="Sample data" description="This workspace still has sample jobs and resumes (tagged Sample). Remove them before you go live; your own jobs and candidates are kept." />
      <CardBody><Button variant="danger" loading={busy} onClick={clear}>Remove sample data</Button></CardBody></Card>
  )
}

