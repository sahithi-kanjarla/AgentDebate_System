/**
 * Debater, severity and answer-cluster colours. The values mirror src/styles/tokens.css (a test keeps
 * them in sync). `css*` helpers return `var(--…)` references for components; the hex tables are for
 * code that cannot read CSS variables (d3 scales, the M4 graph, contrast tests).
 */
import type { Severity } from './types'

export const DEBATER_COLORS = ['#3f4fb8', '#0a6c67', '#9a3b86'] as const
export const DEBATER_TINTS = ['#e4e7f6', '#dcefee', '#f3e3f0'] as const

export const SEVERITY_COLORS: Record<Severity, string> = {
  low: '#8a6d00',
  medium: '#b04e08',
  high: '#b3261e',
}
export const SEVERITY_TINTS: Record<Severity, string> = {
  low: '#f6eecb',
  medium: '#f8e3d3',
  high: '#f7dcda',
}

export const CLUSTER_COLORS = ['#2e6f95', '#566f1a', '#b0446a', '#5b6578'] as const
export const CLUSTER_OTHER_COLOR = '#6b7580'

export const SURFACES = {
  mist: '#e8ecef',
  vellum: '#f6f8f9',
  paper: '#ffffff',
  ink: '#17222e',
  inkSoft: '#44525f',
  rule: '#c5ced6',
  brass: '#8a6a1f',
} as const

export type ClusterPattern = 'solid' | 'stripes' | 'dots' | 'grid' | 'hollow'
const CLUSTER_PATTERNS: ClusterPattern[] = ['solid', 'stripes', 'dots', 'grid']
const CLUSTER_NAMES = ['a', 'b', 'c', 'd'] as const

/** Slot used for the 1-based debater position; the same position always gets the same hue. */
export function debaterSlot(index: number): number {
  return ((index % DEBATER_COLORS.length) + DEBATER_COLORS.length) % DEBATER_COLORS.length
}

export function debaterColor(index: number): string {
  return `var(--color-debater-${debaterSlot(index) + 1})`
}
export function debaterTint(index: number): string {
  return `var(--color-debater-${debaterSlot(index) + 1}-tint)`
}
export function severityColor(severity: Severity): string {
  return `var(--color-severity-${severity})`
}
export function severityTint(severity: Severity): string {
  return `var(--color-severity-${severity}-tint)`
}

/** Cluster ids start at 0 on the server; A, B, C, ... */
export function clusterLetter(clusterId: number): string {
  return String.fromCharCode(65 + (((clusterId % 26) + 26) % 26))
}
export function clusterColor(clusterId: number): string {
  const name = CLUSTER_NAMES[clusterId]
  return name ? `var(--color-cluster-${name})` : 'var(--color-cluster-other)'
}
export function clusterPattern(clusterId: number): ClusterPattern {
  return CLUSTER_PATTERNS[clusterId] ?? 'hollow'
}
