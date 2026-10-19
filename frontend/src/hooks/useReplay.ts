import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { initialState, reduceAll, type DebateState } from '../lib/debateState'
import {
  buildSchedule,
  clampPosition,
  delayAt,
  describePosition,
  nextMark,
  prevMark,
  roundMarks,
  type Speed,
} from '../lib/replay'
import type { RawEvent } from '../lib/types'

export interface Replay {
  /** Events applied so far (0..total). */
  position: number
  total: number
  playing: boolean
  speed: Speed
  /** False when there is nothing to replay (a live debate, or an empty log). */
  available: boolean
  /** True once the visitor has played or moved the replay; announcements stay silent before that. */
  touched: boolean
  /** True only while playing and the last change was a natural tick; seeks are always static. */
  motion: boolean
  /** The state at `position`: exactly reduceAll(events.slice(0, position)); at the end, `finalState`. */
  state: DebateState
  marks: number[]
  valueText: string
  play(): void
  pause(): void
  toggle(): void
  seek(position: number): void
  step(delta: number): void
  jumpRound(direction: 1 | -1): void
  setSpeed(speed: Speed): void
}

/**
 * Replays an ordered event log through the same reducer the live view uses. A position is how many
 * events are applied; the state shown is always derived from that prefix, never patched, so
 * scrubbing forwards and backwards cannot drift. `finalState` is what the page already shows for the
 * whole log (it may include the end-of-stream marking), used at the last position so the two agree.
 *
 * `startAtBeginning` is for recorded examples that should play on arrival.
 */
export function useReplay(
  events: RawEvent[],
  finalState: DebateState,
  options: { startAtBeginning?: boolean; autoplay?: boolean } = {},
): Replay {
  const total = events.length
  const [at, setAt] = useState<number | null>(options.startAtBeginning ? 0 : null)
  const [playing, setPlaying] = useState(options.autoplay === true)
  const [speed, setSpeedState] = useState<Speed>(1)
  const [lastKind, setLastKind] = useState<'tick' | 'seek'>(options.autoplay ? 'tick' : 'seek')
  const [touched, setTouched] = useState(options.autoplay === true)
  const immediate = useRef(options.autoplay === true)

  const position = clampPosition(at ?? total, total)
  const schedule = useMemo(() => buildSchedule(events), [events])
  const marks = useMemo(() => roundMarks(events), [events])

  const state = useMemo(
    () =>
      position >= total
        ? finalState
        : position === 0
          ? initialState()
          : reduceAll(events.slice(0, position), initialState()),
    [events, position, total, finalState],
  )

  const seek = useCallback(
    (p: number) => {
      setAt(clampPosition(p, total))
      setLastKind('seek')
    },
    [total],
  )

  // One timer per position while playing. Changing speed or position re-arms it, so a speed change
  // simply applies to the next event.
  useEffect(() => {
    if (!playing || position >= total) return
    const wait = immediate.current ? 0 : delayAt(schedule, position, speed)
    immediate.current = false
    const id = setTimeout(() => {
      setAt(position + 1)
      setLastKind('tick')
      if (position + 1 >= total) setPlaying(false)
    }, wait)
    return () => clearTimeout(id)
  }, [playing, position, speed, schedule, total])

  const play = useCallback(() => {
    if (total === 0) return
    setTouched(true)
    immediate.current = true
    if (position >= total) setAt(0)
    setLastKind('tick')
    setPlaying(true)
  }, [position, total])
  const pause = useCallback(() => setPlaying(false), [])
  const toggle = useCallback(() => (playing ? pause() : play()), [playing, play, pause])

  const step = useCallback(
    (delta: number) => {
      setTouched(true)
      setPlaying(false)
      seek(position + delta)
    },
    [position, seek],
  )
  const jumpRound = useCallback(
    (direction: 1 | -1) => {
      setTouched(true)
      setPlaying(false)
      seek(direction === 1 ? nextMark(marks, position) : prevMark(marks, position))
    },
    [marks, position, seek],
  )
  const userSeek = useCallback(
    (p: number) => {
      setTouched(true)
      setPlaying(false)
      seek(p)
    },
    [seek],
  )

  return {
    position,
    total,
    playing,
    speed,
    available: total > 0,
    touched,
    motion: playing && lastKind === 'tick',
    state,
    marks,
    valueText: describePosition(events, position),
    play,
    pause,
    toggle,
    seek: userSeek,
    step,
    jumpRound,
    setSpeed: setSpeedState,
  }
}
