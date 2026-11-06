import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { narrationAt, pickSentence, stagesFor } from './demoStages'
import { eventsFor, stageEnds } from './demoEvents'
import { initialState, reduceAll } from './debateState'
import { parseExamples } from './landing'

const set = parseExamples(
  JSON.parse(readFileSync(join(process.cwd(), 'public', 'examples.json'), 'utf8')),
)!
const [first] = set.examples

describe('demo stages', () => {
  it('runs Ask, one stage per round, then the Verdict', () => {
    const stages = stagesFor(first!)
    expect(stages[0]!.kind).toBe('ask')
    expect(stages[1]!.kind).toBe('alone')
    expect(stages.at(-1)!.kind).toBe('verdict')
    expect(stages).toHaveLength(first!.rounds.length + 2)
    expect(stages.slice(2, -1).every((s) => s.kind === 'challenge')).toBe(true)
  })

  it('turns a run into events whose stages end where the log says', () => {
    for (const ex of set.examples) {
      const events = eventsFor(ex)
      const ends = stageEnds(events)
      expect(ends).toHaveLength(stagesFor(ex).length)
      expect(ends).toEqual([...ends].sort((a, b) => a - b))
      expect(ends.at(-1)).toBe(events.length)
      // At the end of the Ask stage the question is out but nobody has answered.
      const asked = reduceAll(events.slice(0, ends[0]), initialState())
      expect(Object.values(asked.rounds[0]!.turns).every((t) => t.status === 'thinking')).toBe(true)
      // At the end, the ruling is the stored one and the graph letters are the option letters.
      const done = reduceAll(events, initialState())
      expect(done.verdict!.final_answer.startsWith(`${ex.final.answer}.`)).toBe(true)
      const turn = Object.values(done.rounds[0]!.turns)[0]!
      expect(turn.clusterId).toBe(turn.finalAnswer!.charCodeAt(0) - 65)
    }
  })

  it('marks a change of answer from the stored rounds', () => {
    const changed = set.examples.flatMap((ex) => {
      const state = reduceAll(eventsFor(ex), initialState())
      return Object.values(state.rounds)
        .flatMap((r) => Object.values(r.turns))
        .filter((t) => t.changedMind)
    })
    expect(changed.length).toBeGreaterThan(0)
  })

  it('names who picked what, and who gave no answer', () => {
    expect(
      pickSentence([
        { debater: 1, answer: 'D' },
        { debater: 2, answer: 'G' },
        { debater: 3, answer: 'G' },
      ]),
    ).toBe('Debater 1 picked D. Debater 2 and Debater 3 picked G.')
    expect(pickSentence([{ debater: 2, answer: null }])).toBe('Debater 2 gave no valid answer.')
  })

  it('narrates every stage of every example from the data', () => {
    for (const ex of set.examples) {
      for (const stage of stagesFor(ex)) {
        const n = narrationAt(ex, stage)
        expect(n.title.length).toBeGreaterThan(0)
        expect(n.lines.length).toBeGreaterThan(0)
      }
      const verdict = narrationAt(ex, stagesFor(ex).at(-1)!)
      expect(verdict.title).toContain(`rules ${ex.final.answer}`)
      expect(verdict.lines.join(' ')).toContain('matches the dataset')
    }
  })

  it('writes nothing in the judge’s voice unless it was stored', () => {
    for (const ex of set.examples) {
      const lines = narrationAt(ex, stagesFor(ex).at(-1)!).lines
      if (ex.final.summary) expect(lines[0]).toBe(ex.final.summary)
      else expect(lines.join(' ')).not.toMatch(/reads the whole exchange/)
    }
    const stored = set.examples.filter((e) => e.final.summary === null)
    expect(stored.length).toBeGreaterThan(0)
    for (const ex of stored) {
      expect(narrationAt(ex, stagesFor(ex).at(-1)!).lines).toHaveLength(1)
    }
  })
})
