/**
 * The Debate Graph's data model: nodes, edges and clusters derived from the reducer state. Pure and
 * layout-free, so the layered layout (layout.ts) and a later force-directed view can share it.
 *
 * Reading rules, in one place:
 *  - a node is one agent's answer in one round (plus a Question node and a Judge node);
 *  - a critique raised in round r targets the answer the target gave in the previous round, because
 *    that is what the critic was shown. Its edge therefore runs from the target's previous-round
 *    node to the critic's round-r node, the turn in which the critique was written;
 *  - nothing here claims a critique caused a change of answer.
 *
 * Older stored debates may lack cluster ids, the server-derived changed_mind and received_critiques;
 * those are derived from the answers and critique edges instead (flagged `derived`).
 */
import {
  JUDGE_LABEL,
  orderedRounds,
  type DebateState,
  type ReceivedCritique,
  type TurnState,
} from './debateState'
import { clusterLetter, clusterPattern, type ClusterPattern } from './palette'
import type { Severity } from './types'

export { JUDGE_LABEL }

export type NodeKind = 'question' | 'answer' | 'judge'
export type NodeStatus =
  'question' | 'thinking' | 'answered' | 'invalid' | 'waiting' | 'judging' | 'ruled'
export type EdgeKind = 'question' | 'read' | 'memory' | 'critique' | 'judge'

export interface GraphColumn {
  /** Index in left-to-right order: 0 is the Question, the last is the Judge. */
  index: number
  kind: NodeKind
  /** Debate round for answer columns. */
  round: number | null
  label: string
  sublabel: string
}

export interface GraphNode {
  id: string
  kind: NodeKind
  column: number
  round: number | null
  agent: string | null
  agentIndex: number
  persona: string
  status: NodeStatus
  confidence: number | null
  clusterId: number | null
  letter: string | null
  pattern: ClusterPattern | null
  changedMind: boolean
  /** The changed-answer flag was worked out here because the stored debate has no server value. */
  changedMindDerived: boolean
  previousClusterId: number | null
  fallbackUsed: boolean
  answer: string
}

export interface GraphEdge {
  id: string
  kind: EdgeKind
  from: string
  to: string
  /** Round in which the edge was created (the round of its right-hand node). */
  round: number | null
  severity?: Severity
  issue?: string
  /** Critique edges: who raised it and about whom, as agent labels. */
  critic?: string
  target?: string
  /** Critique edges: position among edges between the same two nodes, for visual separation. */
  lane?: number
  lanes?: number
}

export interface GraphCluster {
  id: string
  column: number
  round: number
  clusterId: number
  letter: string
  pattern: ClusterPattern
  answer: string
  nodeIds: string[]
}

export interface GraphModel {
  agents: { label: string; persona: string }[]
  columns: GraphColumn[]
  nodes: GraphNode[]
  edges: GraphEdge[]
  clusters: GraphCluster[]
  judgeConfidence: number | null
  question: string | null
}

export const questionNodeId = 'q'
export const judgeNodeId = 'j'
export const answerNodeId = (round: number, agent: string) => `n:${round}:${agent}`

function roundLabel(round: number): { label: string; sublabel: string } {
  return round === 0
    ? { label: 'Round 0', sublabel: 'independent answers' }
    : { label: `Round ${round}`, sublabel: 'critique and revise' }
}

/** Cluster id for a turn: the server's, else the round summary's, else a stand-in per distinct answer. */
function makeClusterResolver(state: DebateState) {
  let next = 0
  for (const r of Object.values(state.rounds)) {
    for (const t of Object.values(r.turns))
      if (t.clusterId !== undefined) next = Math.max(next, t.clusterId + 1)
    for (const c of r.summary?.clusters ?? []) next = Math.max(next, c.clusterId + 1)
  }
  const byAnswer = new Map<string, number>()
  return (round: number, agent: string, turn: TurnState): number => {
    if (turn.clusterId !== undefined) return turn.clusterId
    const fromSummary = state.rounds[round]?.summary?.clusters.find((c) => c.agents.includes(agent))
    if (fromSummary) return fromSummary.clusterId
    const key = turn.finalAnswer ?? ''
    let id = byAnswer.get(key)
    if (id === undefined) {
      id = next++
      byAnswer.set(key, id)
    }
    return id
  }
}

