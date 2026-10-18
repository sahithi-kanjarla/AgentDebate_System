/**
 * Plain-English captions for the Debate Graph, from templates (no LLM calls). Derived from the graph
 * model, so a live debate and a finished one read the same. Order is by round, then answers,
 * critiques, changes and agreement; it is not the arrival order of events.
 */
import { clusterLetter } from './palette'
import type { GraphModel, GraphNode } from './graphModel'

export interface Caption {
  id: string
  text: string
  kind: 'answer' | 'critique' | 'change' | 'agreement' | 'invalid' | 'waiting' | 'judge'
  round: number | null
}

const SEVERITY_WORD = { low: 'low-severity', medium: 'medium-severity', high: 'high-severity' }

const answerName = (clusterId: number) => `Answer ${clusterLetter(clusterId)}`

function list(names: string[]): string {
  if (names.length <= 1) return names[0] ?? ''
  if (names.length === 2) return `${names[0]} and ${names[1]}`
  return `${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}`
}

function agreementCaption(nodes: GraphNode[], round: number): Caption | null {
  const answered = nodes.filter((n) => n.clusterId !== null)
  if (answered.length === 0) return null
  const counts = new Map<number, number>()
  for (const n of answered) counts.set(n.clusterId!, (counts.get(n.clusterId!) ?? 0) + 1)
  const top = Math.max(...counts.values())
  const leaders = [...counts].filter(([, c]) => c === top).map(([id]) => id)
  const total = answered.length
  let text: string
  if (top === total && total > 1) text = `All ${total} agree on ${answerName(leaders[0]!)}.`
  else if (top === 1) text = `No two debaters agree yet: ${list(leaders.map(answerName))}.`
  else if (leaders.length > 1)
    text = `The debaters are split between ${list(leaders.map(answerName))}.`
  else text = `${top} of ${total} agree on ${answerName(leaders[0]!)}.`
  return { id: `agree:${round}`, text, kind: 'agreement', round }
}

export function narrate(model: GraphModel): Caption[] {
  const out: Caption[] = []
  const rounds = model.columns.filter((c) => c.kind === 'answer')

  for (const col of rounds) {
    const round = col.round!
    const nodes = model.nodes.filter((n) => n.kind === 'answer' && n.round === round)

    if (round === 0) {
      for (const n of nodes) {
        if (n.status === 'answered') {
          out.push({
            id: `answer:${n.id}`,
            text: `${n.agent} answered independently: ${answerName(n.clusterId!)}.`,
            kind: 'answer',
            round,
          })
        }
      }
    }
    for (const e of model.edges) {
      if (e.kind !== 'critique' || e.round !== round) continue
      out.push({
        id: `critique:${e.id}`,
        text: `${e.critic} flagged a ${SEVERITY_WORD[e.severity!]} problem with ${e.target}'s answer.`,
        kind: 'critique',
        round,
      })
    }
    for (const n of nodes) {
      if (n.status === 'invalid') {
        out.push({
          id: `invalid:${n.id}`,
          text: `${n.agent} gave no usable answer this round.`,
          kind: 'invalid',
          round,
        })
      }
      if (n.changedMind && n.clusterId !== null) {
        const from = n.previousClusterId !== null ? ` from ${answerName(n.previousClusterId)}` : ''
        out.push({
          id: `change:${n.id}`,
          text: `${n.agent} changed its answer${from} to ${answerName(n.clusterId)}.`,
          kind: 'change',
          round,
        })
      }
    }
    const agree = agreementCaption(nodes, round)
    if (agree) out.push(agree)

    const waiting = nodes.filter((n) => n.status === 'thinking').map((n) => n.agent!)
    if (waiting.length > 0) {
      out.push({
        id: `waiting:${round}`,
        text: `Waiting for ${list(waiting)}.`,
        kind: 'waiting',
        round,
      })
    }
  }

  const judge = model.nodes.find((n) => n.kind === 'judge')
  if (judge?.status === 'judging') {
    out.push({
      id: 'judge:thinking',
      text: 'The judge is reviewing the debate.',
      kind: 'judge',
      round: null,
    })
  } else if (judge?.status === 'ruled') {
    const match = model.clusters.find((c) => c.answer === judge.answer)
    const which = match ? ` for ${answerName(match.clusterId)}` : ''
    out.push({
      id: 'judge:ruled',
      text: `The judge has ruled${which}, with ${judge.confidence ?? 0}% confidence.`,
      kind: 'judge',
      round: null,
    })
  }
  return out
}
