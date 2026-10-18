import type { ReceivedCritique, TurnCritique } from '../lib/debateState'
import { SeverityMark } from './SeverityMark'

/** Critiques this debater raised. Issue text is shown verbatim (it uses the critic's own labels). */
export function CritiqueList({ from, critiques }: { from: string; critiques: TurnCritique[] }) {
  if (critiques.length === 0) {
    return <p className="text-sm text-ink-soft">Raised no critiques.</p>
  }
  return (
    <ul className="space-y-2">
      {critiques.map((c, i) => (
        <li key={i} className="rounded-card border border-rule bg-paper p-2.5">
          <p className="mb-1 flex flex-wrap items-center gap-2 text-sm">
            <SeverityMark severity={c.severity} />
            <span className="font-medium text-ink">
              {from}
              <span aria-hidden="true"> → </span>
              <span className="sr-only"> to </span>
              {c.target ?? 'a peer'}
            </span>
          </p>
          <p className="whitespace-pre-wrap break-words text-sm text-ink">{c.issue}</p>
        </li>
      ))}
    </ul>
  )
}

/**
 * Critiques raised this round against the answer the debater revised. Debaters do not see these,
 * so this is context, not an explanation of why anyone changed their answer.
 */
export function ReceivedCritiques({ critiques }: { critiques: ReceivedCritique[] }) {
  return (
    <section aria-label="Critiques of the answer it revised">
      <h4 className="mb-1.5 text-sm font-semibold text-ink">Critiques of the answer it revised</h4>
      {critiques.length === 0 ? (
        <p className="text-sm text-ink-soft">None were raised.</p>
      ) : (
        <ul className="space-y-2">
          {critiques.map((c, i) => (
            <li key={i} className="rounded-card border border-rule bg-paper p-2.5">
              <p className="mb-1 flex flex-wrap items-center gap-2 text-sm">
                <SeverityMark severity={c.severity} />
                <span className="font-medium text-ink">From {c.from_agent}</span>
              </p>
              <p className="whitespace-pre-wrap break-words text-sm text-ink">{c.issue}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
