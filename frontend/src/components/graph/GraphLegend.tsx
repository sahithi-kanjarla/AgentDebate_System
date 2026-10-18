import type { ReactNode } from 'react'
import type { Severity } from '../../lib/types'
import {
  STAGE,
  STAGE_CLUSTER_COLORS,
  STAGE_SEVERITY_COLORS,
  stageClusterColor,
} from '../../lib/palette'
import { SEVERITY_DASH, SEVERITY_WIDTH, SeverityMarker } from './CritiqueEdge'
import { clusterFill } from './Defs'

const PATTERN_NAMES = ['solid', 'stripes', 'dots', 'grid']

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
  const severities: Severity[] = ['low', 'medium', 'high']
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
      <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <h3 className="mb-1.5 font-sans text-sm font-semibold">Nodes</h3>
          <ul className="space-y-1.5">
            <Row sample={<ClusterSample id={0} />}>
              One debater&apos;s answer in one round. Bigger means more confident.
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
                  <circle cx={24} cy={5} r={5} fill="#c9a24a" stroke={STAGE.bg} strokeWidth={1.5} />
                </Sample>
              }
            >
              Dashed outline and a swap badge: changed its answer.
            </Row>
            <Row
              sample={
                <Sample w={30}>
                  <circle
                    cx={15}
                    cy={13}
                    r={9}
                    fill={STAGE.bg2}
                    stroke={STAGE.inkSoft}
                    strokeDasharray="2 4"
                  />
                  <circle
                    cx={15}
                    cy={13}
                    r={12}
                    fill="none"
                    stroke={STAGE.inkSoft}
                    strokeDasharray="3 4"
                    opacity={0.7}
                  />
                </Sample>
              }
            >
              Pulsing dotted ring: still thinking.
            </Row>
            <Row
              sample={
                <Sample w={30}>
                  <circle
                    cx={15}
                    cy={13}
                    r={10}
                    fill="none"
                    stroke={STAGE_SEVERITY_COLORS.high}
                    strokeWidth={2}
                    strokeDasharray="1 4"
                    strokeLinecap="round"
                  />
                  <path
                    d="M11 9 19 17M19 9 11 17"
                    stroke={STAGE_SEVERITY_COLORS.high}
                    strokeWidth={2.4}
                    strokeLinecap="round"
                  />
                </Sample>
              }
            >
              Red cross: no usable answer.
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
                  />
                  <circle
                    cx={8}
                    cy={6}
                    r={3.5}
                    fill={STAGE.inkSoft}
                    stroke={STAGE.bg}
                    strokeWidth={1.2}
                  />
                </Sample>
              }
            >
              Small grey dot: a backup answered this turn.
            </Row>
            <Row
              sample={
                <Sample w={30}>
                  <circle cx={15} cy={13} r={16} fill="url(#judge-glow)" opacity={0.7} />
                  <circle cx={15} cy={13} r={9} fill="#3a2f14" stroke="#c9a24a" strokeWidth={2.5} />
                </Sample>
              }
            >
              Judge. It glows more when it is more confident.
            </Row>
          </ul>
        </div>

        <div>
          <h3 className="mb-1.5 font-sans text-sm font-semibold">
            Answers: colour, letter and pattern
          </h3>
          <ul className="space-y-1.5">
            {[0, 1, 2, 3].map((id) => (
              <Row key={id} sample={<ClusterSample id={id} />}>
                Answer {String.fromCharCode(65 + id)} ({PATTERN_NAMES[id]})
              </Row>
            ))}
            <Row sample={<ClusterSample id={4} />}>
              Any further answer: grey, hollow, own letter
            </Row>
            <Row
              sample={
                <Sample>
                  <rect
                    x={4}
                    y={3}
                    width={36}
                    height={20}
                    rx={10}
                    fill={STAGE_CLUSTER_COLORS[0]}
                    opacity={0.18}
                  />
                </Sample>
              }
            >
              A soft halo joins debaters who gave the same answer in a round.
            </Row>
          </ul>
        </div>

        <div>
          <h3 className="mb-1.5 font-sans text-sm font-semibold">Edges</h3>
          <ul className="space-y-1.5">
            <Row
              sample={
                <Sample>
                  <path
                    d="M2 18C20 18 24 8 42 8"
                    stroke={STAGE.inkSoft}
                    strokeOpacity={0.35}
                    fill="none"
                  />
                </Sample>
              }
            >
              Faint curve: each debater reads every other debater&apos;s previous answer.
            </Row>
            <Row
              sample={
                <Sample>
                  <path d="M2 13H42" stroke={STAGE.rule} strokeWidth={1.6} fill="none" />
                </Sample>
              }
            >
              Grey line: a debater&apos;s own earlier answer (its memory).
            </Row>
            <Row
              sample={
                <Sample>
                  <path
                    d="M2 13H42"
                    stroke="#c9a24a"
                    strokeOpacity={0.6}
                    strokeWidth={2}
                    fill="none"
                  />
                </Sample>
              }
            >
              Gold line: final answers go to the judge.
            </Row>
          </ul>
          <h3 className="mb-1.5 mt-3 font-sans text-sm font-semibold">Critiques and severity</h3>
          <ul className="space-y-1.5">
            {severities.map((s) => (
              <Row
                key={s}
                sample={
                  <Sample>
                    <path
                      d="M2 13H30"
                      stroke={STAGE_SEVERITY_COLORS[s]}
                      strokeWidth={SEVERITY_WIDTH[s]}
                      strokeDasharray={SEVERITY_DASH[s]}
                      strokeLinecap="round"
                    />
                    <g transform="translate(36,13)">
                      <SeverityMarker severity={s} color={STAGE_SEVERITY_COLORS[s]} />
                    </g>
                  </Sample>
                }
              >
                {s === 'low'
                  ? 'Low: thin dotted, round marker'
                  : s === 'medium'
                    ? 'Medium: dashed, triangle marker'
                    : 'High: thick solid, diamond marker'}
              </Row>
            ))}
          </ul>
          <p className="mt-2 text-sm text-ink-soft">
            A critique line leads from the answer that was criticised into the critic&apos;s next
            answer. The marker sits at the accuser&apos;s end, and a pulse travels along new ones.
          </p>
        </div>
      </div>
    </section>
  )
}
