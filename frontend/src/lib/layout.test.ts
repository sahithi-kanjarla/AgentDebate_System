import { describe, expect, it } from 'vitest'
import {
  capsulePath,
  COLUMN_PITCH,
  computeLayout,
  edgePath,
  fitView,
  laneShift,
  MAX_STAGE_H,
  MIN_ZOOM,
} from './layout'

describe('computeLayout', () => {
  const cases: [number, number][] = []
  for (let agents = 2; agents <= 7; agents++)
    for (let cols = 3; cols <= 6; cols++) cases.push([agents, cols])

  it.each(cases)('%i debaters, %i columns: ordered, spaced, inside the canvas', (agents, cols) => {
    const l = computeLayout(agents, cols)
    expect(l.colX).toHaveLength(cols)
    expect(l.rowY).toHaveLength(agents)
    for (let i = 1; i < cols; i++) expect(l.colX[i]! - l.colX[i - 1]!).toBe(COLUMN_PITCH)
    for (let i = 1; i < agents; i++) {
      const gap = l.rowY[i]! - l.rowY[i - 1]!
      expect(gap).toBe(l.rowPitch)
      // the largest nodes in neighbouring rows never touch
      expect(gap).toBeGreaterThan(l.maxRadius * 2 + 8)
    }
    expect(l.width).toBeGreaterThan(l.colX[cols - 1]!)
    expect(l.height).toBeGreaterThan(l.rowY[agents - 1]! + l.maxRadius)
    expect(l.centerY).toBeGreaterThan(l.rowY[0]! - 1)
    expect(l.centerY).toBeLessThan(l.rowY[agents - 1]! + 1)
  })

  it('keeps existing columns in place when a round is added', () => {
    const a = computeLayout(4, 4)
    const b = computeLayout(4, 5)
    expect(b.colX.slice(0, 3)).toEqual(a.colX.slice(0, 3))
  })

  it('sizes nodes by confidence within bounds', () => {
    const l = computeLayout(5, 4)
    expect(l.radius(0)).toBe(l.minRadius)
    expect(l.radius(100)).toBeCloseTo(l.maxRadius)
    expect(l.radius(80)).toBeGreaterThan(l.radius(40))
    expect(l.radius(null)).toBeGreaterThan(l.minRadius)
    expect(l.radius(null)).toBeLessThan(l.maxRadius)
    expect(l.radius(250)).toBeLessThanOrEqual(l.maxRadius)
  })

  it('survives degenerate input', () => {
    const l = computeLayout(0, 0)
    expect(l.colX).toHaveLength(1)
    expect(l.rowY).toHaveLength(1)
  })
})

describe('paths', () => {
  it('draws a curve between two points and shifts parallel lanes', () => {
    const d = edgePath(0, 0, 100, 50)
    expect(d.startsWith('M0,0')).toBe(true)
    expect(d.endsWith('100,50')).toBe(true)
    expect(edgePath(0, 0, 100, 50, 7)).not.toBe(d)
    expect([0, 1, 2].map((i) => laneShift(i, 3))).toEqual([-7, 0, 7])
    expect(laneShift(0, 1)).toBe(0)
  })

  it('builds a capsule through the members, top to bottom', () => {
    expect(
      capsulePath([
        { x: 5, y: 90 },
        { x: 5, y: 10 },
      ]),
    ).toBe('M5,10L5,90')
    expect(capsulePath([{ x: 1, y: 2 }])).toBe('M1,2')
    expect(capsulePath([])).toBe('')
  })
})

describe('fitView', () => {
  const content = computeLayout(3, 3)

  it('fits the whole graph width on a 360px phone, below 1x', () => {
    const v = fitView(360, content, false)
    expect(v.scale).toBeLessThan(1)
    expect(v.scale).toBeGreaterThanOrEqual(MIN_ZOOM)
    // Every column is on screen: the content, scaled and shifted, sits inside the viewport.
    expect(v.tx).toBeGreaterThanOrEqual(0)
    expect(v.tx + content.width * v.scale).toBeLessThanOrEqual(360)
  })

  it('does not blow a small graph up past 1.25x, and centres it', () => {
    const v = fitView(1600, content, false)
    expect(v.scale).toBe(1.25)
    expect(v.tx).toBeCloseTo((1600 - content.width * 1.25) / 2)
  })

  it('only falls back to the left edge or the newest column when even the minimum zoom is too wide', () => {
    const wide = { width: 4000, height: 400 }
    expect(fitView(360, wide, false).tx).toBe(8)
    expect(fitView(360, wide, true).tx).toBe(360 - 4000 * MIN_ZOOM - 8)
  })

  it('gives the stage a sensible height', () => {
    for (const w of [360, 768, 1280]) {
      const v = fitView(w, content, false)
      expect(v.height).toBeGreaterThanOrEqual(w < 600 ? 150 : 280)
      expect(v.height).toBeLessThanOrEqual(MAX_STAGE_H)
    }
  })
})
