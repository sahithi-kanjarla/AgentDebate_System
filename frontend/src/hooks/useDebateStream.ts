import { useEffect, useRef, useState } from 'react'
import { initialState, reduceAll, streamEnded, type DebateState } from '../lib/debateState'
import { streamUrl } from '../lib/api'
import type { RawEvent } from '../lib/types'

export type Connection = 'open' | 'reconnecting' | 'closed'
export type SourceFactory = (url: string) => EventSource

const EVENT_TYPES = [
  'debate_started',
  'agent_thinking',
  'agent_response',
  'critique_edge',
  'round_complete',
  'judge_verdict',
] as const

/** Consecutive connection errors, with no event in between, before the hook gives up. */
export const MAX_CONNECTION_ERRORS = 4
const CLOSED = 2 // EventSource.CLOSED; the global is absent in some environments
const FLUSH_MS = 30

const defaultFactory: SourceFactory = (url) => new EventSource(url)

function parse(data: unknown): unknown {
  if (typeof data !== 'string') return undefined
  try {
    return JSON.parse(data)
  } catch {
    return undefined
  }
}

/**
 * Feeds a running debate's SSE stream into the reducer.
 *
 * - closes the EventSource after `done` (the server ends the stream, and EventSource would
 *   otherwise reconnect forever);
 * - the SSE event named "error" collides with EventSource's built-in error event, so one
 *   listener tells them apart: a MessageEvent with string data is an application error,
 *   anything else is a connection problem;
 * - keepalive pings are comments and never reach listeners;
 * - after a dropped connection the browser reconnects with Last-Event-ID and the reducer ignores
 *   any event it has already applied.
 */
export function useDebateStream(
  id: string,
  enabled: boolean,
  factory: SourceFactory = defaultFactory,
): { state: DebateState; connection: Connection } {
  const [state, setState] = useState<DebateState>(initialState)
  const [connection, setConnection] = useState<Connection>('open')
  const factoryRef = useRef(factory)

  useEffect(() => {
    if (!enabled) return
    setState(initialState())
    setConnection('open')

    let buffer: RawEvent[] = []
    let timer: ReturnType<typeof setTimeout> | undefined
    let errors = 0
    let finished = false

    // Replays arrive as a burst; batch them so React renders once per burst, not per event.
    const flush = () => {
      timer = undefined
      if (buffer.length === 0) return
      const batch = buffer
      buffer = []
      setState((prev) => reduceAll(batch, prev))
    }
    const push = (event: RawEvent) => {
      buffer.push(event)
      if (timer === undefined) timer = setTimeout(flush, FLUSH_MS)
    }

    const es = factoryRef.current(streamUrl(id))

    const finish = (failed: boolean) => {
      if (finished) return
      finished = true
      es.close()
      if (timer !== undefined) clearTimeout(timer)
      flush()
      setConnection('closed')
      if (failed) setState((prev) => streamEnded(prev))
    }

    const seqOf = (e: MessageEvent): number | undefined => {
      const n = Number.parseInt(e.lastEventId, 10)
      return Number.isNaN(n) ? undefined : n
    }

    for (const type of EVENT_TYPES) {
      es.addEventListener(type, (e) => {
        const m = e as MessageEvent
        const data = parse(m.data)
        if (data === undefined) return
        errors = 0
        setConnection('open')
        push({ seq: seqOf(m), type, data })
      })
    }

    es.addEventListener('done', (e) => {
      const m = e as MessageEvent
      push({ seq: seqOf(m), type: 'done', data: parse(m.data) ?? {} })
      finish(false)
    })

    es.addEventListener('error', (e) => {
      const m = e as MessageEvent
      if (e instanceof MessageEvent && typeof m.data === 'string') {
        const data = parse(m.data)
        if (data !== undefined) push({ seq: seqOf(m), type: 'error', data })
        return
      }
      errors += 1
      if (es.readyState === CLOSED || errors >= MAX_CONNECTION_ERRORS) {
        finish(true)
      } else {
        setConnection('reconnecting')
      }
    })

    return () => {
      finished = true
      if (timer !== undefined) clearTimeout(timer)
      es.close()
    }
  }, [id, enabled])

  return { state, connection }
}
