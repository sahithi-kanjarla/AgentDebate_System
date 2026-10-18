import { STAGE, STAGE_CLUSTER_COLORS } from '../../lib/palette'

/** Fill patterns for answer clusters (solid, stripes, dots, grid; hollow has none) and the judge glow. */
export function GraphDefs() {
  const [, b, c, d] = STAGE_CLUSTER_COLORS
  return (
    <defs>
      <pattern id="pat-grid-dots" width="28" height="28" patternUnits="userSpaceOnUse">
        <circle cx="2" cy="2" r="1" fill={STAGE.grid} />
      </pattern>
      <pattern
        id="pat-1"
        width="7"
        height="7"
        patternUnits="userSpaceOnUse"
        patternTransform="rotate(45)"
      >
        <rect width="3" height="7" fill={b} />
      </pattern>
      <pattern id="pat-2" width="7" height="7" patternUnits="userSpaceOnUse">
        <circle cx="3.5" cy="3.5" r="1.5" fill={c} />
      </pattern>
      <pattern id="pat-3" width="7" height="7" patternUnits="userSpaceOnUse">
        <path d="M0 .75H7M.75 0V7" stroke={d} strokeWidth="1.5" />
      </pattern>
      <radialGradient id="judge-glow">
        <stop offset="0%" stopColor="#c9a24a" stopOpacity="0.9" />
        <stop offset="45%" stopColor="#c9a24a" stopOpacity="0.28" />
        <stop offset="100%" stopColor="#c9a24a" stopOpacity="0" />
      </radialGradient>
      <radialGradient id="node-sheen" cx="35%" cy="30%">
        <stop offset="0%" stopColor="#ffffff" stopOpacity="0.14" />
        <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
      </radialGradient>
    </defs>
  )
}

/** The fill a cluster's node gets inside its ring. */
export function clusterFill(clusterId: number, color: string): { fill: string; opacity: number } {
  if (clusterId === 0) return { fill: color, opacity: 0.5 }
  if (clusterId >= 1 && clusterId <= 3) return { fill: `url(#pat-${clusterId})`, opacity: 0.85 }
  return { fill: 'none', opacity: 0 } // hollow
}
