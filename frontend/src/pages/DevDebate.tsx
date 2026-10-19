import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { DebateScreen } from '../components/DebateScreen'
import { initialState, reduceAll, streamEnded } from '../lib/debateState'
import { FIXTURES, TEST_ONLY_NOTICE, type FixtureName } from '../test/graphFixtures'

/**
 * Development-only page (the route exists only under `vite dev`): the whole debate screen, with
 * replay, insights and the linked verdict, fed by a TEST-ONLY fixture instead of a server.
 */
export default function DevDebate() {
  const { fixture = '' } = useParams()
  const entry = FIXTURES[fixture as FixtureName]
  const state = useMemo(
    () => (entry ? streamEnded(reduceAll(entry.events, initialState())) : initialState()),
    [entry],
  )

  if (!entry) {
    return (
      <div>
        <h1 className="text-3xl">Unknown fixture</h1>
        <ul className="mt-3 list-disc pl-5">
          {Object.keys(FIXTURES).map((k) => (
            <li key={k}>
              <Link className="text-brass underline" to={`/dev/debate/${k}`}>
                {k}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <p className="rounded-card border border-dashed border-rule-strong bg-vellum p-2 text-sm text-ink-soft">
        {TEST_ONLY_NOTICE}
      </p>
      <DebateScreen
        header={{
          id: `fixture-${fixture}`,
          question: entry.question,
          mode: 'answer',
          status: 'completed',
          created_at: '2000-01-01T00:00:00Z',
        }}
        state={state}
        connection="closed"
        events={entry.events}
      />
    </div>
  )
}
