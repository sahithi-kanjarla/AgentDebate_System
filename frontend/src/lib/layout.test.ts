import { describe, expect, it } from 'vitest'
import { capsulePath, COLUMN_PITCH, computeLayout, edgePath, laneShift } from './layout'

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
