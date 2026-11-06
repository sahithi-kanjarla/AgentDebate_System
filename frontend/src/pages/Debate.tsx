import { Link, useParams } from 'react-router-dom'
import { useDebate } from '../hooks/useDebate'
import type { SourceFactory } from '../hooks/useDebateStream'
import { DebateScreen } from '../components/DebateScreen'

export function Debate({ sourceFactory }: { sourceFactory?: SourceFactory }) {
  const { id = '' } = useParams()
  const view = useDebate(id, sourceFactory)

  if (view.phase === 'loading') {
    return <p role="status">Loading debate…</p>
  }
  if (view.phase === 'notfound') {
    return (
      <div className="max-w-xl">
        <h1 className="text-3xl">Debate not found</h1>
        <p className="mt-2 text-ink-soft">
          Nothing is stored under this link. It may have been mistyped, or the history was reset.
        </p>
        <p className="mt-4">
          <Link to="/app" className="font-medium text-brass underline">
            Start a new debate
          </Link>
        </p>
      </div>
    )
  }
  if (view.phase === 'error') {
    return (
      <p
        role="alert"
        className="max-w-xl rounded-card border border-severity-high bg-severity-high-tint p-4"
      >
        {view.message}
      </p>
    )
  }

  const { header, state, connection, events } = view
  return (
    <DebateScreen
      header={header}
      state={state}
      connection={connection}
      events={events}
      revealDebateId={header.id}
    />
  )
}
