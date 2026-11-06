import { ApiError } from './api'
import type { DebateError } from './debateState'

/**
 * Text that is safe to show. Only an ApiError carries a message this app wrote; any other error
 * (a network TypeError, a parse failure, a server exception) gets the fallback instead.
 */
export function friendlyMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

/**
 * What the "problems" note says for one error event. The server's own wording ("internal error: ...",
 * exception names, provider messages) is never shown.
 */
export function friendlyDebateError(e: DebateError): string {
  const raw = e.message.toLowerCase()
  const judge = e.agent === 'Judge'
  if (!e.recoverable) return 'Something went wrong, so the debate stopped early.'
  if (judge) return 'The judge didn’t respond, so the verdict may be missing or incomplete.'
  if (/rate.?limit|429|quota/.test(raw)) {
    return 'This model was rate-limited, so the debate continued without it.'
  }
  if (/invalid|schema|parse|json/.test(raw)) {
    return 'This model gave an answer that could not be read, so the debate continued without it.'
  }
  return 'This model didn’t respond, so the debate continued without it.'
}
