import { describe, expect, it } from 'vitest'
import {
  MAX_SLOWDOWN,
  MIN_DWELL_MS,
  TARGET_MAX_MS,
  TARGET_MIN_MS,
  baseDwell,
  buildSchedule,
  clampPosition,
  delayAt,
  describePosition,
  nextMark,
  prevMark,
  roundMarks,
} from './replay'
import type { RawEvent } from './types'
import { FIXTURES } from '../test/graphFixtures'

const ev = (type: string, data: unknown = {}): RawEvent => ({ type, data })

describe('baseDwell', () => {
  it('treats a run of thinking events as one beat', () => {
    const events = [
      ev('agent_thinking', { round: 0, agent: 'A' }),
      ev('agent_thinking', { round: 0, agent: 'B' }),
      ev('agent_response', { round: 0, agent: 'A' }),
      ev('agent_thinking', { round: 1, agent: 'A' }),
    ]
    expect(baseDwell(events, 0)).toBeGreaterThan(baseDwell(events, 1))
    expect(baseDwell(events, 3)).toBe(baseDwell(events, 0))
  })

  it('gives the judge a longer beat and unknown events a short one', () => {
    const events = [ev('agent_thinking', { round: 2, agent: 'Judge' }), ev('mystery')]
    expect(baseDwell(events, 0)).toBe(800)
    expect(baseDwell(events, 1)).toBe(100)
    expect(baseDwell(events, 5)).toBe(0)
  })
})

describe('buildSchedule', () => {
  it('is empty for an empty log', () => {
    expect(buildSchedule([])).toEqual({ dwell: [], totalMs: 0 })
  })

  it('lands typical debates in the 20 to 40 second band at 1x', () => {
    for (const name of ['mergeWrongCluster', 'five', 'invalidAndFallback'] as const) {
      const { totalMs } = buildSchedule(FIXTURES[name].events)
      expect(totalMs).toBeGreaterThanOrEqual(TARGET_MIN_MS * 0.7)
      expect(totalMs).toBeLessThanOrEqual(TARGET_MAX_MS * 1.05)
    }
  })

  it('squeezes a huge debate down to the maximum', () => {
    const { totalMs } = buildSchedule(FIXTURES.seven.events)
    expect(totalMs).toBeLessThanOrEqual(TARGET_MAX_MS * 1.05)
    expect(totalMs).toBeGreaterThan(TARGET_MIN_MS)
  })

  it('does not stretch a tiny debate past the slow-down cap', () => {
    const events = FIXTURES.two.events
    const raw = events.reduce((n, _, i) => n + baseDwell(events, i), 0)
    expect(raw).toBeLessThan(TARGET_MIN_MS)
    const { totalMs } = buildSchedule(events)
    expect(totalMs).toBeLessThanOrEqual(Math.round(raw * MAX_SLOWDOWN) + events.length)
    expect(totalMs).toBeLessThan(TARGET_MIN_MS)
  })

  it('never goes below the minimum dwell and sums to the total', () => {
    const s = buildSchedule(FIXTURES.seven.events)
    expect(Math.min(...s.dwell)).toBeGreaterThanOrEqual(MIN_DWELL_MS)
    expect(s.dwell.reduce((a, b) => a + b, 0)).toBe(s.totalMs)
    expect(s.dwell).toHaveLength(FIXTURES.seven.events.length)
  })
})

describe('delayAt', () => {
  const s = { dwell: [600, 300, 1000], totalMs: 1900 }
  it('waits the previous event dwell, divided by speed', () => {
    expect(delayAt(s, 2, 1)).toBe(300)
    expect(delayAt(s, 2, 4)).toBe(75)
    expect(delayAt(s, 2, 0.5)).toBe(600)
  })
  it('uses the first dwell at the start and is safe past the end', () => {
    expect(delayAt(s, 0, 1)).toBe(600)
    expect(delayAt(s, 99, 1)).toBe(0)
  })
})

describe('roundMarks and navigation', () => {
  const events = [
    ev('debate_started'),
    ev('agent_response'),
    ev('round_complete', { round: 0 }),
    ev('agent_response'),
    ev('round_complete', { round: 1 }),
    ev('judge_verdict'),
    ev('done'),
  ]

  it('marks the start, the end of each round and the end', () => {
    expect(roundMarks(events)).toEqual([0, 3, 5, 7])
  })

  it('has just start and end when there is no round_complete', () => {
    expect(roundMarks([ev('debate_started'), ev('done')])).toEqual([0, 2])
    expect(roundMarks([])).toEqual([0])
  })

  it('moves to the next and previous mark', () => {
    const marks = roundMarks(events)
    expect(nextMark(marks, 0)).toBe(3)
    expect(nextMark(marks, 3)).toBe(5)
    expect(nextMark(marks, 4)).toBe(5)
    expect(nextMark(marks, 7)).toBe(7)
    expect(prevMark(marks, 7)).toBe(5)
    expect(prevMark(marks, 5)).toBe(3)
    expect(prevMark(marks, 4)).toBe(3)
    expect(prevMark(marks, 0)).toBe(0)
  })

  it('clamps positions', () => {
    expect(clampPosition(-3, 10)).toBe(0)
    expect(clampPosition(99, 10)).toBe(10)
    expect(clampPosition(4.4, 10)).toBe(4)
    expect(clampPosition(Number.NaN, 10)).toBe(10)
  })
})

describe('describePosition', () => {
  it('names the event that was just applied', () => {
    const events = FIXTURES.mergeWrongCluster.events
    expect(describePosition(events, 0)).toMatch(/^Start/)
    expect(describePosition(events, 1)).toBe(`Event 1 of ${events.length}: The debate started`)
    const i = events.findIndex((e) => e.type === 'critique_edge')
    expect(describePosition(events, i + 1)).toMatch(/Debater 1 flagged Debater 2 in round 1/)
    expect(describePosition([], 0)).toBe('No events')
  })
})
