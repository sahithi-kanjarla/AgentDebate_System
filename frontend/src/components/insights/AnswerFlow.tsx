import { useId, useMemo } from 'react'
import {
  sankey,
  sankeyLinkHorizontal,
  type SankeyGraph,
  type SankeyLink,
  type SankeyNode,
} from 'd3-sankey'
import {
  answerFlowSummary,
  type AnswerFlow as Flow,
  type FlowLink,
  type FlowNode,
} from '../../lib/answerFlow'
import { STAGE, STAGE_CLUSTER_COLORS, stageClusterColor } from '../../lib/palette'
import { ChartFrame } from './ChartFrame'

const NODE_W = 18
const PAD_X = 30
const PAD_TOP = 50
const PAD_BOTTOM = 14
const COLUMN_PITCH = 168
const NONE_COLOR = '#6f7d8a'
const BRASS = '#c9a24a'

type N = FlowNode & SankeyNode<FlowNode, FlowLink>
type L = FlowLink & SankeyLink<FlowNode, FlowLink>

function nodeColor(n: FlowNode): string {
  return n.kind === 'none' || n.clusterId === null ? NONE_COLOR : stageClusterColor(n.clusterId)
}

/** Patterns for clusters, defined inside this svg so it does not depend on the graph being mounted. */
function Patterns({ uid }: { uid: string }) {
  const [, b, c, d] = STAGE_CLUSTER_COLORS
  return (
    <defs>
      <pattern
        id={`${uid}-p1`}
        width="7"
        height="7"
        patternUnits="userSpaceOnUse"
        patternTransform="rotate(45)"
      >
        <rect width="7" height="7" fill={STAGE.bg} />
        <rect width="3" height="7" fill={b} />
      </pattern>
      <pattern id={`${uid}-p2`} width="7" height="7" patternUnits="userSpaceOnUse">
        <rect width="7" height="7" fill={STAGE.bg} />
        <circle cx="3.5" cy="3.5" r="1.7" fill={c} />
      </pattern>
      <pattern id={`${uid}-p3`} width="7" height="7" patternUnits="userSpaceOnUse">
        <rect width="7" height="7" fill={STAGE.bg} />
        <path d="M0 .75H7M.75 0V7" stroke={d} strokeWidth="1.5" />
      </pattern>
      <pattern
        id={`${uid}-none`}
        width="6"
        height="6"
        patternUnits="userSpaceOnUse"
        patternTransform="rotate(-45)"
      >
        <rect width="6" height="6" fill={STAGE.bg} />
        <rect width="1.6" height="6" fill={NONE_COLOR} />
      </pattern>
    </defs>
  )
}

function nodeFill(n: FlowNode, uid: string): string {
  if (n.kind === 'none') return `url(#${uid}-none)`
  if (n.clusterId === 0) return nodeColor(n)
  if (n.clusterId !== null && n.clusterId >= 1 && n.clusterId <= 3)
    return `url(#${uid}-p${n.clusterId})`
  return STAGE.bg
}

function describeNode(n: FlowNode, col: string): string {
  const who = n.agents.join(', ')
  const what = n.kind === 'none' ? 'no valid answer' : `answer ${n.letter}`
  return `${col}: ${what}, ${n.count} ${n.count === 1 ? 'debater' : 'debaters'} (${who})${n.winner ? ', the judge’s answer' : ''}`
}

/**
 * The Sankey: columns are rounds, bands are the debaters who stayed with an answer (solid) or
 * switched (a dashed line through the band), so wrong answers visibly shrink and the winner grows.
 */
