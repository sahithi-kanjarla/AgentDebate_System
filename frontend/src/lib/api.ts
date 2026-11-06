import { clientIdHeaders } from './clientId'
import { parseReveal, type Reveal } from './reveal'
import type { DebateDetail, DebateHeader, DebateListItem, Mode, RawEvent } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export type LimitScope = 'ip_hour' | 'ip_day' | 'global_day' | 'busy'
const SCOPES: readonly string[] = ['ip_hour', 'ip_day', 'global_day', 'busy']

/** 429 from the demo's protection: which limit was hit and how long until a retry can work. */
export class RateLimitedError extends ApiError {
  scope: LimitScope
  retryAfterS: number
  constructor(scope: LimitScope, retryAfterS: number, message: string) {
    super(429, message)
    this.name = 'RateLimitedError'
    this.scope = scope
    this.retryAfterS = retryAfterS
  }
}

/** Reads the server's structured 429 body (Retry-After header as a fallback); null if it is not one. */
async function parseRateLimit(res: Response): Promise<RateLimitedError | null> {
  let body: unknown
  try {
    body = await res.json()
  } catch {
    return null
  }
  if (typeof body !== 'object' || body === null) return null
  const b = body as Record<string, unknown>
  if (b.error !== 'rate_limited' || typeof b.scope !== 'string' || !SCOPES.includes(b.scope)) {
    return null
  }
  const header = Number(res.headers.get('Retry-After'))
  const seconds =
    typeof b.retry_after_s === 'number' ? b.retry_after_s : Number.isFinite(header) ? header : 60
  const message = typeof b.message === 'string' ? b.message : friendly(429)
  return new RateLimitedError(b.scope as LimitScope, Math.max(1, Math.ceil(seconds)), message)
}

function friendly(status: number): string {
  if (status === 422) return 'The question must be between 1 and 4,000 characters.'
  if (status === 429) return 'Too many debates started recently. Wait a little and try again.'
  if (status >= 500) return 'The server hit a problem. Try again in a moment.'
  return `The request failed (HTTP ${status}).`
}

async function request(input: string, init?: RequestInit): Promise<Response> {
  let res: Response
  try {
    res = await fetch(input, init)
  } catch {
    throw new ApiError(0, 'Could not reach the server. Check that the backend is running.')
  }
  return res
}

/** The question is sent exactly as typed: no trimming, no reformatting. */
export async function createDebate(question: string, mode: Mode): Promise<string> {
  const res = await request('/api/debates', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...clientIdHeaders() },
    body: JSON.stringify({ question, mode }),
  })
  if (res.status === 429) {
    throw (await parseRateLimit(res)) ?? new ApiError(429, friendly(429))
  }
  if (!res.ok) throw new ApiError(res.status, friendly(res.status))
  const body = (await res.json()) as { id?: unknown }
  if (typeof body.id !== 'string')
    throw new ApiError(res.status, 'The server returned no debate id.')
  return body.id
}

/**
 * Header fields plus the stored event log. The server already withholds provider, model and
 * `label_map`; `turns` are still dropped here, so they never reach component state.
 */
export async function getDebate(id: string): Promise<DebateDetail | null> {
  const res = await request(`/api/debates/${encodeURIComponent(id)}`)
  if (res.status === 404) return null
  if (!res.ok) throw new ApiError(res.status, friendly(res.status))
  const d = (await res.json()) as DebateHeader & { events?: RawEvent[] }
  return {
    id: d.id,
    question: d.question,
    mode: d.mode,
    status: d.status,
    created_at: d.created_at,
    events: Array.isArray(d.events) ? d.events : [],
  }
}

/** Which model answered each turn. Only offered once a debate is over; anonymity is the default. */
export async function getReveal(id: string): Promise<Reveal> {
  const res = await request(`/api/debates/${encodeURIComponent(id)}/reveal`)
  if (res.status === 409) throw new ApiError(409, 'The debate is still running.')
  if (res.status === 404) throw new ApiError(404, 'This debate could not be found.')
  if (!res.ok) throw new ApiError(res.status, friendly(res.status))
  const reveal = parseReveal(await res.json())
  if (!reveal) throw new ApiError(res.status, 'The server sent a reveal this page cannot read.')
  return reveal
}

export async function listDebates(limit = 20): Promise<DebateListItem[]> {
  const res = await request(`/api/debates?limit=${limit}`, { headers: clientIdHeaders() })
  if (!res.ok) throw new ApiError(res.status, friendly(res.status))
  return (await res.json()) as DebateListItem[]
}

export function streamUrl(id: string): string {
  return `/api/debates/${encodeURIComponent(id)}/stream`
}
