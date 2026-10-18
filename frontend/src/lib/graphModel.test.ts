import { describe, expect, it } from 'vitest'
import { reduceAll } from './debateState'
import { buildGraphModel, nodeById, receivedFor, relatedTo, type GraphModel } from './graphModel'
import { FIXTURES, legacy, mergeWrongCluster, type FixtureName } from '../test/graphFixtures'

function model(name: FixtureName): GraphModel {
  const f = FIXTURES[name]
  return buildGraphModel(reduceAll(f.events), f.question)
}
const kinds = (m: GraphModel, kind: string) => m.edges.filter((e) => e.kind === kind)

describe('counts per fixture', () => {
  it.each([
    // [fixture, debaters, critique rounds after round 0]
    ['mergeWrongCluster', 3, 2],
    ['invalidAndFallback', 3, 1],
    ['five', 5, 2],
    ['two', 2, 1],
    ['seven', 7, 3],
  ] as const)('%s', (name, n, later) => {
    const m = model(name)
    const rounds = later + 1
    // question + n answers per round + judge
    expect(m.nodes).toHaveLength(2 + n * rounds)
    expect(m.columns).toHaveLength(rounds + 2)
    expect(kinds(m, 'question')).toHaveLength(n)
    expect(kinds(m, 'memory')).toHaveLength(n * later)
    expect(kinds(m, 'judge').length).toBeGreaterThan(0)
  })

  it('read edges: every other agent’s answered previous node, per later round', () => {
    const m = model('mergeWrongCluster')
    expect(kinds(m, 'read')).toHaveLength(3 * 2 * 2)
    const s = model('seven')
    expect(kinds(s, 'read')).toHaveLength(7 * 6 * 3)
  })
})

describe('critique edges', () => {
  it('run from the criticised answer in the previous column to the critic in the round it was raised', () => {
    const m = model('mergeWrongCluster')
    const critiques = kinds(m, 'critique')
    expect(critiques.map((e) => [e.from, e.to, e.severity])).toEqual([
      ['n:0:Debater 2', 'n:1:Debater 1', 'medium'],
      ['n:0:Debater 3', 'n:1:Debater 1', 'high'],
    ])
    expect(critiques.map((e) => [e.critic, e.target])).toEqual([
      ['Debater 1', 'Debater 2'],
      ['Debater 1', 'Debater 3'],
    ])
    for (const e of critiques) {
      expect(nodeById(m, e.from)!.column).toBe(nodeById(m, e.to)!.column - 1)
    }
  })

  it('separates parallel critiques between the same two nodes into lanes', () => {
    const events = structuredClone(mergeWrongCluster.events)
    const edge = events.find((e) => e.type === 'critique_edge')!
    events.splice(events.indexOf(edge) + 1, 0, {
      ...edge,
      seq: 999,
      data: { ...(edge.data as object), issue: 'A second, different issue.' },
    })
    const m = buildGraphModel(reduceAll(events), null)
    const same = kinds(m, 'critique').filter((e) => e.from === 'n:0:Debater 2')
    expect(same.map((e) => [e.lane, e.lanes])).toEqual([
      [0, 2],
      [1, 2],
    ])
  })
})

describe('nodes and clusters', () => {
  it('uses stable cluster letters and marks the server-derived changes', () => {
    const m = model('mergeWrongCluster')
    const d2 = (r: number) => nodeById(m, `n:${r}:Debater 2`)!
    expect([0, 1, 2].map((r) => d2(r).letter)).toEqual(['B', 'B', 'A'])
    expect([0, 1, 2].map((r) => d2(r).changedMind)).toEqual([false, false, true])
    expect(d2(2).previousClusterId).toBe(1)
    expect(nodeById(m, 'n:2:Debater 1')!.changedMind).toBe(false)
  })

  it('groups agreeing nodes per column and keeps the answer text exactly', () => {
    const m = model('mergeWrongCluster')
    const last = m.clusters.filter((c) => c.round === 2)
    expect(last).toHaveLength(1)
    expect(last[0]!.nodeIds).toHaveLength(3)
    expect(last[0]!.answer).toBe('[1]\n[1, 2]')
    expect(m.clusters.filter((c) => c.round === 0)).toHaveLength(3)
  })

  it('gives the fifth cluster a distinct letter and the hollow pattern', () => {
    const m = model('five')
    const fifth = nodeById(m, 'n:0:Debater 5')!
    expect(fifth.letter).toBe('E')
    expect(fifth.pattern).toBe('hollow')
  })

  it('marks invalid and fallback turns, and draws no read edges from an invalid node', () => {
    const m = model('invalidAndFallback')
    expect(nodeById(m, 'n:1:Debater 2')!.status).toBe('invalid')
    expect(nodeById(m, 'n:0:Debater 3')!.fallbackUsed).toBe(true)
    expect(kinds(m, 'read').every((e) => e.from !== 'n:1:Debater 2')).toBe(true)
  })

  it('shows the judge as waiting, reviewing, then ruled', () => {
    const events = mergeWrongCluster.events
    const upTo = (type: string) =>
      events.slice(
        0,
        events.findIndex((e) => e.type === type),
      )
    const judgeOf = (list: typeof events) => nodeById(buildGraphModel(reduceAll(list), null), 'j')!
    expect(judgeOf(upTo('agent_thinking').slice(0, 3)).status).toBe('waiting')
    const thinkingJudge = events.findIndex((e) => e.type === 'judge_verdict') - 1
    expect(judgeOf(events.slice(0, thinkingJudge + 1)).status).toBe('judging')
    const ruled = judgeOf(events)
    expect(ruled.status).toBe('ruled')
    expect(ruled.confidence).toBe(93)
  })

  it('has no judge edges until the judge starts', () => {
    const before = events_before_judge()
    expect(kinds(before, 'judge')).toHaveLength(0)
    expect(kinds(model('mergeWrongCluster'), 'judge')).toHaveLength(3)
  })
})

