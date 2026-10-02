// Two to five candidates side by side: profile facts, every round's score and headline, and flags.
// The best value on each scored row is highlighted; nothing is ranked or decided for you.
import { Flag, Star } from 'lucide-react'
import { Badge, Modal, cn } from '../../components/ui'
import { ErrorBox, Loading, useApi } from '../../components/kit'
import { REC_TONE, STATUS_TONE, type RoundType } from './types'

interface Cell { status: string; status_label: string; score: number | null; recommendation?: string | null; headline: string; flagged: boolean }
interface Item {
  id: string; ref: string; stage_label: string; rating: number | null; match_score: number | null; rounds: Record<string, Cell>
  candidate: { name: string; headline?: string; location?: string; years?: number | null; notice_days?: number | null; expected_salary?: number | null; current_company?: string; college?: string }
}
interface Data { job: { title: string }; rounds: { id: string; name: string; type: RoundType }[]; items: Item[] }

export default function Compare({ jobId, ids, onClose, onOpen }: { jobId: string; ids: string[]; onClose: () => void; onOpen: (id: string) => void }) {
  const { data, error, reload } = useApi<Data>(`/api/jobs/${jobId}/compare?ids=${ids.join(',')}`)
  const best = (vals: (number | null | undefined)[], low = false) => {
    const xs = vals.filter((v): v is number => typeof v === 'number')
    return xs.length > 1 ? (low ? Math.min(...xs) : Math.max(...xs)) : null
  }
  const row = (label: string, cells: React.ReactNode[], hint?: string) => (
    <tr className="border-t border-slate-100 align-top dark:border-ink-800">
      <th scope="row" className="w-40 py-2.5 pr-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400">{label}{hint && <span className="block font-normal">{hint}</span>}</th>
      {cells.map((c, i) => <td key={i} className="py-2.5 pr-3 text-sm">{c}</td>)}
    </tr>
  )
  const num = (v: number | null | undefined, b: number | null, suffix = '') => v == null ? <span className="text-slate-400">-</span>
    : <span className={cn('tabular font-semibold', v === b && 'rounded-md bg-emerald-50 px-1.5 py-0.5 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200')}>{v}{suffix}</span>
  return (
    <Modal open wide onOpenChange={o => !o && onClose()} title="Compare candidates" description={data ? `${data.job.title}. Green marks the best value in a row; it is not a ranking.` : undefined}>
      <div className="mt-4">
        {error ? <ErrorBox error={error} retry={reload} /> : !data ? <Loading /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] table-fixed">
              <thead><tr><th className="w-40" />{data.items.map(it => (
                <th key={it.id} className="pb-2 pr-3 text-left align-bottom">
                  <button className="text-left font-semibold text-brand-600 hover:underline dark:text-brand-400" onClick={() => onOpen(it.id)}>{it.candidate.name}</button>
                  <div className="truncate text-xs font-normal text-slate-500 dark:text-slate-400">{it.candidate.headline || it.candidate.current_company || it.candidate.college || ''}</div>
                  <Badge className="mt-1">{it.stage_label}</Badge>
                </th>))}</tr></thead>
              <tbody>
                {row('Match score', data.items.map(it => num(it.match_score, best(data.items.map(x => x.match_score)))))}
                {row('Experience', data.items.map(it => num(it.candidate.years, null, it.candidate.years === 1 ? ' year' : ' years')))}
                {row('Notice period', data.items.map(it => num(it.candidate.notice_days, best(data.items.map(x => x.candidate.notice_days), true), ' days')), 'shorter is better')}
                {row('Expected salary', data.items.map(it => it.candidate.expected_salary != null ? <span className="tabular">{it.candidate.expected_salary.toLocaleString('en-IN')}</span> : <span className="text-slate-400">-</span>))}
                {row('Location', data.items.map(it => it.candidate.location || <span className="text-slate-400">-</span>))}
                {data.rounds.map(r => {
                  const b = best(data.items.map(it => it.rounds[r.id]?.score))
                  return row(r.name, data.items.map(it => {
                    const c = it.rounds[r.id]
                    if (!c) return <span className="text-slate-400">Not reached</span>
                    return <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-1.5">{num(c.score, b)}{c.recommendation && <Badge tone={REC_TONE[c.recommendation]}>{c.recommendation}</Badge>}
                        <Badge tone={STATUS_TONE[c.status]}>{c.status_label}</Badge>{c.flagged && <Badge tone="danger" icon={<Flag />}>Flag</Badge>}</div>
                      {c.headline && <p className="line-clamp-3 text-xs text-slate-600 dark:text-slate-300">{c.headline}</p>}
                    </div>
                  }))
                })}
                {row('Team rating', data.items.map(it => it.rating ? <span className="text-amber-500">{Array.from({ length: it.rating }, (_, i) => <Star key={i} className="inline size-3.5 fill-current" />)}</span> : <span className="text-slate-400">-</span>))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Modal>
  )
}