export function buildGraphModel(state: DebateState, question: string | null = null): GraphModel {
  const rounds = orderedRounds(state).filter(
    (r) => Object.keys(r.turns).length > 0 || r.edges.length > 0,
  )
  const agents = state.agents
  const resolveCluster = makeClusterResolver(state)

  const columns: GraphColumn[] = [
    { index: 0, kind: 'question', round: null, label: 'Question', sublabel: 'what was asked' },
    ...rounds.map((r, i) => ({
      index: i + 1,
      kind: 'answer' as const,
      round: r.round,
      ...roundLabel(r.round),
    })),
    {
      index: rounds.length + 1,
      kind: 'judge',
      round: null,
      label: 'Judge',
      sublabel: 'the ruling',
    },
  ]
  const columnOfRound = new Map(rounds.map((r, i) => [r.round, i + 1]))

  const nodes: GraphNode[] = [
    {
      id: questionNodeId,
      kind: 'question',
      column: 0,
      round: null,
      agent: null,
      agentIndex: -1,
      persona: '',
      status: 'question',
      confidence: null,
      clusterId: null,
      letter: null,
      pattern: null,
      changedMind: false,
      changedMindDerived: false,
      previousClusterId: null,
      fallbackUsed: false,
      answer: question ?? '',
    },
  ]

  // Cluster of each agent's latest answered turn before a round, to derive changes for old logs.
  const lastCluster = new Map<string, number>()
  for (const r of rounds) {
    agents.forEach((a, agentIndex) => {
      const turn = r.turns[a.label]
      if (!turn) return
      const answered = turn.status === 'answered'
      const clusterId = answered ? resolveCluster(r.round, a.label, turn) : null
      let changedMind = turn.changedMind
      let changedMindDerived = false
      let previous: number | null = turn.previousClusterId ?? null
      if (answered && turn.previousClusterId === undefined && r.round > 0) {
        // No server record (older stored debate): compare with the agent's last answer.
        const before = lastCluster.get(a.label)
        previous = before ?? null
        changedMind = before !== undefined && before !== clusterId
        changedMindDerived = true
      }
      if (r.round === 0) changedMind = false // the server never marks the first answer
      if (clusterId !== null) lastCluster.set(a.label, clusterId)
      nodes.push({
        id: answerNodeId(r.round, a.label),
        kind: 'answer',
        column: columnOfRound.get(r.round)!,
        round: r.round,
        agent: a.label,
        agentIndex,
        persona: a.persona,
        status: turn.status,
        confidence: answered ? (turn.confidence ?? null) : null,
        clusterId,
        letter: clusterId === null ? null : clusterLetter(clusterId),
        pattern: clusterId === null ? null : clusterPattern(clusterId),
        changedMind,
        changedMindDerived,
        previousClusterId: previous,
        fallbackUsed: turn.fallbackUsed,
        answer: turn.finalAnswer ?? '',
      })
    })
  }

  const lastRound = rounds[rounds.length - 1]
  const judgeStatus: NodeStatus = state.verdict ? 'ruled' : state.judging ? 'judging' : 'waiting'
  nodes.push({
    id: judgeNodeId,
    kind: 'judge',
    column: columns.length - 1,
    round: null,
    agent: JUDGE_LABEL,
    agentIndex: -1,
    persona: 'Judge',
    status: judgeStatus,
    confidence: state.verdict?.confidence ?? null,
    clusterId: null,
    letter: null,
    pattern: null,
    changedMind: false,
    changedMindDerived: false,
    previousClusterId: null,
    fallbackUsed: false,
    answer: state.verdict?.final_answer ?? '',
  })

  const byId = new Map(nodes.map((n) => [n.id, n]))
  const edges: GraphEdge[] = []

  // Question -> each independent answer.
  const first = rounds[0]
  if (first) {
    for (const n of nodes) {
      if (n.kind === 'answer' && n.round === first.round) {
        edges.push({
          id: `q:${n.id}`,
          kind: 'question',
          from: questionNodeId,
          to: n.id,
          round: n.round,
        })
      }
    }
  }

  for (let i = 1; i < rounds.length; i++) {
    const prev = rounds[i - 1]!
    const cur = rounds[i]!
    for (const a of agents) {
      const to = answerNodeId(cur.round, a.label)
      if (!byId.has(to)) continue
      // memory: the agent's own previous node
      const own = answerNodeId(prev.round, a.label)
      if (byId.has(own))
        edges.push({ id: `m:${own}>${to}`, kind: 'memory', from: own, to, round: cur.round })
      // read: every other agent's previous answer (the critique prompt shows all peers' answers)
      for (const b of agents) {
        if (b.label === a.label) continue
        const from = answerNodeId(prev.round, b.label)
        if (byId.get(from)?.status !== 'answered') continue
        edges.push({ id: `r:${from}>${to}`, kind: 'read', from, to, round: cur.round })
      }
    }
  }

  // critique: criticised answer (previous column) -> the critic's node where it was raised.
  const critiqueEdges: GraphEdge[] = []
  rounds.forEach((r, i) => {
    const prev = rounds[i - 1]
    if (!prev) return
    r.edges.forEach((e, k) => {
      const from = answerNodeId(prev.round, e.to)
      const to = answerNodeId(r.round, e.from)
      if (!byId.has(from) || !byId.has(to)) return
      critiqueEdges.push({
        id: `c:${r.round}:${k}`,
        kind: 'critique',
        from,
        to,
        round: r.round,
        severity: e.severity,
        issue: e.issue,
        critic: e.from,
        target: e.to,
      })
    })
  })
  const pairCount = new Map<string, number>()
  for (const e of critiqueEdges) {
    const key = `${e.from}>${e.to}`
    pairCount.set(key, (pairCount.get(key) ?? 0) + 1)
  }
  const pairSeen = new Map<string, number>()
  for (const e of critiqueEdges) {
    const key = `${e.from}>${e.to}`
    const lane = pairSeen.get(key) ?? 0
    pairSeen.set(key, lane + 1)
    edges.push({ ...e, lane, lanes: pairCount.get(key) })
  }

  // judge: the final column's answers feed the judge once it starts.
  if (lastRound && (state.judging || state.verdict)) {
    for (const n of nodes) {
      if (n.kind === 'answer' && n.round === lastRound.round && n.status === 'answered') {
        edges.push({ id: `j:${n.id}`, kind: 'judge', from: n.id, to: judgeNodeId, round: null })
      }
    }
  }

  // clusters: answers that agree within a column
  const clusters: GraphCluster[] = []
  for (const r of rounds) {
    const col = columnOfRound.get(r.round)!
    const groups = new Map<number, GraphNode[]>()
    for (const n of nodes) {
      if (n.kind !== 'answer' || n.round !== r.round || n.clusterId === null) continue
      groups.set(n.clusterId, [...(groups.get(n.clusterId) ?? []), n])
    }
    for (const [clusterId, members] of groups) {
      const summary = r.summary?.clusters.find((c) => c.clusterId === clusterId)
      clusters.push({
        id: `k:${r.round}:${clusterId}`,
        column: col,
        round: r.round,
        clusterId,
        letter: clusterLetter(clusterId),
        pattern: clusterPattern(clusterId),
        answer: summary?.answer ?? members[0]!.answer,
        nodeIds: members.map((m) => m.id),
      })
    }
  }

  return {
    agents,
    columns,
    nodes,
    edges,
    clusters,
    judgeConfidence: state.verdict?.confidence ?? null,
    question,
  }
}

