import { Link } from 'react-router-dom'
import { useFetch } from '../hooks/useFetch'
import type { LimitScope } from '../lib/api'
import { clockAfter, formatWait } from '../lib/wait'
import { loadIndex } from './ShowcaseList'

const COPY: Record<LimitScope, { title: string; body: string }> = {
  ip_hour: {
    title: 'You have reached the hourly limit',
    body: 'The free models behind this demo are shared by every visitor, so each person can start only a few debates an hour.',
  },
  ip_day: {
    title: 'You have reached the daily limit',
    body: 'The free models behind this demo are shared by every visitor, so each person can start only a few debates a day.',
  },
  global_day: {
    title: 'Today’s free model quota is used up',
    body: 'Visitors together have used the free quota for today. It resets at midnight UTC.',
  },
  busy: {
    title: 'The debaters are busy',
    body: 'Several debates are running right now and the free models cannot take another one yet.',
  },
}

/** A refused start: which limit, when to try again, and a debate to watch in the meantime. */
export function RateLimitNotice({
  scope,
  retryAfterS,
  now,
}: {
  scope: LimitScope
  retryAfterS: number
  /** Test hook: the current time in ms. */
  now?: number
}) {
  const { title, body } = COPY[scope]
  const index = useFetch(loadIndex, 'index')
  const first = index.status === 'ready' ? index.data[0] : undefined
  return (
    <div
      role="alert"
      data-testid="rate-limit-notice"
      className="rounded-card border border-severity-medium bg-severity-medium-tint p-4 text-ink"
    >
      <p className="font-semibold">{title}</p>
      <p className="mt-1 text-sm">{body}</p>
      <p className="mt-2 text-sm font-medium">
        Try again in {formatWait(retryAfterS)} (around {clockAfter(retryAfterS, now)}). Your
        question is still here.
      </p>
      {first && (
        <p className="mt-2 text-sm">
          <Link to={`/showcase/${first.slug}`} className="font-medium text-brass underline">
            Watch a recorded debate instead
          </Link>
        </p>
      )}
    </div>
  )
}
