import { describe, expect, it } from 'vitest'
import { buildAnswerFlow, answerFlowSummary } from './answerFlow'
import { initialState, reduceAll } from './debateState'
import { buildGraphModel } from './graphModel'
import { agreementSeries, agreementSummary, confidenceSeries } from './insights'
import { caughtEdgeIds, mistakesByEdge, resolveMistake, resolveMistakes } from './mistakeLinks'
import { FIXTURES, agentLabels, buildEvents, type FixtureName } from '../test/graphFixtures'

function flowFor(name: FixtureName, upTo?: number) {
  const f = FIXTURES[name]
  const state = reduceAll(upTo === undefined ? f.events : f.events.slice(0, upTo), initialState())
  const model = buildGraphModel(state, f.question)
  return { state, model, flow: buildAnswerFlow(state, model, state.verdict?.final_answer ?? null) }
}

describe('buildAnswerFlow', () => {
  it('keeps every column summing to the number of debaters, for 2 to 7 debaters', () => {
    for (const name of [
      'two',
      'mergeWrongCluster',
      'five',
      'seven',
      'invalidAndFallback',
    ] as const) {
      const { flow, state } = flowFor(name)
      expect(flow.debaters).toBe(state.agents.length)
      for (const c of flow.columns) {
        const sum = flow.nodes.filter((n) => n.column === c.index).reduce((a, n) => a + n.count, 0)
        expect(sum).toBe(flow.debaters)
      }
    }
  })

  it('shows a wrong answer shrinking and the winner growing', () => {
    const { flow } = flowFor('mergeWrongCluster')
    const winner = (col: number) =>
      flow.nodes.find((n) => n.column === col && n.kind === 'cluster' && n.answer === '[1]\n[1, 2]')
    expect(flow.columns).toHaveLength(3)
    expect(winner(0)?.count).toBe(1)
    expect(winner(2)?.count).toBe(3)
    expect(flow.nodes.filter((n) => n.column === 2)).toHaveLength(1)
    expect(flow.hasWinner).toBe(true)
    expect(flow.nodes.filter((n) => n.winner).every((n) => n.column === 2)).toBe(true)
  })

  it('puts an invalid turn in the no-valid-answer bucket', () => {
    const { flow } = flowFor('invalidAndFallback')
    const none = flow.nodes.find((n) => n.kind === 'none')
    expect(none).toBeDefined()
    expect(none?.column).toBe(1)
    expect(none?.agents).toEqual(['Debater 2'])
    expect(flow.links.some((l) => l.target === none?.id && l.kind === 'move')).toBe(true)
  })

  it('has stay and move links, and never a zero-value link', () => {
    const { flow } = flowFor('five')
    expect(flow.links.length).toBeGreaterThan(0)
    expect(flow.links.every((l) => l.value > 0 && l.agents.length === l.value)).toBe(true)
    expect(flow.links.some((l) => l.kind === 'stay')).toBe(true)
    expect(flow.links.some((l) => l.kind === 'move')).toBe(true)
  })

  it('handles one column and an empty debate', () => {
    const first = flowFor('five', 12)
    expect(first.flow.columns.length).toBeLessThanOrEqual(1)
    expect(first.flow.links).toHaveLength(0)
    const empty = buildAnswerFlow(initialState(), buildGraphModel(initialState(), null), null)
    expect(empty.columns).toEqual([])
    expect(empty.nodes).toEqual([])
    expect(answerFlowSummary(empty)).toMatch(/No round has finished/)
  })

  it('finds no winner when the judge answer matches nothing', () => {
    const f = FIXTURES.two
    const state = reduceAll(f.events, initialState())
    const flow = buildAnswerFlow(state, buildGraphModel(state, f.question), 'something else')
    expect(flow.hasWinner).toBe(false)
  })

  it('works for older logs with no cluster ids', () => {
    const { flow } = flowFor('legacy')
    expect(flow.columns).toHaveLength(3)
    expect(flow.nodes.find((n) => n.column === 2)?.count).toBe(3)
  })

  it('handles 2 to 7 debaters over 1 to 3 critique rounds', () => {
    for (const n of [2, 3, 4, 5, 6, 7]) {
      for (const rounds of [1, 2, 3, 4]) {
        const agents = agentLabels(n)
        const events = buildEvents({
          id: `t-${n}-${rounds}`,
          agents,
          rounds: Array.from({ length: rounds }, (_, r) =>
            Object.fromEntries(agents.map((a, i) => [a, { answer: String((i + r) % 3) }])),
          ),
          verdict: { answer: '0', confidence: 80, summary: 's' },
        })
        const state = reduceAll(events, initialState())
        const flow = buildAnswerFlow(state, buildGraphModel(state, 'q'), '0')
        expect(flow.columns).toHaveLength(rounds)
        for (const c of flow.columns) {
          expect(
            flow.nodes.filter((x) => x.column === c.index).reduce((a, x) => a + x.count, 0),
          ).toBe(n)
        }
      }
    }
  })
})

