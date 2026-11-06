import { useEffect, useState } from 'react'

export const SLOW_AFTER_MS = 60_000

/**
 * One line, shown after a running debate has gone about a minute without finishing. Mount it only
 * while the debate runs: the timer starts on mount and the line disappears when it unmounts.
 */
export function SlowNotice() {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), SLOW_AFTER_MS)
    return () => clearTimeout(t)
  }, [])
  if (!slow) return null
  return (
    <p role="status" data-testid="slow-notice" className="text-sm text-ink-soft">
      Free models can be slow. Keep this page open, or{' '}
      <a
        href="/app?tab=demo"
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium text-brass underline"
      >
        watch a demo
      </a>{' '}
      while you wait.
    </p>
  )
}
