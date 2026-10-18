import type { DebateDetail, DebateHeader, DebateListItem, Mode, RawEvent } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
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
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, mode }),
  })
  if (!res.ok) throw new ApiError(res.status, friendly(res.status))
  const body = (await res.json()) as { id?: unknown }
  if (typeof body.id !== 'string')
    throw new ApiError(res.status, 'The server returned no debate id.')
  return body.id
}

/**
 * Header fields plus the stored event log. The response's `turns` (which name providers and models)
 * are dropped here, so they never reach component state.
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

export async function listDebates(limit = 20): Promise<DebateListItem[]> {
  const res = await request(`/api/debates?limit=${limit}`)
  if (!res.ok) throw new ApiError(res.status, friendly(res.status))
  return (await res.json()) as DebateListItem[]
}

export function streamUrl(id: string): string {
  return `/api/debates/${encodeURIComponent(id)}/stream`
}
