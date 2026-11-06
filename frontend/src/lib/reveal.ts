/**
 * The reveal: which provider and model answered each turn of a finished debate.
 *
 * This is the only place provider and model names exist in the UI, and only after the person asks
 * for them. The data lives in component state for one page view; it never enters the debate
 * reducer, so the graph and its answer letters are unaffected.
 */

export interface RevealModel {
  provider: string
  model: string
}

export interface RevealTurn extends RevealModel {
  round: number
  fallback_used: boolean
  valid: boolean
}

export interface RevealEntry {
  label: string
  persona: string
  /** The model that answered most of this debater's turns. */
  primary: RevealModel | null
  turns: RevealTurn[]
}

export interface Reveal {
  debaters: RevealEntry[]
  judge: RevealEntry | null
}

/** Shown beside every reveal. It is about who wrote what, not about which model was right. */
export const REVEAL_NOTE =
  'This only shows who wrote what. The debaters were not told each other’s identity.'

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

function parseModel(v: unknown): RevealModel | null {
  if (!isRecord(v) || typeof v.provider !== 'string' || typeof v.model !== 'string') return null
  return { provider: v.provider, model: v.model }
}

function parseEntry(v: unknown): RevealEntry | null {
  if (!isRecord(v) || typeof v.label !== 'string' || typeof v.persona !== 'string') return null
  if (!Array.isArray(v.turns)) return null
  const turns: RevealTurn[] = []
  for (const t of v.turns) {
    const m = parseModel(t)
    if (!m || !isRecord(t) || typeof t.round !== 'number') return null
    turns.push({
      ...m,
      round: t.round,
      fallback_used: t.fallback_used === true,
      valid: t.valid !== false,
    })
  }
  return {
    label: v.label,
    persona: v.persona,
    primary: v.primary === null ? null : parseModel(v.primary),
    turns,
  }
}

/** Strict: a body that does not look right is refused, not guessed at. */
export function parseReveal(raw: unknown): Reveal | null {
  if (!isRecord(raw) || !Array.isArray(raw.debaters)) return null
  const debaters: RevealEntry[] = []
  for (const d of raw.debaters) {
    const e = parseEntry(d)
    if (!e) return null
    debaters.push(e)
  }
  const judge = raw.judge === null || raw.judge === undefined ? null : parseEntry(raw.judge)
  if (raw.judge && !judge) return null
  return { debaters, judge }
}

export const modelText = (m: RevealModel): string => `${m.provider} / ${m.model}`

export function entryFor(reveal: Reveal, label: string): RevealEntry | undefined {
  return label === 'Judge'
    ? (reveal.judge ?? undefined)
    : reveal.debaters.find((d) => d.label === label)
}

/** The model for one turn (or the debater's main model when no round is given), and whether a backup answered. */
export function modelFor(
  reveal: Reveal,
  label: string,
  round?: number | null,
): { model: RevealModel; backup: boolean } | null {
  const entry = entryFor(reveal, label)
  if (!entry) return null
  if (round !== undefined && round !== null) {
    const turn = entry.turns.find((t) => t.round === round)
    if (turn) return { model: turn, backup: turn.fallback_used }
  }
  return entry.primary ? { model: entry.primary, backup: false } : null
}

/** Turns answered by something other than the debater's main model, for a short note. */
export function backupTurns(entry: RevealEntry): RevealTurn[] {
  const main = entry.primary
  return entry.turns.filter(
    (t) => t.fallback_used || (main !== null && modelText(t) !== modelText(main)),
  )
}
