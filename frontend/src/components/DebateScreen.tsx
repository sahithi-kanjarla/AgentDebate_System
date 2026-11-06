import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { useReplay } from '../hooks/useReplay'
import { usePrefersReducedMotion } from '../hooks/usePrefersReducedMotion'
import type { Connection } from '../hooks/useDebateStream'
import { orderedRounds, type DebateState } from '../lib/debateState'
import { buildGraphModel } from '../lib/graphModel'
import { caughtEdgeIds, mistakesByEdge, resolveMistakes } from '../lib/mistakeLinks'
import type { Reveal } from '../lib/reveal'
import type { DebateHeader, RawEvent } from '../lib/types'
import { DebateBoard } from './DebateBoard'
import { ErrorNotes } from './ErrorNotes'
import { QuestionPlate } from './QuestionPlate'
import { SlowNotice } from './SlowNotice'
import { VerdictCard, VerdictMissing, VerdictPending } from './VerdictCard'
import { DebateGraph, type GraphHighlight } from './graph/DebateGraph'
import { Insights } from './insights/Insights'
import { RevealPanel, RevealSanitizedNote } from './reveal/RevealPanel'
import { RevealProvider } from './reveal/RevealContext'
import { ReplayBar } from './replay/ReplayBar'
import { Tour, tourDone } from './tour/Tour'

const NO_EVENTS: RawEvent[] = []

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

function ViewToggle({
  view,
  onChange,
  extra,
}: {
  view: View
  onChange: (v: View) => void
  extra?: ReactNode
}) {
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
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div role="group" aria-label="Debate view" className="flex gap-2">
        {item('graph', 'Graph')}
        {item('columns', 'Columns')}
      </div>
      {extra}
    </div>
  )
}

const EMPTY_HIGHLIGHT: GraphHighlight = { edgeIds: new Set(), nodeIds: new Set() }

interface Props {
  header: DebateHeader
  /** The state of the whole debate so far (the final state once it has finished). */
  state: DebateState
  connection: Connection
  /** The ordered event log; a finished debate can be replayed from it. */
  events: RawEvent[]
  /** A saved example: it starts at the beginning and plays once (unless the person prefers less motion). */
  recorded?: boolean
  /** Shown above the debate, e.g. the "Recorded example" notice. */
  banner?: ReactNode
  /**
   * Set only for a stored debate on the server: a finished one then offers "Show which model was
   * which". Left out for fixtures and recorded examples, which have nothing to reveal.
   */
  revealDebateId?: string
}

/**
 * One debate, live or finished. Everything on screen is derived from a single DebateState: the real
 * one, or, while a replay is not at its end, the reducer's state for the events played so far. So the
 * graph, narrator, insights and verdict can never disagree about where the debate is.
 */
