/**
 * Data for the landing page. Everything shown there that looks like content comes from files:
 * the panel (public/panel.json, generated from the agents config by `python -m app.debate.panel`)
 * and the worked examples (public/examples.json, generated from the stored evaluation results by
 * `python -m eval.landing_examples`). Nothing about a model or a debate is typed into a component.
 */
export const publicUrl = (name: string) => `${import.meta.env.BASE_URL}${name}`

export const PANEL_FORMAT = 1

export interface PanelModel {
  model: string
  lab: string
}
export interface Panel {
  debaters: PanelModel[]
  personas: string[]
  judge: PanelModel
  judgeSharesModel: boolean
}

type Rec = Record<string, unknown>
const isRec = (v: unknown): v is Rec => typeof v === 'object' && v !== null && !Array.isArray(v)

function toModel(v: unknown): PanelModel | null {
  if (!isRec(v) || typeof v.model !== 'string' || typeof v.lab !== 'string') return null
  return { model: v.model, lab: v.lab }
}

export function parsePanel(raw: unknown): Panel | null {
  if (!isRec(raw) || raw.format !== PANEL_FORMAT) return null
  if (!Array.isArray(raw.debaters) || !Array.isArray(raw.personas)) return null
  const debaters = raw.debaters.map(toModel)
  const judge = toModel(raw.judge)
  if (judge === null || debaters.length === 0 || debaters.some((d) => d === null)) return null
  return {
    debaters: debaters as PanelModel[],
    personas: raw.personas.filter((p): p is string => typeof p === 'string'),
    judge,
    judgeSharesModel: raw.judge_shares_model_with_a_debater === true,
  }
}

export async function loadPanel(): Promise<Panel | null> {
  try {
    const res = await fetch(publicUrl('panel.json'))
    return res.ok ? parsePanel(await res.json()) : null
  } catch {
    return null
  }
}

/** How many different labs the panel's models come from (the "three labs" claim is computed). */
export function labCount(panel: Panel): number {
  return new Set(panel.debaters.map((d) => d.lab)).size
}

const WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine']
export const numberWord = (n: number) => WORDS[n] ?? String(n)

export interface ExampleAnswer {
  debater: number
  answer: string | null
  confidence: number | null
}
export interface ExampleRound {
  round: number
  answers: ExampleAnswer[]
}
export interface LandingExample {
  id: string
  category: string
  stem: string
  options: { letter: string; text: string }[]
  gold: string
  /** Persona by debater number, as every debate screen shows it. */
  personas: Record<number, string>
  round0Correct: number
  rounds: ExampleRound[]
  final: { answer: string; confidence: number | null; summary: string | null }
}
export interface ExampleSet {
  selection: string
  examples: LandingExample[]
}

const str = (v: unknown): v is string => typeof v === 'string'
const numOrNull = (v: unknown): number | null => (typeof v === 'number' ? v : null)

function toAnswer(v: unknown): ExampleAnswer | null {
  if (!isRec(v) || typeof v.debater !== 'number') return null
  return {
    debater: v.debater,
    answer: str(v.answer) ? v.answer : null,
    confidence: numOrNull(v.confidence),
  }
}

function toExample(v: unknown): LandingExample | null {
  if (!isRec(v) || !str(v.id) || !str(v.category) || !str(v.stem) || !str(v.gold)) return null
  if (!Array.isArray(v.options) || !Array.isArray(v.rounds) || !isRec(v.final)) return null
  const options = v.options
    .filter(isRec)
    .map((o) => ({ letter: String(o.letter), text: String(o.text) }))
  const rounds: ExampleRound[] = []
  for (const r of v.rounds) {
    if (!isRec(r) || typeof r.round !== 'number' || !Array.isArray(r.answers)) return null
    const answers = r.answers.map(toAnswer)
    if (answers.some((a) => a === null)) return null
    rounds.push({ round: r.round, answers: answers as ExampleAnswer[] })
  }
  if (options.length < 2 || rounds.length === 0 || !str(v.final.answer)) return null
  const personas: Record<number, string> = {}
  if (Array.isArray(v.debaters)) {
    for (const d of v.debaters) {
      if (isRec(d) && typeof d.debater === 'number' && str(d.persona))
        personas[d.debater] = d.persona
    }
  }
  return {
    id: v.id,
    category: v.category,
    stem: v.stem,
    options,
    gold: v.gold,
    personas,
    round0Correct: typeof v.round0_correct === 'number' ? v.round0_correct : 0,
    rounds,
    final: {
      answer: v.final.answer,
      confidence: numOrNull(v.final.confidence),
      summary: str(v.final.summary) ? v.final.summary : null,
    },
  }
}

export function parseExamples(raw: unknown): ExampleSet | null {
  if (!isRec(raw) || raw.format !== 1 || !str(raw.selection) || !Array.isArray(raw.examples)) {
    return null
  }
  const examples = raw.examples.map(toExample)
  if (examples.length === 0 || examples.some((e) => e === null)) return null
  return { selection: raw.selection, examples: examples as LandingExample[] }
}

export async function loadExamples(): Promise<ExampleSet | null> {
  try {
    const res = await fetch(publicUrl('examples.json'))
    return res.ok ? parseExamples(await res.json()) : null
  } catch {
    return null
  }
}

/** What changed between two rounds, as plain sentences. Empty when nobody changed. */
export function changesBetween(prev: ExampleRound, next: ExampleRound): string[] {
  const out: string[] = []
  for (const a of next.answers) {
    const before = prev.answers.find((p) => p.debater === a.debater)
    if (a.answer === null) out.push(`Debater ${a.debater} gave no valid answer.`)
    else if (before?.answer && before.answer !== a.answer) {
      out.push(`Debater ${a.debater} changed from ${before.answer} to ${a.answer}.`)
    }
  }
  return out
}
