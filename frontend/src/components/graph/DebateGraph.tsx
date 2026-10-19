import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { select } from 'd3-selection'
import { zoom, zoomIdentity, type ZoomBehavior } from 'd3-zoom'
import type { DebateState } from '../../lib/debateState'
import {
  buildGraphModel,
  relatedTo,
  type GraphEdge,
  type GraphModel,
  type GraphNode as GNode,
} from '../../lib/graphModel'
import { capsulePath, computeLayout, edgePath, laneShift, type Layout } from '../../lib/layout'
import { narrate } from '../../lib/narrate'
import { STAGE, STAGE_SEVERITY_COLORS, stageClusterColor } from '../../lib/palette'
import { useFreshIds } from '../../hooks/useFreshIds'
import { usePrefersReducedMotion } from '../../hooks/usePrefersReducedMotion'
import { CritiqueEdge, SEVERITY_WORD } from './CritiqueEdge'
import { GraphDefs } from './Defs'
import { GraphLegend } from './GraphLegend'
import { GraphNode, JUDGE_RADIUS, QUESTION_HALF_W } from './GraphNode'
import { NarratorBar } from './NarratorBar'
import { NodeInspector } from './NodeInspector'

const LEGEND_KEY = 'tribunal.graph.legend'
const MAX_STAGE_H = 700

function readLegendPref(): boolean {
  try {
    const stored = window.localStorage.getItem(LEGEND_KEY)
    if (stored) return stored === 'shown'
  } catch {
    /* fall through to the default */
  }
  // First visit: open on wide screens, closed on narrow ones so the graph comes first.
  return typeof window.matchMedia !== 'function' || !window.matchMedia('(max-width: 639px)').matches
}
function writeLegendPref(open: boolean) {
  try {
    window.localStorage.setItem(LEGEND_KEY, open ? 'shown' : 'hidden')
  } catch {
    /* storage can be unavailable; the legend still works for this visit */
  }
}

interface Pos {
  x: number
  y: number
  r: number
}

function positions(model: GraphModel, layout: Layout): Map<string, Pos> {
  const out = new Map<string, Pos>()
  for (const n of model.nodes) {
    const x = layout.colX[n.column] ?? 0
    if (n.kind === 'answer') {
      out.set(n.id, {
        x,
        y: layout.rowY[n.agentIndex] ?? layout.centerY,
        r: layout.radius(n.confidence),
      })
    } else if (n.kind === 'judge') {
      out.set(n.id, { x, y: layout.centerY, r: JUDGE_RADIUS })
    } else {
      out.set(n.id, { x, y: layout.centerY, r: QUESTION_HALF_W })
    }
  }
  return out
}

function edgeGeometry(
  e: GraphEdge,
  pos: Map<string, Pos>,
): { d: string; ex: number; ey: number } | null {
  const a = pos.get(e.from)
  const b = pos.get(e.to)
  if (!a || !b) return null
  const shift = e.lane !== undefined && e.lanes ? laneShift(e.lane, e.lanes) : 0
  const x1 = a.x + a.r + 3
  const x2 = b.x - b.r - 3
  return { d: edgePath(x1, a.y, x2, b.y, shift), ex: x2, ey: b.y + shift }
}

function critiqueLabel(e: GraphEdge, model: GraphModel, caught: boolean): string {
  const fromRound = model.nodes.find((n) => n.id === e.from)?.round
  const listed = caught ? ' Listed under Mistakes caught.' : ''
  return `${e.critic} flagged a ${SEVERITY_WORD[e.severity!]}-severity problem with ${e.target}'s Round ${fromRound} answer: ${e.issue}${listed}`
}

export interface GraphHighlight {
  edgeIds: ReadonlySet<string>
  nodeIds: ReadonlySet<string>
}

