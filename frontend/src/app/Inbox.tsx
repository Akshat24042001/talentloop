// Small HR pages: candidate requests (accommodations, human interviews), the message outbox and my interviews.
import { CalendarClock, ClipboardCheck, ExternalLink, HandHelping, Inbox, Mail, MessageCircle, RefreshCw, Video } from 'lucide-react'
import { useState } from 'react'
import { Alert, Badge, Button, Card, CardBody, Input, Select, toast } from '../components/ui'
import { Empty, ErrorBox, Loading, PageHeader, Pager, useApi } from '../components/kit'
import { api } from '../lib/api'
import { ago, when } from '../lib/format'
import { MSG_LABEL, MSG_TONE } from './flow/AppDrawer'

interface Req { kind: 'human' | 'accommodation'; application_id: string; candidate: string; candidate_ref: string; job: string; job_ref: string; at: number; note: string; status: string; extra_time_pct?: number }

export function Requests() {
  const { data, error, reload } = useApi<Req[]>('/api/requests')
  const [pct, setPct] = useState<Record<string, number>>({})
  if (error) return <ErrorBox error={error} retry={reload} />
  async function acc(r: Req, status: string) {
    try { await api(`/api/applications/${r.application_id}/accommodation`, { json: { status, extra_time_pct: pct[r.application_id] ?? 25 } }); toast(status === 'approved' ? 'Approved; the candidate was told' : 'Declined; the candidate was told'); reload() } catch (e: any) { toast(e.message) }
  }
  async function human(r: Req, action: string) {
    try { await api(`/api/applications/${r.application_id}/human-request`, { json: { action } }); toast(action === 'human' ? 'Moved to the human interview round' : 'Reply sent'); reload() } catch (e: any) { toast(e.message) }
  }
  const open = (data || []).filter(r => r.status === 'open' || r.status === 'requested'), done = (data || []).filter(r => !(r.status === 'open' || r.status === 'requested'))
  return (
    <>
      <PageHeader title="Candidate requests" description="Accommodations (for example extra time) and requests for an interview with a person instead of the AI interviewer." />
      {!data ? <Loading /> : !data.length ? <Card><Empty icon={<HandHelping />} title="No requests">Candidates can ask from their application status page.</Empty></Card> : <>
        <div className="space-y-3">{open.map(r => (
          <Card key={`${r.kind}-${r.application_id}`}><CardBody className="space-y-2">
            <div className="flex flex-wrap items-center gap-2"><Badge tone="warning">{r.kind === 'human' ? 'Human interview' : 'Accommodation'}</Badge>
              <a className="font-semibold hover:underline" href={`/app/candidates/${r.candidate_ref}`}>{r.candidate}</a><span className="text-sm text-slate-500">for <a className="hover:underline" href={`/app/jobs/${r.job_ref}?tab=pipeline&app=${r.application_id}`}>{r.job}</a> · {ago(r.at)}</span></div>
            {r.note && <p className="text-sm">"{r.note}"</p>}
            {r.kind === 'human' ? <div className="flex flex-wrap gap-2"><Button size="sm" variant="primary" onClick={() => human(r, 'human')}>Switch to a human interview</Button><Button size="sm" onClick={() => human(r, 'keep')}>Keep the AI round and reply</Button></div>
              : <div className="flex flex-wrap items-center gap-2"><label className="flex items-center gap-1.5 text-sm">Extra time on tests<Input type="number" aria-label="Extra time percent" className="h-8 w-16" min={0} max={100} value={pct[r.application_id] ?? 25} onChange={e => setPct({ ...pct, [r.application_id]: +e.target.value })} />%</label>
                <Button size="sm" variant="primary" onClick={() => acc(r, 'approved')}>Approve</Button><Button size="sm" onClick={() => acc(r, 'declined')}>Decline</Button></div>}
          </CardBody></Card>))}</div>
        {!open.length && <Alert tone="success">Nothing waiting. Handled requests are below.</Alert>}
        {done.length > 0 && <><h2 className="mb-2 mt-6 text-sm font-semibold text-slate-500">Handled</h2>
          <Card><ul className="divide-y divide-slate-100 dark:divide-ink-800">{done.map(r => <li key={`${r.kind}-${r.application_id}`} className="flex flex-wrap items-center gap-2 px-5 py-3 text-sm">
            <Badge tone={r.status === 'approved' ? 'success' : 'neutral'}>{r.status}</Badge><span className="font-medium">{r.candidate}</span><span className="text-slate-500">{r.job} · {r.note}</span></li>)}</ul></Card></>}
      </>}
    </>
  )
}

