/**
 * Turns one real run (an entry of public/examples.json) into the same ordered event log a live
 * debate produces, so the demo can use the real reducer, the real Debate Graph and the real node
 * inspector. Nothing is invented: every answer, confidence and the ruling are from the stored run.
 *
 * What the stored runs do not keep is the text of the critiques, so there are no critique edges and
 * no reasoning. The inspector says so instead of leaving a gap. Cluster ids are the option's index
 * (A = 0, B = 1, ...), so a node's letter in the graph is the option letter in the question.
 */
import type { LandingExample } from './landing'
import type { RawEvent } from './types'

export const NO_REASONING_NOTE =
  'The reasoning and critiques of this test run were not stored, only the answers. Ask your own question to read them.'

const clusterOf = (letter: string) => letter.charCodeAt(0) - 65

export function eventsFor(ex: LandingExample): RawEvent[] {
  const events: RawEvent[] = []
  const push = (type: string, data: Record<string, unknown>) =>
    events.push({ seq: events.length, type, data })

  const optionText = (letter: string) => ex.options.find((o) => o.letter === letter)?.text ?? ''
  const label = (n: number) => `Debater ${n}`
  const answerText = (letter: string) => `${letter}. ${optionText(letter)}`

  push('debate_started', {
    id: ex.id,
    agents: ex.rounds[0]!.answers.map((a) => ({
      label: label(a.debater),
      persona: ex.personas[a.debater] ?? '',
    })),
  })

  ex.rounds.forEach((round, ri) => {
    for (const a of round.answers)
      push('agent_thinking', { round: round.round, agent: label(a.debater) })
    for (const a of round.answers) {
      const before =
        ri > 0 ? ex.rounds[ri - 1]!.answers.find((p) => p.debater === a.debater)?.answer : undefined
      if (a.answer === null) {
        push('agent_response', {
          round: round.round,
          agent: label(a.debater),
          payload: { valid: false, error: 'This debater gave no valid answer.' },
        })
        continue
      }
      push('agent_response', {
        round: round.round,
        agent: label(a.debater),
        payload: {
          valid: true,
          final_answer: answerText(a.answer),
          reasoning: NO_REASONING_NOTE,
          confidence: a.confidence ?? undefined,
          cluster_id: clusterOf(a.answer),
          ...(ri > 0 ? { previous_cluster_id: before ? clusterOf(before) : null } : {}),
          changed_mind: ri > 0 && before != null && before !== a.answer,
        },
      })
    }

    const groups = new Map<string, string[]>()
    for (const a of round.answers) {
      if (a.answer) groups.set(a.answer, [...(groups.get(a.answer) ?? []), label(a.debater)])
    }
    const biggest = Math.max(0, ...[...groups.values()].map((g) => g.length))
    push('round_complete', {
      round: round.round,
      consensus_score: round.answers.length > 0 ? biggest / round.answers.length : 0,
      agreed: groups.size === 1 && biggest === round.answers.length,
      clusters: [...groups].map(([letter, agents]) => ({
        cluster_id: clusterOf(letter),
        normalized_answer: optionText(letter),
        agents,
      })),
    })
  })

  const last = ex.rounds[ex.rounds.length - 1]!
  push('agent_thinking', { round: last.round + 1, agent: 'Judge' })
  push('judge_verdict', {
    payload: {
      final_answer: answerText(ex.final.answer),
      confidence: ex.final.confidence ?? 0,
      summary: ex.final.summary ?? '',
      mistakes_caught: [],
      dissent: null,
      consensus_reached: new Set(last.answers.map((a) => a.answer)).size === 1,
    },
  })
  push('done', { stats: {} })
  return events
}

/**
 * The replay position at which each stage is complete, in stage order (see stagesFor): Ask ends once
 * the question has gone out to every debater, each round ends at its round_complete, and the verdict
 * ends with the log.
 */
export function stageEnds(events: RawEvent[]): number[] {
  const ends: number[] = []
  const firstRoundThinking = events.findIndex((e) => e.type === 'agent_thinking')
  let i = firstRoundThinking
  while (events[i]?.type === 'agent_thinking') i++
  ends.push(i)
  events.forEach((e, n) => {
    if (e.type === 'round_complete') ends.push(n + 1)
  })
  ends.push(events.length)
  return ends
}
