/**
 * Fixed-grid positions for the layered Debate Graph, computed with d3-scale (no simulation).
 * Columns have a fixed pitch, so a new round only extends the canvas to the right and existing
 * nodes never move. Works for 2 to 7 debaters and any number of rounds.
 */
import { scaleLinear, scalePoint, scaleSqrt } from 'd3-scale'
import { line, curveBumpX } from 'd3-shape'

export const COLUMN_PITCH = 200
export const GUTTER = 150 // left, for the debater labels
export const HEADER = 64 // top, for the column headings
export const MARGIN_RIGHT = 70
export const MARGIN_BOTTOM = 44

export interface Layout {
  width: number
  height: number
  colX: number[]
  rowY: number[]
  centerY: number
  rowPitch: number
  maxRadius: number
  minRadius: number
  /** Node radius for a confidence of 0..100; unknown confidence uses the middle of the range. */
  radius: (confidence: number | null) => number
}

export function rowPitchFor(agentCount: number): number {
  if (agentCount <= 3) return 112
  if (agentCount <= 5) return 98
  return 88
}

export function computeLayout(agentCount: number, columnCount: number): Layout {
  const agents = Math.max(1, Math.floor(agentCount))
  const columns = Math.max(1, Math.floor(columnCount))
  const rowPitch = rowPitchFor(agents)
  const maxRadius = Math.min(30, rowPitch * 0.34)
  const minRadius = 13

  const xs = scalePoint<number>()
    .domain(Array.from({ length: columns }, (_, i) => i))
    .range([GUTTER + 60, GUTTER + 60 + COLUMN_PITCH * Math.max(0, columns - 1)])
  const ys = scalePoint<number>()
    .domain(Array.from({ length: agents }, (_, i) => i))
    .range([HEADER + rowPitch / 2, HEADER + rowPitch / 2 + rowPitch * (agents - 1)])
    .padding(0)
  const r = scaleSqrt().domain([0, 100]).range([minRadius, maxRadius]).clamp(true)
  const mid = scaleLinear().domain([0, 1]).range([minRadius, maxRadius])

  const colX = Array.from({ length: columns }, (_, i) => xs(i) ?? 0)
  const rowY = Array.from({ length: agents }, (_, i) => ys(i) ?? 0)
  const height = HEADER + rowPitch * agents + MARGIN_BOTTOM
  return {
    width: (colX[columns - 1] ?? 0) + MARGIN_RIGHT,
    height,
    colX,
    rowY,
    centerY: HEADER + (rowPitch * agents) / 2,
    rowPitch,
    maxRadius,
    minRadius,
    radius: (c) => (c === null ? mid(0.5) : r(c)),
  }
}

const bump = line<[number, number]>().curve(curveBumpX)

/** A smooth left-to-right curve; `lane` shifts both ends vertically so parallel edges stay apart. */
export function edgePath(x1: number, y1: number, x2: number, y2: number, shift = 0): string {
  return bump([
    [x1, y1 + shift],
    [x2, y2 + shift],
  ])!
}

/** Offset (px) for the nth of k parallel edges, centred on zero. */
export function laneShift(lane: number, lanes: number, gap = 7): number {
  return (lane - (lanes - 1) / 2) * gap
}

/** A capsule through the given points; stroked wide with round joins it makes a cluster halo. */
export function capsulePath(points: { x: number; y: number }[]): string {
  const pts = [...points].sort((a, b) => a.y - b.y)
  const [head, ...rest] = pts
  if (!head) return ''
  if (rest.length === 0) return `M${head.x},${head.y}`
  return `M${head.x},${head.y}` + rest.map((p) => `L${p.x},${p.y}`).join('')
}

export const MAX_STAGE_H = 700
export const MIN_ZOOM = 0.2
export const MAX_ZOOM = 3

export interface FitView {
  scale: number
  tx: number
  ty: number
  /** The height the stage should take for this content. */
  height: number
}

/**
 * Where the graph sits when it is "fitted": the whole width on screen (down to MIN_ZOOM, so a phone sees
 * every column and can still pan and zoom from there), never bigger than 1.25. When it still does not
 * fit, a live debate follows the newest column and a finished one starts at the left.
 */
export function fitView(
  viewportWidth: number,
  content: { width: number; height: number },
  followNewest: boolean,
): FitView {
  const scale = Math.min(
    1.25,
    Math.max(
      MIN_ZOOM,
      Math.min((viewportWidth - 16) / content.width, MAX_STAGE_H / content.height),
    ),
  )
  const height = Math.round(
    Math.min(MAX_STAGE_H, Math.max(viewportWidth < 600 ? 150 : 280, content.height * scale + 28)),
  )
  const w = content.width * scale
  const tx = w <= viewportWidth ? (viewportWidth - w) / 2 : followNewest ? viewportWidth - w - 8 : 8
  const ty = Math.max(8, (height - content.height * scale) / 2)
  return { scale, tx, ty, height }
}