interface Msg { id: string; channel: string; to: string; subject: string; body: string; template: string; status: string; error: string; created_at: number; sent_at: number | null }
export function Outbox() {
  const [status, setStatus] = useState(''), [page, setPage] = useState(1), [open, setOpen] = useState<string | null>(null)
  const { data, error, reload } = useApi<{ total: number; items: Msg[]; channels: { email: boolean; whatsapp: boolean } }>(`/api/messages?status=${status}&page=${page}`)
  if (error) return <ErrorBox error={error} retry={reload} />
  async function retry(id: string) { try { await api(`/api/messages/${id}/retry`, { method: 'POST' }); toast('Queued again'); reload() } catch (e: any) { toast(e.message) } }
  return (
    <>
      <PageHeader title="Outbox" description="Every email and WhatsApp message sent to candidates, managers and interviewers." actions={<Button icon={<RefreshCw />} onClick={reload}>Refresh</Button>} />
      {data && (!data.channels.email || !data.channels.whatsapp) && <Alert className="mb-4" tone="info" title="Channels">
        Email is {data.channels.email ? 'set up' : 'not set up (SMTP_HOST and related settings on the server)'}. WhatsApp is {data.channels.whatsapp ? 'set up' : 'not set up (WHATSAPP_TOKEN and related settings)'}. Messages on a channel that isn't set up are kept here and can be retried later.</Alert>}
      <div className="mb-3"><Select aria-label="Status" className="w-48" value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}><option value="">All messages</option>{Object.entries(MSG_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></div>
      {!data ? <Loading /> : !data.items.length ? <Card><Empty icon={<Inbox />} title="No messages">Messages appear here when candidates move through a flow.</Empty></Card> : <>
        <Card><ul className="divide-y divide-slate-100 dark:divide-ink-800">{data.items.map(m => (
          <li key={m.id} className="px-5 py-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">{m.channel === 'whatsapp' ? <MessageCircle className="size-4 text-emerald-600" /> : <Mail className="size-4 text-slate-400" />}
              <button className="min-w-0 flex-1 truncate text-left font-medium hover:underline" onClick={() => setOpen(open === m.id ? null : m.id)}>{m.subject || m.template}</button>
              <Badge tone={MSG_TONE[m.status] || 'neutral'}>{MSG_LABEL[m.status] || m.status}</Badge>
              {['failed', 'not_configured'].includes(m.status) && <Button size="sm" variant="ghost" onClick={() => retry(m.id)}>Retry</Button>}</div>
            <div className="text-xs text-slate-500">To {m.to} · {when(m.created_at)}{m.sent_at ? ` · sent ${ago(m.sent_at)}` : ''}{m.error ? ` · ${m.error}` : ''}</div>
            {open === m.id && <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-slate-50 p-3 font-sans text-sm dark:bg-ink-850">{m.body.split('\n\n--ICS--')[0]}</pre>}
          </li>))}</ul></Card>
        <Pager page={page} total={data.total} limit={50} onPage={setPage} />
      </>}
    </>
  )
}

interface Mine { round_result_id: string; status: string; starts_at: number; ends_at: number; meeting_url: string; location: string; round: string; job: string; job_ref: string; candidate: string; candidate_ref: string; feedback_given: boolean; feedback_link: string }
export function MyInterviews() {
  const { data, error, reload } = useApi<Mine[]>('/api/my-interviews')
  if (error) return <ErrorBox error={error} retry={reload} />
  const now = Date.now() / 1000
  const upcoming = (data || []).filter(x => x.ends_at > now), past = (data || []).filter(x => x.ends_at <= now).reverse()
  const row = (x: Mine) => (
    <li key={x.round_result_id} className="flex flex-wrap items-center gap-3 px-5 py-3">
      <CalendarClock className="size-5 text-slate-400" />
      <div className="min-w-0 flex-1"><div className="font-semibold"><a className="hover:underline" href={`/app/candidates/${x.candidate_ref}`}>{x.candidate}</a> <span className="font-normal text-slate-500">· {x.round}, {x.job}</span></div>
        <div className="text-sm text-slate-500">{when(x.starts_at)}{x.location ? ` · ${x.location}` : ''}</div></div>
      {x.meeting_url && x.ends_at > now && <Button size="sm" icon={<Video />} href={x.meeting_url} target="_blank">Join</Button>}
      <Button size="sm" variant={x.feedback_given || x.ends_at > now ? 'secondary' : 'primary'} icon={x.feedback_given ? <ClipboardCheck /> : <ExternalLink />} href={x.feedback_link} target="_blank">
        {x.feedback_given ? 'Feedback given' : x.ends_at > now ? 'Prep kit' : 'Give feedback'}</Button>
    </li>)
  return (
    <>
      <PageHeader title="My interviews" description="Interviews candidates booked with you. Open the prep kit before, and give one-click feedback after." />
      {!data ? <Loading /> : !data.length ? <Card><Empty icon={<CalendarClock />} title="No interviews booked with you">When a candidate books one of your slots it shows here, and you get an email with a calendar invite.</Empty></Card> : <>
        {upcoming.length > 0 && <Card className="mb-4"><div className="px-5 pt-4 text-sm font-semibold">Upcoming</div><ul className="divide-y divide-slate-100 dark:divide-ink-800">{upcoming.map(row)}</ul></Card>}
        {past.length > 0 && <Card><div className="px-5 pt-4 text-sm font-semibold">Past two weeks</div><ul className="divide-y divide-slate-100 dark:divide-ink-800">{past.map(row)}</ul></Card>}
      </>}
    </>
  )
}
