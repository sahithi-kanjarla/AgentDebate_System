import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useDebate } from '../hooks/useDebate'
import type { SourceFactory } from '../hooks/useDebateStream'
import { orderedRounds, type DebateState } from '../lib/debateState'
import { DebateBoard } from '../components/DebateBoard'
import { DebateGraph } from '../components/graph/DebateGraph'
import { ErrorNotes } from '../components/ErrorNotes'
import { QuestionPlate } from '../components/QuestionPlate'
import { VerdictCard, VerdictMissing, VerdictPending } from '../components/VerdictCard'

/** Screen-reader summary of progress; the visual page is the source of truth. */
function progressText(state: DebateState): string {
  if (state.verdict) return 'The verdict is ready.'
  const rounds = orderedRounds(state)
  const last = rounds[rounds.length - 1]
  if (!last) return 'Waiting for the debate to start.'
  const turns = Object.values(last.turns)
  const answered = turns.filter((t) => t.status !== 'thinking').length
  return `Round ${last.round}: ${answered} of ${state.agents.length} debaters have answered.`
}

type View = 'graph' | 'columns'

function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  const item = (v: View, text: string) => (
    <button
      type="button"
      className="graph-btn"
      aria-pressed={view === v}
      onClick={() => onChange(v)}
    >
      {text}
    </button>
  )
  return (
    <div role="group" aria-label="Debate view" className="flex gap-2">
      {item('graph', 'Graph')}
      {item('columns', 'Columns')}
    </div>
  )
}

export function Debate({ sourceFactory }: { sourceFactory?: SourceFactory }) {
  const { id = '' } = useParams()
  const view = useDebate(id, sourceFactory)
  const [mode, setMode] = useState<View>('graph')

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
          <Link to="/" className="font-medium text-brass underline">
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

  const { header, state, connection } = view
  const rounds = orderedRounds(state)
  const finished = state.status === 'done' || state.status === 'failed'

  return (
    <div className="space-y-6">
      <QuestionPlate header={header} status={state.status} />

      <p role="status" className="sr-only-live">
        {progressText(state)}
      </p>

      {connection === 'reconnecting' && (
        <p role="status" className="rounded-card border border-rule-strong bg-vellum p-3 text-sm">
          The live connection dropped. Reconnecting…
        </p>
      )}
      {state.status === 'failed' && rounds.length > 0 && (
        <p role="status" className="rounded-card border border-rule-strong bg-vellum p-3 text-sm">
          This debate stopped before it finished. Showing everything that was received.
        </p>
      )}

      {rounds.length === 0 && !finished && <p role="status">Waiting for the debaters…</p>}

      {rounds.length > 0 && <ViewToggle view={mode} onChange={setMode} />}
      {mode === 'graph' ? (
        rounds.length > 0 && (
          <DebateGraph state={state} question={header.question} animate={connection !== 'closed'} />
        )
      ) : (
        <DebateBoard state={state} />
      )}

      <ErrorNotes errors={state.errors} />

      {state.verdict ? (
        <VerdictCard verdict={state.verdict} />
      ) : finished ? (
        <VerdictMissing
          interrupted={header.status === 'interrupted' || state.status === 'failed'}
        />
      ) : (
        state.judging && <VerdictPending />
      )}
    </div>
  )
}