interface Props {
  state: DebateState
  question: string | null
  /** Animate arrivals (a live debate). Finished debates and reduced-motion visitors get a static graph. */
  animate: boolean
  /** Edges and nodes lit from outside the graph (a hovered Mistakes caught item). */
  highlight?: GraphHighlight | null
  /** Called with the critique edge being hovered or focused, or null. */
  onEdgeActive?: (id: string | null) => void
  /** Critique edges that appear under Mistakes caught; they get a ring. */
  caughtEdgeIds?: ReadonlySet<string>
  /** During a replay, how the narrator should announce captions. */
  replay?: { playing: boolean; speed: number } | null
}

export function DebateGraph({
  state,
  question,
  animate,
  highlight = null,
  onEdgeActive,
  caughtEdgeIds,
  replay = null,
}: Props) {
  const reduced = usePrefersReducedMotion()
  const motionOn = animate && !reduced
  const model = useMemo(() => buildGraphModel(state, question), [state, question])
  const layout = useMemo(
    () => computeLayout(model.agents.length || 1, model.columns.length),
    [model.agents.length, model.columns.length],
  )
  const pos = useMemo(() => positions(model, layout), [model, layout])
  const captions = useMemo(() => narrate(model), [model])
  const fresh = useFreshIds(model, motionOn)

  const [hoverId, setHoverId] = useState<string | null>(null)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showRead, setShowRead] = useState(true)
  const [legendOpen, setLegendOpen] = useState(readLegendPref)
  const [tip, setTip] = useState<{ id: string; x: number; y: number; h: number } | null>(null)
  const [stageH, setStageH] = useState<number | null>(null)

  const stageRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const viewportRef = useRef<SVGGElement>(null)
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null)
  const autoFit = useRef(true)
  const drawerRef = useRef<HTMLElement>(null)
  const slotRef = useRef<HTMLDivElement>(null)
  const returnTo = useRef<string | null>(null)

  const activeId = hoverId ?? focusId
  const related = useMemo(() => {
    const own = activeId ? relatedTo(model, activeId) : null
    if (!highlight || (highlight.edgeIds.size === 0 && highlight.nodeIds.size === 0)) return own
    const edgeIds = new Set(own?.edgeIds)
    const nodeIds = new Set(own?.nodeIds)
    for (const id of highlight.nodeIds) nodeIds.add(id)
    for (const id of highlight.edgeIds) {
      edgeIds.add(id)
      const e = model.edges.find((x) => x.id === id)
      if (e) {
        nodeIds.add(e.from)
        nodeIds.add(e.to)
      }
    }
    return { edgeIds, nodeIds }
  }, [model, activeId, highlight])

  // Tell the page which critique edge is active so a linked Mistakes caught item can light up.
  const activeCritique =
    activeId !== null && model.edges.some((e) => e.id === activeId && e.kind === 'critique')
      ? activeId
      : null
  useEffect(() => {
    onEdgeActive?.(activeCritique)
  }, [activeCritique, onEdgeActive])

  // A node can disappear when a replay is scrubbed back; close its inspector rather than show a ghost.
  if (selectedId && !model.nodes.some((n) => n.id === selectedId)) setSelectedId(null)

  // --- pan and zoom (d3-zoom writes the transform straight to the DOM; no React re-render per frame)
  useEffect(() => {
    const svg = svgRef.current
    const g = viewportRef.current
    if (!svg || !g) return
    const z = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.35, 3])
      .filter((ev: Event) => {
        if (ev.type === 'wheel') return (ev as WheelEvent).ctrlKey || (ev as WheelEvent).metaKey
        return !(ev as MouseEvent).button
      })
      .on('zoom', (ev) => {
        g.setAttribute('transform', ev.transform.toString())
        if (ev.sourceEvent) autoFit.current = false
      })
    zoomRef.current = z
    const sel = select(svg)
    sel.call(z).on('dblclick.zoom', null)
    return () => {
      sel.on('.zoom', null)
    }
  }, [])

  const fit = useCallback(() => {
    const svg = svgRef.current
    const z = zoomRef.current
    if (!svg || !z) return
    const rect = svg.getBoundingClientRect()
    if (rect.width === 0) return
    // The scale depends on the width only; the stage then takes the height the content needs.
    const s = Math.min(
      1.25,
      Math.max(0.7, Math.min((rect.width - 16) / layout.width, MAX_STAGE_H / layout.height)),
    )
    const height = Math.round(Math.min(MAX_STAGE_H, Math.max(280, layout.height * s + 28)))
    setStageH(height)
    const w = layout.width * s
    // Too wide for the screen: follow the newest column on a live debate, start at the left otherwise.
    const tx = w <= rect.width ? (rect.width - w) / 2 : motionOn ? rect.width - w - 8 : 8
    const ty = Math.max(8, (height - layout.height * s) / 2)
    select(svg).call(z.transform, zoomIdentity.translate(tx, ty).scale(s))
  }, [layout.width, layout.height, motionOn])

  useEffect(() => {
    if (autoFit.current) fit()
  }, [fit])

  useEffect(() => {
    const svg = svgRef.current
    if (!svg || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => {
      if (autoFit.current) fit()
    })
    ro.observe(svg)
    return () => ro.disconnect()
  }, [fit])

  const zoomBy = (k: number) => {
    if (!svgRef.current || !zoomRef.current) return
    autoFit.current = false
    select(svgRef.current).call(zoomRef.current.scaleBy, k)
  }
  const resetView = () => {
    autoFit.current = true
    fit()
  }
  const onCanvasKey = (e: React.KeyboardEvent<SVGSVGElement>) => {
    if (e.target !== e.currentTarget) return
    const svg = svgRef.current
    const z = zoomRef.current
    if (!svg || !z) return
    const step = 48
    const sel = select(svg)
    const move = (dx: number, dy: number) => {
      autoFit.current = false
      sel.call(z.translateBy, dx, dy)
    }
    if (e.key === '+' || e.key === '=') zoomBy(1.25)
    else if (e.key === '-' || e.key === '_') zoomBy(0.8)
    else if (e.key === '0') resetView()
    else if (e.key === 'ArrowLeft') move(step, 0)
    else if (e.key === 'ArrowRight') move(-step, 0)
    else if (e.key === 'ArrowUp') move(0, step)
    else if (e.key === 'ArrowDown') move(0, -step)
    else return
    e.preventDefault()
  }

  // --- selection and the inspector
  const select_ = useCallback((id: string) => {
    returnTo.current = id
    setSelectedId(id)
  }, [])
  const closeInspector = useCallback(() => {
    setSelectedId(null)
    const id = returnTo.current
    if (id) {
      requestAnimationFrame(() => {
        const el = stageRef.current?.querySelector<SVGElement>(`[data-node-id="${CSS.escape(id)}"]`)
        el?.focus()
      })
    }
  }, [])
  useEffect(() => {
    if (!selectedId) return
    // Narrow screens: the panel is a bottom sheet over the lower half of the screen. A spacer below
    // the page content lets the page scroll so the graph can sit above the sheet; this moves the
    // page only, never the graph's own size, pan or zoom.
    const stage = stageRef.current
    if (stage && window.matchMedia?.('(max-width: 1099px)').matches) {
      const top = stage.getBoundingClientRect().top
      if (top > window.innerHeight * 0.3) window.scrollBy({ top: top - 8 })
    }
    // The panel scrolls on its own: start each node at the top, and never scroll the page.
    if (slotRef.current) slotRef.current.scrollTop = 0
    drawerRef.current?.focus({ preventScroll: true })
  }, [selectedId])

  // --- hover and the critique tooltip
  const onEdgeHover = useCallback(
    (id: string | null, el: Element | null, e?: { clientX: number; clientY: number }) => {
      setHoverId(id)
      const stage = stageRef.current
      if (!id || !el || !stage) return setTip(null)
      const box = stage.getBoundingClientRect()
      const r = el.getBoundingClientRect()
      const x = e ? e.clientX : r.left + r.width / 2
      const y = e ? e.clientY : r.top
      setTip({ id, x: x - box.left, y: y - box.top, h: box.height })
    },
    [],
  )
  const onEdgeFocus = useCallback((id: string | null, el: Element | null) => {
    setFocusId(id)
    const stage = stageRef.current
    if (!id || !el || !stage) return setTip(null)
    const box = stage.getBoundingClientRect()
    const r = el.getBoundingClientRect()
    setTip({ id, x: r.left + r.width / 2 - box.left, y: r.top - box.top, h: box.height })
  }, [])
  const onNodeHover = useCallback((id: string | null) => {
    setHoverId(id)
    setTip(null)
  }, [])
  const onNodeFocus = useCallback((id: string | null) => {
    setFocusId(id)
    setTip(null)
  }, [])

  // --- drawing data
  const critiques = model.edges.filter((e) => e.kind === 'critique')
  const readBatches = useMemo(() => {
    const byRound = new Map<number, string[]>()
    for (const e of model.edges) {
      if (e.kind !== 'read' || e.round === null) continue
      const g = edgeGeometry(e, pos)
      if (g) byRound.set(e.round, [...(byRound.get(e.round) ?? []), g.d])
    }
    return [...byRound].map(([round, ds]) => ({ round, d: ds.join(' '), count: ds.length }))
  }, [model.edges, pos])
  const readOpacity = Math.min(0.14, Math.max(0.06, 0.2 - 0.02 * model.agents.length))
  const tipEdge = tip ? model.edges.find((e) => e.id === tip.id) : undefined
  const nodePhase = (n: GNode) => ((n.agentIndex + 1) * 0.37 + n.column * 0.61) % 2.4
  const dimmed = related !== null

  const nodeCount = model.nodes.length
  const edgeCount = model.edges.length

  return (
    <div
      className="space-y-3"
      data-testid="debate-graph"
      data-nodes={nodeCount}
      data-edges={edgeCount}
    >
      <NarratorBar captions={captions} replay={replay} />

      <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Graph controls">
        <button
          type="button"
          className="graph-btn"
          onClick={() => zoomBy(1.25)}
          aria-label="Zoom in"
        >
          Zoom in
        </button>
        <button
          type="button"
          className="graph-btn"
          onClick={() => zoomBy(0.8)}
          aria-label="Zoom out"
        >
          Zoom out
        </button>
        <button type="button" className="graph-btn" onClick={resetView}>
          Reset view
        </button>
        <button
          type="button"
          className="graph-btn"
          aria-pressed={showRead}
          onClick={() => setShowRead((v) => !v)}
        >
          Reading edges
        </button>
        <button
          type="button"
          className="graph-btn"
          aria-pressed={legendOpen}
          onClick={() => {
            setLegendOpen(!legendOpen)
            writeLegendPref(!legendOpen)
          }}
        >
          Legend
        </button>
        <span className="text-xs text-ink-soft">Drag to pan. Ctrl + scroll or pinch to zoom.</span>
      </div>

      <div
        className="graph-layout"
        style={
          stageH ? ({ ['--stage-h' as string]: `${stageH}px` } as React.CSSProperties) : undefined
        }
      >
        <div ref={stageRef} className="graph-stage">
          <svg
            ref={svgRef}
            className="graph-svg"
            role="group"
            aria-label="Debate graph. Tab through the answers; Enter opens the details. Plus, minus and arrow keys zoom and pan."
            tabIndex={0}
            data-motion={motionOn ? 'on' : 'off'}
            data-dim={dimmed ? 'true' : 'false'}
            style={stageH ? { height: stageH } : undefined}
            onKeyDown={onCanvasKey}
          >
            <GraphDefs />
            <rect width="100%" height="100%" fill={STAGE.bg} />
            <rect width="100%" height="100%" fill="url(#pat-grid-dots)" opacity={0.6} />
            <g ref={viewportRef}>
              {/* column guides and headings */}
              {model.columns.map((c) => (
                <g
                  key={c.index}
                  className="pos"
                  style={{ transform: `translate(${layout.colX[c.index]}px, 0px)` }}
                >
                  <line
                    y1={46}
                    y2={layout.height - 20}
                    stroke={STAGE.grid}
                    strokeDasharray="2 7"
                    strokeWidth={1.5}
                  />
                  <text
                    className="gtext gtext-serif"
                    textAnchor="middle"
                    y={22}
                    fontSize={16}
                    fontWeight={600}
                  >
                    {c.label}
                  </text>
                  <text className="gtext gtext-soft" textAnchor="middle" y={39} fontSize={11}>
                    {c.sublabel}
                  </text>
                </g>
              ))}
              {/* debater labels */}
              {model.agents.map((a, i) => (
                <g key={a.label} transform={`translate(14, ${layout.rowY[i]})`}>
                  <text className="gtext" fontSize={13} fontWeight={600} y={-2}>
                    {a.label}
                  </text>
                  <text className="gtext gtext-soft" fontSize={11} y={13}>
                    {a.persona}
                  </text>
                </g>
              ))}

              {/* cluster halos; a different answer sitting between members is cut out of the halo */}
              <g aria-hidden="true">
                {model.clusters
                  .filter((c) => c.nodeIds.length > 1)
                  .map((c) => {
                    const pts = c.nodeIds.map((id) => pos.get(id)).filter((p): p is Pos => !!p)
                    return (
                      <path
                        key={c.id}
                        className={`mark${fresh.has(c.nodeIds[c.nodeIds.length - 1]!) ? ' is-fresh' : ''}`}
                        d={capsulePath(pts)}
                        fill="none"
                        stroke={stageClusterColor(c.clusterId)}
                        strokeOpacity={0.15}
                        strokeWidth={layout.maxRadius * 2 + 14}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        data-halo={c.id}
                      />
                    )
                  })}
                {model.clusters
                  .filter((c) => c.nodeIds.length > 1)
                  .flatMap((c) => {
                    const ys = c.nodeIds.map((id) => pos.get(id)?.y ?? 0)
                    const [lo, hi] = [Math.min(...ys), Math.max(...ys)]
                    return model.nodes
                      .filter(
                        (n) =>
                          n.kind === 'answer' &&
                          n.column === c.column &&
                          !c.nodeIds.includes(n.id) &&
                          (pos.get(n.id)?.y ?? -1) > lo &&
                          (pos.get(n.id)?.y ?? -1) < hi,
                      )
                      .map((n) => {
                        const p = pos.get(n.id)!
                        return (
                          <circle
                            key={`${c.id}:${n.id}`}
                            cx={p.x}
                            cy={p.y}
                            r={p.r + 11}
                            fill={STAGE.bg}
                            data-cutout={n.id}
                          />
                        )
                      })
                  })}
              </g>

              {/* faint reading edges, batched: one path per round */}
              {showRead && (
                <g aria-hidden="true">
                  {readBatches.map((b) => (
                    <path
                      key={b.round}
                      className="mark"
                      d={b.d}
                      fill="none"
                      stroke={STAGE.inkSoft}
                      strokeOpacity={readOpacity}
                      strokeWidth={1.2}
                      data-edge-kind="read-batch"
                      data-count={b.count}
                    />
                  ))}
                </g>
              )}

              {/* memory, question and judge edges */}
              <g aria-hidden="true">
                {model.edges
                  .filter((e) => e.kind === 'memory' || e.kind === 'question' || e.kind === 'judge')
                  .map((e) => {
                    const g = edgeGeometry(e, pos)
                    if (!g) return null
                    const isJudge = e.kind === 'judge'
                    const conf = model.judgeConfidence ?? 0
                    return (
                      <path
                        key={e.id}
                        className={`mark${fresh.has(e.id) ? ' is-fresh' : ''}`}
                        d={g.d}
                        fill="none"
                        stroke={
                          isJudge ? '#c9a24a' : e.kind === 'question' ? STAGE.inkSoft : STAGE.rule
                        }
                        strokeOpacity={
                          isJudge ? 0.3 + conf / 250 : e.kind === 'question' ? 0.3 : 0.7
                        }
                        strokeWidth={isJudge ? 1.8 + conf / 60 : e.kind === 'question' ? 1.2 : 1.6}
                        strokeDasharray={
                          e.kind === 'memory' &&
                          (model.nodes.find((n) => n.id === e.to)?.status === 'invalid' ||
                            model.nodes.find((n) => n.id === e.from)?.status === 'invalid')
                            ? '3 5'
                            : undefined
                        }
                        data-edge-id={e.id}
                        data-edge-kind={e.kind}
                        data-related={related?.edgeIds.has(e.id) ? 'true' : undefined}
                      />
                    )
                  })}
              </g>

              {/* what the hovered node read */}
              {related && (
                <g aria-hidden="true">
                  {model.edges
                    .filter((e) => e.kind === 'read' && related.edgeIds.has(e.id))
                    .map((e) => {
                      const g = edgeGeometry(e, pos)
                      return g ? (
                        <path
                          key={e.id}
                          d={g.d}
                          fill="none"
                          stroke={STAGE.ink}
                          strokeOpacity={0.5}
                          strokeWidth={1.6}
                          data-edge-kind="read-lit"
                        />
                      ) : null
                    })}
                </g>
              )}

              {/* critique edges */}
              {critiques.map((e) => {
                const g = edgeGeometry(e, pos)
                if (!g) return null
                return (
                  <CritiqueEdge
                    key={e.id}
                    id={e.id}
                    d={g.d}
                    severity={e.severity!}
                    mx={g.ex}
                    my={g.ey}
                    label={critiqueLabel(e, model, caughtEdgeIds?.has(e.id) ?? false)}
                    caught={caughtEdgeIds?.has(e.id) ?? false}
                    related={related?.edgeIds.has(e.id) ?? false}
                    fresh={fresh.has(e.id)}
                    onHover={onEdgeHover}
                    onFocus={onEdgeFocus}
                  />
                )
              })}

              {/* nodes */}
              {model.nodes.map((n) => {
                const p = pos.get(n.id)!
                return (
                  <GraphNode
                    key={n.id}
                    node={n}
                    columnLabel={model.columns[n.column]?.label ?? ''}
                    x={p.x}
                    y={p.y}
                    r={p.r}
                    phase={nodePhase(n)}
                    fresh={fresh.has(n.id)}
                    selected={selectedId === n.id}
                    related={related?.nodeIds.has(n.id) ?? false}
                    onHover={onNodeHover}
                    onFocus={onNodeFocus}
                    onSelect={select_}
                  />
                )
              })}
            </g>
          </svg>

          {tip && tipEdge && (
            <div
              className={`graph-tip${tip.y < tip.h * 0.6 ? ' graph-tip-below' : ''}`}
              role="tooltip"
              style={{ left: tip.x, top: tip.y }}
              data-testid="edge-tip"
            >
              <p
                className="font-medium"
                style={{ color: STAGE_SEVERITY_COLORS[tipEdge.severity!] }}
              >
                {tipEdge.critic} flagged a {SEVERITY_WORD[tipEdge.severity!]}-severity problem with{' '}
                {tipEdge.target}&apos;s answer
              </p>
              <p className="mt-1 whitespace-pre-wrap break-words">{tipEdge.issue}</p>
              {caughtEdgeIds?.has(tipEdge.id) && (
                <p className="mt-1 text-xs text-stage-ink-soft">Listed under Mistakes caught.</p>
              )}
            </div>
          )}
        </div>

        <div
          ref={slotRef}
          className="graph-inspector-slot"
          data-testid="inspector-slot"
          data-open={selectedId ? 'true' : 'false'}
        >
          {selectedId ? (
            <NodeInspector
              ref={drawerRef}
              state={state}
              model={model}
              nodeId={selectedId}
              onClose={closeInspector}
            />
          ) : (
            <p className="inspector-placeholder text-sm text-ink-soft">
              Select a node to read its reasoning.
            </p>
          )}
        </div>
      </div>

      <p className="text-sm text-ink-soft" data-testid="honesty-note">
        This graph shows the reasoning network between agents: who critiqued whom, who changed their
        answer, and how answers converged. It does not show the models&apos; internals.
      </p>

      {selectedId && <div className="graph-sheet-spacer" aria-hidden="true" />}

      {legendOpen && (
        <GraphLegend
          onDismiss={() => {
            setLegendOpen(false)
            writeLegendPref(false)
          }}
        />
      )}
    </div>
  )
}
