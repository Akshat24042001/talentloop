// Report charts: spider (radar), donut and a score distribution. No chart library: each is a few
// dozen lines, follows the theme's series/status colours (validated for colour-blind separation in light and dark),
// has a legend or direct labels, a hover tooltip, and an aria-label carrying the numbers.
import { useState } from 'react'

interface Tip { x: number; y: number; text: string }
function Tooltip({ t }: { t: Tip | null }) {
  if (!t) return null
  return <div className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-lg bg-slate-900 px-2 py-1 text-xs text-white shadow-lg dark:bg-white dark:text-ink-900"
    style={{ left: t.x, top: t.y - 8 }}>{t.text}</div>
}

/** Spider chart: one axis per signal (0-100), one or two series. */
export function Radar({ axes, series, size = 280 }: { axes: string[]; series: { label: string; values: number[]; color: string; dashed?: boolean }[]; size?: number }) {
  const [tip, setTip] = useState<Tip | null>(null)
  const pad = 58, r = (size - pad * 2) / 2, cx = size / 2, cy = size / 2, n = axes.length
  const pt = (i: number, v: number) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / n; return [cx + Math.cos(a) * r * v / 100, cy + Math.sin(a) * r * v / 100] as const }
  const label = series.map(s => `${s.label}: ${axes.map((a, i) => `${a} ${Math.round(s.values[i] ?? 0)}`).join(', ')}`).join('. ')
  return (
    <div className="relative mx-auto w-fit">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} className="overflow-visible">
        {[25, 50, 75, 100].map(g => <polygon key={g} points={axes.map((_, i) => pt(i, g).join(',')).join(' ')} fill="none" className="stroke-slate-200 dark:stroke-ink-700" strokeWidth={1} />)}
        {axes.map((a, i) => { const [x, y] = pt(i, 100), [lx, ly] = pt(i, 122); return (
          <g key={a}><line x1={cx} y1={cy} x2={x} y2={y} className="stroke-slate-200 dark:stroke-ink-700" strokeWidth={1} />
            <text x={lx} y={ly} textAnchor={Math.abs(lx - cx) < 4 ? 'middle' : lx > cx ? 'start' : 'end'} dominantBaseline="middle" className="fill-slate-600 text-[11px] font-medium dark:fill-slate-300">{a}</text></g>) })}
        {series.map(s => (
          <g key={s.label}>
            <polygon points={s.values.map((v, i) => pt(i, v).join(',')).join(' ')} fill={s.color} fillOpacity={s.dashed ? 0 : 0.16} stroke={s.color} strokeWidth={2} strokeDasharray={s.dashed ? '5 4' : undefined} strokeLinejoin="round" />
            {s.values.map((v, i) => { const [x, y] = pt(i, v); return (
              <g key={i} onMouseEnter={() => setTip({ x, y, text: `${s.label} · ${axes[i]}: ${Math.round(v)}` })} onMouseLeave={() => setTip(null)}>
                <circle cx={x} cy={y} r={12} fill="transparent" />
                <circle cx={x} cy={y} r={4} fill={s.color} className="stroke-white dark:stroke-ink-900" strokeWidth={2} />
              </g>) })}
          </g>))}
      </svg>
      <Tooltip t={tip} />
      <div className="mt-1 flex flex-wrap justify-center gap-4 text-xs text-slate-600 dark:text-slate-300">{series.map(s => (
        <span key={s.label} className="flex items-center gap-1.5"><svg width="18" height="8"><line x1="1" y1="4" x2="17" y2="4" stroke={s.color} strokeWidth={2} strokeDasharray={s.dashed ? '4 3' : undefined} /></svg>{s.label}</span>))}</div>
    </div>
  )
}

