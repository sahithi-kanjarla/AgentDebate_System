import type { DebateError } from '../lib/debateState'

export function ErrorNotes({ errors }: { errors: DebateError[] }) {
  if (errors.length === 0) return null
  return (
    <details className="rounded-card border border-rule-strong bg-vellum p-3 text-sm">
      <summary className="font-medium text-ink">
        {errors.length === 1
          ? '1 problem during this debate'
          : `${errors.length} problems during this debate`}
      </summary>
      <ul className="mt-2 space-y-1.5">
        {errors.map((e, i) => (
          <li key={i} className="text-ink">
            <span className="font-medium">{e.agent ?? 'Debate'}:</span>{' '}
            <span className="whitespace-pre-wrap break-words">{e.message}</span>{' '}
            <span className="text-ink-soft">
              ({e.recoverable ? 'the debate continued' : 'not recoverable'})
            </span>
          </li>
        ))}
      </ul>
    </details>
  )
}
