import type { Severity } from '../lib/types'
import { severityColor, severityTint } from '../lib/palette'
import { SeverityIcon } from './Icons'

const WORD: Record<Severity, string> = { low: 'Low', medium: 'Medium', high: 'High' }

/** Severity is a shape, a word and a colour; never the colour alone. */
export function SeverityMark({ severity }: { severity: Severity }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-chip border px-1.5 py-0.5 text-xs font-medium text-ink"
      style={{ borderColor: severityColor(severity), background: severityTint(severity) }}
      data-severity={severity}
    >
      <span style={{ color: severityColor(severity) }}>
        <SeverityIcon severity={severity} size={14} />
      </span>
      {WORD[severity]}
    </span>
  )
}
