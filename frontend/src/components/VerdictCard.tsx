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

/** The ruling. `final_answer` is rendered exactly as received: pre-wrap, monospace, never trimmed. */
export function VerdictCard({ verdict }: { verdict: Verdict }) {
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
            {verdict.mistakes_caught.map((m, i) => (
              <li key={i} className="rounded-card border border-rule bg-vellum p-3">
                <p className="mb-1 text-sm font-medium text-ink">
                  {m.caught_by} caught this in round {m.round}
                </p>
                <p className="whitespace-pre-wrap break-words text-sm text-ink">{m.description}</p>
              </li>
            ))}
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