export function nodeById(model: GraphModel, id: string): GraphNode | undefined {
  return model.nodes.find((n) => n.id === id)
}

/** Critiques raised against the answer this node's agent revised: the server's list, else from the edges. */
export function receivedFor(state: DebateState, node: GraphNode): ReceivedCritique[] {
  if (node.kind !== 'answer' || node.round === null || node.agent === null || node.round === 0)
    return []
  const round = state.rounds[node.round]
  if (!round) return []
  const server = round.turns[node.agent]?.receivedCritiques ?? []
  if (server.length > 0) return server
  return round.edges
    .filter((e) => e.to === node.agent)
    .map((e) => ({ from_agent: e.from, issue: e.issue, severity: e.severity, round: node.round! }))
}

/** What to keep lit while a node or edge is hovered or focused. */
export function relatedTo(
  model: GraphModel,
  id: string,
): { nodeIds: Set<string>; edgeIds: Set<string> } {
  const nodeIds = new Set<string>()
  const edgeIds = new Set<string>()
  const edge = model.edges.find((e) => e.id === id)
  if (edge) {
    edgeIds.add(edge.id)
    nodeIds.add(edge.from)
    nodeIds.add(edge.to)
    return { nodeIds, edgeIds }
  }
  if (!model.nodes.some((n) => n.id === id)) return { nodeIds, edgeIds }
  nodeIds.add(id)
  for (const e of model.edges) {
    // Read edges are shown only into the hovered node ("what it read"), not out of it.
    const touches = e.kind === 'read' ? e.to === id : e.from === id || e.to === id
    if (!touches) continue
    edgeIds.add(e.id)
    nodeIds.add(e.from)
    nodeIds.add(e.to)
  }
  return { nodeIds, edgeIds }
}
