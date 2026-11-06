import { useState } from 'react'
import { getReveal } from '../../lib/api'
import { friendlyMessage } from '../../lib/friendly'
import {
  REVEAL_NOTE,
  backupTurns,
  modelText,
  type Reveal,
  type RevealEntry,
} from '../../lib/reveal'
import { PersonaBadge } from '../PersonaBadge'

function EntryRow({ entry, index }: { entry: RevealEntry; index: number }) {
  const backups = backupTurns(entry)
  return (
    <li className="flex flex-col gap-1.5 rounded-card border border-rule bg-paper p-3 sm:flex-row sm:items-start sm:justify-between">
      <div>
        {entry.label === 'Judge' ? (
          <p className="text-sm font-semibold text-ink">Judge</p>
        ) : (
          <PersonaBadge label={entry.label} persona={entry.persona} index={index} />
        )}
        {backups.length > 0 && (
          <p className="mt-1.5 text-xs text-ink-soft">
            A backup answered {backups.map((t) => `round ${t.round} (${modelText(t)})`).join(', ')}.
          </p>
        )}
      </div>
      <p
        data-testid="revealed-model"
        className="break-all font-mono text-sm text-ink sm:text-right"
      >
        {entry.primary ? modelText(entry.primary) : 'unknown'}
      </p>
    </li>
  )
}

interface Props {
  debateId: string
  reveal: Reveal | null
  onChange: (reveal: Reveal | null) => void
}

/**
 * "Show which model was which", offered once a debate is over. Anonymity is the default and the
 * reveal lasts for this page view only (nothing is stored); "Hide the models" puts it back.
 */
export function RevealPanel({ debateId, reveal, onChange }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function show() {
    setBusy(true)
    setError(null)
    try {
      onChange(await getReveal(debateId))
    } catch (err) {
      setError(friendlyMessage(err, 'Could not load the models.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      aria-labelledby="reveal-heading"
      data-testid="reveal-panel"
      className="rounded-card border border-rule-strong bg-vellum p-4 sm:p-5"
    >
      <h2 id="reveal-heading" className="font-sans text-xl text-ink">
        Who was who?
      </h2>
      <p className="mt-1 max-w-[62ch] text-sm text-ink-soft">{REVEAL_NOTE}</p>

      {!reveal ? (
        <div className="mt-3">
          <button
            type="button"
            onClick={show}
            disabled={busy}
            className="rounded-card border-2 border-ink bg-paper px-4 py-2 text-sm font-semibold text-ink hover:bg-brass-tint disabled:opacity-60"
          >
            {busy ? 'Loading…' : 'Show which model was which'}
          </button>
          {error && (
            <p role="alert" className="mt-2 text-sm text-severity-high">
              {error}
            </p>
          )}
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          <ul className="space-y-2">
            {reveal.debaters.map((d, i) => (
              <EntryRow key={d.label} entry={d} index={i} />
            ))}
            {reveal.judge && <EntryRow entry={reveal.judge} index={reveal.debaters.length} />}
          </ul>
          <button type="button" className="graph-btn" onClick={() => onChange(null)}>
            Hide the models
          </button>
        </div>
      )}
    </section>
  )
}

/** In a recorded example: model names were removed when it was saved, so there is nothing to reveal. */
export function RevealSanitizedNote() {
  return (
    <p
      data-testid="reveal-sanitized"
      className="rounded-card border border-rule bg-vellum p-3 text-sm text-ink-soft"
    >
      Recorded examples are sanitized: model names were removed before saving, so there is nothing
      to reveal here. Start a live debate to see which model was which.
    </p>
  )
}
