import { useEffect, useMemo, useState } from 'react'
import { useReplay } from '../../hooks/useReplay'
import { initialState, reduceAll, streamEnded } from '../../lib/debateState'
import { eventsFor, stageEnds } from '../../lib/demoEvents'
import { narrationAt, stagesFor } from '../../lib/demoStages'
import type { ExampleSet, LandingExample } from '../../lib/landing'
import { DebateGraph } from '../graph/DebateGraph'

/** Quick enough to watch a whole run in about a quarter of a minute. */
const PLAY_SPEED = 2

/** The question as asked, with the ruling and the answer key marked once the judge has spoken. */
function Question({ example, atVerdict }: { example: LandingExample; atVerdict: boolean }) {
  return (
    <div>
      <p className="text-xs font-medium text-ink-soft">
        {example.category} question from the test set
      </p>
      <p className="mt-1.5 whitespace-pre-wrap text-base leading-6 text-ink">{example.stem}</p>
      <ul className="mt-3 max-h-56 space-y-0.5 overflow-y-auto pr-1" aria-label="Answer options">
        {example.options.map((o) => {
          const ruled = atVerdict && o.letter === example.final.answer
          const key = atVerdict && o.letter === example.gold
          return (
            <li
              key={o.letter}
              className={`opt ${ruled || key ? 'is-held' : ''} ${key ? 'is-key' : ''}`}
            >
              <span className="opt-letter">{o.letter}</span>
              <span className="min-w-0 flex-1 text-sm leading-5 text-ink">{o.text}</span>
              {ruled && <span className="tag mg-in">Judge&rsquo;s ruling</span>}
              {key && <span className="tag tag-key mg-in">Answer key</span>}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function Player({ example }: { example: LandingExample }) {
  const events = useMemo(() => eventsFor(example), [example])
  const stages = useMemo(() => stagesFor(example), [example])
  const ends = useMemo(() => stageEnds(events), [events])
  const finalState = useMemo(() => streamEnded(reduceAll(events, initialState())), [events])
  const replay = useReplay(events, finalState, { startAtBeginning: true })
  const { setSpeed, seek, position, total } = replay
  useEffect(() => setSpeed(PLAY_SPEED), [setSpeed])

  // The stage we are in: the first one whose end has not been passed.
  const found = ends.findIndex((e) => position <= e)
  const current = found === -1 ? stages.length - 1 : found
  const last = stages.length - 1
  const atVerdict = position >= total
  const narration = narrationAt(example, stages[current]!)
  const view = replay.state

  const go = (n: number) => {
    replay.pause()
    seek(ends[Math.max(0, Math.min(last, n))]!)
  }
  // Back goes to the start of the stage you are in, or the one before if already there.
  const settled = position === ends[current]
  const back = () => go(settled ? current - 1 : current)

  return (
    <div>
      {/* controls first, so Play is on screen without scrolling */}
      <div className="rounded-card border border-rule-strong bg-paper">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <div className="border-b border-rule p-4 sm:p-5 lg:border-b-0 lg:border-r">
            <Question example={example} atVerdict={atVerdict} />
          </div>
          <div className="flex flex-col p-4 sm:p-5">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={replay.toggle}
                aria-pressed={replay.playing}
              >
                {replay.playing
                  ? 'Pause'
                  : atVerdict
                    ? 'Replay'
                    : position === 0
                      ? 'Play'
                      : 'Resume'}
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={back}
                disabled={position === 0}
              >
                Back
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => go(current + (settled ? 1 : 0))}
                disabled={atVerdict}
              >
                Next stage
              </button>
            </div>

            <ol
              aria-label="Stages of the debate"
              className="mt-4 grid auto-cols-fr grid-flow-col gap-1.5"
            >
              {stages.map((s, n) => (
                <li key={s.label}>
                  <button
                    type="button"
                    onClick={() => go(n)}
                    aria-current={n === current ? 'step' : undefined}
                    className={`stage-btn ${n === current ? 'is-current' : n < current ? 'is-done' : ''}`}
                  >
                    <span className="block text-xs">{n + 1}</span>
                    <span className="block text-[0.8125rem] font-medium leading-tight">
                      {s.label}
                    </span>
                  </button>
                </li>
              ))}
            </ol>

            <div key={current} className="mg-in mt-4" aria-live="polite">
              <h3 className="text-lg leading-6 text-ink">{narration.title}</h3>
              <div className="mt-1 space-y-1 text-sm text-ink-soft">
                {narration.lines.map((l) => (
                  <p key={l}>{l}</p>
                ))}
              </div>
            </div>
            <p className="mt-auto pt-4 text-xs text-ink-soft">
              Click any circle in the graph below to see that debater&rsquo;s answer.
            </p>
          </div>
        </div>
      </div>

      <div className="mt-4">
        {position > 0 && (
          <DebateGraph
            state={view}
            question={example.stem}
            animate={replay.motion}
            replay={replay.touched ? { playing: replay.playing, speed: replay.speed } : null}
          />
        )}
        {position === 0 && (
          <p className="rounded-card border border-rule bg-vellum p-6 text-sm text-ink-soft">
            Press Play, or Next stage, to send the question to the debaters.
          </p>
        )}
      </div>
    </div>
  )
}

/** Pick one of the real questions, then play it or step through it stage by stage. */
export function ExampleDemo({ set, initialId }: { set: ExampleSet; initialId?: string | null }) {
  const start = Math.max(
    0,
    set.examples.findIndex((e) => e.id === initialId),
  )
  const [chosen, setChosen] = useState(start)
  const example = set.examples[Math.min(chosen, set.examples.length - 1)]!

  return (
    <div>
      <div
        role="radiogroup"
        aria-label="Choose a question"
        className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4"
      >
        {set.examples.map((e, n) => (
          <button
            key={e.id}
            type="button"
            role="radio"
            aria-checked={n === chosen}
            onClick={() => setChosen(n)}
            className={`pick ${n === chosen ? 'is-active' : ''}`}
          >
            <span className="block text-xs font-medium text-ink-soft">{e.category}</span>
            <span className="mt-0.5 line-clamp-2 text-sm leading-5 text-ink">{e.stem}</span>
          </button>
        ))}
      </div>
      <div className="mt-4">
        <Player key={example.id} example={example} />
      </div>
      <p className="mt-3 max-w-[72ch] text-xs text-ink-soft">
        Real runs from our test set, hand-picked.
      </p>
    </div>
  )
}
