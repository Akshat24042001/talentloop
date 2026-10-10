// One control for every link we hand out: copy it, open it in a new tab, or send it (email, WhatsApp, the
// device's share sheet) with a ready-made message, so nobody has to copy, switch apps and paste.
import * as Popover from '@radix-ui/react-popover'
import { Copy, ExternalLink, Mail, MessageCircle, Send, Share2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { Tip, cn, copyText } from './ui'

export interface ShareTo { email?: string; phone?: string; name?: string }

import { parsePhoneNumberFromString } from 'libphonenumber-js/min'
const digits = (p?: string) => (parsePhoneNumberFromString(p || '', 'IN')?.number.replace('+', '')) || (p || '').replace(/[^\d]/g, '')
const SEG = 'inline-flex items-center gap-1.5 whitespace-nowrap bg-white font-semibold text-slate-800 ring-1 ring-inset ring-slate-200 transition-colors hover:bg-slate-50 focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-brand-600 dark:bg-ink-850 dark:text-slate-100 dark:ring-ink-700 dark:hover:bg-ink-800'

export function LinkActions({ url, label = 'Copy link', copied = 'Link copied', subject, message, to, size = 'sm', icon, className }: {
  url: string; label?: ReactNode; copied?: string
  subject?: string; message?: string            // the text sent with the link; the link is appended
  to?: ShareTo; size?: 'sm' | 'md'; icon?: ReactNode; className?: string
}) {
  const h = size === 'sm' ? 'h-8 px-2.5 text-[13px]' : 'h-10 px-3.5 text-sm'
  const text = `${message ? message.trim() + '\n\n' : ''}${url}`
  const mail = `mailto:${encodeURIComponent(to?.email || '')}?subject=${encodeURIComponent(subject || 'Link')}&body=${encodeURIComponent(text)}`
  const wa = `https://wa.me/${digits(to?.phone)}?text=${encodeURIComponent(text)}`
  const canShare = typeof navigator !== 'undefined' && !!navigator.share
  const item = 'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm hover:bg-slate-100 dark:hover:bg-ink-800'
  return (
    <span className={cn('inline-flex rounded-lg shadow-sm', className)}>
      <button type="button" className={cn(SEG, h, 'rounded-l-lg')} onClick={() => copyText(url, copied)}>{icon ?? <Copy className="size-3.5" />}{label}</button>
      <Tip label="Open in a new tab"><a href={url} target="_blank" rel="noopener" aria-label="Open in a new tab" className={cn(SEG, h, '-ml-px')}><ExternalLink className="size-3.5" /></a></Tip>
      <Popover.Root>
        <Tip label="Send"><Popover.Trigger aria-label="Send link" className={cn(SEG, h, '-ml-px rounded-r-lg')}><Share2 className="size-3.5" /></Popover.Trigger></Tip>
        <Popover.Portal>
          <Popover.Content align="end" sideOffset={6} collisionPadding={12}
            className="z-[70] w-64 rounded-xl bg-white p-1.5 text-slate-800 shadow-xl shadow-slate-900/10 ring-1 ring-slate-200 animate-rise dark:bg-ink-850 dark:text-slate-100 dark:shadow-black/40 dark:ring-ink-700">
            {to?.name && <div className="px-2.5 pb-1 pt-1.5 text-xs text-slate-500 dark:text-slate-400">Send to {to.name}</div>}
            <a className={item} href={mail}><Mail className="size-4 text-slate-500" /><span className="min-w-0 flex-1"><span className="block">Email</span>{to?.email && <span className="block truncate text-xs text-slate-500 dark:text-slate-400">{to.email}</span>}</span></a>
            <a className={item} href={wa} target="_blank" rel="noopener"><MessageCircle className="size-4 text-emerald-600" /><span className="min-w-0 flex-1"><span className="block">WhatsApp</span>{to?.phone && <span className="block truncate text-xs text-slate-500 dark:text-slate-400">{to.phone}</span>}</span></a>
            {canShare && <button type="button" className={item} onClick={() => navigator.share({ title: subject, text: message, url }).catch(() => {})}><Send className="size-4 text-slate-500" />More options…</button>}
            <button type="button" className={item} onClick={() => copyText(text, 'Message copied')}><Copy className="size-4 text-slate-500" />Copy link with message</button>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </span>
  )
}
