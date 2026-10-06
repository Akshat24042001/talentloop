import * as Dialog from '@radix-ui/react-dialog'
import * as Popover from '@radix-ui/react-popover'
import * as RTooltip from '@radix-ui/react-tooltip'
import clsx from 'clsx'
import { Check, ChevronDown, Eye, EyeOff, LoaderCircle, X } from 'lucide-react'
import { Children, Fragment, forwardRef, isValidElement, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import type { Tone } from '../lib/format'

export const cn = clsx

type BtnVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'subtle'
const BTN: Record<BtnVariant, string> = {
  primary: 'bg-brand-600 text-white shadow-sm shadow-brand-600/20 hover:bg-brand-700 focus-visible:outline-brand-600',
  secondary: 'bg-white text-slate-800 ring-1 ring-inset ring-slate-200 hover:bg-slate-50 dark:bg-ink-850 dark:text-slate-100 dark:ring-ink-700 dark:hover:bg-ink-800',
  ghost: 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-ink-800 dark:hover:text-white',
  danger: 'bg-red-600 text-white hover:bg-red-700 focus-visible:outline-red-600',
  subtle: 'bg-brand-50 text-brand-700 hover:bg-brand-100 dark:bg-brand-500/15 dark:text-brand-300 dark:hover:bg-brand-500/25',
}
const SIZE = { sm: 'h-8 px-3 text-[13px] gap-1.5 rounded-lg', md: 'h-10 px-4 text-sm gap-2 rounded-xl', lg: 'h-12 px-6 text-[15px] gap-2 rounded-xl' }

type BtnProps = { variant?: BtnVariant; size?: keyof typeof SIZE; icon?: ReactNode; loading?: boolean; href?: string; target?: string; download?: boolean } &
  React.ButtonHTMLAttributes<HTMLButtonElement>

export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button(
  { variant = 'secondary', size = 'md', icon, loading, href, target, download, className, children, disabled, ...rest }, ref) {
  const cls = cn('inline-flex shrink-0 items-center justify-center whitespace-nowrap font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0',
    BTN[variant], SIZE[size], className)
  const inner = <>{loading ? <LoaderCircle className="animate-spin" /> : icon}{children}</>
  if (href) return <a href={href} target={target} rel={target ? 'noopener' : undefined} download={download} className={cls}>{inner}</a>
  return <button ref={ref} className={cls} disabled={disabled || loading} {...rest}>{inner}</button>
})

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-2xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(16,24,40,.04)] dark:border-ink-700 dark:bg-ink-900', className)} {...rest}>{children}</div>
}
export function CardHeader({ title, description, action, className }: { title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-3 px-5 pt-5', className)}>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold tracking-tight text-slate-900 dark:text-white">{title}</h2>
        {description && <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {action}
    </div>
  )
}
export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('p-5', className)}>{children}</div>
}

const TONE: Record<Tone, string> = {
  neutral: 'bg-slate-100 text-slate-600 ring-slate-200 dark:bg-ink-800 dark:text-slate-300 dark:ring-ink-700',
  brand: 'bg-brand-50 text-brand-700 ring-brand-100 dark:bg-brand-500/15 dark:text-brand-300 dark:ring-brand-500/20',
  success: 'bg-emerald-50 text-emerald-700 ring-emerald-100 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-500/20',
  warning: 'bg-amber-50 text-amber-700 ring-amber-100 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-500/20',
  danger: 'bg-red-50 text-red-700 ring-red-100 dark:bg-red-500/15 dark:text-red-300 dark:ring-red-500/20',
  violet: 'bg-violet-50 text-violet-700 ring-violet-100 dark:bg-violet-500/15 dark:text-violet-300 dark:ring-violet-500/20',
}
export function Badge({ tone = 'neutral', icon, children, className }: { tone?: Tone; icon?: ReactNode; children: ReactNode; className?: string }) {
  return <span className={cn('inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset [&_svg]:size-3', TONE[tone], className)}>{icon}{children}</span>
}

