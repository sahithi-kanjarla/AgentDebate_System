import { memo, type KeyboardEvent } from 'react'
import type { GraphNode as Node } from '../../lib/graphModel'
import { STAGE, STAGE_SEVERITY_COLORS, stageClusterColor } from '../../lib/palette'
import { clusterFill } from './Defs'

export const QUESTION_HALF_W = 54
export const QUESTION_HALF_H = 28
export const JUDGE_RADIUS = 34

export function nodeLabel(n: Node, columnLabel: string): string {
  if (n.kind === 'question') return 'Question. Open the full text.'
  if (n.kind === 'judge') {
    if (n.status === 'ruled') return `Judge, ruled with ${n.confidence ?? 0} percent confidence`
    if (n.status === 'judging') return 'Judge, reviewing the debate'
    return 'Judge, waiting for the debate to finish'
  }
  const head = `${n.agent}, ${columnLabel}`
  if (n.status === 'thinking') return `${head}, still thinking`
  if (n.status === 'invalid') return `${head}, no usable answer`
  const parts = [head, `Answer ${n.letter}`]
  if (n.confidence !== null) parts.push(`confidence ${n.confidence} percent`)
  if (n.changedMind) parts.push('changed its answer')
  if (n.fallbackUsed) parts.push('answered by a backup')
  return parts.join(', ')
}

interface Props {
  node: Node
  columnLabel: string
  x: number
  y: number
  r: number
  phase: number
  fresh: boolean
  selected: boolean
  related: boolean
  onHover: (id: string | null) => void
  onFocus: (id: string | null) => void
  onSelect: (id: string) => void
}

function Content({ node, r, fresh }: { node: Node; r: number; fresh: boolean }) {
  if (node.kind === 'question') {
    return (
      <>
        <rect
          x={-QUESTION_HALF_W}
          y={-QUESTION_HALF_H}
          width={QUESTION_HALF_W * 2}
          height={QUESTION_HALF_H * 2}
          rx={8}
          fill={STAGE.bg2}
          stroke={STAGE.rule}
          strokeWidth={1.5}
        />
        <text
          className="gtext gtext-serif"
          textAnchor="middle"
          y={-2}
          fontSize={17}
          fontWeight={600}
        >
          Question
        </text>
        <text className="gtext gtext-soft" textAnchor="middle" y={16} fontSize={11}>
          open to read
        </text>
      </>
    )
  }
  if (node.kind === 'judge') {
    const ruled = node.status === 'ruled'
    const conf = node.confidence ?? 0
    const glowR = 44 + conf * 0.55
    return (
      <>
        {ruled && (
          <circle
            className="judge-glow"
            r={glowR}
            fill="url(#judge-glow)"
            opacity={0.35 + conf / 160}
            data-testid="judge-glow"
          />
        )}
        <circle
          r={JUDGE_RADIUS}
          fill={ruled ? '#3a2f14' : STAGE.bg2}
          stroke="#c9a24a"
          strokeWidth={ruled ? 3 : 2}
          strokeDasharray={ruled ? undefined : '5 4'}
          opacity={ruled || node.status === 'judging' ? 1 : 0.7}
        />
        {node.status === 'judging' && <circle className="thinking-ring" r={JUDGE_RADIUS + 6} />}
        <text
          className="gtext gtext-serif"
          textAnchor="middle"
          y={6}
          fontSize={17}
          fontWeight={600}
        >
          Judge
        </text>
        {ruled && (
          <text className="gtext" textAnchor="middle" y={JUDGE_RADIUS + 18} fontSize={12}>
            {conf}%
          </text>
        )}
      </>
    )
  }

  const color = node.clusterId === null ? STAGE.inkSoft : stageClusterColor(node.clusterId)
  if (node.status === 'thinking') {
    return (
      <>
        <circle
          r={r}
          fill={STAGE.bg2}
          stroke={STAGE.inkSoft}
          strokeWidth={1.5}
          strokeDasharray="2 4"
        />
        <circle className="thinking-ring" r={r + 5} />
        <text className="gtext gtext-soft" textAnchor="middle" y={5} fontSize={14}>
          …
        </text>
      </>
    )
  }
  if (node.status === 'invalid') {
    const red = STAGE_SEVERITY_COLORS.high
    const k = r * 0.4
    return (
      <>
        <circle
          r={r}
          fill="none"
          stroke={red}
          strokeWidth={2}
          strokeDasharray="1 4"
          strokeLinecap="round"
        />
        <path
          d={`M${-k},${-k}L${k},${k}M${k},${-k}L${-k},${k}`}
          stroke={red}
          strokeWidth={2.5}
          strokeLinecap="round"
        />
        <text className="gtext gtext-soft" textAnchor="middle" y={r + 16} fontSize={11}>
          no answer
        </text>
      </>
    )
  }
  const fill = clusterFill(node.clusterId ?? 99, color)
  return (
    <>
      <circle r={r} fill={STAGE.bg2} />
      {fill.opacity > 0 && <circle r={r} fill={fill.fill} opacity={fill.opacity} />}
      <circle r={r} fill="url(#node-sheen)" />
      {node.changedMind && fresh && (
        <circle className="flash-ring" r={r + 3} fill="none" stroke={color} strokeWidth={3} />
      )}
      <circle
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={node.changedMind ? 3 : 2.5}
        strokeDasharray={node.changedMind ? '5 3.5' : undefined}
      />
      <text
        className="gtext"
        textAnchor="middle"
        y={r > 20 ? 7 : 5}
        fontSize={r > 20 ? 20 : 15}
        fontWeight={700}
        stroke={STAGE.bg}
        strokeWidth={3.5}
        paintOrder="stroke"
      >
        {node.letter}
      </text>
      {node.confidence !== null && (
        <text className="gtext gtext-soft" textAnchor="middle" y={r + 15} fontSize={11}>
          {node.confidence}%
        </text>
      )}
      {node.changedMind && (
        <g transform={`translate(${r * 0.72},${-r * 0.72})`}>
          <circle r={8} fill="#c9a24a" stroke={STAGE.bg} strokeWidth={2} />
          <path
            d="M-3.2 -1.2H3.2M1.6 -2.8 3.2 -1.2 1.6 .4M3.2 1.6H-3.2M-1.6 0 -3.2 1.6 -1.6 3.2"
            stroke="#1b1405"
            strokeWidth={1.4}
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      )}
      {node.fallbackUsed && (
        <circle
          cx={-r * 0.72}
          cy={-r * 0.72}
          r={4}
          fill={STAGE.inkSoft}
          stroke={STAGE.bg}
          strokeWidth={1.5}
        />
      )}
    </>
  )
}

