/**
 * Recorded examples ("Watch a real debate"). A showcase file is a saved event log, so the same
 * reducer and replay play it as play a live debate. Everything here is pure.
 *
 * Privacy: files are built by a WHITELIST, per event type, of the fields the reducer reads. Anything
 * else (`label_map`, `provider`, `model`, future fields) cannot get through. Free text is scanned for
 * provider and model names and reported as warnings; it is never rewritten.
 */
import type { RawEvent } from './types'

export const SHOWCASE_FORMAT = 1
export const SLUG_RE = /^[a-z0-9-]+$/
/** Keys that must never appear anywhere in a showcase file, at any depth. */
export const FORBIDDEN_KEYS = ['label_map', 'provider', 'model'] as const

export interface ShowcaseFile {
  format: 1
  slug: string
  title: string
  /** True for invented placeholders; the page labels them and the bundle check lists them. */
  testOnly: boolean
  question: string
  mode: 'answer'
  recorded_on?: string
  events: RawEvent[]
}

export interface ShowcaseIndexItem {
  slug: string
  title: string
  question: string
  testOnly: boolean
  debaters: number
  rounds: number
  final_answer: string | null
}

type Rec = Record<string, unknown>
const isRec = (v: unknown): v is Rec => typeof v === 'object' && v !== null && !Array.isArray(v)
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])

/** Copy only `keys` (and only those that are present) from `src`, in a fixed order. */
function pick(src: Rec, keys: string[]): Rec {
  const out: Rec = {}
  for (const k of keys) if (k in src && src[k] !== undefined) out[k] = src[k]
  return out
}
function mapList(v: unknown, fn: (r: Rec) => Rec): Rec[] {
  return list(v).filter(isRec).map(fn)
}

const CRITIQUE_KEYS = ['target_agent', 'issue', 'severity']
const RECEIVED_KEYS = ['from_agent', 'issue', 'severity', 'round']
const STAT_KEYS = ['total_tokens', 'latency_ms', 'calls', 'api_calls', 'cache_hits', 'fallbacks']

const CLEAN: Record<string, (d: Rec, slug: string) => Rec> = {
  debate_started: (d, slug) => ({
    id: slug,
    agents: mapList(d.agents, (a) => pick(a, ['label', 'persona'])),
  }),
  agent_thinking: (d) => pick(d, ['round', 'agent']),
  agent_response: (d) => {
    const out = pick(d, ['round', 'agent'])
    if (isRec(d.payload)) {
      const p = d.payload
      const payload = pick(p, [
        'valid',
        'error',
        'final_answer',
        'reasoning',
        'confidence',
        'cluster_id',
        'previous_cluster_id',
        'changed_mind',
        'fallback_used',
      ])
      if ('critiques' in p) payload.critiques = mapList(p.critiques, (c) => pick(c, CRITIQUE_KEYS))
      out.payload = payload
    }
    return out
  },
  critique_edge: (d) => pick(d, ['round', 'from_agent', 'to_agent', 'severity', 'issue']),
  round_complete: (d) => {
    const out = pick(d, ['round', 'consensus_score', 'agreed'])
    out.clusters = mapList(d.clusters, (c) =>
      pick(c, ['cluster_id', 'normalized_answer', 'agents']),
    )
    if (isRec(d.received_critiques)) {
      const received: Rec = {}
      for (const [label, items] of Object.entries(d.received_critiques)) {
        received[label] = mapList(items, (r) => pick(r, RECEIVED_KEYS))
      }
      out.received_critiques = received
    }
    return out
  },
  judge_verdict: (d) => {
    const out: Rec = {}
    if (isRec(d.payload)) {
      const p = d.payload
      const payload = pick(p, [
        'final_answer',
        'confidence',
        'summary',
        'dissent',
        'consensus_reached',
      ])
      payload.mistakes_caught = mapList(p.mistakes_caught, (m) =>
        pick(m, ['description', 'caught_by', 'round']),
      )
      out.payload = payload
    }
    return out
  },
  error: (d) => pick(d, ['agent', 'message', 'recoverable']),
  done: (d) => ({ stats: isRec(d.stats) ? pick(d.stats, STAT_KEYS) : {} }),
}

/** Whitelist an event log. Unknown event types are dropped; `seq` is kept or assigned (0, 1, 2…). */
export function sanitizeEvents(events: RawEvent[], slug: string): RawEvent[] {
  const out: RawEvent[] = []
  for (const ev of events) {
    const clean = CLEAN[ev.type]
    if (!clean || !isRec(ev.data)) continue
    const seq = typeof ev.seq === 'number' && Number.isInteger(ev.seq) ? ev.seq : out.length
    out.push({ seq, type: ev.type, data: clean(ev.data, slug) })
  }
  return out
}

export function sanitizeShowcase(input: {
  slug: string
  title: string
  testOnly: boolean
  question: string
  recorded_on?: string
  events: RawEvent[]
}): ShowcaseFile {
  const file: ShowcaseFile = {
    format: SHOWCASE_FORMAT,
    slug: input.slug,
    title: input.title,
    testOnly: input.testOnly,
    question: input.question,
    mode: 'answer',
    events: sanitizeEvents(input.events, input.slug),
  }
  if (input.recorded_on) file.recorded_on = input.recorded_on
  return file
}