const FIELD = 'block w-full rounded-xl border-0 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm ring-1 ring-inset ring-slate-200 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-60 dark:bg-ink-850 dark:text-slate-100 dark:ring-ink-700 dark:placeholder:text-slate-500'
export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cn(FIELD, className)} {...p} />
})
/** A password box with an eye button to show or hide what was typed. */
export const PasswordInput = forwardRef<HTMLInputElement, Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'>>(function PasswordInput({ className, ...p }, ref) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input ref={ref} type={show ? 'text' : 'password'} className={cn(FIELD, 'pr-11', className)} {...p} />
      <button type="button" onClick={() => setShow(v => !v)} aria-label={show ? 'Hide password' : 'Show password'} aria-pressed={show} title={show ? 'Hide password' : 'Show password'}
        className="absolute right-1.5 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 dark:text-slate-400 dark:hover:bg-ink-800 dark:hover:text-white">
        {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}</button>
    </div>
  )
})
export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...p }, ref) {
  return <textarea ref={ref} className={cn(FIELD, 'min-h-28 resize-y leading-relaxed', className)} {...p} />
})
// Dropdowns: one styled listbox for the whole app, with the same props as a native <select> and <option> children
// (`value` + `onChange={e => ...e.target.value}`), so every form keeps working. Long lists (more than 8 options) get
// a search box. Keyboard: arrows, Home/End, Enter, Escape, type to search. A hidden native <select> keeps `required`
// and form submission working.
type Opt = { value: string; label: ReactNode; text: string; disabled?: boolean }
const textOf = (n: ReactNode): string => typeof n === 'string' || typeof n === 'number' ? String(n)
  : Array.isArray(n) ? n.map(textOf).join('') : isValidElement(n) ? textOf((n.props as { children?: ReactNode }).children) : ''
