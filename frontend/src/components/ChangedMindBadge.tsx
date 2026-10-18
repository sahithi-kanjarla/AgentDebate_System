import { SwapIcon } from './Icons'

/** Shown only when the server says this debater's answer differs from its previous valid one. */
export function ChangedMindBadge({ before }: { before?: string }) {
  return (
    <div className="rounded-card border border-brass bg-brass-tint px-2.5 py-1.5 text-sm text-ink">
      <p className="flex items-center gap-1.5 font-medium">
        <span className="text-brass">
          <SwapIcon size={16} />
        </span>
        Changed its answer
      </p>
      {before !== undefined && (
        <p className="mt-1 text-xs text-ink-soft">
          Previously
          <span className="answer-text mt-0.5 block max-h-20 overflow-auto text-ink">{before}</span>
        </p>
      )}
    </div>
  )
}