/** Donut with a 2px surface gap between segments and the total in the middle. */
export function Donut({ parts, center, sub, size = 150 }: { parts: { label: string; value: number; color: string }[]; center: string; sub?: string; size?: number }) {
  const [tip, setTip] = useState<Tip | null>(null)
  const total = parts.reduce((a, p) => a + p.value, 0) || 1, r = size / 2 - 10, c = 2 * Math.PI * r
  let off = 0
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="relative">
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={parts.map(p => `${p.label} ${p.value}`).join(', ')}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--track)" strokeWidth={16} />
          {parts.filter(p => p.value > 0).map(p => {
            const len = (p.value / total) * c, gap = parts.filter(x => x.value > 0).length > 1 ? 2 : 0
            const el = <circle key={p.label} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={p.color} strokeWidth={16} strokeDasharray={`${Math.max(0, len - gap)} ${c}`}
              strokeDashoffset={-off} transform={`rotate(-90 ${size / 2} ${size / 2})`}
              onMouseEnter={() => setTip({ x: size / 2, y: 14, text: `${p.label}: ${p.value} (${Math.round(p.value / total * 100)}%)` })} onMouseLeave={() => setTip(null)} />
            off += len
            return el
          })}
          <text x="50%" y="48%" textAnchor="middle" dominantBaseline="middle" className="fill-slate-900 text-xl font-semibold tabular-nums dark:fill-slate-100">{center}</text>
          {sub && <text x="50%" y="63%" textAnchor="middle" className="fill-slate-500 text-[11px] dark:fill-slate-400">{sub}</text>}
        </svg>
        <Tooltip t={tip} />
      </div>
      <ul className="space-y-1.5 text-sm">{parts.map(p => (
        <li key={p.label} className="flex items-center gap-2"><i className="size-2.5 rounded-sm" style={{ background: p.color }} /><span className="text-slate-600 dark:text-slate-300">{p.label}</span><b className="tabular-nums">{p.value}</b></li>))}</ul>
    </div>
  )
}

/** How everyone scored for the job (bins of 10), with this candidate's bin highlighted and marked. */
export function Distribution({ scores, mine, height = 110 }: { scores: number[]; mine: number; height?: number }) {
  const [tip, setTip] = useState<Tip | null>(null)
  const bins = Array.from({ length: 10 }, (_, i) => scores.filter(s => (i === 9 ? s >= 90 : s >= i * 10 && s < i * 10 + 10)).length)
  const max = Math.max(1, ...bins), W = 320, bw = W / 10, myBin = Math.min(9, Math.floor(mine / 10))
  const above = scores.filter(s => s > mine).length
  return (
    <div className="relative">
      <svg width="100%" viewBox={`0 0 ${W} ${height + 18}`} role="img" aria-label={`${scores.length} candidates scored; ${above} scored higher than this candidate (${Math.round(mine)}).`}>
        <line x1={0} y1={height} x2={W} y2={height} className="stroke-slate-200 dark:stroke-ink-700" />
        {bins.map((n, i) => { const h = n ? Math.max(3, (n / max) * (height - 14)) : 0, x = i * bw + 2; return (
          <g key={i} onMouseEnter={() => setTip({ x: ((x + bw / 2) / W) * 100, y: height - h, text: `${i * 10}-${i === 9 ? 100 : i * 10 + 9}: ${n} candidate${n === 1 ? '' : 's'}` })} onMouseLeave={() => setTip(null)}>
            <rect x={i * bw} y={0} width={bw} height={height} fill="transparent" />
            {n > 0 && <path d={`M${x},${height} v${-(h - 4)} q0,-4 4,-4 h${bw - 12} q4,0 4,4 v${h - 4} z`} fill={i === myBin ? 'var(--series-1)' : 'var(--track)'} className={i === myBin ? '' : 'stroke-slate-300 dark:stroke-ink-600'} strokeWidth={i === myBin ? 0 : 1} />}
            {i % 2 === 0 && <text x={i * bw} y={height + 13} textAnchor={i === 0 ? 'start' : 'middle'} className="fill-slate-500 text-[10px] dark:fill-slate-400">{i * 10}</text>}
          </g>) })}
        <text x={W} y={height + 13} textAnchor="end" className="fill-slate-500 text-[10px] dark:fill-slate-400">100</text>
      </svg>
      {tip && <div className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-lg bg-slate-900 px-2 py-1 text-xs text-white dark:bg-white dark:text-ink-900" style={{ left: `${tip.x}%`, top: tip.y }}>{tip.text}</div>}
      <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">{scores.length > 1 ? <><b className="text-slate-900 dark:text-slate-100">{above === 0 ? 'Highest score' : `${above} of ${scores.length}`}</b>{above === 0 ? ` of ${scores.length} candidates scored.` : ' candidates scored higher.'} Highlighted: this candidate's range.</> : 'Only this candidate has been scored.'}</p>
    </div>
  )
}