function optionsOf(children: ReactNode): Opt[] {
  const out: Opt[] = []
  Children.forEach(children, ch => {
    if (!isValidElement(ch)) return
    const props = ch.props as { value?: string | number; children?: ReactNode; disabled?: boolean }
    if (ch.type === 'option') out.push({ value: String(props.value ?? textOf(props.children)), label: props.children, text: textOf(props.children), disabled: props.disabled })
    else if (ch.type === Fragment || ch.type === 'optgroup') out.push(...optionsOf(props.children))
  })
  return out
}
type SelectProps = Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'onChange'> & { onChange?: (e: { target: { value: string }; currentTarget: { value: string } }) => void; searchable?: boolean }
export function Select({ className, children, value, defaultValue, onChange, id, required, disabled, name, searchable, ...rest }: SelectProps) {
  const opts = optionsOf(children)
  const [inner, setInner] = useState(String(defaultValue ?? opts[0]?.value ?? ''))
  const cur = value !== undefined ? String(value) : inner
  const isPh = (o: Opt) => o.value === '' && /(…|\.\.\.)$/.test(o.text)       // "Select…" is a hint, not a choice
  const choices = opts.filter(o => !isPh(o))
  const selected = opts.find(o => o.value === cur)
  const placeholder = !selected || isPh(selected)
  const label = placeholder ? (opts.find(isPh)?.label ?? 'Select…') : selected!.label
  const [open, setOpen] = useState(false), [q, setQ] = useState(''), [hi, setHi] = useState(0)
  const search = searchable ?? choices.length > 8
  const shown = q ? choices.filter(o => o.text.toLowerCase().includes(q.toLowerCase())) : choices
  const listId = `${id || name || 'sel'}-list`
  const pick = (o: Opt) => { if (o.disabled) return; if (value === undefined) setInner(o.value); onChange?.({ target: { value: o.value }, currentTarget: { value: o.value } }); setOpen(false) }
  const openList = (o: boolean) => { setOpen(o); if (o) { setQ(''); setHi(Math.max(0, choices.findIndex(x => x.value === cur))) } }
  function keys(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setHi(h => Math.min(shown.length - 1, h + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi(h => Math.max(0, h - 1)) }
    else if (e.key === 'Home') { e.preventDefault(); setHi(0) }
    else if (e.key === 'End') { e.preventDefault(); setHi(shown.length - 1) }
    else if (e.key === 'Enter') { e.preventDefault(); const o = shown[hi]; if (o) pick(o) }
    else if (!search && e.key.length === 1) { const i = shown.findIndex(o => o.text.toLowerCase().startsWith(e.key.toLowerCase())); if (i >= 0) setHi(i) }
  }
  useEffect(() => { document.getElementById(`${listId}-${hi}`)?.scrollIntoView({ block: 'nearest' }) }, [hi, open, listId])
  return (
    <Popover.Root open={open} onOpenChange={openList}>
      <Popover.Trigger id={id} type="button" role="combobox" aria-expanded={open} aria-controls={listId} aria-haspopup="listbox" aria-label={rest['aria-label']}
        title={rest.title} disabled={disabled} data-state={open ? 'open' : 'closed'} onKeyDown={e => { if (!open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { e.preventDefault(); openList(true) } }}
        className={cn(TRIGGER, placeholder && 'text-slate-500 dark:text-slate-400', className)}>
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <span className="grid size-5 shrink-0 place-items-center rounded-md bg-slate-100 text-slate-500 transition-colors group-hover:bg-slate-200 dark:bg-ink-800 dark:text-slate-300 dark:group-hover:bg-ink-700">
          <ChevronDown className="size-3.5 transition-transform group-data-[state=open]:rotate-180" /></span>
      </Popover.Trigger>
      <select aria-hidden tabIndex={-1} required={required} name={name} value={placeholder ? '' : cur} onChange={() => {}} disabled={disabled}
        className="pointer-events-none absolute h-px w-px opacity-0" onFocus={() => document.getElementById(id || '')?.focus()}>
        <option value="" />{choices.map(o => <option key={o.value} value={o.value}>{o.text}</option>)}</select>
      <Popover.Portal>
        <Popover.Content sideOffset={6} collisionPadding={12} align="start" onKeyDown={keys}
          onOpenAutoFocus={e => { if (!search) { e.preventDefault(); document.getElementById(listId)?.focus() } }}
          className="z-[70] w-[var(--radix-popover-trigger-width)] min-w-48 max-w-[min(92vw,30rem)] overflow-hidden rounded-xl bg-white text-sm text-slate-800 shadow-xl shadow-slate-900/10 ring-1 ring-slate-200 animate-rise dark:bg-ink-850 dark:text-slate-100 dark:shadow-black/40 dark:ring-ink-700">
          {search && <div className="border-b border-slate-100 p-2 dark:border-ink-700">
            <input autoFocus aria-label="Search options" placeholder="Search…" value={q} onChange={e => { setQ(e.target.value); setHi(0) }}
              className="w-full rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-900 outline-none ring-1 ring-inset ring-slate-200 placeholder:text-slate-400 focus:ring-2 focus:ring-brand-500 dark:bg-ink-900 dark:text-slate-100 dark:ring-ink-700" /></div>}
          <div id={listId} role="listbox" tabIndex={-1} aria-activedescendant={`${listId}-${hi}`} className="max-h-[min(var(--radix-popover-content-available-height),320px)] overflow-y-auto p-1 outline-none">
            {shown.map((o, i) => { const on = o.value === cur && !placeholder; return (
              <div key={o.value} id={`${listId}-${i}`} role="option" aria-selected={on} aria-disabled={o.disabled || undefined}
                onMouseEnter={() => setHi(i)} onClick={() => pick(o)}
                className={cn('relative flex cursor-pointer select-none items-center gap-2 rounded-lg py-2 pl-3 pr-9 transition-colors',
                  i === hi && 'bg-brand-50 text-brand-900 dark:bg-brand-500/20 dark:text-white', on && 'font-semibold',
                  o.value === '' && 'text-slate-500 dark:text-slate-400', o.disabled && 'pointer-events-none opacity-40')}>
                <span className="min-w-0 flex-1 truncate">{o.label}</span>
                {on && <Check className="absolute right-3 size-4 text-brand-600 dark:text-brand-300" />}
              </div>) })}
            {!shown.length && <div className="px-3 py-6 text-center text-sm text-slate-500 dark:text-slate-400">No matches</div>}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
const TRIGGER = 'group relative flex h-10 w-full items-center gap-2 rounded-xl border-0 bg-white pl-3.5 pr-2.5 text-left text-sm text-slate-900 shadow-sm ring-1 ring-inset ring-slate-200 transition-shadow hover:ring-slate-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 data-[state=open]:ring-2 data-[state=open]:ring-brand-500 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-ink-850 dark:text-slate-100 dark:ring-ink-700 dark:hover:ring-ink-600'
export function Field({ label, hint, htmlFor, action, children, className }: { label: ReactNode; hint?: ReactNode; htmlFor?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <label htmlFor={htmlFor} className="text-[13px] font-semibold text-slate-700 dark:text-slate-200">{label}</label>
        {action}
      </div>
      {children}
      {hint && <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  )
}

export function Switch({ checked, onChange, label, description, id, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; description?: ReactNode; id: string; disabled?: boolean }) {
  return (
    <div className={cn('flex items-start justify-between gap-4 py-3', disabled && 'opacity-50')}>
      <label htmlFor={id} className="min-w-0 cursor-pointer">
        <span className="block text-sm font-medium text-slate-800 dark:text-slate-100">{label}</span>
        {description && <span className="mt-0.5 block text-[13px] text-slate-500 dark:text-slate-400">{description}</span>}
      </label>
      <button id={id} type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
        className={cn('relative mt-0.5 inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600',
          checked ? 'bg-brand-600' : 'bg-slate-200 dark:bg-ink-700')}>
        <span className={cn('absolute top-0.5 size-5 rounded-full bg-white shadow transition-transform', checked ? 'translate-x-5.5' : 'translate-x-0.5')} />
      </button>
    </div>
  )
}

export function Stat({ label, value, sub, icon, tone }: { label: ReactNode; value: ReactNode; sub?: ReactNode; icon?: ReactNode; tone?: 'danger' | 'warning' }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</span>
        {icon && <span className={cn('grid size-8 place-items-center rounded-lg [&_svg]:size-4',
          tone === 'danger' ? 'bg-red-50 text-red-600 dark:bg-red-500/15 dark:text-red-300' : tone === 'warning' ? 'bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300' : 'bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300')}>{icon}</span>}
      </div>
      <div className="tabular mt-2 text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{sub}</div>}
    </Card>
  )
}

export function Spinner({ className }: { className?: string }) { return <LoaderCircle className={cn('animate-spin', className)} /> }

export function Alert({ tone = 'warning', icon, title, children, className }: { tone?: 'warning' | 'danger' | 'info' | 'success'; icon?: ReactNode; title?: ReactNode; children?: ReactNode; className?: string }) {
  const t = { warning: 'bg-amber-50 text-amber-900 ring-amber-200/70 dark:bg-amber-500/10 dark:text-amber-200 dark:ring-amber-500/20',
    danger: 'bg-red-50 text-red-900 ring-red-200/70 dark:bg-red-500/10 dark:text-red-200 dark:ring-red-500/20',
    info: 'bg-brand-50 text-brand-900 ring-brand-200/70 dark:bg-brand-500/10 dark:text-brand-200 dark:ring-brand-500/20',
    success: 'bg-emerald-50 text-emerald-900 ring-emerald-200/70 dark:bg-emerald-500/10 dark:text-emerald-200 dark:ring-emerald-500/20' }[tone]
  return (
    <div role={tone === 'danger' ? 'alert' : undefined} className={cn('flex gap-3 rounded-xl px-4 py-3 text-sm ring-1 ring-inset [&>svg]:mt-0.5 [&>svg]:size-4 [&>svg]:shrink-0', t, className)}>
      {icon}
      <div className="min-w-0">{title && <div className="font-semibold">{title}</div>}{children && <div className={title ? 'mt-0.5 opacity-90' : ''}>{children}</div>}</div>
    </div>
  )
}

export function Modal({ open, onOpenChange, title, description, children, footer, dark, dismissable = true, id, icon, wide }: {
  open: boolean; onOpenChange?: (o: boolean) => void; title: ReactNode; description?: ReactNode; children?: ReactNode; footer?: ReactNode; dark?: boolean; dismissable?: boolean; id?: string; icon?: ReactNode; wide?: boolean }) {
  return (
    <Dialog.Root open={open} onOpenChange={o => (dismissable || o) && onOpenChange?.(o)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-ink-950/70 backdrop-blur-sm" />
        <Dialog.Content id={id} onEscapeKeyDown={e => !dismissable && e.preventDefault()} onPointerDownOutside={e => !dismissable && e.preventDefault()}
          className={cn('fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-2xl p-6 shadow-2xl focus:outline-none animate-rise', wide ? 'max-h-[90vh] max-w-5xl overflow-y-auto' : 'max-w-md',
            dark ? 'bg-ink-850 text-slate-100 ring-1 ring-white/10' : 'bg-white text-slate-900 dark:bg-ink-850 dark:text-slate-100 dark:ring-1 dark:ring-white/10')}>
          {icon && <div className="mb-4 grid size-11 place-items-center rounded-xl bg-red-500/15 text-red-500 [&_svg]:size-5">{icon}</div>}
          <Dialog.Title className="text-lg font-semibold tracking-tight">{title}</Dialog.Title>
          {description ? <Dialog.Description className={cn('mt-1.5 text-sm leading-relaxed', dark ? 'text-slate-300' : 'text-slate-600 dark:text-slate-300')}>{description}</Dialog.Description>
            : <Dialog.Description className="sr-only">{typeof title === 'string' ? title : 'Dialog'}</Dialog.Description>}
          {children}
          {footer && <div className="mt-6 flex flex-wrap justify-end gap-2">{footer}</div>}
          {dismissable && onOpenChange && <Dialog.Close className="absolute right-4 top-4 rounded-lg p-1 text-slate-500 dark:text-slate-400 hover:bg-black/5 hover:text-slate-600 dark:hover:bg-white/10" aria-label="Close"><X className="size-4" /></Dialog.Close>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export function Tip({ label, children, side = 'top' }: { label: ReactNode; children: ReactNode; side?: 'top' | 'bottom' | 'left' | 'right' }) {
  return (
    <RTooltip.Root delayDuration={250}>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content side={side} sideOffset={8} className="z-[60] max-w-xs rounded-lg bg-ink-800 px-2.5 py-1.5 text-xs font-medium text-white shadow-lg ring-1 ring-white/10">
          {label}
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  )
}
export const TooltipProvider = RTooltip.Provider

// ---- toasts
let toasts: { id: number; msg: string }[] = []
const tl = new Set<() => void>()
export function toast(msg: string) {
  const id = Date.now() + Math.random()
  toasts = [...toasts, { id, msg }]; tl.forEach(f => f())
  setTimeout(() => { toasts = toasts.filter(t => t.id !== id); tl.forEach(f => f()) }, 3200)
}
export function Toaster({ dark }: { dark?: boolean }) {
  const list = useSyncExternalStore(f => { tl.add(f); return () => { tl.delete(f) } }, () => toasts)
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-24 z-[70] flex flex-col items-center gap-2 px-4 sm:bottom-6" aria-live="polite">
      {list.map(t => <div key={t.id} className={cn('toast animate-rise rounded-xl px-4 py-2.5 text-sm font-medium shadow-xl ring-1', dark ? 'bg-ink-800 text-white ring-white/10' : 'bg-ink-900 text-white ring-black/5')}>{t.msg}</div>)}
    </div>
  )
}

export function copyText(text: string, msg = 'Copied') {
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => toast(msg), () => window.prompt('Copy this:', text))
  else window.prompt('Copy this:', text)
}

export function useInterval(fn: () => void, ms: number | null) {
  useEffect(() => { if (ms == null) return; const t = setInterval(fn, ms); return () => clearInterval(t) }, [fn, ms])
}
export function useNow(ms = 30000) { const [n, set] = useState(Date.now()); useInterval(() => set(Date.now()), ms); return n }

export function Logo({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <span className="grid size-8 place-items-center rounded-[10px] bg-gradient-to-br from-brand-500 to-violet-500 text-white shadow-sm shadow-brand-600/30">
        <svg viewBox="0 0 24 24" className="size-4.5" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M17 3a4 4 0 0 1 0 8H7a4 4 0 0 0 0 8h10" /><path d="m14 16 3 3-3 3" /></svg>
      </span>
      {!compact && <span className="text-[15px] font-semibold tracking-tight">TalentLoop</span>}
    </span>
  )
}
