import { describe, expect, it } from 'vitest'
import { reduceAll } from './debateState'
import { buildGraphModel } from './graphModel'
import { narrate } from './narrate'
import {
  FIXTURES,
  five,
  legacy,
  mergeWrongCluster,
  two,
  type FixtureName,
} from '../test/graphFixtures'

const captions = (f: { question: string; events: Parameters<typeof reduceAll>[0] }) =>
  narrate(buildGraphModel(reduceAll(f.events), f.question)).map((c) => c.text)

describe('narrate', () => {
  it('tells the merge story in plain English', () => {
    const text = captions(mergeWrongCluster)
    expect(text).toContain("Debater 1 flagged a medium-severity problem with Debater 2's answer.")
    expect(text).toContain("Debater 1 flagged a high-severity problem with Debater 3's answer.")
    expect(text).toContain('No two debaters agree yet: Answer A, Answer B, and Answer C.')
    expect(text).toContain('Debater 2 changed its answer from Answer B to Answer A.')
    expect(text).toContain('All 3 agree on Answer A.')
    expect(text[text.length - 1]).toBe('The judge has ruled for Answer A, with 93% confidence.')
  })

  it('always names who flagged whom', () => {
    for (const name of Object.keys(FIXTURES) as FixtureName[]) {
      for (const t of captions(FIXTURES[name]).filter((c) => c.includes('flagged'))) {
        expect(t).toMatch(
          /^Debater \d flagged a (low|medium|high)-severity problem with Debater \d's answer\.$/,
        )
      }
    }
  })

  it('counts agreement as "N of M agree"', () => {
    expect(captions(five)).toContain('4 of 5 agree on Answer A.')
    expect(captions(two)).toContain('All 2 agree on Answer A.')
  })

  it('says when a debater gave no usable answer', () => {
    expect(captions(FIXTURES.invalidAndFallback)).toContain(
      'Debater 2 gave no usable answer this round.',
    )
  })

  it('narrates a stored older debate too', () => {
    const text = captions(legacy)
    expect(text.some((t) => t.includes('changed its answer'))).toBe(true)
    expect(text.some((t) => t.startsWith('All 3 agree'))).toBe(true)
  })

  it('says who it is waiting for and when the judge is working', () => {
    const live = mergeWrongCluster.events.slice(0, 4)
    expect(captions({ question: '', events: live })).toEqual([
      'Waiting for Debater 1, Debater 2, and Debater 3.',
    ])
    const judging = mergeWrongCluster.events.slice(
      0,
      mergeWrongCluster.events.findIndex((e) => e.type === 'judge_verdict'),
    )
    const text = captions({ question: '', events: judging })
    expect(text[text.length - 1]).toBe('The judge is reviewing the debate.')
  })

  it('says nothing before the debate starts', () => {
    expect(captions({ question: '', events: [] })).toEqual([])
  })
})
