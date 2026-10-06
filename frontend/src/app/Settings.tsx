import { Copy, ImageIcon, Save, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button, Card, CardBody, CardHeader, Field, Input, Select, Switch, Textarea, copyText, toast } from '../components/ui'
import { Loading, PageHeader, Tabs, TagInput, useApi } from '../components/kit'
import { api } from '../lib/api'
import { navigate, useLocation } from '../lib/router'
import { useMe, useSession } from '../lib/session'
import { useHealth } from '../lib/health'
import HiringSettings from './HiringSettings'
import { ask } from '../components/dialogs'

type Tab = 'company' | 'careers' | 'hiring' | 'matching' | 'data'
const W_LABEL: Record<string, string> = { skills: 'Skills', experience: 'Experience', relevance: 'Keyword relevance', location: 'Location', logistics: 'Notice & salary' }

// The browser's list uses old names for some zones (Chrome lists Asia/Calcutta, not Asia/Kolkata, which is the server's
// default), so modern names are swapped in and the saved value is always an option: otherwise the picker shows "Select…".
const MODERN: Record<string, string> = { 'Asia/Calcutta': 'Asia/Kolkata', 'Asia/Katmandu': 'Asia/Kathmandu', 'Asia/Saigon': 'Asia/Ho_Chi_Minh', 'Asia/Rangoon': 'Asia/Yangon', 'Europe/Kiev': 'Europe/Kyiv' }
const TIMEZONES: string[] = (() => {
  let z: string[]
  try { z = (Intl as any).supportedValuesOf('timeZone') as string[] } catch { z = ['Asia/Kolkata', 'Asia/Dubai', 'Asia/Singapore', 'Europe/London', 'America/New_York', 'UTC'] }
  return [...new Set(z.map(x => MODERN[x] || x))].sort()
})()
const tzOptions = (v: string) => (TIMEZONES.includes(v) ? TIMEZONES : [v, ...TIMEZONES])

export default function Settings() {
  const me = useMe()
  const { query } = useLocation()
  const q = query.get('tab')
  useEffect(() => { if (q === 'account') navigate('/app/account', { replace: true }); else if (q === 'system') navigate(me.platform_admin ? '/admin' : '/app/settings', { replace: true }) }, [q])
  const tab = (q as Tab) || 'company'
  const { data: orgInfo, reload: reloadOrg } = useApi<{ has_sample_data: boolean }>('/api/org')
  const samples = !!orgInfo?.has_sample_data
  const dev = useHealth()?.production === false
  const setTab = (t: Tab) => navigate(`/app/settings?tab=${t}`, { replace: true, keepScroll: true })
  const tabs = [...(me.can.manage_team ? [{ id: 'company' as Tab, label: 'Company' }, { id: 'careers' as Tab, label: 'Careers page' }, { id: 'hiring' as Tab, label: 'Hiring' }, { id: 'matching' as Tab, label: 'Matching & AI' }, ...(samples || dev ? [{ id: 'data' as Tab, label: 'Sample data' }] : [])] : [])]
  return (
    <>
      <PageHeader title="Settings" description={me.org?.name} />
      <Tabs className="mb-5" tabs={tabs} value={tab} onChange={setTab} />
      {['company', 'careers', 'matching'].includes(tab) && me.can.manage_team && <OrgSettings tab={tab} />}
      {tab === 'hiring' && me.can.manage_team && <HiringSettings />}
      {tab === 'data' && me.can.manage_team && <DataTab samples={samples} onDone={reloadOrg} />}
    </>
  )
}

