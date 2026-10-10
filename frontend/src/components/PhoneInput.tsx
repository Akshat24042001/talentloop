import { useEffect, useMemo, useRef, useState } from 'react'
import { AsYouType, getCountries, getCountryCallingCode, isValidPhoneNumber, parsePhoneNumberFromString, type CountryCode } from 'libphonenumber-js/min'
import { ChevronDown, Search } from 'lucide-react'
import { cn } from './ui'

/** Flag images are SVG files from country-flag-icons, copied to /flags at build time (scripts/vendor-flags.mjs): no outside request, and they
 * show on Windows, where flag emoji do not. */
const flagUrl = (c: string) => `/flags/${c}.svg`

const names = (() => { try { return new Intl.DisplayNames(['en'], { type: 'region' }) } catch { return null } })()
const COUNTRIES = getCountries().map(c => ({ code: c, name: names?.of(c) || c, dial: getCountryCallingCode(c) }))
  .sort((a, b) => a.name.localeCompare(b.name))
const TOP: CountryCode[] = ['IN', 'US', 'GB', 'AE', 'SG', 'CA', 'AU', 'DE']

export function Flag({ country, className }: { country?: string; className?: string }) {
  const u = country ? flagUrl(country) : ''
  return u ? <img src={u} alt="" aria-hidden loading="lazy" decoding="async" className={cn('h-3.5 w-5 shrink-0 rounded-[2px] object-cover ring-1 ring-black/10', className)} /> : <span className={cn('inline-block h-3.5 w-5 shrink-0 rounded-[2px] bg-slate-200 dark:bg-ink-700', className)} />
}

/** India first: this is an Indian hiring product, and many Indian browsers report en-US, so the browser's language is not a safe guide. */
const guessCountry = (): CountryCode => 'IN'

/** The country and the number inside a stored phone value ("+91 98765 43210", "9876543210" or ""). */
export function splitPhone(v: string, fallback: CountryCode = 'IN'): { country: CountryCode; national: string } {
  const s = (v || '').trim()
  if (!s) return { country: fallback, national: '' }
  const p = parsePhoneNumberFromString(s.startsWith('+') || s.startsWith('00') ? s.replace(/^00/, '+') : s, fallback)
  return p?.country ? { country: p.country, national: p.formatNational() } : { country: fallback, national: s.replace(/^\+/, '') }
}

