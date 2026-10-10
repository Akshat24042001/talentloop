import { LANGUAGES } from '../app/flow/types'
import { cn } from './ui'

/** Which languages the candidate may choose from on the interview page. `value` undefined means all of them. */
export function LanguageChoice({ value, onChange }: { value?: string[]; onChange: (v: string[] | undefined) => void }) {
  const on = (k: string) => !value || value.includes(k)
  const toggle = (k: string) => {
    const cur = value || LANGUAGES.map(([c]) => c)
    const next = cur.includes(k) ? cur.filter(x => x !== k) : [...cur, k]
    if (!next.length) return                                   // at least one language
    onChange(next.length === LANGUAGES.length ? undefined : LANGUAGES.map(([c]) => c).filter(c => next.includes(c)))
  }
  return (
    <div>
      <div className="flex flex-wrap gap-1.5">{LANGUAGES.map(([k, n]) => (
        <button type="button" key={k} aria-pressed={on(k)} onClick={() => toggle(k)}
          className={cn('rounded-full px-2.5 py-1 text-[12.5px] font-medium ring-1 ring-inset transition-colors', on(k) ? 'bg-brand-600 text-white ring-brand-600' : 'bg-white text-slate-600 ring-slate-200 hover:bg-slate-50 dark:bg-ink-850 dark:text-slate-300 dark:ring-ink-700')}>{n}</button>))}
      </div>
      <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">The candidate chooses one of these before the interview starts; the questions are translated and the interviewer speaks and listens in that language. Scores and the report stay in English.</p>
    </div>
  )
}
