import type { MistakeLink } from '../lib/mistakeLinks'
import type { Verdict } from '../lib/types'
import { CheckIcon } from './Icons'
import { ThinkingState } from './ThinkingState'

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(value)))
  return (
    <div>
      <p className="mb-1 text-sm text-ink-soft">
        Confidence <span className="font-semibold text-ink">{pct}%</span>
      </p>
      <div
        role="meter"
        aria-label="Confidence"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={`${pct} percent`}
        className="h-3 w-full overflow-hidden rounded-pill border border-ink bg-paper"
      >
        <div className="h-full bg-brass-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

/** Hover, focus and pin state for the Mistakes caught items, owned by the page so the graph can share it. */
export interface MistakeLinking {
  links: MistakeLink[]
  /** Indices to show as linked: hovered or focused here, or the edge being hovered in the graph. */
  active: ReadonlySet<number>
  pinned: number | null
  onActivate: (index: number | null) => void
  onPin: (index: number) => void
}

/** The ruling. `final_answer` is rendered exactly as received: pre-wrap, monospace, never trimmed. */
export function VerdictCard({ verdict, linking }: { verdict: Verdict; linking?: MistakeLinking }) {
  return (
    <section
      aria-labelledby="verdict-heading"
      className="fade-in rounded-card border border-rule-strong border-t-[6px] border-t-brass-fill bg-paper p-5 sm:p-6"
    >
      <h2 id="verdict-heading" className="mb-3 font-serif text-2xl text-ink">
        Verdict
      </h2>

      <div className="grid gap-5 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="min-w-0">
          <p className="mb-1 text-sm font-semibold text-ink">Final answer</p>
          <p
            data-testid="final-answer"
            className="answer-text rounded-card border border-rule bg-vellum p-3 text-base text-ink"
          >
            {verdict.final_answer}
          </p>
        </div>
        <div className="space-y-3">
          <ConfidenceBar value={verdict.confidence} />
          <p className="flex items-center gap-1.5 text-sm text-ink">
            {verdict.consensus_reached ? (
              <>
                <span className="text-ok">
                  <CheckIcon size={16} />
                </span>
                The debaters reached consensus
              </>
            ) : (
              'The debaters did not reach consensus'
            )}
          </p>
        </div>
      </div>

      {verdict.summary && (
        <p className="mt-5 max-w-[68ch] whitespace-pre-wrap font-serif text-lg leading-relaxed text-ink">
          {verdict.summary}
        </p>
      )}

      <section aria-labelledby="mistakes-heading" className="mt-6">
        <h3 id="mistakes-heading" className="mb-2 font-sans text-base font-semibold text-ink">
          Mistakes caught ({verdict.mistakes_caught.length})
        </h3>
        {verdict.mistakes_caught.length === 0 ? (
          <p className="text-sm text-ink-soft">No mistakes were recorded in this debate.</p>
        ) : (
          <ul className="space-y-2">
            {verdict.mistakes_caught.map((m, i) => {
              const link = linking?.links[i]
              const linkable = linking !== undefined && link !== undefined && link.kind !== 'none'
              const active = linkable && linking.active.has(i)
              const pinned = linkable && linking.pinned === i
              const noteId = `mistake-note-${i}`
              return (
                <li
                  key={i}
                  className="mistake-item rounded-card border border-rule bg-vellum p-3"
                  data-testid="mistake-item"
                  data-linked={active ? 'true' : undefined}
                  data-link-kind={link?.kind}
                  onPointerEnter={linkable ? () => linking.onActivate(i) : undefined}
                  onPointerLeave={linkable ? () => linking.onActivate(null) : undefined}
                  onFocus={linkable ? () => linking.onActivate(i) : undefined}
                  onBlur={linkable ? () => linking.onActivate(null) : undefined}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p className="text-sm font-medium text-ink">
                      {m.caught_by} caught this in round {m.round}
                    </p>
                    {linkable && (
                      <button
                        type="button"
                        className="graph-btn"
                        aria-pressed={pinned}
                        aria-describedby={link.note ? noteId : undefined}
                        onClick={() => linking.onPin(i)}
                      >
                        Show in graph
                      </button>
                    )}
                  </div>
                  <p className="mt-1 whitespace-pre-wrap break-words text-sm text-ink">
                    {m.description}
                  </p>
                  {linkable && link.note && (
                    <p id={noteId} className="mt-1.5 text-xs text-ink-soft">
                      {link.note}
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {verdict.dissent && (
        <section aria-labelledby="dissent-heading" className="mt-6">
          <h3 id="dissent-heading" className="mb-1 font-sans text-base font-semibold text-ink">
            Dissent
          </h3>
          <p className="max-w-[68ch] whitespace-pre-wrap text-sm text-ink">{verdict.dissent}</p>
        </section>
      )}
    </section>
  )
}

export function VerdictPending() {
  return (
    <section className="rounded-card border border-dashed border-rule-strong bg-vellum p-5">
      <ThinkingState text="The judge is reviewing the debate…" />
    </section>
  )
}

export function VerdictMissing({ interrupted }: { interrupted: boolean }) {
  return (
    <section className="rounded-card border border-dashed border-rule-strong bg-vellum p-5 text-sm text-ink">
      <p className="font-medium">No verdict was produced</p>
      <p className="mt-1 text-ink-soft">
        {interrupted
          ? 'This debate was interrupted before the judge ruled.'
          : 'The debate ended before the judge ruled.'}
      </p>
    </section>
  )
}