/** A phone number with the country flag and dial code: the value handed back is always international ("+91 98765 43210"), or "" when empty. */
export function PhoneInput({ id, value, onChange, required, defaultCountry, className, disabled, placeholder }: { id?: string; value: string; onChange: (v: string) => void; required?: boolean; defaultCountry?: CountryCode; className?: string; disabled?: boolean; placeholder?: string }) {
  const start = useMemo(() => splitPhone(value, defaultCountry || guessCountry()), [])       // eslint-disable-line react-hooks/exhaustive-deps
  const [country, setCountry] = useState<CountryCode>(start.country)
  const [text, setText] = useState(start.national)
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const box = useRef<HTMLDivElement>(null)
  const emitted = useRef(value)

  // a value that changes from outside (a resume was read, a form was reset) replaces what is shown
  useEffect(() => {
    if (value === emitted.current) return
    emitted.current = value
    const s = splitPhone(value, country); setCountry(s.country); setText(s.national)
  }, [value]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return
    const off = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', off); return () => document.removeEventListener('mousedown', off)
  }, [open])

  function emit(c: CountryCode, t: string) {
    const digits = t.replace(/[^\d]/g, '')
    const out = !digits ? '' : (parsePhoneNumberFromString(t, c)?.formatInternational() || `+${getCountryCallingCode(c)} ${digits}`)
    emitted.current = out; onChange(out)
  }
  function type(raw: string) {
    // a number pasted with its own +code switches the country
    if (raw.trim().startsWith('+')) {
      const p = parsePhoneNumberFromString(raw.replace(/\s+/g, ''))
      if (p?.country) { setCountry(p.country); const nat = p.formatNational(); setText(nat); emit(p.country, nat); return }
    }
    const f = new AsYouType(country).input(raw.replace(/[^\d\s()-]/g, ''))
    setText(f); emit(country, f)
  }
  const bad = !!text.replace(/\D/g, '') && !isValidPhoneNumber(text, country)
  const list = useMemo(() => {
    const s = q.trim().toLowerCase().replace(/^\+/, '')
    const hit = COUNTRIES.filter(c => !s || c.name.toLowerCase().includes(s) || c.code.toLowerCase() === s || c.dial.startsWith(s))
    return s ? hit : [...TOP.map(t => COUNTRIES.find(c => c.code === t)!), ...hit.filter(c => !TOP.includes(c.code))]
  }, [q])
  const cur = COUNTRIES.find(c => c.code === country)!

  return (
    <div ref={box} className={cn('relative', className)}>
      <div className={cn('flex rounded-xl border bg-white transition focus-within:ring-2 focus-within:ring-brand-500 dark:bg-ink-900', bad ? 'border-red-400' : 'border-slate-300 dark:border-ink-700')}>
        <button type="button" disabled={disabled} onClick={() => { setOpen(o => !o); setQ('') }} aria-haspopup="listbox" aria-expanded={open} aria-label={`Country code: ${cur.name} +${cur.dial}`}
          className="flex shrink-0 items-center gap-1.5 rounded-l-xl border-r border-slate-200 px-3 text-sm text-slate-700 hover:bg-slate-50 focus-visible:outline-none dark:border-ink-700 dark:text-slate-200 dark:hover:bg-ink-800">
          <Flag country={country} /><span className="tabular-nums">+{cur.dial}</span><ChevronDown className="size-3.5 text-slate-400" />
        </button>
        <input id={id} type="tel" inputMode="tel" autoComplete="tel-national" required={required} disabled={disabled} value={text} aria-invalid={bad || undefined}
          placeholder={placeholder || (parsePhoneNumberFromString('', country) ? '' : '98765 43210')} onChange={e => type(e.target.value)}
          className="min-w-0 flex-1 rounded-r-xl bg-transparent px-3 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none dark:text-white" />
      </div>
      {bad && <p className="mt-1 text-xs text-red-600 dark:text-red-400">This does not look like a valid {cur.name} number.</p>}
      {open && (
        <div role="listbox" className="absolute left-0 z-30 mt-1 w-72 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl dark:border-ink-700 dark:bg-ink-900">
          <div className="flex items-center gap-2 border-b border-slate-200 px-3 dark:border-ink-700"><Search className="size-4 text-slate-400" />
            <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search country or code" aria-label="Search country or code" className="w-full bg-transparent py-2.5 text-sm focus:outline-none dark:text-white" /></div>
          <ul className="max-h-64 overflow-y-auto py-1">
            {list.map(c => (
              <li key={c.code} role="option" aria-selected={c.code === country}>
                <button type="button" onClick={() => { setCountry(c.code); setOpen(false); emit(c.code, text) }}
                  className={cn('flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-ink-800', c.code === country && 'bg-brand-50 dark:bg-brand-500/10')}>
                  <Flag country={c.code} /><span className="min-w-0 flex-1 truncate">{c.name}</span><span className="tabular-nums text-slate-500">+{c.dial}</span>
                </button>
              </li>
            ))}
            {!list.length && <li className="px-3 py-3 text-sm text-slate-500">No country found.</li>}
          </ul>
        </div>
      )}
    </div>
  )
}

/** A phone number shown with its country flag, as a call link. */
export function PhoneText({ value, className, link = true }: { value?: string; className?: string; link?: boolean }) {
  const v = (value || '').trim()
  if (!v) return null
  const p = parsePhoneNumberFromString(v.startsWith('+') ? v : v, 'IN')
  const shown = p ? p.formatInternational() : v
  const body = <><Flag country={p?.country} /><span className="tabular-nums">{shown}</span></>
  return link ? <a href={`tel:${p?.number || v}`} className={cn('inline-flex items-center gap-2', className)}>{body}</a> : <span className={cn('inline-flex items-center gap-2', className)}>{body}</span>
}
