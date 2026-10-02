// Styled confirmations instead of the browser's confirm() box: `if (!(await ask('Delete this?'))) return`.
// The first sentence becomes the title and the rest the explanation.
import { TriangleAlert } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Button, Modal } from './ui'

type Ask = { title: ReactNode; body?: ReactNode; confirm: string; cancel: string; danger: boolean; resolve: (ok: boolean) => void }
let show: ((a: Ask) => void) | null = null
const DANGER = /\b(delete|remove|revoke|disable|pause|reject|close|replace|permanently)\b/i

export function ask(text: string, o: { title?: string; confirm?: string; cancel?: string; danger?: boolean } = {}): Promise<boolean> {
  const m = text.match(/^(.+?[?.!])\s+([\s\S]+)$/)
  const title = o.title ?? (m ? m[1]! : text), body = o.title ? text : m ? m[2] : undefined
  const verb = (o.title ?? text).match(/^(\w+)/)?.[1] || 'Confirm'
  return new Promise(resolve => {
    if (!show) { resolve(window.confirm(text)); return }
    show({ title, body, confirm: o.confirm ?? (verb.length < 14 ? verb[0]!.toUpperCase() + verb.slice(1) : 'Confirm'), cancel: o.cancel ?? 'Cancel',
      danger: o.danger ?? DANGER.test(title), resolve })
  })
}

export function DialogHost() {
  const [a, setA] = useState<Ask | null>(null)
  useEffect(() => { show = setA; return () => { show = null } }, [])
  const done = (ok: boolean) => { a?.resolve(ok); setA(null) }
  return (
    <Modal open={!!a} onOpenChange={o => !o && done(false)} title={a?.title} description={a?.body} icon={a?.danger ? <TriangleAlert /> : undefined}
      footer={<><Button onClick={() => done(false)}>{a?.cancel}</Button>
        <Button id="ask-ok" autoFocus variant={a?.danger ? "danger" : "primary"} onClick={() => done(true)}>{a?.confirm}</Button></>} />
  )
}
