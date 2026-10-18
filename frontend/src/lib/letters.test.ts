import { describe, expect, it } from 'vitest'
import { agreement, initialState, orderedRounds, reduce, reduceAll } from './debateState'
import { buildGraphModel } from './graphModel'
import { clusterLetter } from './palette'
import { FIXTURES, type FixtureName } from '../test/graphFixtures'

type Answers = Record<string, string | null>

/** What each agent actually answered in each round, read straight from the raw events. */
function rawAnswers(name: FixtureName): Map<number, Answers> {
  const out = new Map<number, Answers>()
  for (const e of FIXTURES[name].events) {
    if (e.type !== 'agent_response') continue
    const d = e.data as {
      round: number
      agent: string
      payload: { valid?: boolean; final_answer?: string }
    }
    const round = out.get(d.round) ?? {}
    round[d.agent] = d.payload.valid === false ? null : (d.payload.final_answer ?? null)
    out.set(d.round, round)
  }
  return out
}

const NAMES = Object.keys(FIXTURES) as FixtureName[]

describe.each(NAMES)('cluster letters: %s', (name) => {
  const f = FIXTURES[name]
  const state = reduceAll(f.events)
  const model = buildGraphModel(state, f.question)
  const raw = rawAnswers(name)

  it('gives agents who hold the same answer one letter, and different answers different letters', () => {
    for (const [round, answers] of raw) {
      const nodes = model.nodes.filter((n) => n.kind === 'answer' && n.round === round)
      const byAgent = new Map(nodes.map((n) => [n.agent!, n.letter]))
      const agents = Object.keys(answers).filter((a) => answers[a] !== null)
      for (const a of agents)
        for (const b of agents) {
          const same = answers[a] === answers[b]
          expect(byAgent.get(a) === byAgent.get(b), `${name} round ${round}: ${a} vs ${b}`).toBe(
            same,
          )
        }
      const letters = new Set(agents.map((a) => byAgent.get(a)))
      expect(letters.size).toBe(new Set(agents.map((a) => answers[a])).size)
    }
  })

  it('never lets two different answer strings share a letter anywhere in the debate', () => {
    const lettersOf = new Map<string, Set<string>>()
    const answersOf = new Map<string, Set<string>>()
    for (const n of model.nodes) {
      if (n.kind !== 'answer' || n.letter === null) continue
      lettersOf.set(n.answer, (lettersOf.get(n.answer) ?? new Set()).add(n.letter))
      answersOf.set(n.letter, (answersOf.get(n.letter) ?? new Set()).add(n.answer))
    }
    for (const [answer, letters] of lettersOf) expect([...letters], answer).toHaveLength(1)
    for (const [letter, answers] of answersOf) expect([...answers], letter).toHaveLength(1)
  })

  it('agrees with the consensus meter and the server clusters in every round', () => {
    for (const round of orderedRounds(state)) {
      const nodes = model.nodes.filter(
        (n) => n.kind === 'answer' && n.round === round.round && n.letter,
      )
      const groups = new Map<string, string[]>()
      for (const n of nodes) groups.set(n.letter!, [...(groups.get(n.letter!) ?? []), n.agent!])
      const meter = agreement(round)
      if (meter && meter.total > 0) {
        expect(Math.max(0, ...[...groups.values()].map((g) => g.length))).toBe(meter.agree)
        expect(nodes.length).toBe(meter.total)
      }
      for (const c of round.summary?.clusters ?? []) {
        expect(groups.get(clusterLetter(c.clusterId))?.sort()).toEqual([...c.agents].sort())
      }
      // (an older stored debate has no server clusters to compare with)
      if (round.summary && round.summary.clusters.length > 0) {
        expect(groups.size).toBe(round.summary.clusters.length)
      }
    }
  })

  it('gives the same letters when events arrive one at a time as a stream', () => {
    let streamed = initialState()
    for (const e of f.events) streamed = reduce(streamed, e)
    const a = buildGraphModel(streamed, f.question).nodes.map((n) => [n.id, n.letter])
    expect(a).toEqual(model.nodes.map((n) => [n.id, n.letter]))
  })
})

describe('the letters per column of the named fixtures', () => {
  const lettersByColumn = (name: FixtureName) => {
    const model = buildGraphModel(reduceAll(FIXTURES[name].events), null)
    return model.columns
      .filter((c) => c.kind === 'answer')
      .map((c) =>
        model.nodes
          .filter((n) => n.kind === 'answer' && n.column === c.index)
          .map((n) => n.letter ?? '-')
          .join(''),
      )
  }

  it('mergeWrongCluster: A B C at first, B and C stay wrong, then all A', () => {
    expect(lettersByColumn('mergeWrongCluster')).toEqual(['ABC', 'ABC', 'AAA'])
  })

  it('five: five different first answers, then converging', () => {
    expect(lettersByColumn('five')).toEqual(['ABCDE', 'AAADC', 'AAAAC'])
  })

  it('invalidAndFallback: B differs from A, and the invalid turn has no letter', () => {
    expect(lettersByColumn('invalidAndFallback')).toEqual(['ABA', 'A-A'])
  })

  it('legacy (no cluster ids from the server) still tells different answers apart', () => {
    expect(lettersByColumn('legacy').map((c) => new Set(c).size)).toEqual([3, 3, 1])
  })
})
