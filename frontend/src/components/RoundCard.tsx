import type { TurnState } from '../lib/debateState'
import { clusterLetter, debaterColor } from '../lib/palette'
import { ChangedMindBadge } from './ChangedMindBadge'
import { CritiqueList, ReceivedCritiques } from './CritiqueList'
import { PersonaBadge } from './PersonaBadge'
import { ModelTag } from './reveal/RevealContext'
import { ThinkingState } from './ThinkingState'

interface Props {
  round: number
  label: string
  persona: string
  index: number
  turn: TurnState | undefined
  previousAnswer: string | undefined
}

/** One debater's contribution to one round. `turn` is undefined until the round reaches them. */
export function RoundCard({ round, label, persona, index, turn, previousAnswer }: Props) {
  return (
    <article
      aria-label={`${label}, round ${round}`}
      className="fade-in flex min-w-0 flex-col gap-3 rounded-card border border-rule border-t-4 bg-vellum p-4"
      style={{ borderTopColor: debaterColor(index) }}
    >
      {/* Repeated on every card so a stacked (narrow) layout still says whose card this is. */}
      <header className="md:hidden">
        <PersonaBadge label={label} persona={persona} index={index} />
        <ModelTag label={label} round={round} className="ml-1 mt-1.5" />
      </header>
      {/* The column heading already names the main model; only a backup is worth a note here. */}
      <ModelTag label={label} round={round} onlyBackup className="hidden md:inline-flex" />

      {turn === undefined && <ThinkingState text={`Waiting for ${label}…`} />}
      {turn?.status === 'thinking' && <ThinkingState text={`${label} is thinking…`} />}

      {turn?.status === 'invalid' && (
        <div
          role="alert"
          className="rounded-card border border-severity-high bg-severity-high-tint p-3 text-sm text-ink"
        >
          <p className="font-medium">No usable answer this round</p>
          <p className="mt-1 whitespace-pre-wrap break-words text-ink-soft">{turn.error}</p>
        </div>
      )}

      {turn?.status === 'answered' && (
        <AnsweredBody round={round} label={label} turn={turn} previousAnswer={previousAnswer} />
      )}
    </article>
  )
}

function AnsweredBody({
  round,
  label,
  turn,
  previousAnswer,
}: {
  round: number
  label: string
  turn: TurnState
  previousAnswer: string | undefined
}) {
  return (
    <>
      <section aria-label="Final answer">
        <h3 className="mb-1 flex items-baseline justify-between gap-2 font-sans text-sm font-semibold text-ink">
          <span>{round === 0 ? 'Independent answer' : 'Answer after critique'}</span>
          {turn.clusterId !== undefined && (
            <span className="text-xs font-normal text-ink-soft">
              Answer {clusterLetter(turn.clusterId)}
            </span>
          )}
        </h3>
        <p className="answer-text rounded-card border border-rule bg-paper p-2.5 text-ink">
          {turn.finalAnswer}
        </p>
        {turn.confidence !== undefined && (
          <p className="mt-1 text-xs text-ink-soft">Confidence {turn.confidence}%</p>
        )}
      </section>

      {turn.changedMind && <ChangedMindBadge before={previousAnswer} />}

      {turn.reasoning ? (
        <details className="group">
          <summary className="cursor-pointer text-sm font-medium text-ink-soft group-open:text-ink">
            Reasoning
          </summary>
          <p className="mt-2 whitespace-pre-wrap break-words text-sm text-ink">{turn.reasoning}</p>
        </details>
      ) : null}

      {round > 0 && <CritiquesBlock label={label} turn={turn} />}
    </>
  )
}

function CritiquesBlock({ label, turn }: { label: string; turn: TurnState }) {
  return (
    <div className="space-y-4">
      <section aria-label="Critiques it raised">
        <h4 className="mb-1.5 text-sm font-semibold text-ink">Critiques it raised</h4>
        <CritiqueList from={label} critiques={turn.critiques} />
      </section>
      <ReceivedCritiques critiques={turn.receivedCritiques} />
    </div>
  )
}
