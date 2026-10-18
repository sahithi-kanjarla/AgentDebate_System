import { describe, expect, it } from 'vitest'
import {
  agreement,
  answerBefore,
  initialState,
  orderedRounds,
  reduce,
  reduceAll,
  streamEnded,
} from './debateState'
import type { RawEvent } from './types'
import { D1, D2, D3, fullRun, response } from '../test/fixtures'

const noSeq = (events: RawEvent[]): RawEvent[] => events.map(({ type, data }) => ({ type, data }))

describe('reduceAll over a full run', () => {
  const state = reduceAll(fullRun())

  it('ends done with stats, verdict and two rounds', () => {
    expect(state.status).toBe('done')
    expect(state.id).toBe('d1')
    expect(state.stats?.total_tokens).toBe(1234)
    expect(state.verdict?.final_answer).toBe('[1, 2, 3]')
    expect(state.verdict?.mistakes_caught).toHaveLength(1)
    expect(orderedRounds(state).map((r) => r.round)).toEqual([0, 1])
    expect(state.agents.map((a) => a.persona)).toEqual(['Solver', 'Skeptic', 'Fact-Checker'])
  })

  it('takes changed_mind from the server field, never the model claim', () => {
    const r1 = state.rounds[1]!
    expect(r1.turns[D2]!.changedMind).toBe(true) // changed_mind_claimed was false
    expect(r1.turns[D1]!.changedMind).toBe(false)
    expect(JSON.stringify(state)).not.toContain('changed_mind_claimed')
  })

  it('attaches received critiques to the revising debater', () => {
    const r1 = state.rounds[1]!
    expect(r1.turns[D2]!.receivedCritiques).toEqual([
      expect.objectContaining({ from_agent: D1, severity: 'medium', round: 1 }),
    ])
    expect(r1.turns[D1]!.receivedCritiques).toEqual([])
    expect(state.rounds[0]!.turns[D1]!.receivedCritiques).toEqual([])
  })

  it('resolves critique targets and records edges', () => {
    const r1 = state.rounds[1]!
    expect(r1.turns[D1]!.critiques[0]).toMatchObject({ target: D2, severity: 'medium' })
    expect(r1.edges).toEqual([expect.objectContaining({ from: D1, to: D2 })])
  })

  it('counts agreement and finds the answer before a round', () => {
    expect(agreement(state.rounds[0]!)).toEqual({ agree: 2, total: 3 })
    expect(agreement(state.rounds[1]!)).toEqual({ agree: 3, total: 3 })
    expect(answerBefore(state, 1, D2)).toBe('[1,2,3]')
    expect(answerBefore(state, 0, D2)).toBeUndefined()
  })

  it('never keeps label_map, provider or model', () => {
    const events = fullRun()
    const tainted = events.map((e) =>
      e.type === 'agent_response'
        ? {
            ...e,
            data: {
              ...(e.data as object),
              payload: {
                ...((e.data as { payload: object }).payload as object),
                provider: 'groq',
                model: 'secret-model',
              },
            },
          }
        : e,
    )
    const json = JSON.stringify(reduceAll(tainted))
    for (const word of ['label_map', 'provider', 'secret-model', 'groq']) {
      expect(json).not.toContain(word)
    }
  })
})

describe('the judge', () => {
  it('is not a debater: no column, no round, just a judging flag until the verdict', () => {
    const events = fullRun()
    const before = reduceAll(
      events.slice(
        0,
        events.findIndex((e) => e.type === 'judge_verdict'),
      ),
    )
    expect(before.judging).toBe(true)
    expect(before.verdict).toBeNull()
    expect(before.agents.map((a) => a.label)).toEqual([D1, D2, D3])
    expect(Object.keys(before.rounds)).toEqual(['0', '1'])

    const after = reduceAll(events)
    expect(after.judging).toBe(false)
    expect(after.agents).toHaveLength(3)
  })

  it('ignores a judge thinking event that arrives after the verdict', () => {
    const done = reduceAll(fullRun())
    const late = reduce(done, { type: 'agent_thinking', data: { round: 2, agent: 'Judge' } })
    expect(late.judging).toBe(false)
  })
})

