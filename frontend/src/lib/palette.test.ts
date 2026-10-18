import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  CLUSTER_COLORS,
  CLUSTER_OTHER_COLOR,
  DEBATER_COLORS,
  DEBATER_TINTS,
  SEVERITY_COLORS,
  SEVERITY_TINTS,
  STAGE,
  STAGE_CLUSTER_COLORS,
  STAGE_CLUSTER_OTHER_COLOR,
  STAGE_SEVERITY_COLORS,
  SURFACES,
  clusterColor,
  clusterLetter,
  clusterPattern,
  debaterColor,
  debaterSlot,
  severityColor,
  stageClusterColor,
} from './palette'

// Read from disk: the vitest config turns CSS imports into empty modules.
const tokensCss = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf-8')

function tokens(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of tokensCss.matchAll(/--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    out[m[1]!] = m[2]!.toLowerCase()
  }
  return out
}

function luminance(hex: string): number {
  const channel = (i: number) => {
    const c = Number.parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2)
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}

describe('palette.ts mirrors tokens.css', () => {
  const css = tokens()

  it('debater colours and tints', () => {
    DEBATER_COLORS.forEach((hex, i) => expect(css[`debater-${i + 1}`]).toBe(hex))
    DEBATER_TINTS.forEach((hex, i) => expect(css[`debater-${i + 1}-tint`]).toBe(hex))
  })

  it('severity colours and tints', () => {
    for (const s of ['low', 'medium', 'high'] as const) {
      expect(css[`severity-${s}`]).toBe(SEVERITY_COLORS[s])
      expect(css[`severity-${s}-tint`]).toBe(SEVERITY_TINTS[s])
    }
  })

  it('cluster colours and surfaces', () => {
    ;(['a', 'b', 'c', 'd'] as const).forEach((n, i) =>
      expect(css[`cluster-${n}`]).toBe(CLUSTER_COLORS[i]),
    )
    expect(css['cluster-other']).toBe(CLUSTER_OTHER_COLOR)
    expect(css.mist).toBe(SURFACES.mist)
    expect(css.vellum).toBe(SURFACES.vellum)
    expect(css.paper).toBe(SURFACES.paper)
    expect(css.ink).toBe(SURFACES.ink)
    expect(css['ink-soft']).toBe(SURFACES.inkSoft)
    expect(css.rule).toBe(SURFACES.rule)
    expect(css.brass).toBe(SURFACES.brass)
  })
})

describe('contrast (WCAG AA)', () => {
  const grounds = [SURFACES.mist, SURFACES.vellum, SURFACES.paper]

  it('body text on every surface is at least 4.5:1', () => {
    for (const g of grounds) {
      expect(contrast(SURFACES.ink, g)).toBeGreaterThanOrEqual(4.5)
      expect(contrast(SURFACES.inkSoft, g)).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('brass text on vellum and paper is at least 4.5:1', () => {
    expect(contrast(SURFACES.brass, SURFACES.vellum)).toBeGreaterThanOrEqual(4.5)
    expect(contrast(SURFACES.brass, SURFACES.paper)).toBeGreaterThanOrEqual(4.5)
  })

  it('debater colours as text on their tint and on vellum are at least 4.5:1', () => {
    DEBATER_COLORS.forEach((c, i) => {
      expect(contrast(c, DEBATER_TINTS[i]!)).toBeGreaterThanOrEqual(4.5)
      expect(contrast(c, SURFACES.vellum)).toBeGreaterThanOrEqual(4.5)
    })
  })

  it('severity and cluster colours (icons, swatches, borders) are at least 3:1', () => {
    for (const s of ['low', 'medium', 'high'] as const) {
      expect(contrast(SEVERITY_COLORS[s], SEVERITY_TINTS[s])).toBeGreaterThanOrEqual(3)
      expect(contrast(SEVERITY_COLORS[s], SURFACES.paper)).toBeGreaterThanOrEqual(3)
    }
    for (const c of [...CLUSTER_COLORS, CLUSTER_OTHER_COLOR]) {
      expect(contrast(c, SURFACES.paper)).toBeGreaterThanOrEqual(3)
    }
  })
})

describe('helpers', () => {
  it('keeps the three debater colours, severities and four clusters distinct', () => {
    expect(new Set(DEBATER_COLORS).size).toBe(3)
    expect(new Set(Object.values(SEVERITY_COLORS)).size).toBe(3)
    expect(new Set([...CLUSTER_COLORS, CLUSTER_OTHER_COLOR]).size).toBe(5)
  })

  it('maps positions to debater colours, wrapping safely', () => {
    expect(debaterColor(0)).toBe('var(--color-debater-1)')
    expect(debaterColor(2)).toBe('var(--color-debater-3)')
    expect(debaterSlot(3)).toBe(0)
    expect(debaterSlot(-1)).toBe(2)
    expect(severityColor('high')).toBe('var(--color-severity-high)')
  })

  it('gives each cluster a letter and a pattern, falling back after four', () => {
    expect([0, 1, 2].map(clusterLetter)).toEqual(['A', 'B', 'C'])
    expect([0, 1, 2, 3].map(clusterPattern)).toEqual(['solid', 'stripes', 'dots', 'grid'])
    expect(new Set([0, 1, 2, 3].map(clusterPattern)).size).toBe(4)
    expect(clusterPattern(7)).toBe('hollow')
    expect(clusterColor(7)).toBe('var(--color-cluster-other)')
  })
})

describe('debate graph stage', () => {
  const css = tokens()

  it('mirrors tokens.css', () => {
    expect(css['stage-bg']).toBe(STAGE.bg)
    expect(css['stage-bg-2']).toBe(STAGE.bg2)
    expect(css['stage-grid']).toBe(STAGE.grid)
    expect(css['stage-ink']).toBe(STAGE.ink)
    expect(css['stage-ink-soft']).toBe(STAGE.inkSoft)
    expect(css['stage-rule']).toBe(STAGE.rule)
    ;(['a', 'b', 'c', 'd'] as const).forEach((n, i) =>
      expect(css[`stage-cluster-${n}`]).toBe(STAGE_CLUSTER_COLORS[i]),
    )
    expect(css['stage-cluster-other']).toBe(STAGE_CLUSTER_OTHER_COLOR)
    for (const s of ['low', 'medium', 'high'] as const) {
      expect(css[`stage-severity-${s}`]).toBe(STAGE_SEVERITY_COLORS[s])
    }
  })

  it('text is at least 4.5:1 and marks at least 3:1 on the stage', () => {
    for (const g of [STAGE.bg, STAGE.bg2]) {
      expect(contrast(STAGE.ink, g)).toBeGreaterThanOrEqual(4.5)
      expect(contrast(STAGE.inkSoft, g)).toBeGreaterThanOrEqual(4.5)
      for (const c of [...STAGE_CLUSTER_COLORS, STAGE_CLUSTER_OTHER_COLOR]) {
        expect(contrast(c, g)).toBeGreaterThanOrEqual(4.5)
      }
      for (const c of Object.values(STAGE_SEVERITY_COLORS)) {
        expect(contrast(c, g)).toBeGreaterThanOrEqual(3)
      }
    }
    expect(contrast(STAGE.rule, STAGE.bg)).toBeGreaterThanOrEqual(3)
  })

  it('uses the neutral colour from the fifth answer on', () => {
    expect(stageClusterColor(0)).toBe(STAGE_CLUSTER_COLORS[0])
    expect(stageClusterColor(4)).toBe(STAGE_CLUSTER_OTHER_COLOR)
  })
})
