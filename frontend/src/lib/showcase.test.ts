import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { initialState, reduceAll } from './debateState'
import {
  extractBannedTerms,
  forbiddenKeyPaths,
  indexItemFor,
  sanitizeEvents,
  sanitizeShowcase,
  scanBannedTerms,
  validateIndex,
  validateShowcase,
  type ShowcaseFile,
} from './showcase'
import type { RawEvent } from './types'
import { FIXTURES, type FixtureName } from '../test/graphFixtures'

// vitest runs from frontend/ (the jsdom environment gives import.meta.url an http scheme).
const SHOWCASE_DIR = join(process.cwd(), 'public', 'showcase')
const CONFIG_DIR = join(process.cwd(), '..', 'backend', 'config')
const INDEX_SCRIPT = join(process.cwd(), 'scripts', 'showcase-index.mjs')

/** Provider and model names, read from the backend config files (never typed into the tests). */
const BANNED = extractBannedTerms(
  readdirSync(CONFIG_DIR)
    .filter((n) => /^agents.*\.yaml$/.test(n))
    .map((n) => readFileSync(join(CONFIG_DIR, n), 'utf8')),
)

/** What a real server's log might carry beyond what the screen needs. */
function withLeaks(events: RawEvent[]): RawEvent[] {
  const term = BANNED[0] ?? 'some-provider'
  return events.map((ev, i) => {
    const data = { ...(ev.data as Record<string, unknown>) }
    data.label_map = { 'Debater 1': 'x' }
    data.provider = term
    data.model = term
    data.extra_field = { model: term }
    if (data.payload && typeof data.payload === 'object') {
      data.payload = {
        ...(data.payload as Record<string, unknown>),
        provider: term,
        model: term,
        label_map: { A: 'B' },
        critiques: (((data.payload as Record<string, unknown>).critiques as unknown[]) ?? []).map(
          (c) => ({ ...(c as object), model: term, provider: term }),
        ),
      }
    }
    if (ev.type === 'debate_started') {
      data.agents = (data.agents as object[]).map((a) => ({ ...a, provider: term, model: term }))
    }
    return { ...ev, seq: i, data }
  })
}

const PLACEHOLDERS: { fixture: FixtureName; slug: string; title: string }[] = [
  {
    fixture: 'mergeWrongCluster',
    slug: 'placeholder-wrong-answer-loses',
    title: 'Placeholder: a wrong answer loses support',
  },
  { fixture: 'five', slug: 'placeholder-five-debaters', title: 'Placeholder: five debaters' },
  {
    fixture: 'invalidAndFallback',
    slug: 'placeholder-invalid-turn',
    title: 'Placeholder: one debater gives no valid answer',
  },
]

function generate(p: (typeof PLACEHOLDERS)[number]): ShowcaseFile {
  const f = FIXTURES[p.fixture]
  return sanitizeShowcase({
    slug: p.slug,
    title: p.title,
    testOnly: true,
    question: f.question,
    events: f.events,
  })
}

const text = (f: ShowcaseFile) => JSON.stringify(f, null, 2) + '\n'

describe('placeholder files', () => {
  // UPDATE_SHOWCASE=1 npx vitest run src/lib/showcase.test.ts  rewrites them (and the index).
  if (process.env.UPDATE_SHOWCASE) {
    it('writes the placeholder showcase files and the index', () => {
      mkdirSync(SHOWCASE_DIR, { recursive: true })
      for (const p of PLACEHOLDERS)
        writeFileSync(join(SHOWCASE_DIR, `${p.slug}.json`), text(generate(p)))
      execFileSync(process.execPath, [INDEX_SCRIPT])
    })
  }

  it.each(PLACEHOLDERS)('$slug matches what the generator produces', (p) => {
    const path = join(SHOWCASE_DIR, `${p.slug}.json`)
    expect(existsSync(path), 'run with UPDATE_SHOWCASE=1 to create it').toBe(true)
    expect(readFileSync(path, 'utf8')).toBe(text(generate(p)))
  })

  it('index.json is up to date', () => {
    expect(() =>
      execFileSync(process.execPath, [INDEX_SCRIPT, '--check'], { stdio: 'pipe' }),
    ).not.toThrow()
  })
})