describe('repeated events', () => {
  it('ignores events whose seq was already applied', () => {
    const once = reduceAll(fullRun())
    const twice = reduceAll(fullRun(), once)
    expect(twice).toBe(once)
  })

  it('ignores a repeated seq even when its data differs', () => {
    const first = reduce(initialState(), {
      seq: 3,
      type: 'error',
      data: { message: 'first', recoverable: true },
    })
    const second = reduce(first, {
      seq: 3,
      type: 'error',
      data: { message: 'other', recoverable: true },
    })
    expect(second.errors).toHaveLength(1)
    expect(second.errors[0]!.message).toBe('first')
  })

  it('is idempotent for events without a seq', () => {
    const events = noSeq(fullRun())
    const once = reduceAll(events)
    const twice = reduceAll(events, once)
    expect(twice.rounds).toEqual(once.rounds)
    expect(twice.errors).toEqual(once.errors)
    expect(twice.verdict).toEqual(once.verdict)
  })

  it('accepts a lower seq arriving after a higher one', () => {
    let s = reduce(initialState(), {
      seq: 5,
      type: 'error',
      data: { message: 'late', recoverable: true },
    })
    s = reduce(s, { seq: 3, type: 'error', data: { message: 'early', recoverable: true } })
    expect(s.errors.map((e) => e.message)).toEqual(['late', 'early'])
    expect(s.lastSeq).toBe(5)
  })
})

describe('out-of-order events', () => {
  it('converges to the same rounds when the whole run arrives reversed', () => {
    const forward = reduceAll(noSeq(fullRun()))
    const reversed = reduceAll(noSeq(fullRun()).reverse())
    expect(reversed.rounds).toEqual(forward.rounds)
    expect(reversed.verdict).toEqual(forward.verdict)
    expect(reversed.status).toBe('done')
  })

  it('applies round_complete before a late agent_response', () => {
    const events = noSeq(fullRun())
    const complete = events.find(
      (e) => e.type === 'round_complete' && (e.data as { round: number }).round === 1,
    )!
    const without = events.filter((e) => e !== complete)
    const lateD2 = without.findIndex(
      (e) => e.type === 'agent_response' && (e.data as { agent: string }).agent === D2,
    )
    // Put round_complete right before the last D2 response.
    const index = without
      .map((e, i) => (e.type === 'agent_response' ? i : -1))
      .filter((i) => i >= 0)
    const target = Math.max(
      ...index.filter((i) => (without[i]!.data as { agent: string }).agent === D2),
    )
    expect(lateD2).toBeGreaterThanOrEqual(0)
    const reordered = [...without.slice(0, target), complete, ...without.slice(target)]
    const s = reduceAll(reordered)
    expect(s.rounds[1]!.turns[D2]!.receivedCritiques).toHaveLength(1)
    expect(s.rounds[1]!.turns[D2]!.changedMind).toBe(true)
  })

  it('does not downgrade an answered turn when a thinking event arrives late', () => {
    let s = reduce(initialState(), { type: 'agent_response', data: response(0, D1, '42', 0) })
    s = reduce(s, { type: 'agent_thinking', data: { round: 0, agent: D1 } })
    expect(s.rounds[0]!.turns[D1]!.status).toBe('answered')
  })

  it('adds an unseen agent lazily when debate_started never arrived', () => {
    const s = reduce(initialState(), { type: 'agent_thinking', data: { round: 0, agent: D3 } })
    expect(s.agents).toEqual([{ label: D3, persona: '' }])
    expect(s.status).toBe('running')
  })
})

