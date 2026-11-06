import { Link } from 'react-router-dom'
import { PageTitle } from '../components/SiteChrome'
import { HistoryNotice } from '../components/DemoNotice'
import { useFetch } from '../hooks/useFetch'
import { listDebates } from '../lib/api'
import type { DebateListItem } from '../lib/types'

const STATUS_WORD: Record<string, string> = {
  completed: 'Finished',
  running: 'In progress',
  interrupted: 'Interrupted',
  failed: 'Failed',
}

function when(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function HistoryItem({ item }: { item: DebateListItem }) {
  return (
    <li>
      <Link to={`/debate/${item.id}`} className="card card-link block">
        <p className="mb-1 flex flex-wrap gap-x-3 text-sm text-ink-soft">
          <span>{item.mode === 'review' ? 'Review' : 'Answer'}</span>
          <span>{STATUS_WORD[item.status] ?? item.status}</span>
          <time dateTime={item.created_at}>{when(item.created_at)}</time>
        </p>
        {/* Clamped by CSS only; the full text stays in the page. */}
        <p className="line-clamp-2 whitespace-pre-wrap break-words font-sans text-lg text-ink">
          {item.question}
        </p>
        {item.final_answer != null && (
          <p className="mt-2 text-sm text-ink-soft">
            Ruling{item.confidence != null ? ` (${item.confidence}% confident)` : ''}
            <span className="answer-text mt-0.5 line-clamp-2 block text-ink">
              {item.final_answer}
            </span>
          </p>
        )}
      </Link>
    </li>
  )
}

export function History() {
  const result = useFetch(() => listDebates(20), 'history')
  return (
    <div className="mx-auto max-w-3xl">
      <PageTitle title="Recent debates">Debates started from this browser.</PageTitle>
      <HistoryNotice />
      {result.status === 'loading' && <p role="status">Loading…</p>}
      {result.status === 'error' && (
        <p
          role="alert"
          className="rounded-card border border-severity-high bg-severity-high-tint p-4"
        >
          {result.message}
        </p>
      )}
      {result.status === 'ready' &&
        (result.data.length === 0 ? (
          <p className="text-ink-soft">
            No debates yet.{' '}
            <Link to="/app" className="font-medium text-brass underline">
              Start the first one
            </Link>
          </p>
        ) : (
          <ul className="space-y-3">
            {result.data.map((item) => (
              <HistoryItem key={item.id} item={item} />
            ))}
          </ul>
        ))}
    </div>
  )
}