describe('chart series', () => {
  it('agreement rises across rounds with a plain summary', () => {
    const state = reduceAll(FIXTURES.mergeWrongCluster.events, initialState())
    const s = agreementSeries(state)
    expect(s.map((p) => p.agree)).toEqual([1, 1, 3])
    expect(s.every((p) => p.debaters === 3)).toBe(true)
    expect(agreementSummary(s)).toBe(
      'Agreement rose from 1 of 3 to 3 of 3, from round 0 to round 2.',
    )
    expect(agreementSummary([])).toMatch(/No round has finished/)
  })

  it('confidence marks an invalid round as a gap', () => {
    const state = reduceAll(FIXTURES.invalidAndFallback.events, initialState())
    const d2 = confidenceSeries(state).find((x) => x.label === 'Debater 2')!
    expect(d2.points.map((p) => p.status)).toEqual(['answered', 'invalid'])
    expect(d2.points[1]!.value).toBeNull()
  })
})

describe('resolveMistake', () => {
  const state = reduceAll(FIXTURES.mergeWrongCluster.events, initialState())
  const model = buildGraphModel(state, 'q')
  const mistakes = state.verdict!.mistakes_caught

  it('links an exact (round, critic, issue) match to its critique edge', () => {
    const links = resolveMistakes(model, mistakes)
    expect(links.map((l) => l.kind)).toEqual(['edge', 'edge'])
    for (const [i, l] of links.entries()) {
      const edge = model.edges.find((e) => e.id === l.edgeIds[0])!
      expect(edge.kind).toBe('critique')
      expect(edge.issue).toBe(mistakes[i]!.description)
      expect(edge.critic).toBe(mistakes[i]!.caught_by)
    }
    expect(mistakesByEdge(links).get(links[0]!.edgeIds[0]!)).toEqual([0])
    expect(caughtEdgeIds(links).size).toBe(2)
  })

  it('matches after collapsing whitespace', () => {
    const m = { ...mistakes[0]!, description: `  ${mistakes[0]!.description.replace(/ /g, '  ')} ` }
    expect(resolveMistake(model, m).kind).toBe('edge')
  })

  it('falls back to the only critique the critic raised that round', () => {
    const fx = FIXTURES.two
    const st = reduceAll(fx.events, initialState())
    const md = buildGraphModel(st, 'q')
    const l = resolveMistake(md, {
      description: 'worded differently',
      caught_by: 'Debater 1',
      round: 1,
    })
    expect(l.kind).toBe('approx')
    expect(l.note).toMatch(/approximate/)
    expect(l.edgeIds).toHaveLength(1)
  })

  it('falls back to the critic node, then to nothing', () => {
    const node = resolveMistake(model, {
      description: 'unmatched',
      caught_by: 'Debater 1',
      round: 2,
    })
    expect(node.kind).toBe('node')
    expect(node.nodeIds).toEqual(['n:2:Debater 1'])
    expect(node.edgeIds).toEqual([])
    const none = resolveMistake(model, { description: 'x', caught_by: 'Nobody', round: 9 })
    expect(none.kind).toBe('none')
    expect(caughtEdgeIds([node, none]).size).toBe(0)
  })
})