/** Every key path in a value, e.g. "events.3.data.payload.model", with the key and its value. */
function* walk(value: unknown, path: string): Generator<[string, string, unknown]> {
  if (Array.isArray(value)) {
    for (const [i, v] of value.entries()) yield* walk(v, `${path}.${i}`)
  } else if (isRec(value)) {
    for (const [k, v] of Object.entries(value)) {
      yield [`${path}.${k}`, k, v]
      yield* walk(v, `${path}.${k}`)
    }
  }
}

/** Paths of forbidden keys anywhere in the value (empty when clean). */
export function forbiddenKeyPaths(value: unknown): string[] {
  const hits: string[] = []
  for (const [path, key] of walk(value, 'file')) {
    if ((FORBIDDEN_KEYS as readonly string[]).includes(key)) hits.push(path)
  }
  return hits
}

/** Provider and model names from the backend config files (`provider:` and `model:` lines). */
export function extractBannedTerms(yamlTexts: string[]): string[] {
  const terms = new Set<string>()
  for (const text of yamlTexts) {
    for (const m of text.matchAll(/^\s*(?:provider|model)\s*:\s*['"]?([^\s#'"]+)/gm)) {
      const t = m[1]!
      if (/^mock/i.test(t)) continue
      terms.add(t)
      if (t.includes('/')) terms.add(t.slice(t.lastIndexOf('/') + 1))
    }
  }
  return [...terms].sort()
}

/** Free-text fields that mention a banned term. Returns warnings, not a rewrite. */
export function scanBannedTerms(file: ShowcaseFile, terms: string[]): string[] {
  const warnings: string[] = []
  const check = (where: string, text: string) => {
    const hay = text.toLowerCase()
    for (const t of terms)
      if (t && hay.includes(t.toLowerCase())) warnings.push(`${where} mentions "${t}"`)
  }
  check('title', file.title)
  check('question', file.question)
  file.events.forEach((ev, i) => {
    for (const [path, , v] of walk(ev.data, `events.${i}.${ev.type}`)) {
      if (typeof v === 'string') check(path, v)
    }
  })
  return [...new Set(warnings)]
}

export type Validation = { ok: true; file: ShowcaseFile } | { ok: false; reason: string }

/** Strict check of a file fetched from /showcase. Anything unexpected is refused, not repaired. */
export function validateShowcase(raw: unknown): Validation {
  if (!isRec(raw)) return { ok: false, reason: 'not an object' }
  if (raw.format !== SHOWCASE_FORMAT) return { ok: false, reason: 'unsupported format' }
  const { slug, title, testOnly, question, events } = raw
  if (typeof slug !== 'string' || !SLUG_RE.test(slug)) return { ok: false, reason: 'bad slug' }
  if (typeof title !== 'string' || title === '') return { ok: false, reason: 'missing title' }
  if (typeof testOnly !== 'boolean') return { ok: false, reason: 'missing testOnly' }
  if (typeof question !== 'string' || question === '') return { ok: false, reason: 'no question' }
  if (!Array.isArray(events) || events.length === 0) return { ok: false, reason: 'no events' }
  for (const ev of events) {
    if (!isRec(ev) || typeof ev.type !== 'string' || !(ev.type in CLEAN) || !isRec(ev.data)) {
      return { ok: false, reason: 'bad event' }
    }
    if (typeof ev.seq !== 'number' || !Number.isInteger(ev.seq)) {
      return { ok: false, reason: 'event without seq' }
    }
  }
  const bad = forbiddenKeyPaths(raw)
  if (bad.length > 0) return { ok: false, reason: `forbidden key at ${bad[0]}` }
  return { ok: true, file: raw as unknown as ShowcaseFile }
}

export function validateIndex(raw: unknown): ShowcaseIndexItem[] | null {
  if (!isRec(raw) || raw.format !== SHOWCASE_FORMAT || !Array.isArray(raw.items)) return null
  const items: ShowcaseIndexItem[] = []
  for (const it of raw.items) {
    if (!isRec(it)) return null
    if (typeof it.slug !== 'string' || !SLUG_RE.test(it.slug)) return null
    if (typeof it.title !== 'string' || typeof it.question !== 'string') return null
    items.push({
      slug: it.slug,
      title: it.title,
      question: it.question,
      testOnly: it.testOnly === true,
      debaters: typeof it.debaters === 'number' ? it.debaters : 0,
      rounds: typeof it.rounds === 'number' ? it.rounds : 0,
      final_answer: typeof it.final_answer === 'string' ? it.final_answer : null,
    })
  }
  return items
}

/** The index entry for a file; scripts/showcase-index.mjs mirrors this for the files on disk. */
export function indexItemFor(file: ShowcaseFile): ShowcaseIndexItem {
  const started = file.events.find((e) => e.type === 'debate_started')
  const debaters = isRec(started?.data) ? list(started.data.agents).length : 0
  const rounds = new Set<number>()
  let final: string | null = null
  for (const e of file.events) {
    if (!isRec(e.data)) continue
    if (e.type === 'agent_response' && typeof e.data.round === 'number') rounds.add(e.data.round)
    if (e.type === 'judge_verdict' && isRec(e.data.payload)) {
      const f = e.data.payload.final_answer
      if (typeof f === 'string') final = f
    }
  }
  return {
    slug: file.slug,
    title: file.title,
    question: file.question,
    testOnly: file.testOnly,
    debaters,
    rounds: rounds.size,
    final_answer: final,
  }
}
