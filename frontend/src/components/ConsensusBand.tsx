import { agreement, type RoundState } from '../lib/debateState'
import { AnswerChip } from './AnswerChip'
import { CheckIcon } from './Icons'

/**
 * The band between rounds: how many debaters hold the same answer, and which answers exist.
 * Agreement is words, segments and chips grouped by answer; colour never carries it alone.
 */
export function ConsensusBand({ round }: { round: RoundState }) {
  const counts = agreement(round)
  if (!round.summary || !counts) return null
  const { agree, total } = counts
  const unanimous = round.summary.agreed

  return (
    <section
      aria-label={`Agreement after round ${round.round}`}
      className="fade-in rounded-card border border-rule-strong bg-paper p-4"
    >
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="font-serif text-lg font-semibold text-ink">
          {unanimous ? (
            <span className="inline-flex items-center gap-1.5">
              <span className="text-ok">
                <CheckIcon size={18} />
              </span>
              All {total} agree
            </span>
          ) : (
            <>
              {agree} of {total} agree
            </>
          )}
        </p>
        <div
          role="img"
          aria-label={`${agree} of ${total} agree`}
          className="flex gap-1"
          data-testid="consensus-segments"
        >
          {Array.from({ length: total }, (_, i) => (
            <span
              key={i}
              className={`h-2.5 w-7 rounded-chip border border-ink ${i < agree ? 'bg-ink' : 'bg-paper'}`}
            />
          ))}
        </div>
        <p className="text-sm text-ink-soft">
          After {round.round === 0 ? 'the independent answers' : `round ${round.round}`}
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {round.summary.clusters.map((c) => (
          <AnswerChip
            key={c.clusterId}
            clusterId={c.clusterId}
            answer={c.answer}
            members={c.agents}
          />
        ))}
      </div>
    </section>
  )
}