describe('invalid turns and errors', () => {
  it('marks an invalid turn with its reason and keeps the debate going', () => {
    let s = reduce(initialState(), { type: 'agent_thinking', data: { round: 1, agent: D2 } })
    s = reduce(s, {
      type: 'agent_response',
      data: { round: 1, agent: D2, payload: { valid: false, error: 'invalid JSON from agent' } },
    })
    s = reduce(s, {
      type: 'error',
      data: { agent: D2, message: 'invalid JSON from agent', recoverable: true },
    })
    expect(s.rounds[1]!.turns[D2]).toMatchObject({
      status: 'invalid',
      error: 'invalid JSON from agent',
    })
    expect(s.errors).toEqual([{ agent: D2, message: 'invalid JSON from agent', recoverable: true }])
    expect(s.status).toBe('running')
  })

  it('does not duplicate an identical error event', () => {
    const e: RawEvent = {
      type: 'error',
      data: { agent: D1, message: 'rate limited', recoverable: true },
    }
    expect(reduceAll([e, e, e]).errors).toHaveLength(1)
  })

  it('error events never end the debate; done does, and stays done', () => {
    let s = reduce(initialState(), {
      type: 'error',
      data: { message: 'judge unavailable', recoverable: false },
    })
    expect(s.status).toBe('running')
    s = reduce(s, { type: 'done', data: { stats: {} } })
    expect(s.status).toBe('done')
    s = reduce(s, { type: 'agent_thinking', data: { round: 9, agent: D1 } })
    expect(s.status).toBe('done')
  })

  it('streamEnded marks an unfinished debate failed but leaves a done one alone', () => {
    const running = reduce(initialState(), {
      type: 'agent_thinking',
      data: { round: 0, agent: D1 },
    })
    expect(streamEnded(running).status).toBe('failed')
    const done = reduceAll(fullRun())
    expect(streamEnded(done)).toBe(done)
  })
})

describe('malformed input', () => {
  it('ignores unknown types, non-object data and missing fields without throwing', () => {
    const base = reduceAll(fullRun().slice(0, 5))
    const junk: RawEvent[] = [
      { type: 'something_new', data: { a: 1 } },
      { type: 'agent_response', data: null },
      { type: 'agent_response', data: 'text' },
      { type: 'agent_response', data: { round: 'x', agent: D1, payload: {} } },
      {
        type: 'agent_response',
        data: { round: 0, agent: D1, payload: { reasoning: 'no answer' } },
      },
      { type: 'critique_edge', data: { round: 1 } },
      { type: 'round_complete', data: {} },
      { type: 'judge_verdict', data: { payload: 'nope' } },
      { type: 'error', data: { recoverable: true } },
    ]
    expect(() => reduceAll(junk, base)).not.toThrow()
    expect(reduceAll(junk, base)).toEqual(base)
  })

  it('coerces an unknown severity to low instead of failing', () => {
    const s = reduce(initialState(), {
      type: 'critique_edge',
      data: { round: 1, from_agent: D1, to_agent: D2, severity: 'catastrophic', issue: 'x' },
    })
    expect(s.rounds[1]!.edges[0]!.severity).toBe('low')
  })
})

describe('exact answers', () => {
  const messy = '  [1,\n  2]\n\t'

  it('keeps final_answer and the verdict answer untouched', () => {
    let s = reduce(initialState(), { type: 'agent_response', data: response(0, D1, messy, 0) })
    s = reduce(s, {
      type: 'judge_verdict',
      data: {
        payload: {
          final_answer: messy,
          confidence: 50,
          summary: 's',
          mistakes_caught: [],
          dissent: null,
          consensus_reached: true,
        },
      },
    })
    expect(s.rounds[0]!.turns[D1]!.finalAnswer).toBe(messy)
    expect(s.verdict!.final_answer).toBe(messy)
  })

  it('keeps cluster answers untouched', () => {
    const s = reduce(initialState(), {
      type: 'round_complete',
      data: {
        round: 0,
        consensus_score: 1,
        agreed: true,
        clusters: [{ cluster_id: 0, normalized_answer: messy, agents: [D1] }],
        received_critiques: {},
      },
    })
    expect(s.rounds[0]!.summary!.clusters[0]!.answer).toBe(messy)
  })
})
