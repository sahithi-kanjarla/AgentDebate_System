import { useState } from 'react'
import type { Caption } from '../../lib/narrate'

/**
 * Plain-English captions from templates. The bar shows the latest step; Pause freezes it while a
 * live debate keeps moving, and "All steps" lists everything so far.
 */
export function NarratorBar({ captions }: { captions: Caption[] }) {
  const [pausedAt, setPausedAt] = useState<number | null>(null)
  const paused = pausedAt !== null
  const shownIndex = paused ? Math.min(pausedAt, captions.length - 1) : captions.length - 1
  const shown = captions[shownIndex]
  const newer = paused ? captions.length - 1 - shownIndex : 0

  return (
    <div
      className="rounded-card border border-rule-strong bg-vellum px-3 py-2"
      data-testid="narrator"
    >
      <div className="flex flex-wrap items-center gap-3">
        <p
          className="min-w-0 flex-1 text-base text-ink"
          aria-live={paused ? 'off' : 'polite'}
          data-testid="caption"
        >
          {shown ? shown.text : 'Waiting for the debate to start.'}
        </p>
        {paused && newer > 0 && <span className="text-xs text-ink-soft">{newer} newer</span>}
        <button
          type="button"
          className="graph-btn"
          aria-pressed={paused}
          onClick={() => setPausedAt(paused ? null : Math.max(0, captions.length - 1))}
        >
          {paused ? 'Resume captions' : 'Pause captions'}
        </button>
      </div>
      {captions.length > 1 && (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-sm text-ink-soft">
            All steps ({captions.length})
          </summary>
          <ol className="mt-1.5 max-h-48 list-decimal space-y-0.5 overflow-auto pl-5 text-sm text-ink">
            {captions.map((c) => (
              <li key={c.id}>{c.text}</li>
            ))}
          </ol>
        </details>
      )}
    </div>
  )
}