export function AnswerFlow({ flow }: { flow: Flow }) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '')

  const layout = useMemo(() => {
    const cols = flow.columns.length
    if (cols === 0 || flow.nodes.length === 0) return null
    const width = Math.max(520, PAD_X * 2 + COLUMN_PITCH * (cols - 1) + NODE_W + 150)
    const unit = 34 // pixels per debater in the tallest column
    const tallest = Math.max(
      ...flow.columns.map((c) => flow.nodes.filter((n) => n.column === c.index).length),
    )
    const height = Math.max(200, PAD_TOP + PAD_BOTTOM + flow.debaters * unit + (tallest - 1) * 28)
    const graph: SankeyGraph<FlowNode, FlowLink> = {
      nodes: flow.nodes.map((n) => ({ ...n })),
      links: flow.links.map((l) => ({ ...l })),
    }
    const g = sankey<FlowNode, FlowLink>()
      .nodeId((n) => n.id)
      .nodeAlign((n) => (n as unknown as FlowNode).column)
      .nodeSort((a, b) => a.order - b.order)
      .nodeWidth(NODE_W)
      .nodePadding(28)
      .extent([
        [PAD_X, PAD_TOP],
        [width - 150, height - PAD_BOTTOM],
      ])(graph)
    return { width, height, nodes: g.nodes as N[], links: g.links as L[] }
  }, [flow])

  const table = {
    caption: 'Debaters supporting each answer in each round',
    head: ['Answer', ...flow.columns.map((c) => c.label)],
    rows: answerRows(flow),
  }

  const link = sankeyLinkHorizontal<FlowNode, FlowLink>()

  return (
    <ChartFrame title="Answer flow" summary={answerFlowSummary(flow)} table={table}>
      {({ title, titleId, descId }) =>
        !layout ? (
          <p
            className="insights-empty"
            role="img"
            aria-labelledby={titleId}
            aria-describedby={descId}
          >
            <span id={titleId} className="sr-only">
              {title}
            </span>
            The answer flow appears once the first round has finished.
          </p>
        ) : (
          <>
            <div
              className="insights-scroll"
              tabIndex={0}
              role="region"
              aria-label="Answer flow, scrolls sideways"
            >
              <svg
                className="insights-svg insights-flow"
                viewBox={`0 0 ${layout.width} ${layout.height}`}
                style={{
                  minWidth: layout.width,
                  width: '100%',
                  maxWidth: layout.width * 1.5,
                  height: 'auto',
                }}
                role="img"
                aria-labelledby={titleId}
                aria-describedby={descId}
                data-testid="answer-flow"
              >
                <title id={titleId}>{title}</title>
                <Patterns uid={uid} />
                {layout.links.some((l) => l.kind === 'move') && (
                  <defs>
                    {layout.links
                      .filter((l) => l.kind === 'move')
                      .map((l) => {
                        const s = l.source as N
                        const t = l.target as N
                        return (
                          <linearGradient
                            key={l.id}
                            id={`${uid}-g-${l.id.replace(/[^a-zA-Z0-9]/g, '_')}`}
                            gradientUnits="userSpaceOnUse"
                            x1={s.x1}
                            x2={t.x0}
                          >
                            <stop offset="0%" stopColor={nodeColor(s)} />
                            <stop offset="100%" stopColor={nodeColor(t)} />
                          </linearGradient>
                        )
                      })}
                  </defs>
                )}

                {flow.columns.map((c) => {
                  const first = layout.nodes.find((n) => n.column === c.index)
                  if (!first) return null
                  return (
                    <text
                      key={c.index}
                      className="gtext"
                      x={first.x0! + NODE_W / 2}
                      y={22}
                      textAnchor="middle"
                      fontSize={13}
                      fontWeight={600}
                    >
                      {c.label}
                    </text>
                  )
                })}

                <g fill="none">
                  {layout.links.map((l) => {
                    const s = l.source as N
                    const t = l.target as N
                    const move = l.kind === 'move'
                    const d = link(l as never) ?? undefined
                    return (
                      <g key={l.id} data-link={l.id} data-kind={l.kind}>
                        <title>{`${l.agents.join(', ')}: ${
                          move ? 'switched' : 'kept the answer'
                        } (${l.value})`}</title>
                        <path
                          d={d}
                          stroke={
                            move
                              ? `url(#${uid}-g-${l.id.replace(/[^a-zA-Z0-9]/g, '_')})`
                              : nodeColor(s)
                          }
                          strokeOpacity={move ? 0.5 : 0.36}
                          strokeWidth={Math.max(2, l.width ?? 0)}
                        />
                        {move && (
                          <path
                            d={d}
                            stroke={STAGE.ink}
                            strokeOpacity={0.85}
                            strokeWidth={1.6}
                            strokeDasharray="5 5"
                          />
                        )}
                        <desc>{`${s.id} to ${t.id}`}</desc>
                      </g>
                    )
                  })}
                </g>

                {layout.nodes.map((n) => {
                  const h = Math.max(4, (n.y1 ?? 0) - (n.y0 ?? 0))
                  const col = flow.columns[n.column]?.label ?? ''
                  const color = nodeColor(n)
                  const last = n.column === flow.columns.length - 1
                  return (
                    <g key={n.id} data-node={n.id} data-winner={n.winner ? 'true' : undefined}>
                      <title>{describeNode(n, col)}</title>
                      <rect
                        x={n.x0}
                        y={n.y0}
                        width={NODE_W}
                        height={h}
                        rx={2}
                        fill={nodeFill(n, uid)}
                        stroke={n.winner ? BRASS : color}
                        strokeWidth={n.winner ? 3 : 1.8}
                      />
                      <text
                        className="gtext"
                        x={last ? (n.x1 ?? 0) + 9 : (n.x0 ?? 0)}
                        y={last ? (n.y0 ?? 0) + h / 2 - (n.winner ? 6 : 0) : (n.y0 ?? 0) - 8}
                        dominantBaseline={last ? 'middle' : 'auto'}
                        fontSize={12.5}
                        fontWeight={600}
                      >
                        {n.kind === 'none' ? 'No valid answer' : `Answer ${n.letter}`}
                        {' · '}
                        {n.count}
                      </text>
                      {n.winner && (
                        <text
                          className="gtext"
                          x={(n.x1 ?? 0) + 9}
                          y={(n.y0 ?? 0) + h / 2 + 10}
                          dominantBaseline="middle"
                          fontSize={11.5}
                          style={{ fill: BRASS }}
                        >
                          Judge’s answer
                        </text>
                      )}
                    </g>
                  )
                })}
              </svg>
            </div>
            <AnswerKey flow={flow} />
          </>
        )
      }
    </ChartFrame>
  )
}

