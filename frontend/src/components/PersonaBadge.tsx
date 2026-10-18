import { debaterColor, debaterTint } from '../lib/palette'
import { PersonaGlyph } from './Icons'

/** A debater's identity: position-coloured ring, persona glyph, label and persona name. */
export function PersonaBadge({
  label,
  persona,
  index,
}: {
  label: string
  persona: string
  index: number
}) {
  return (
    <span
      className="inline-flex items-center gap-2 rounded-card border-2 px-2.5 py-1 text-sm"
      style={{ borderColor: debaterColor(index), background: debaterTint(index) }}
    >
      <span style={{ color: debaterColor(index) }}>
        <PersonaGlyph persona={persona} size={18} />
      </span>
      <span className="font-semibold text-ink">{label}</span>
      {persona && <span className="text-ink-soft">{persona}</span>}
    </span>
  )
}
