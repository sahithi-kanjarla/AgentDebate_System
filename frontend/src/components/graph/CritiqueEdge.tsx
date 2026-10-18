import { memo } from 'react'
import type { Severity } from '../../lib/types'
import { STAGE, STAGE_SEVERITY_COLORS } from '../../lib/palette'

export const SEVERITY_WIDTH: Record<Severity, number> = { low: 1.6, medium: 2.8, high: 4.4 }
export const SEVERITY_DASH: Record<Severity, string | undefined> = {
  low: '1.5 6',
  medium: '9 5',
  high: undefined,
}
export const SEVERITY_WORD: Record<Severity, string> = {
  low: 'low',
  medium: 'medium',
  high: 'high',
}

/** Severity marker at the accuser's end: dot (low), triangle (medium), diamond (high). */
export function SeverityMarker({ severity, color }: { severity: Severity; color: string }) {
  const common = { fill: color, stroke: STAGE.bg, strokeWidth: 1.6 }
  if (severity === 'low') return <circle r={5} {...common} />
  if (severity === 'medium')
    return <path d="M0 -6.5 6.5 5 -6.5 5z" {...common} strokeLinejoin="round" />
  return <path d="M0 -8 8 0 0 8 -8 0z" {...common} strokeLinejoin="round" />
}

interface Props {
  id: string
  d: string
  severity: Severity
  /** End point (the critic's node) for the marker. */
  mx: number
  my: number
  label: string
  related: boolean
  fresh: boolean
  onHover: (id: string | null, el: Element | null, e?: { clientX: number; clientY: number }) => void
  onFocus: (id: string | null, el: Element | null) => void
}

export const CritiqueEdge = memo(function CritiqueEdge(p: Props) {
  const color = STAGE_SEVERITY_COLORS[p.severity]
  const w = SEVERITY_WIDTH[p.severity]
  return (
    <g
      className={`gedge mark${p.fresh ? ' is-fresh' : ''}`}
      data-edge-id={p.id}
      data-edge-kind="critique"
      data-severity={p.severity}
      data-related={p.related ? 'true' : undefined}
      tabIndex={0}
      role="img"
      aria-label={p.label}
      onPointerEnter={(e) => p.onHover(p.id, e.currentTarget, e)}
      onPointerMove={(e) => p.onHover(p.id, e.currentTarget, e)}
      onPointerLeave={() => p.onHover(null, null)}
      onFocus={(e) => p.onFocus(p.id, e.currentTarget)}
      onBlur={() => p.onFocus(null, null)}
    >
      <path className="hit" d={p.d} strokeWidth={18} />
      <path
        d={p.d}
        fill="none"
        stroke={color}
        strokeWidth={w + 7}
        strokeOpacity={0.14}
        strokeLinecap="round"
      />
      <path
        className="line focus-ring-line"
        d={p.d}
        fill="none"
        stroke={color}
        strokeWidth={w}
        strokeDasharray={SEVERITY_DASH[p.severity]}
        strokeLinecap="round"
      />
      {p.fresh && (
        <path
          className="pulse"
          d={p.d}
          pathLength={1}
          stroke="#ffffff"
          strokeWidth={w + 2}
          strokeDasharray="0.14 1"
          strokeOpacity={0.9}
        />
      )}
      <g transform={`translate(${p.mx - 10},${p.my})`}>
        <SeverityMarker severity={p.severity} color={color} />
      </g>
    </g>
  )
})
