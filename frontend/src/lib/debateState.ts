/**
 * Pure reducer for debate events. The same fold serves live SSE streaming and a finished debate
 * replayed from stored events (and M4's graph and replay), so it never touches the network or time.
 *
 * Robustness rules:
 *  - repeated events are ignored (by SSE `seq` when present, otherwise handlers are upserts);
 *  - events may arrive in any order (round_complete before a late agent_response, thinking after
 *    an answer, ...) and still converge on the same state;
 *  - unknown or malformed events are ignored; the reducer never throws;
 *  - `final_answer` is stored exactly as received (never trimmed), `label_map` and anything that
 *    could reveal a provider or model are dropped.
 */
import type { DoneStats, RawEvent, Severity, Verdict, Mistake } from './types'

export type Status = 'connecting' | 'running' | 'done' | 'failed'
export type TurnStatus = 'thinking' | 'answered' | 'invalid'

export interface TurnCritique {
  /** Resolved target ("Debater 2"), or null if the server could not resolve the critic's label. */
  target: string | null
  issue: string
  severity: Severity
}

export interface ReceivedCritique {
  from_agent: string
  issue: string
  severity: Severity
  round: number
}

export interface TurnState {
  status: TurnStatus
  reasoning?: string
  finalAnswer?: string
  confidence?: number
  clusterId?: number
  previousClusterId?: number | null
  /** Server-derived. The model's own claim is deliberately not kept. */
  changedMind: boolean
  critiques: TurnCritique[]
  /** Critiques raised this round against the answer this agent revised. Not a claim of cause. */
  receivedCritiques: ReceivedCritique[]
  fallbackUsed: boolean
  error?: string
}

export interface CritiqueEdgeState {
  round: number
  from: string
  to: string
  severity: Severity
  issue: string
}

export interface ClusterState {
  clusterId: number
  answer: string
  agents: string[]
}

export interface RoundSummary {
  consensusScore: number
  agreed: boolean
  clusters: ClusterState[]
}

export interface RoundState {
  round: number
  turns: Record<string, TurnState>
  edges: CritiqueEdgeState[]
  summary: RoundSummary | null
  /** Authoritative copy of round_complete.received_critiques, kept so late turns can pick it up. */
  received: Record<string, ReceivedCritique[]>
}

export interface DebateError {
  agent?: string
  message: string
  recoverable: boolean
}

export interface DebateState {
  id: string | null
  status: Status
  agents: { label: string; persona: string }[]
  rounds: Record<number, RoundState>
  verdict: Verdict | null
  /** The judge has started but not ruled. The judge is not a debater: it gets no column or round. */
  judging: boolean
  stats: DoneStats | null
  errors: DebateError[]
  /** Highest SSE seq applied, -1 if none. */
  lastSeq: number
  seen: Record<number, true>
}

export function initialState(): DebateState {
  return {
    id: null,
    status: 'connecting',
    agents: [],
    rounds: {},
    verdict: null,
    judging: false,
    stats: null,
    errors: [],
    lastSeq: -1,
    seen: {},
  }
}

/** The label the server uses for the judge in agent_thinking and error events. */
export const JUDGE_LABEL = 'Judge'

// --- tolerant readers ---

type Rec = Record<string, unknown>

