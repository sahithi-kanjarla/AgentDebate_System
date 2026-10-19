import { useEffect, useRef, useState } from 'react'
import type { Caption } from '../../lib/narrate'

/** While a replay plays, screen readers hear at most one caption this often. */
export const REPLAY_ANNOUNCE_MS = 2500
/** While a replay is paused or scrubbed, a caption is read once the position settles. */
export const SETTLE_MS = 400

type Mode = 'throttle' | 'settle' | 'off'

/**
 * Text for a polite live region that stays quiet during a replay: nothing at 2x and above, at most
 * one caption per REPLAY_ANNOUNCE_MS at slower speeds, and only the settled caption after a scrub.
 */
function useReplayAnnouncement(text: string, mode: Mode): string {
  const [spoken, setSpoken] = useState('')
  const lastAt = useRef(0)

  useEffect(() => {
    if (mode === 'off') {
      setSpoken('')
      return
    }
    const now = Date.now()
    const wait =
      mode === 'settle' ? SETTLE_MS : Math.max(0, lastAt.current + REPLAY_ANNOUNCE_MS - now)
    const id = setTimeout(() => {
      lastAt.current = Date.now()
      setSpoken(text)
    }, wait)
    return () => clearTimeout(id)
  }, [text, mode])

  return spoken
}

interface Props {
  captions: Caption[]
  /** Set during a replay so captions are announced sparingly instead of on every step. */
  replay?: { playing: boolean; speed: number } | null
}

/**
 * Plain-English captions from templates. The bar shows the latest step; Pause freezes it while a
 * live debate keeps moving, and "All steps" lists everything so far.
 */
export function NarratorBar({ captions, replay = null }: Props) {
  const [pausedAt, setPausedAt] = useState<number | null>(null)
  const paused = pausedAt !== null
  const shownIndex = paused ? Math.min(pausedAt, captions.length - 1) : captions.length - 1
  const shown = captions[shownIndex]
  const newer = paused ? captions.length - 1 - shownIndex : 0
  const text = shown ? shown.text : 'Waiting for the debate to start.'

  const mode: Mode = !replay
    ? 'off'
    : paused
      ? 'off'
      : replay.playing
        ? replay.speed >= 2
          ? 'off'
          : 'throttle'
        : 'settle'
  const spoken = useReplayAnnouncement(text, mode)

  return (
    <div
      className="rounded-card border border-rule-strong bg-vellum px-3 py-2"
      data-testid="narrator"
    >
      <div className="flex flex-wrap items-center gap-3">
        <p
          className="min-w-0 flex-1 text-base text-ink"
          aria-live={replay ? 'off' : paused ? 'off' : 'polite'}
          data-testid="caption"
        >
          {text}
        </p>
        {replay && (
          <p className="sr-only-live" aria-live="polite" data-testid="caption-announce">
            {spoken}
          </p>
        )}
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