export const GraphNode = memo(function GraphNode(p: Props) {
  const { node, x, y, r } = p
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      p.onSelect(node.id)
    }
  }
  const ring = (node.kind === 'judge' ? JUDGE_RADIUS : r) + 7
  return (
    <g className="pos" style={{ transform: `translate(${x}px, ${y}px)` }}>
      <g
        className={`gnode node-wrap mark${p.fresh ? ' is-fresh' : ''}`}
        data-node-id={node.id}
        data-node-kind={node.kind}
        data-status={node.status}
        data-cluster={node.clusterId ?? undefined}
        data-changed={node.changedMind ? 'true' : undefined}
        data-selected={p.selected ? 'true' : 'false'}
        data-related={p.related ? 'true' : undefined}
        tabIndex={0}
        role="button"
        aria-label={nodeLabel(node, p.columnLabel)}
        aria-pressed={p.selected}
        onClick={() => p.onSelect(node.id)}
        onKeyDown={onKey}
        onPointerEnter={() => p.onHover(node.id)}
        onPointerLeave={() => p.onHover(null)}
        onFocus={() => p.onFocus(node.id)}
        onBlur={() => p.onFocus(null)}
      >
        <g className="node-body" style={{ ['--phase' as string]: `${-p.phase}s` }}>
          <Content node={node} r={r} fresh={p.fresh} />
        </g>
        {node.kind === 'question' ? (
          <rect
            className="focus-ring"
            x={-QUESTION_HALF_W - 6}
            y={-QUESTION_HALF_H - 6}
            width={(QUESTION_HALF_W + 6) * 2}
            height={(QUESTION_HALF_H + 6) * 2}
            rx={12}
          />
        ) : (
          <circle className="focus-ring" r={ring} />
        )}
      </g>
    </g>
  )
})