export function DebateScreen({
  header,
  state,
  connection,
  events,
  recorded,
  banner,
  revealDebateId,
}: Props) {
  const [mode, setMode] = useState<View>('graph')
  // Who answered each turn, once asked for. Per page view: nothing is stored.
  const [reveal, setReveal] = useState<Reveal | null>(null)
  const finished = state.status === 'done' || state.status === 'failed'
  const reduced = usePrefersReducedMotion()
  const replay = useReplay(finished ? events : NO_EVENTS, state, {
    // Under reduced motion a recorded example opens on the finished debate, with the same controls.
    startAtBeginning: recorded === true && !reduced,
    autoplay: recorded === true && !reduced,
  })
  const view = replay.available ? replay.state : state

  const rounds = orderedRounds(state)
  const viewFinished = view.status === 'done' || view.status === 'failed'
  const animate = replay.available ? replay.motion : connection !== 'closed'

  // --- Mistakes caught <-> critique edges
  const model = useMemo(() => buildGraphModel(view, header.question), [view, header.question])
  const links = useMemo(
    () => resolveMistakes(model, view.verdict?.mistakes_caught ?? []),
    [model, view.verdict],
  )
  const byEdge = useMemo(() => mistakesByEdge(links), [links])
  const caught = useMemo(() => caughtEdgeIds(links), [links])
  const [hovered, setHovered] = useState<number | null>(null)
  const [pinned, setPinned] = useState<number | null>(null)
  const [activeEdge, setActiveEdge] = useState<string | null>(null)
  const onEdgeActive = useCallback((id: string | null) => setActiveEdge(id), [])

  // --- tour: only once there is a finished debate to point at, and never while it is playing
  const [tourOpen, setTourOpen] = useState<boolean | null>(null)
  const [tourStep, setTourStep] = useState<string | null>(null)
  const tourReady = finished && rounds.length > 0 && !(replay.available && replay.playing)
  const showTour = tourReady && mode === 'graph' && (tourOpen ?? !tourDone())
  const closeTour = useCallback(() => setTourOpen(false), [])

  const lit = hovered ?? pinned
  const highlight = useMemo<GraphHighlight>(() => {
    const l = lit !== null ? links[lit] : undefined
    return l ? { edgeIds: new Set(l.edgeIds), nodeIds: new Set(l.nodeIds) } : EMPTY_HIGHLIGHT
  }, [lit, links])
  const activeMistakes = useMemo(() => {
    const out = new Set<number>()
    if (hovered !== null) out.add(hovered)
    if (pinned !== null) out.add(pinned)
    if (activeEdge) for (const i of byEdge.get(activeEdge) ?? []) out.add(i)
    return out
  }, [hovered, pinned, activeEdge, byEdge])

  return (
    <RevealProvider value={reveal}>
      <div
        className="space-y-6"
        data-replay-seek={replay.available && !replay.motion ? '' : undefined}
        data-tour={showTour ? (tourStep ?? undefined) : undefined}
      >
        {banner}
        <QuestionPlate header={header} status={view.status} />

        <p role="status" className="sr-only-live" aria-live={replay.available ? 'off' : undefined}>
          {progressText(view)}
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

        {!finished && !recorded && <SlowNotice />}

        {rounds.length === 0 && !finished && <p role="status">Waiting for the debaters…</p>}

        {replay.available && rounds.length > 0 && <ReplayBar replay={replay} />}

        {rounds.length > 0 && (
          <ViewToggle
            view={mode}
            onChange={setMode}
            extra={
              tourReady && mode === 'graph' ? (
                <button type="button" className="graph-btn" onClick={() => setTourOpen(true)}>
                  Replay the tour
                </button>
              ) : null
            }
          />
        )}
        {mode === 'graph' ? (
          rounds.length > 0 && (
            <DebateGraph
              state={view}
              question={header.question}
              animate={animate}
              highlight={highlight}
              onEdgeActive={onEdgeActive}
              caughtEdgeIds={caught}
              replay={
                replay.available && replay.touched
                  ? { playing: replay.playing, speed: replay.speed }
                  : null
              }
            />
          )
        ) : (
          <DebateBoard state={view} />
        )}

        {rounds.length > 0 && <Insights state={view} question={header.question} />}

        <ErrorNotes errors={view.errors} />

        {view.verdict ? (
          <VerdictCard
            verdict={view.verdict}
            linking={{
              links,
              active: activeMistakes,
              pinned,
              onActivate: setHovered,
              onPin: (i) => setPinned((p) => (p === i ? null : i)),
            }}
          />
        ) : viewFinished ? (
          <VerdictMissing
            interrupted={header.status === 'interrupted' || view.status === 'failed'}
          />
        ) : (
          view.judging && <VerdictPending />
        )}
        {finished && revealDebateId && (
          <RevealPanel debateId={revealDebateId} reveal={reveal} onChange={setReveal} />
        )}
        {finished && recorded && <RevealSanitizedNote />}
        {showTour && <Tour onStep={setTourStep} onClose={closeTour} />}
      </div>
    </RevealProvider>
  )
}
