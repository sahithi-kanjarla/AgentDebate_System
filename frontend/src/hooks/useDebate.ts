import { useMemo } from 'react'
import { getDebate } from '../lib/api'
import { initialState, reduceAll, streamEnded, type DebateState } from '../lib/debateState'
import type { DebateHeader, RawEvent } from '../lib/types'
import { useFetch } from './useFetch'
import { useDebateStream, type Connection, type SourceFactory } from './useDebateStream'

export type DebateView =
  | { phase: 'loading' }
  | { phase: 'error'; message: string }
  | { phase: 'notfound' }
  | {
      phase: 'ready'
      header: DebateHeader
      state: DebateState
      connection: Connection
      /** The ordered event log so far; what a replay plays back. */
      events: RawEvent[]
    }

/**
 * The one entry point for the debate page. A running debate is followed over SSE; anything else
 * (finished, interrupted, failed, opened from a shared URL) is folded from its stored events. Both
 * paths go through the same reducer and produce the same DebateState, so the page cannot tell them
 * apart.
 */
export function useDebate(id: string, factory?: SourceFactory): DebateView {
  const detail = useFetch(() => getDebate(id), id)
  const data = detail.status === 'ready' ? detail.data : null
  const live = data !== null && data.status === 'running'

  const stream = useDebateStream(id, live, factory)

  const stored = useMemo(
    () => (data && !live ? streamEnded(reduceAll(data.events, initialState())) : null),
    [data, live],
  )

  if (detail.status === 'loading') return { phase: 'loading' }
  if (detail.status === 'error') return { phase: 'error', message: detail.message }
  if (data === null) return { phase: 'notfound' }

  const header: DebateHeader = {
    id: data.id,
    question: data.question,
    mode: data.mode,
    status: data.status,
    created_at: data.created_at,
  }
  if (live) {
    return {
      phase: 'ready',
      header,
      state: stream.state,
      connection: stream.connection,
      events: stream.events,
    }
  }
  return {
    phase: 'ready',
    header,
    state: stored ?? initialState(),
    connection: 'closed',
    events: data.events,
  }
}
