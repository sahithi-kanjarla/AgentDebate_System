/**
 * Replay of a finished debate: pacing and position logic, pure and framework-free.
 *
 * Events carry no timestamps, so playback is paced by event type. A position `k` (0..N) means "the
 * first k events are applied"; the state shown there is always `reduceAll(events.slice(0, k))`, so a
 * replay can never disagree with the live view. Nothing here knows about React.
 */
import { JUDGE_LABEL } from './debateState'
import type { RawEvent } from './types'

export const SPEEDS = [0.5, 1, 2, 4] as const
export type Speed = (typeof SPEEDS)[number]

/** Whole playback at 1x lands in this band when the events allow it. */
export const TARGET_MIN_MS = 20_000
export const TARGET_MAX_MS = 40_000
/** A very short debate is slowed down at most this much, so it is not dragged out to the minimum. */
export const MAX_SLOWDOWN = 1.5
export const MIN_DWELL_MS = 40

/** How long each event stays on screen at 1x, before normalisation. */
export const BASE_DWELL_MS = {
  debate_started: 600,
  thinking_first: 350,
  thinking_rest: 120,
  thinking_judge: 800,
  agent_response: 700,
  critique_edge: 550,
  round_complete: 1000,
  judge_verdict: 1500,
  error: 600,
  done: 400,
  unknown: 100,
} as const

function dataOf(e: RawEvent): Record<string, unknown> {
  return e.data !== null && typeof e.data === 'object' ? (e.data as Record<string, unknown>) : {}
}

function isJudgeThinking(e: RawEvent): boolean {
  return e.type === 'agent_thinking' && dataOf(e).agent === JUDGE_LABEL
}

/** Dwell for event `i` before normalisation. Agents think in parallel, so a run of thinking events
 *  is one beat: the first is longer, the rest are quick. */
export function baseDwell(events: RawEvent[], i: number): number {
  const e = events[i]
  if (!e) return 0
  switch (e.type) {
    case 'debate_started':
      return BASE_DWELL_MS.debate_started
    case 'agent_thinking': {
      if (isJudgeThinking(e)) return BASE_DWELL_MS.thinking_judge
      const prev = events[i - 1]
      const continuing = prev?.type === 'agent_thinking' && !isJudgeThinking(prev)
      return continuing ? BASE_DWELL_MS.thinking_rest : BASE_DWELL_MS.thinking_first
    }
    case 'agent_response':
      return BASE_DWELL_MS.agent_response
    case 'critique_edge':
      return BASE_DWELL_MS.critique_edge
    case 'round_complete':
      return BASE_DWELL_MS.round_complete
    case 'judge_verdict':
      return BASE_DWELL_MS.judge_verdict
    case 'error':
      return BASE_DWELL_MS.error
    case 'done':
      return BASE_DWELL_MS.done
    default:
      return BASE_DWELL_MS.unknown
  }
}

export interface Schedule {
  /** dwell[i] is how long event i stays on screen at 1x, in ms. */
  dwell: number[]
  /** Sum of the dwells: the length of a full playback at 1x. */
  totalMs: number
}

/** Pacing for a whole log, scaled so playback at 1x lands in roughly 20 to 40 seconds. */
export function buildSchedule(events: RawEvent[]): Schedule {
  const base = events.map((_, i) => baseDwell(events, i))
  const sum = base.reduce((a, b) => a + b, 0)
  if (sum === 0) return { dwell: [], totalMs: 0 }
  let factor = 1
  if (sum > TARGET_MAX_MS) factor = TARGET_MAX_MS / sum
  else if (sum < TARGET_MIN_MS) factor = Math.min(TARGET_MIN_MS / sum, MAX_SLOWDOWN)
  const dwell = base.map((b) => Math.max(MIN_DWELL_MS, Math.round(b * factor)))
  return { dwell, totalMs: dwell.reduce((a, b) => a + b, 0) }
}

/** Wait before applying the next event when sitting at `position`, at the given speed. */
export function delayAt(schedule: Schedule, position: number, speed: number): number {
  const d = position <= 0 ? (schedule.dwell[0] ?? 0) : (schedule.dwell[position - 1] ?? 0)
  return Math.round(d / speed)
}

/**
 * Positions worth jumping to: the very start, the end of every round, and the very end. Sorted,
 * unique. A mark after `round_complete` shows that round's result with nothing of the next round.
 */
export function roundMarks(events: RawEvent[]): number[] {
  const marks = new Set<number>([0, events.length])
  events.forEach((e, i) => {
    if (e.type === 'round_complete') marks.add(i + 1)
  })
  return [...marks].sort((a, b) => a - b)
}

/** The next mark above `position`, or the end. */
export function nextMark(marks: number[], position: number): number {
  return marks.find((m) => m > position) ?? marks[marks.length - 1] ?? position
}

/** The greatest mark below `position`, or the start. */
export function prevMark(marks: number[], position: number): number {
  for (let i = marks.length - 1; i >= 0; i--) if (marks[i]! < position) return marks[i]!
  return 0
}

export function clampPosition(position: number, total: number): number {
  if (!Number.isFinite(position)) return total
  return Math.max(0, Math.min(total, Math.round(position)))
}

function roundOf(e: RawEvent): number | null {
  const r = dataOf(e).round
  return typeof r === 'number' ? r : null
}

/** A short plain-English description of the event that was just applied (for aria-valuetext). */
export function describeEvent(e: RawEvent | undefined): string {
  if (!e) return 'Before the first event'
  const d = dataOf(e)
  const round = roundOf(e)
  const where = round === null ? '' : ` in round ${round}`
  switch (e.type) {
    case 'debate_started':
      return 'The debate started'
    case 'agent_thinking':
      return d.agent === JUDGE_LABEL
        ? 'The judge is reviewing'
        : `${String(d.agent)} is thinking${where}`
    case 'agent_response':
      return `${String(d.agent)} answered${where}`
    case 'critique_edge':
      return `${String(d.from_agent)} flagged ${String(d.to_agent)}${where}`
    case 'round_complete':
      return `Round ${round ?? '?'} complete`
    case 'judge_verdict':
      return 'The judge ruled'
    case 'error':
      return 'An error was reported'
    case 'done':
      return 'The debate finished'
    default:
      return 'An update arrived'
  }
}

/** "Event 12 of 41: Debater 2 answered in round 1". */
export function describePosition(events: RawEvent[], position: number): string {
  if (events.length === 0) return 'No events'
  if (position <= 0) return `Start, before event 1 of ${events.length}`
  return `Event ${position} of ${events.length}: ${describeEvent(events[position - 1])}`
}
