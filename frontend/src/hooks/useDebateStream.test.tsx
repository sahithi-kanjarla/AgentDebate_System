import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { MAX_CONNECTION_ERRORS, useDebateStream, type SourceFactory } from './useDebateStream'
import { FakeEventSource } from '../test/fakeEventSource'
import { AGENTS, D1, response } from '../test/fixtures'

const factory: SourceFactory = (url) => new FakeEventSource(url) as unknown as EventSource

function setup(enabled = true) {
  return renderHook(() => useDebateStream('abc', enabled, factory))
}

beforeEach(() => FakeEventSource.reset())

describe('useDebateStream', () => {
  it('connects to the stream URL and folds events into state', async () => {
    const { result } = setup()
    const es = FakeEventSource.last
    expect(es.url).toBe('/api/debates/abc/stream')

    act(() => {
      es.emit('debate_started', { id: 'abc', agents: AGENTS }, 0)
      es.emit('agent_thinking', { round: 0, agent: D1 }, 1)
    })
    await waitFor(() => expect(result.current.state.agents).toHaveLength(3))
    expect(result.current.state.rounds[0]!.turns[D1]!.status).toBe('thinking')
    expect(result.current.state.status).toBe('running')
  })

  it('closes the EventSource after done and never reopens', async () => {
    const { result } = setup()
    const es = FakeEventSource.last
    act(() => {
      es.emit('agent_response', response(0, D1, '42', 0), 0)
      es.emit('done', { stats: { total_tokens: 5 } }, 1)
    })
    await waitFor(() => expect(result.current.state.status).toBe('done'))
    expect(es.closed).toBe(true)
    expect(result.current.connection).toBe('closed')
    expect(result.current.state.rounds[0]!.turns[D1]!.finalAnswer).toBe('42')
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('treats a named "error" event with data as an application error, not a disconnect', async () => {
    const { result } = setup()
    const es = FakeEventSource.last
    act(() => {
      es.emit('error', { agent: D1, message: 'rate limited', recoverable: true }, 4)
    })
    await waitFor(() => expect(result.current.state.errors).toHaveLength(1))
    expect(result.current.state.errors[0]).toMatchObject({ agent: D1, message: 'rate limited' })
    expect(es.closed).toBe(false)
    expect(result.current.connection).toBe('open')
    expect(result.current.state.status).toBe('running')
  })

  it('treats a bare error Event as a connection problem and lets the browser reconnect', async () => {
    const { result } = setup()
    const es = FakeEventSource.last
    act(() => es.connectionError(0))
    await waitFor(() => expect(result.current.connection).toBe('reconnecting'))
    expect(es.closed).toBe(false)
    expect(result.current.state.errors).toHaveLength(0)
  })

  it('ignores events replayed after a reconnect', async () => {
    const { result } = setup()
    const es = FakeEventSource.last
    act(() => {
      es.emit('agent_response', response(0, D1, '42', 0), 7)
      es.connectionError(0)
      es.emit('agent_response', response(0, D1, '42', 0), 7)
      es.emit('error', { message: 'once', recoverable: true }, 8)
      es.emit('error', { message: 'once', recoverable: true }, 8)
    })
    await waitFor(() => expect(result.current.state.errors).toHaveLength(1))
    expect(result.current.state.lastSeq).toBe(8)
    expect(result.current.connection).toBe('open')
  })

  it('gives up after repeated connection errors and marks the debate failed', async () => {
    const { result } = setup()
    const es = FakeEventSource.last
    act(() => {
      es.emit('agent_thinking', { round: 0, agent: D1 }, 0)
    })
    act(() => {
      for (let i = 0; i < MAX_CONNECTION_ERRORS; i++) es.connectionError(0)
    })
    await waitFor(() => expect(result.current.state.status).toBe('failed'))
    expect(es.closed).toBe(true)
    expect(result.current.connection).toBe('closed')
  })

  it('stops immediately when the browser reports the connection closed', async () => {
    const { result } = setup()
    const es = FakeEventSource.last
    act(() => es.connectionError(2))
    await waitFor(() => expect(result.current.state.status).toBe('failed'))
  })

  it('ignores malformed event bodies', async () => {
    const { result } = setup()
    const es = FakeEventSource.last
    act(() => {
      es.emit('agent_thinking', 'not-an-object' as unknown, 0)
    })
    expect(result.current.state.rounds).toEqual({})
  })

  it('does not open a stream when disabled, and closes on unmount', () => {
    setup(false)
    expect(FakeEventSource.instances).toHaveLength(0)
    const { unmount } = setup(true)
    const es = FakeEventSource.last
    unmount()
    expect(es.closed).toBe(true)
  })
})