function events_before_judge(): GraphModel {
  const i = mergeWrongCluster.events.findIndex(
    (e) => e.type === 'agent_thinking' && (e.data as { agent: string }).agent === 'Judge',
  )
  return buildGraphModel(reduceAll(mergeWrongCluster.events.slice(0, i)), null)
}

describe('relatedTo', () => {
  it('lights a node, its incoming reads, its own line and its critiques', () => {
    const m = model('mergeWrongCluster')
    const r = relatedTo(m, 'n:1:Debater 1')
    expect(r.nodeIds.has('n:0:Debater 2')).toBe(true) // criticised answer
    expect(r.nodeIds.has('n:0:Debater 1')).toBe(true) // its own earlier answer
    expect(r.nodeIds.has('n:2:Debater 1')).toBe(true)
    expect(r.nodeIds.has('n:1:Debater 2')).toBe(false) // a peer in the same column
    expect([...r.edgeIds].some((id) => id.startsWith('c:'))).toBe(true)
  })

  it('lights only the two ends of an edge', () => {
    const m = model('mergeWrongCluster')
    const r = relatedTo(m, 'c:1:0')
    expect(r.edgeIds).toEqual(new Set(['c:1:0']))
    expect([...r.nodeIds].sort()).toEqual(['n:0:Debater 2', 'n:1:Debater 1'])
  })

  it('returns nothing for an unknown id', () => {
    const r = relatedTo(model('two'), 'nope')
    expect(r.nodeIds.size + r.edgeIds.size).toBe(0)
  })
})

describe('an older stored debate (no cluster ids, changed_mind or received_critiques)', () => {
  const state = reduceAll(legacy.events)
  const m = buildGraphModel(state, legacy.question)

  it('still builds the same nodes and edges without throwing', () => {
    const modern = model('mergeWrongCluster')
    expect(m.nodes).toHaveLength(modern.nodes.length)
    expect(m.edges).toHaveLength(modern.edges.length)
  })

  it('works out clusters from the answers', () => {
    const letters = (r: number) =>
      ['Debater 1', 'Debater 2', 'Debater 3'].map((a) => nodeById(m, `n:${r}:${a}`)!.letter)
    expect(new Set(letters(0)).size).toBe(3)
    expect(new Set(letters(2)).size).toBe(1)
    expect(letters(2).every((l) => l !== null)).toBe(true)
  })

  it('derives changes from the answers and says so', () => {
    const d2 = nodeById(m, 'n:2:Debater 2')!
    expect(d2.changedMind).toBe(true)
    expect(d2.changedMindDerived).toBe(true)
    expect(nodeById(m, 'n:1:Debater 2')!.changedMind).toBe(false)
    expect(nodeById(m, 'n:0:Debater 2')!.changedMind).toBe(false)
  })

  it('falls back to the critique edges for the critiques of the revised answer', () => {
    const d2 = nodeById(m, 'n:1:Debater 2')!
    expect(state.rounds[1]!.turns['Debater 2']!.receivedCritiques).toEqual([])
    const got = receivedFor(state, d2)
    expect(got).toHaveLength(1)
    expect(got[0]!.from_agent).toBe('Debater 1')
    expect(receivedFor(state, nodeById(m, 'n:0:Debater 2')!)).toEqual([])
  })
})

describe('robustness', () => {
  it('builds an empty model before any event', () => {
    const m = buildGraphModel(reduceAll([]), null)
    expect(m.nodes.map((n) => n.kind)).toEqual(['question', 'judge'])
    expect(m.edges).toEqual([])
  })
})