/** Which letter is which answer, printed as received (whitespace kept) and clamped in height. */
function AnswerKey({ flow }: { flow: Flow }) {
  const latest = new Map<number, FlowNode>()
  for (const n of flow.nodes)
    if (n.kind === 'cluster' && n.clusterId !== null) latest.set(n.clusterId, n)
  const items = [...latest.values()].sort((a, b) => (a.clusterId ?? 0) - (b.clusterId ?? 0))
  if (items.length === 0) return null
  return (
    <ul className="insights-key" aria-label="What each answer letter stands for">
      {items.map((n) => (
        <li key={n.clusterId}>
          <span className="insights-key-letter" style={{ borderColor: nodeColor(n) }}>
            {n.letter}
          </span>
          <span className="insights-key-answer answer-text">{n.answer}</span>
        </li>
      ))}
    </ul>
  )
}

/** Rows for the table: one per distinct answer text/bucket, with its count in every round. */
function answerRows(flow: Flow): (string | number)[][] {
  const keys: { key: string; label: string }[] = []
  const seen = new Set<string>()
  for (const n of flow.nodes) {
    const key = n.kind === 'none' ? 'none' : `c${n.clusterId}`
    if (seen.has(key)) continue
    seen.add(key)
    keys.push({
      key,
      label: n.kind === 'none' ? 'No valid answer' : `Answer ${n.letter}: ${n.answer}`,
    })
  }
  return keys.map(({ key, label }) => [
    label,
    ...flow.columns.map((c) => {
      const n = flow.nodes.find(
        (x) => x.column === c.index && (x.kind === 'none' ? 'none' : `c${x.clusterId}`) === key,
      )
      return n ? n.count : 0
    }),
  ])
}