describe('every file in public/showcase', () => {
  const names = existsSync(SHOWCASE_DIR)
    ? readdirSync(SHOWCASE_DIR).filter((n) => n.endsWith('.json') && n !== 'index.json')
    : []

  it('has files to check', () => expect(names.length).toBeGreaterThan(0))

  it.each(names)(
    '%s is valid, already sanitised, listed, and free of provider and model names',
    (name) => {
      const raw = readFileSync(join(SHOWCASE_DIR, name), 'utf8')
      const parsed: unknown = JSON.parse(raw)
      const checked = validateShowcase(parsed)
      expect(checked.ok).toBe(true)
      if (!checked.ok) return
      const file = checked.file
      expect(`${file.slug}.json`).toBe(name)
      expect(forbiddenKeyPaths(file)).toEqual([])
      // Already sanitised: running the sanitiser changes nothing.
      expect(sanitizeShowcase(file)).toEqual(file)
      expect(scanBannedTerms(file, BANNED)).toEqual([])
      // Provider and model names appear nowhere in the raw text either.
      for (const t of BANNED) expect(raw.toLowerCase()).not.toContain(t.toLowerCase())
      // It plays: the reducer reaches a finished state with a verdict.
      const state = reduceAll(file.events, initialState())
      expect(state.status).toBe('done')
      expect(state.verdict).not.toBeNull()
      // Listed in the index with the right summary.
      const index = validateIndex(
        JSON.parse(readFileSync(join(SHOWCASE_DIR, 'index.json'), 'utf8')),
      )
      expect(index?.find((i) => i.slug === file.slug)).toEqual(indexItemFor(file))
    },
  )
})

describe('sanitizer', () => {
  const names = Object.keys(FIXTURES) as FixtureName[]

  it.each(names)(
    'drops label_map, provider and model and keeps the replay identical (%s)',
    (name) => {
      const original = FIXTURES[name].events
      const dirty = withLeaks(original)
      expect(JSON.stringify(dirty)).toMatch(/label_map/)
      const clean = sanitizeEvents(dirty, 'a-slug')
      const json = JSON.stringify(clean)
      expect(forbiddenKeyPaths(clean)).toEqual([])
      expect(json).not.toMatch(/label_map|"provider"|"model"|extra_field/)
      for (const t of BANNED) expect(json.toLowerCase()).not.toContain(t.toLowerCase())

      const strip = (s: ReturnType<typeof reduceAll>) => ({ ...s, id: null })
      expect(strip(reduceAll(clean, initialState()))).toEqual(
        strip(reduceAll(original, initialState())),
      )
    },
  )

  it('replaces the debate id with the slug and assigns missing seq', () => {
    const noSeq = FIXTURES.two.events.map(({ type, data }) => ({ type, data }))
    const clean = sanitizeEvents(noSeq, 'my-slug')
    expect(clean.map((e) => e.seq)).toEqual(clean.map((_, i) => i))
    expect((clean[0]!.data as { id: string }).id).toBe('my-slug')
  })

  it('is idempotent and drops unknown event types', () => {
    const once = sanitizeEvents(withLeaks(FIXTURES.five.events), 's')
    expect(sanitizeEvents(once, 's')).toEqual(once)
    const withUnknown = [...once, { seq: 999, type: 'heartbeat', data: { model: 'x' } }]
    expect(sanitizeEvents(withUnknown, 's')).toEqual(once)
  })

  it('keeps final_answer whitespace exactly', () => {
    const answer = '  line one\n\n    indented\n'
    const events: RawEvent[] = [
      {
        type: 'judge_verdict',
        data: { payload: { final_answer: answer, confidence: 50, summary: 's' } },
      },
    ]
    const clean = sanitizeEvents(events, 's')
    const payload = (clean[0]!.data as { payload: { final_answer: string } }).payload
    expect(payload.final_answer).toBe(answer)
  })
})

describe('scanBannedTerms and extractBannedTerms', () => {
  it('reads provider and model values from config text, skipping mock', () => {
    const terms = extractBannedTerms([
      'provider: alpha\n  model: org/big-model-1  # note\nprovider: mock\nmodel: mock-solver\n',
    ])
    expect(terms).toEqual(['alpha', 'big-model-1', 'org/big-model-1'])
  })

  it('warns, without rewriting, when free text mentions a banned term', () => {
    const file = sanitizeShowcase({
      slug: 's',
      title: 'About Alpha',
      testOnly: true,
      question: 'q',
      events: [
        {
          type: 'agent_response',
          data: {
            round: 0,
            agent: 'Debater 1',
            payload: { final_answer: 'a', reasoning: 'I am big-model-1' },
          },
        },
      ],
    })
    const warnings = scanBannedTerms(file, ['alpha', 'big-model-1'])
    expect(warnings).toEqual([
      'title mentions "alpha"',
      'events.0.agent_response.payload.reasoning mentions "big-model-1"',
    ])
    expect(file.title).toBe('About Alpha')
  })
})

describe('validateShowcase', () => {
  const good = generate(PLACEHOLDERS[0]!)
  it('accepts a good file and refuses bad ones', () => {
    expect(validateShowcase(good).ok).toBe(true)
    expect(validateShowcase(null).ok).toBe(false)
    expect(validateShowcase({ ...good, format: 2 }).ok).toBe(false)
    expect(validateShowcase({ ...good, slug: '../x' }).ok).toBe(false)
    expect(validateShowcase({ ...good, events: [] }).ok).toBe(false)
    expect(validateShowcase({ ...good, events: [{ seq: 0, type: 'nope', data: {} }] }).ok).toBe(
      false,
    )
    expect(validateShowcase({ ...good, label_map: {} }).ok).toBe(false)
  })
})
