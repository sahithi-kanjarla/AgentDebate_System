/**
 * Links an item of "Mistakes caught" to the critique edge(s) in the graph.
 *
 * The server builds each entry from a critique: `description` is that critique's `issue` verbatim,
 * `caught_by` the critic and `round` the round it was raised in (see DECISIONS.md, "mistakes_caught
 * is built by the server"). So a mistake is matched on (round, critic, issue), never on an edge id:
 * ids depend on arrival order. Older stored debates had judge-written entries, so there are
 * graceful fallbacks, from a looser match down to a plain node or nothing.
 */
import { answerNodeId, type GraphModel } from './graphModel'
import type { Mistake } from './types'

export type MistakeLinkKind =
  /** Matched exactly, or after collapsing whitespace. */
  | 'edge'
  /** Not matched by text, but the critic raised exactly one critique that round. */
  | 'approx'
  /** No critique matched; the critic's answer in that round is shown instead. */
  | 'node'
  /** Nothing in the graph corresponds to this entry. */
  | 'none'

export interface MistakeLink {
  kind: MistakeLinkKind
  edgeIds: string[]
  nodeIds: string[]
  /** Plain-language caveat shown with the item, or null for an exact link. */
  note: string | null
}

const collapse = (s: string) => s.replace(/\s+/g, ' ').trim()

export function resolveMistake(model: GraphModel, m: Mistake): MistakeLink {
  const mine = model.edges.filter(
    (e) => e.kind === 'critique' && e.round === m.round && e.critic === m.caught_by,
  )

  const exact = mine.filter((e) => e.issue === m.description)
  if (exact.length > 0) {
    return { kind: 'edge', edgeIds: exact.map((e) => e.id), nodeIds: [], note: null }
  }

  const wanted = collapse(m.description)
  const loose = mine.filter((e) => collapse(e.issue ?? '') === wanted)
  if (wanted !== '' && loose.length > 0) {
    return { kind: 'edge', edgeIds: loose.map((e) => e.id), nodeIds: [], note: null }
  }

  if (mine.length === 1) {
    return {
      kind: 'approx',
      edgeIds: [mine[0]!.id],
      nodeIds: [],
      note: `Closest critique: ${m.caught_by} raised only one in round ${m.round}, so this is an approximate match.`,
    }
  }

  const nodeId = answerNodeId(m.round, m.caught_by)
  if (model.nodes.some((n) => n.id === nodeId)) {
    return {
      kind: 'node',
      edgeIds: [],
      nodeIds: [nodeId],
      note: `No matching critique was found, so the graph shows ${m.caught_by}'s answer in round ${m.round}.`,
    }
  }

  return { kind: 'none', edgeIds: [], nodeIds: [], note: null }
}

export function resolveMistakes(model: GraphModel, mistakes: Mistake[]): MistakeLink[] {
  return mistakes.map((m) => resolveMistake(model, m))
}

/** Reverse map: critique edge id -> indices of the mistakes that point at it. */
export function mistakesByEdge(links: MistakeLink[]): Map<string, number[]> {
  const out = new Map<string, number[]>()
  links.forEach((l, i) => {
    for (const id of l.edgeIds) out.set(id, [...(out.get(id) ?? []), i])
  })
  return out
}

/** Edges worth a badge in the graph: those a mistake points at with a real (not approximate) match. */
export function caughtEdgeIds(links: MistakeLink[]): Set<string> {
  const out = new Set<string>()
  for (const l of links) if (l.kind === 'edge') for (const id of l.edgeIds) out.add(id)
  return out
}