function isRec(v: unknown): v is Rec {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}
function str(v: unknown): string | undefined {
  return typeof v === 'string' ? v : undefined
}
function int(v: unknown): number | undefined {
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined
}
function severity(v: unknown): Severity {
  return v === 'low' || v === 'medium' || v === 'high' ? v : 'low'
}
function list(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

function emptyTurn(status: TurnStatus): TurnState {
  return {
    status,
    changedMind: false,
    critiques: [],
    receivedCritiques: [],
    fallbackUsed: false,
  }
}

function emptyRound(round: number): RoundState {
  return { round, turns: {}, edges: [], summary: null, received: {} }
}

function withAgent(state: DebateState, label: string): DebateState {
  if (state.agents.some((a) => a.label === label)) return state
  return { ...state, agents: [...state.agents, { label, persona: '' }] }
}

function putTurn(state: DebateState, round: number, label: string, turn: TurnState): DebateState {
  const r = state.rounds[round] ?? emptyRound(round)
  return {
    ...withAgent(state, label),
    rounds: { ...state.rounds, [round]: { ...r, turns: { ...r.turns, [label]: turn } } },
  }
}

function parseReceived(v: unknown, fallbackRound: number): ReceivedCritique[] {
  const out: ReceivedCritique[] = []
  for (const item of list(v)) {
    if (!isRec(item)) continue
    const from = str(item.from_agent)
    const issue = str(item.issue)
    if (from === undefined || issue === undefined) continue
    out.push({
      from_agent: from,
      issue,
      severity: severity(item.severity),
      round: int(item.round) ?? fallbackRound,
    })
  }
  return out
}

// --- event handlers ---

function onDebateStarted(state: DebateState, d: Rec): DebateState {
  const agents = [...state.agents]
  for (const a of list(d.agents)) {
    if (!isRec(a)) continue
    const label = str(a.label)
    if (label === undefined) continue
    const persona = str(a.persona) ?? ''
    const i = agents.findIndex((x) => x.label === label)
    if (i >= 0) agents[i] = { label, persona }
    else agents.push({ label, persona })
  }
  return { ...state, id: str(d.id) ?? state.id, agents }
}

function onThinking(state: DebateState, d: Rec): DebateState {
  const round = int(d.round)
  const agent = str(d.agent)
  if (round === undefined || agent === undefined) return state
  if (agent === JUDGE_LABEL) return state.verdict ? state : { ...state, judging: true }
  if (state.rounds[round]?.turns[agent]) return state // never downgrade an answered/invalid turn
  return putTurn(state, round, agent, emptyTurn('thinking'))
}

function onAgentResponse(state: DebateState, d: Rec): DebateState {
  const round = int(d.round)
  const agent = str(d.agent)
  const p = d.payload
  if (round === undefined || agent === undefined || !isRec(p)) return state
  if (agent === JUDGE_LABEL) return state

  const pendingReceived = state.rounds[round]?.received[agent] ?? []

  if (p.valid === false) {
    return putTurn(state, round, agent, {
      ...emptyTurn('invalid'),
      error: str(p.error) ?? 'No usable answer from this debater.',
      receivedCritiques: pendingReceived,
    })
  }

  const finalAnswer = str(p.final_answer)
  if (finalAnswer === undefined) return state // malformed: leave any thinking state in place

  const critiques: TurnCritique[] = []
  for (const c of list(p.critiques)) {
    if (!isRec(c)) continue
    const issue = str(c.issue)
    if (issue === undefined) continue
    critiques.push({ target: str(c.target_agent) ?? null, issue, severity: severity(c.severity) })
  }

  return putTurn(state, round, agent, {
    status: 'answered',
    reasoning: str(p.reasoning) ?? '',
    finalAnswer,
    confidence: int(p.confidence),
    clusterId: int(p.cluster_id),
    previousClusterId: p.previous_cluster_id === null ? null : int(p.previous_cluster_id),
    changedMind: p.changed_mind === true,
    critiques,
    receivedCritiques: pendingReceived,
    fallbackUsed: p.fallback_used === true,
  })
}

function onCritiqueEdge(state: DebateState, d: Rec): DebateState {
  const round = int(d.round)
  const from = str(d.from_agent)
  const to = str(d.to_agent)
  const issue = str(d.issue)
  if (round === undefined || from === undefined || to === undefined || issue === undefined) {
    return state
  }
  const r = state.rounds[round] ?? emptyRound(round)
  if (r.edges.some((e) => e.from === from && e.to === to && e.issue === issue)) return state
  const edge: CritiqueEdgeState = { round, from, to, severity: severity(d.severity), issue }
  return { ...state, rounds: { ...state.rounds, [round]: { ...r, edges: [...r.edges, edge] } } }
}

function onRoundComplete(state: DebateState, d: Rec): DebateState {
  const round = int(d.round)
  if (round === undefined) return state
  const r = state.rounds[round] ?? emptyRound(round)

  const clusters: ClusterState[] = []
  for (const c of list(d.clusters)) {
    if (!isRec(c)) continue
    const clusterId = int(c.cluster_id)
    if (clusterId === undefined) continue
    clusters.push({
      clusterId,
      answer: str(c.normalized_answer) ?? '',
      agents: list(c.agents).filter((a): a is string => typeof a === 'string'),
    })
  }

  const received: Record<string, ReceivedCritique[]> = {}
  if (isRec(d.received_critiques)) {
    for (const [label, v] of Object.entries(d.received_critiques)) {
      received[label] = parseReceived(v, round)
    }
  }

  const turns = { ...r.turns }
  for (const [label, items] of Object.entries(received)) {
    const t = turns[label]
    if (t) turns[label] = { ...t, receivedCritiques: items }
  }

  return {
    ...state,
    rounds: {
      ...state.rounds,
      [round]: {
        ...r,
        turns,
        received,
        summary: {
          consensusScore: int(d.consensus_score) ?? 0,
          agreed: d.agreed === true,
          clusters,
        },
      },
    },
  }
}

function onVerdict(state: DebateState, d: Rec): DebateState {
  const p = d.payload
  if (!isRec(p)) return state
  const finalAnswer = str(p.final_answer)
  if (finalAnswer === undefined) return state
  const mistakes: Mistake[] = []
  for (const m of list(p.mistakes_caught)) {
    if (!isRec(m)) continue
    const description = str(m.description)
    if (description === undefined) continue
    mistakes.push({
      description,
      caught_by: str(m.caught_by) ?? '',
      round: int(m.round) ?? 0,
    })
  }
  return {
    ...state,
    judging: false,
    verdict: {
      final_answer: finalAnswer,
      confidence: int(p.confidence) ?? 0,
      summary: str(p.summary) ?? '',
      mistakes_caught: mistakes,
      dissent: str(p.dissent) ?? null,
      consensus_reached: p.consensus_reached === true,
    },
  }
}

function onError(state: DebateState, d: Rec): DebateState {
  const message = str(d.message)
  if (message === undefined) return state
  const agent = str(d.agent)
  const recoverable = d.recoverable === true
  if (state.errors.some((e) => e.agent === agent && e.message === message)) return state
  return { ...state, errors: [...state.errors, { agent, message, recoverable }] }
}

function onDone(state: DebateState, d: Rec): DebateState {
  const s = isRec(d.stats) ? d.stats : {}
  return {
    ...state,
    status: 'done',
    stats: {
      total_tokens: int(s.total_tokens) ?? 0,
      latency_ms: int(s.latency_ms) ?? 0,
      calls: int(s.calls) ?? 0,
      api_calls: int(s.api_calls) ?? 0,
      cache_hits: int(s.cache_hits) ?? 0,
      fallbacks: int(s.fallbacks) ?? 0,
    },
  }
}

const HANDLERS: Record<string, (state: DebateState, d: Rec) => DebateState> = {
  debate_started: onDebateStarted,
  agent_thinking: onThinking,
  agent_response: onAgentResponse,
  critique_edge: onCritiqueEdge,
  round_complete: onRoundComplete,
  judge_verdict: onVerdict,
  error: onError,
  done: onDone,
}

/** Apply one event. Returns the same object when nothing changed. */
export function reduce(state: DebateState, event: RawEvent): DebateState {
  const handler = HANDLERS[event.type]
  if (!handler || !isRec(event.data)) return state

  const seq = typeof event.seq === 'number' && Number.isInteger(event.seq) ? event.seq : undefined
  if (seq !== undefined && state.seen[seq]) return state

  let next: DebateState
  try {
    next = handler(state, event.data)
  } catch {
    return state
  }

  if (seq !== undefined) {
    next = { ...next, seen: { ...next.seen, [seq]: true }, lastSeq: Math.max(next.lastSeq, seq) }
  }
  // 'done' is final: nothing after it can reopen the debate.
  if (state.status === 'done') next = { ...next, status: 'done' }
  else if (next.status === 'connecting') next = { ...next, status: 'running' }
  return next
}

export function reduceAll(events: RawEvent[], from: DebateState = initialState()): DebateState {
  return events.reduce(reduce, from)
}

/** The stream ended (or gave up) without a `done` event. */
export function streamEnded(state: DebateState): DebateState {
  return state.status === 'done' ? state : { ...state, status: 'failed' }
}

// --- selectors ---

export function orderedRounds(state: DebateState): RoundState[] {
  return Object.values(state.rounds).sort((a, b) => a.round - b.round)
}

/** "2 of 3 agree": the size of the largest answer cluster out of the debaters that answered. */
export function agreement(round: RoundState): { agree: number; total: number } | null {
  const clusters = round.summary?.clusters
  if (!clusters) return null
  const total = clusters.reduce((n, c) => n + c.agents.length, 0)
  const agree = clusters.reduce((n, c) => Math.max(n, c.agents.length), 0)
  return { agree, total }
}

/** The agent's latest answered turn strictly before `round`. */
export function answerBefore(state: DebateState, round: number, label: string): string | undefined {
  let best: { round: number; answer: string } | undefined
  for (const r of Object.values(state.rounds)) {
    if (r.round >= round) continue
    const t = r.turns[label]
    if (t?.status === 'answered' && t.finalAnswer !== undefined) {
      if (!best || r.round > best.round) best = { round: r.round, answer: t.finalAnswer }
    }
  }
  return best?.answer
}

/** Position (0-based) of a debater, used to pick its colour. Unknown labels sort last. */
export function debaterIndex(state: DebateState, label: string): number {
  const i = state.agents.findIndex((a) => a.label === label)
  return i >= 0 ? i : state.agents.length
}
