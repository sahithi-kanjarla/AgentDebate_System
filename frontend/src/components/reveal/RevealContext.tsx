import { createContext, useContext } from 'react'
import { modelFor, modelText, type Reveal } from '../../lib/reveal'

const RevealContext = createContext<Reveal | null>(null)

/** Holds the revealed models for one page view; null (the default) means everyone is anonymous. */
export const RevealProvider = RevealContext.Provider

export function useReveal(): Reveal | null {
  return useContext(RevealContext)
}

/**
 * A debater's model, shown only after the reveal. With a round it is the model that answered that
 * turn (a backup is marked); without one it is the debater's main model.
 */
export function ModelTag({
  label,
  round,
  onlyBackup = false,
  className = '',
}: {
  label: string
  round?: number | null
  /** Show nothing unless a backup answered this turn. */
  onlyBackup?: boolean
  className?: string
}) {
  const reveal = useReveal()
  if (!reveal) return null
  const found = modelFor(reveal, label, round)
  if (!found || (onlyBackup && !found.backup)) return null
  return (
    <span
      data-testid="model-tag"
      className={`inline-flex max-w-full flex-wrap items-center gap-1.5 rounded-chip border border-brass bg-brass-tint px-1.5 py-0.5 font-mono text-xs text-ink ${className}`}
    >
      <span className="break-all">{modelText(found.model)}</span>
      {found.backup && <span className="font-sans font-semibold">backup</span>}
    </span>
  )
}
