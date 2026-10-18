import { clusterColor, clusterLetter, clusterPattern } from '../lib/palette'

/** An answer cluster: pattern swatch + letter + the answer, shown exactly as received. */
export function AnswerChip({
  clusterId,
  answer,
  members,
}: {
  clusterId: number
  answer: string
  members?: string[]
}) {
  const letter = clusterLetter(clusterId)
  return (
    <div
      className="flex min-w-0 items-start gap-2 rounded-card border border-rule bg-paper px-2.5 py-1.5"
      data-cluster={clusterId}
    >
      <span
        className="swatch mt-1"
        data-pattern={clusterPattern(clusterId)}
        style={{ ['--c' as string]: clusterColor(clusterId) }}
        aria-hidden="true"
      />
      <div className="min-w-0">
        <p className="text-xs font-medium text-ink-soft">
          Answer {letter}
          {members && members.length > 0 ? `, held by ${members.join(', ')}` : ''}
        </p>
        <p className="answer-text max-h-28 overflow-auto text-ink">{answer}</p>
      </div>
    </div>
  )
}
