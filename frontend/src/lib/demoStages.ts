/**
 * Stage-by-stage reading of one real run (an entry of public/examples.json). Pure functions: the
 * demo player decides what to draw from `stageAt`, and what to say from `narrationAt`.
 *
 * Stages, in order: Ask, then one stage per round (round 0 is "answer alone", later rounds are
 * "challenge" rounds), then the Verdict. Only answers are stored for these runs, not the critiques
 * themselves, so the narration says what each debater answered and changed, never what was said.
 */
import { changesBetween, type LandingExample } from './landing'

export type StageKind = 'ask' | 'alone' | 'challenge' | 'verdict'

export interface Stage {
  kind: StageKind
  /** The round this stage shows (alone and challenge only). */
  round: number | null
  label: string
}

export function stagesFor(ex: LandingExample): Stage[] {
  const stages: Stage[] = [{ kind: 'ask', round: null, label: 'Ask' }]
  for (const r of ex.rounds) {
    stages.push(
      r.round === 0
        ? { kind: 'alone', round: 0, label: 'Answer alone' }
        : { kind: 'challenge', round: r.round, label: `Challenge ${r.round}` },
    )
  }
  stages.push({ kind: 'verdict', round: null, label: 'Verdict' })
  return stages
}

function names(debaters: number[]): string {
  const list = debaters.map((d) => `Debater ${d}`)
  if (list.length <= 1) return list[0] ?? ''
  return `${list.slice(0, -1).join(', ')} and ${list[list.length - 1]}`
}

/** "Debater 1 picked D. Debaters 2 and 3 picked G." (letters only; the options are on screen). */
export function pickSentence(answers: { debater: number; answer: string | null }[]): string {
  const by = new Map<string, number[]>()
  for (const a of answers) if (a.answer) by.set(a.answer, [...(by.get(a.answer) ?? []), a.debater])
  const parts = [...by].map(([letter, who]) => `${names(who)} picked ${letter}.`)
  const none = answers.filter((a) => !a.answer).map((a) => a.debater)
  if (none.length > 0) parts.push(`${names(none)} gave no valid answer.`)
  return parts.join(' ')
}

export interface Narration {
  title: string
  /** Plain sentences, in reading order. */
  lines: string[]
}

export function narrationAt(ex: LandingExample, stage: Stage): Narration {
  if (stage.kind === 'ask') {
    return {
      title: 'You ask a question',
      lines: [
        'The question goes to three AI debaters.',
        'None of them can see the others’ answers yet.',
      ],
    }
  }
  if (stage.kind === 'verdict') {
    const { final, gold } = ex
    // The judge's own words only when they were stored; nothing is written in its voice.
    const lines = [
      ...(final.summary ? [final.summary] : []),
      `At the start, ${ex.round0Correct} of ${ex.rounds[0]!.answers.length} debaters had the right answer. The ruling ${final.answer === gold ? 'matches' : 'does not match'} the dataset’s answer key (${gold}).`,
    ]
    return {
      title: `The judge rules ${final.answer}${
        final.confidence !== null ? `, ${Math.round(final.confidence)}% confident` : ''
      }`,
      lines,
    }
  }
  const round = ex.rounds.find((r) => r.round === stage.round)!
  if (stage.kind === 'alone') {
    const letters = new Set(round.answers.map((a) => a.answer).filter(Boolean))
    return {
      title: 'Each debater answers alone',
      lines: [
        pickSentence(round.answers),
        letters.size > 1 ? 'They do not agree.' : 'They all agree.',
      ],
    }
  }
  const prev = ex.rounds.find((r) => r.round === round.round - 1) ?? ex.rounds[0]!
  const changes = changesBetween(prev, round)
  return {
    title: `Challenge ${round.round}: read, point out mistakes, answer again`,
    lines: [
      changes.length > 0 ? changes.join(' ') : 'Nobody changed their answer.',
      pickSentence(round.answers),
    ],
  }
}