function OrgSettings({ tab }: { tab: string }) {
  const { refresh } = useSession()
  const [org, setOrg] = useState<{ name: string; slug: string; settings: Record<string, any> } | null>(null)
  const [busy, setBusy] = useState(false), [logoBusy, setLogoBusy] = useState(false)
  useEffect(() => { api('/api/org').then(setOrg) }, [])
  if (!org) return <Loading />
  const s = org.settings
  const set = (k: string, v: unknown) => setOrg(o => ({ ...o!, settings: { ...o!.settings, [k]: v } }))
  async function uploadLogo(f: File) {
    setLogoBusy(true)
    try { const fd = new FormData(); fd.append('file', f); const r = await api('/api/org/logo', { body: fd }); set('logo_url', r.logo_url); toast('Logo uploaded') } catch (e: any) { toast(e.message) }
    setLogoBusy(false)
  }
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
            <Field label="Time zone" htmlFor="s-tz" hint="Interview times in emails and reminders use it."><Select id="s-tz" value={s.timezone || 'Asia/Kolkata'} onChange={e => set('timezone', e.target.value)}>
              {tzOptions(s.timezone || 'Asia/Kolkata').map(z => <option key={z} value={z}>{z.replace(/_/g, ' ')}</option>)}</Select></Field>
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
            <Field label="Logo" hint="PNG, JPG or WebP, up to 2 MB. Shown on your careers page and candidate pages. Saved straight away.">
              <div className="flex items-center gap-3">
                <span className="grid size-16 shrink-0 place-items-center overflow-hidden rounded-xl bg-slate-50 ring-1 ring-slate-200 dark:bg-ink-850 dark:ring-ink-700">
                  {s.logo_url ? <img src={s.logo_url} alt="Company logo" className="max-h-14 max-w-14 object-contain" /> : <ImageIcon className="size-6 text-slate-400" />}</span>
                <div className="flex flex-wrap gap-2">
                  <label className="inline-flex"><span className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg bg-white px-3 text-sm font-semibold text-slate-800 shadow-sm ring-1 ring-inset ring-slate-200 hover:bg-slate-50 dark:bg-ink-850 dark:text-slate-100 dark:ring-ink-700 dark:hover:bg-ink-800">
                    <Upload className="size-4" />{logoBusy ? 'Uploading…' : s.logo_url ? 'Replace' : 'Upload logo'}</span>
                    <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" disabled={logoBusy} onChange={e => { const f = e.target.files?.[0]; if (f) uploadLogo(f); e.target.value = '' }} /></label>
                  {s.logo_url && <Button variant="ghost" onClick={() => set('logo_url', '')}>Remove</Button>}
                </div>
              </div>
              <details className="mt-2"><summary className="cursor-pointer text-xs font-medium text-slate-500 dark:text-slate-400">Or use an image link</summary>
                <Input className="mt-2" id="s-logo" aria-label="Logo URL" value={s.logo_url || ''} onChange={e => set('logo_url', e.target.value)} placeholder="https://…/logo.png" /></details>
            </Field>
            <Field label="Brand color" htmlFor="s-color"><div className="flex gap-2"><input type="color" aria-label="Pick color" value={s.brand_color || '#2848e6'} onChange={e => set('brand_color', e.target.value)} className="h-10 w-12 rounded-lg" /><Input id="s-color" value={s.brand_color || ''} onChange={e => set('brand_color', e.target.value)} /></div></Field>
          </div>
          <Button href={`/careers/${org.slug}`} target="_blank">Preview careers page</Button>
        </>}
        {tab === 'matching' && <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Default shortlist size per job" htmlFor="s-topn" hint="New jobs start with this. Each job can override it."><Input id="s-topn" type="number" min={1} max={50} value={s.match_top_n} onChange={e => set('match_top_n', +e.target.value)} /></Field>
            <Field label="Best-fit minimum score" htmlFor="s-fit" hint="A candidate's Best-fit jobs tab lists only open jobs they score at least this on (0 to 100). Below it, no job is shown."><Input id="s-fit" type="number" min={0} max={100} value={s.best_fit_min_score ?? 55} onChange={e => set('best_fit_min_score', +e.target.value)} /></Field>
            <div className="sm:col-span-2"><Switch id="s-lookup" checked={s.public_lookup !== false} onChange={v => set('public_lookup', v)} label="Look up public profiles in AI match reports"
              description="The report checks the links the candidate gave (website, GitHub) and public professional pages about them (a GitHub profile with their email, a web search when a search key is set on the server), and shows what it found with the evidence. Never their phone number or personal social media. Candidates are told on the application form." /></div>
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

function DataTab({ samples, onDone }: { samples: boolean; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  async function clear() {
    if (!await ask('Remove all sample jobs and sample candidates? Your own data is kept.')) return
    setBusy(true)
    try { const r = await api('/api/demo/clear', { method: 'POST' }); toast(`Removed ${r.jobs} jobs and ${r.candidates} candidates`); onDone() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  async function load() {
    setBusy(true)
    try { const r = await api('/api/demo/seed', { method: 'POST' }); toast(`Loaded ${r.jobs} sample jobs and ${r.candidates} sample candidates`); onDone() } catch (e: any) { toast(e.message) }
    setBusy(false)
  }
  if (!samples) return (
    <Card className="max-w-3xl"><CardHeader title="Sample data" description="Development server only: load sample jobs, resumes and matches (tagged Sample) to try the product. Production servers never offer this. Remove them here any time; your own data is never touched." />
      <CardBody><Button variant="primary" loading={busy} onClick={load}>Load sample data</Button></CardBody></Card>
  )
  return (
    <Card className="max-w-3xl"><CardHeader title="Sample data" description="This workspace still has sample jobs and resumes (tagged Sample). Remove them before you go live; your own jobs and candidates are kept." />
      <CardBody><Button variant="danger" loading={busy} onClick={clear}>Remove sample data</Button></CardBody></Card>
  )
}

