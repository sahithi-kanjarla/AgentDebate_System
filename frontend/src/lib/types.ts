/** Shapes mirroring backend/app/schemas.py. Only what the UI reads; provider/model are never typed. */

export type Severity = 'low' | 'medium' | 'high'
export type Mode = 'answer' | 'review'

export interface AgentInfo {
  label: string
  persona: string
}

export interface Mistake {
  description: string
  caught_by: string
  round: number
}

export interface Verdict {
  final_answer: string
  confidence: number
  summary: string
  mistakes_caught: Mistake[]
  dissent: string | null
  consensus_reached: boolean
}

export interface DoneStats {
  total_tokens: number
  latency_ms: number
  calls: number
  api_calls: number
  cache_hits: number
  fallbacks: number
}

/** One ordered event as it arrives over SSE (seq = the SSE id) or from a stored log. */
export interface RawEvent {
  seq?: number
  type: string
  data: unknown
}

/** GET /api/debates/{id}: only the header fields; turns (which carry provider/model) are ignored. */
export interface DebateHeader {
  id: string
  question: string
  mode: Mode
  status: string
  created_at: string
}

/** The header plus the stored, ordered event log (what a live stream would have delivered). */
export interface DebateDetail extends DebateHeader {
  events: RawEvent[]
}

/** GET /api/debates?limit=n */
export interface DebateListItem {
  id: string
  question: string
  mode: Mode
  status: string
  created_at: string
  final_answer: string | null
  confidence: number | null
}
