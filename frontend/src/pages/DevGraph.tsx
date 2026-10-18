import { useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { DebateGraph } from '../components/graph/DebateGraph'
import { initialState, reduce, reduceAll, type DebateState } from '../lib/debateState'
import { FIXTURES, TEST_ONLY_NOTICE, type FixtureName } from '../test/graphFixtures'

/**
 * Development-only page (the route exists only under `vite dev`): renders a TEST-ONLY fixture
 * through the same reducer and graph as a real debate. `?live=1` feeds the events in one at a time
 * so arrivals, pulses and flashes can be watched; otherwise the finished state is shown statically.
 */
export default function DevGraph() {
  const { fixture = '' } = useParams()
  const [params] = useSearchParams()
  const live = params.get('live') === '1'
  const interval = Number(params.get('ms') ?? 900)
  const entry = FIXTURES[fixture as FixtureName]
  const [run, setRun] = useState(0)
  const [state, setState] = useState<DebateState>(() => initialState())

  const staticState = useMemo(() => (entry ? reduceAll(entry.events) : initialState()), [entry])

  useEffect(() => {
    if (!entry || !live) return
    setState(initialState())
    let i = 0
    const id = window.setInterval(() => {
      const event = entry.events[i++]
      if (!event) return window.clearInterval(id)
      setState((s) => reduce(s, event))
    }, interval)
    return () => window.clearInterval(id)
  }, [entry, live, interval, run])

  if (!entry) {
    return (
      <div>
        <h1 className="text-3xl">Unknown fixture</h1>
        <ul className="mt-3 list-disc pl-5">
          {Object.keys(FIXTURES).map((k) => (
            <li key={k}>
              <Link className="text-brass underline" to={`/dev/graph/${k}`}>
                {k}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    )
  }
  const shown = live ? state : staticState
  return (
    <div className="space-y-4">
      <p
        role="note"
        className="rounded-card border border-severity-medium bg-severity-medium-tint p-3 text-sm font-medium"
      >
        {TEST_ONLY_NOTICE} ({fixture})
      </p>
      <div className="flex flex-wrap gap-2 text-sm">
        {Object.keys(FIXTURES).map((k) => (
          <Link key={k} className="graph-btn" to={`/dev/graph/${k}${live ? '?live=1' : ''}`}>
            {k}
          </Link>
        ))}
        {live && (
          <button type="button" className="graph-btn" onClick={() => setRun((n) => n + 1)}>
            Replay
          </button>
        )}
      </div>
      {shown.agents.length > 0 || !live ? (
        <DebateGraph state={shown} question={entry.question} animate={live} />
      ) : (
        <p role="status">Waiting for the first event…</p>
      )}
    </div>
  )
}
