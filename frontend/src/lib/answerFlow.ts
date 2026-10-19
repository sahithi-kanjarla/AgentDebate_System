/**
 * How supporters of each distinct answer change from round to round (the data behind the Sankey).
 *
 * Built on the GraphModel so cluster ids, letters and patterns (and the stand-ins used for older
 * stored debates) are exactly the graph's. Columns are rounds, nodes are answer clusters with a count
 * of agents, links are the agents who stayed in a cluster or moved to another between two rounds.
 * Anyone without a valid answer in a round lands in an explicit "no valid answer" bucket.
 */
import type { DebateState } from './debateState'
import type { GraphModel } from './graphModel'
import type { ClusterPattern } from './palette'

export const NONE_KEY = 'none'

export interface FlowColumn {
  /** Index among the flow's columns. */
  index: number
  round: number
  label: string
}

export interface FlowNode {
  id: string
  column: number
  /** `none` for the no-valid-answer bucket, otherwise `cluster`. */
  kind: 'cluster' | 'none'
  clusterId: number | null
  letter: string | null
  pattern: ClusterPattern | null
  /** The answer text, exactly as received (never trimmed). Empty for the none bucket. */
  answer: string
  agents: string[]
  count: number
  /** True for the cluster holding the judge's final answer in the last column. */
  winner: boolean
  /** Position of the first member, used to keep the order stable. */
  order: number
}

export interface FlowLink {
  id: string
  source: string
  target: string
  agents: string[]
  value: number
  kind: 'stay' | 'move'
}

export interface AnswerFlow {
  columns: FlowColumn[]
  nodes: FlowNode[]
  links: FlowLink[]
  debaters: number
  /** The judge's answer matched a cluster in the last column. */
  hasWinner: boolean
}

const nodeId = (column: number, key: string) => `${column}:${key}`

export function buildAnswerFlow(
  state: DebateState,
  model: GraphModel,
  verdictAnswer: string | null,
): AnswerFlow {
  const agents = model.agents.map((a) => a.label)
  const answerColumns = model.columns.filter((c) => c.kind === 'answer' && c.round !== null)

  // A round counts once nobody in it is still thinking, or once the server summarised it.
  const settled = answerColumns.filter((c) => {
    if (state.rounds[c.round!]?.summary) return true
    return !model.nodes.some(
      (n) => n.kind === 'answer' && n.column === c.index && n.status === 'thinking',
    )
  })

  const columns: FlowColumn[] = settled.map((c, index) => ({
    index,
    round: c.round!,
    label: c.label,
  }))

  const nodes: FlowNode[] = []
  const bucketOf = new Map<string, string>() // `${column}|${agent}` -> node id

  settled.forEach((c, column) => {
    const byKey = new Map<string, FlowNode>()
    agents.forEach((agent, agentIdx) => {
      const n = model.nodes.find(
        (x) => x.kind === 'answer' && x.column === c.index && x.agent === agent,
      )
      const valid = n !== undefined && n.status === 'answered' && n.clusterId !== null
      const key = valid ? `c${n.clusterId}` : NONE_KEY
      let node = byKey.get(key)
      if (!node) {
        node = {
          id: nodeId(column, key),
          column,
          kind: valid ? 'cluster' : 'none',
          clusterId: valid ? n.clusterId : null,
          letter: valid ? n.letter : null,
          pattern: valid ? n.pattern : null,
          answer: valid ? n.answer : '',
          agents: [],
          count: 0,
          winner: false,
          order: agentIdx,
        }
        byKey.set(key, node)
        nodes.push(node)
      }
      node.agents.push(agent)
      node.count += 1
      bucketOf.set(`${column}|${agent}`, node.id)
    })
  })

  // The winner is the cluster in the last column that holds the judge's answer (exact comparison,
  // as everywhere else).
  let hasWinner = false
  const lastColumn = columns.length - 1
  if (verdictAnswer !== null && lastColumn >= 0) {
    for (const n of nodes) {
      if (n.column === lastColumn && n.kind === 'cluster' && n.answer === verdictAnswer) {
        n.winner = true
        hasWinner = true
      }
    }
  }

  const links: FlowLink[] = []
  for (let column = 0; column < columns.length - 1; column++) {
    const merged = new Map<string, FlowLink>()
    for (const agent of agents) {
      const source = bucketOf.get(`${column}|${agent}`)
      const target = bucketOf.get(`${column + 1}|${agent}`)
      if (!source || !target) continue
      const id = `${source}>${target}`
      let link = merged.get(id)
      if (!link) {
        const a = nodes.find((x) => x.id === source)!
        const b = nodes.find((x) => x.id === target)!
        const stay = a.kind === b.kind && a.clusterId === b.clusterId
        link = { id, source, target, agents: [], value: 0, kind: stay ? 'stay' : 'move' }
        merged.set(id, link)
        links.push(link)
      }
      link.agents.push(agent)
      link.value += 1
    }
  }

  return { columns, nodes, links, debaters: agents.length, hasWinner }
}

/** "Round 0: answer A 2, answer B 1. Round 1: answer A 3." for the text alternative. */
export function answerFlowSummary(flow: AnswerFlow): string {
  if (flow.columns.length === 0) return 'No round has finished yet, so there is no answer flow.'
  const per = flow.columns.map((c) => {
    const parts = flow.nodes
      .filter((n) => n.column === c.index)
      .map((n) => `${n.kind === 'none' ? 'no valid answer' : `answer ${n.letter}`} ${n.count}`)
    return `${c.label}: ${parts.join(', ')}.`
  })
  const win = flow.hasWinner ? ' The answer the judge chose is marked as the winner.' : ''
  return `${per.join(' ')}${win}`
}
