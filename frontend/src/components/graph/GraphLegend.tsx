import type { ReactNode } from 'react'
import {
  STAGE,
  STAGE_CLUSTER_COLORS,
  STAGE_SEVERITY_COLORS,
  stageClusterColor,
} from '../../lib/palette'
import { SEVERITY_DASH, SEVERITY_WIDTH, SeverityMarker } from './CritiqueEdge'
import { clusterFill } from './Defs'
import { useReveal } from '../reveal/RevealContext'
import { REVEAL_NOTE, modelText } from '../../lib/reveal'

function Sample({ children, w = 44 }: { children: ReactNode; w?: number }) {
  return (
    <svg
      width={w}
      height={26}
      viewBox={`0 0 ${w} 26`}
      aria-hidden="true"
      focusable="false"
      className="shrink-0 rounded-chip"
      style={{ background: STAGE.bg }}
    >
      {children}
    </svg>
  )
}

function Row({ sample, children }: { sample: ReactNode; children: ReactNode }) {
  return (
    <li className="flex items-center gap-2.5 text-sm text-ink">
      {sample}
      <span>{children}</span>
    </li>
  )
}

function ClusterSample({ id }: { id: number }) {
  const color = stageClusterColor(id)
  const fill = clusterFill(id, color)
  return (
    <Sample w={30}>
      <circle cx={15} cy={13} r={10} fill={STAGE.bg2} />
      {fill.opacity > 0 && (
        <circle cx={15} cy={13} r={10} fill={fill.fill} opacity={fill.opacity} />
      )}
      <circle cx={15} cy={13} r={10} fill="none" stroke={color} strokeWidth={2} />
      <text
        x={15}
        y={17}
        textAnchor="middle"
        fontSize={11}
        fontWeight={700}
        fill={STAGE.ink}
        stroke={STAGE.bg}
        strokeWidth={2.5}
        paintOrder="stroke"
      >
        {String.fromCharCode(65 + id)}
      </text>
    </Sample>
  )
}

/** Dismissible key to the graph (uses the pattern defs of the graph's own svg). It sits under the canvas, never over it, so it cannot hide nodes. */
export function GraphLegend({ onDismiss }: { onDismiss: () => void }) {
  const reveal = useReveal()
  return (
    <section
      aria-label="Legend"
      className="rounded-card border border-rule-strong bg-vellum p-4"
      data-testid="legend"
    >
      <header className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-xl">Legend</h2>
        <button type="button" className="graph-btn" onClick={onDismiss}>
          Hide legend
        </button>
      </header>
      <ul className="grid gap-x-8 gap-y-2.5 sm:grid-cols-2">
        <Row sample={<ClusterSample id={0} />}>
          One debater&apos;s answer. The letter is the answer: the same letter means the same
          answer. Bigger means more confident.
        </Row>
        <Row
          sample={
            <Sample w={30}>
              <circle
                cx={15}
                cy={13}
                r={10}
                fill={STAGE.bg2}
                stroke={STAGE_CLUSTER_COLORS[0]}
                strokeWidth={2.5}
                strokeDasharray="5 3.5"
              />
            </Sample>
          }
        >
          Dashed outline: changed its answer.
        </Row>
        <Row
          sample={
            <Sample>
              <path d="M2 13H42" stroke={STAGE.rule} strokeWidth={1.6} fill="none" />
            </Sample>
          }
        >
          Grey line: a debater&apos;s own earlier answer.
        </Row>
        <Row
          sample={
            <Sample>
              <path
                d="M2 18C14 18 16 8 30 8"
                stroke={STAGE_SEVERITY_COLORS.medium}
                strokeWidth={SEVERITY_WIDTH.medium}
                strokeDasharray={SEVERITY_DASH.medium}
                fill="none"
                strokeLinecap="round"
              />
              <g transform="translate(36,8)">
                <SeverityMarker severity="medium" color={STAGE_SEVERITY_COLORS.medium} />
              </g>
            </Sample>
          }
        >
          Coloured line: a critique. The more serious it is, the thicker the line.
        </Row>
        <Row
          sample={
            <Sample w={30}>
              <circle cx={15} cy={13} r={9} fill="#3a2f14" stroke="#c9a24a" strokeWidth={2.5} />
            </Sample>
          }
        >
          Gold circle: the judge.
        </Row>
      </ul>
      <p className="mt-3 text-sm text-ink-soft">
        Hover or click any circle or line for details, including when a debater is still thinking or
        gave no usable answer.
      </p>

      {reveal && (
        <div className="mt-4 border-t border-rule pt-3" data-testid="legend-models">
          <h3 className="mb-1.5 font-sans text-sm font-semibold">Models (revealed)</h3>
          <ul className="grid gap-x-8 gap-y-1 text-sm text-ink sm:grid-cols-2 lg:grid-cols-3">
            {[...reveal.debaters, ...(reveal.judge ? [reveal.judge] : [])].map((e) => (
              <li key={e.label}>
                {e.label}
                {e.persona && e.label !== 'Judge' ? ` (${e.persona})` : ''}:{' '}
                <span className="break-all font-mono text-xs">
                  {e.primary ? modelText(e.primary) : 'unknown'}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs text-ink-soft">
            {REVEAL_NOTE} The answer letters in the graph stay the same.
          </p>
        </div>
      )}
    </section>
  )
}
