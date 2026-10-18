/**
 * TEST-ONLY debate fixtures for the Debate Graph. NOT REAL DEBATES: every answer, critique and
 * verdict here is invented to exercise layouts and states. They follow the server's event schema
 * (backend/app/schemas.py), including the server-derived `changed_mind` / `previous_cluster_id`,
 * stable `cluster_id`s and `received_critiques`, and are never imported by production code.
 */
import type { RawEvent, Severity } from '../lib/types'

export const TEST_ONLY_NOTICE = 'TEST-ONLY FIXTURE: invented for testing, not a real debate.'

const PERSONAS = ['Solver', 'Skeptic', 'Fact-Checker']

export interface Say {
  /** Final answer text; `null` marks an invalid turn. */
  answer: string | null
  confidence?: number
  fallback?: boolean
  reasoning?: string
  error?: string
  critiques?: { to: string; severity: Severity; issue: string }[]
}
export type RoundSpec = Record<string, Say>

export interface DebateSpec {
  id: string
  agents: string[]
  rounds: RoundSpec[]
  verdict?: {
    answer: string
    confidence: number
    summary: string
    mistakes?: { description: string; caught_by: string; round: number }[]
    dissent?: string | null
  }
  errors?: { agent?: string; message: string; recoverable: boolean }[]
}

export function agentLabels(n: number): string[] {
  return Array.from({ length: n }, (_, i) => `Debater ${i + 1}`)
}

/** Turns a compact spec into the ordered events a server would emit. */
export function buildEvents(spec: DebateSpec): RawEvent[] {
  const events: Omit<RawEvent, 'seq'>[] = []
  const ids = new Map<string, number>()
  const idFor = (answer: string) => ids.get(answer) ?? ids.set(answer, ids.size).get(answer)!
  const lastCluster = new Map<string, number>()

  events.push({
    type: 'debate_started',
    data: {
      id: spec.id,
      agents: spec.agents.map((label, i) => ({ label, persona: PERSONAS[i % PERSONAS.length] })),
    },
  })

  spec.rounds.forEach((round, r) => {
    for (const a of spec.agents)
      events.push({ type: 'agent_thinking', data: { round: r, agent: a } })
    const answers: Record<string, string | null> = {}
    const received: Record<string, unknown[]> = {}
    for (const a of spec.agents) received[a] = []

    for (const a of spec.agents) {
      const say = round[a]
      if (!say) continue
      if (say.answer === null) {
        answers[a] = null
        events.push({
          type: 'agent_response',
          data: {
            round: r,
            agent: a,
            payload: {
              valid: false,
              error: say.error ?? 'No usable answer.',
              fallback_used: false,
            },
          },
        })
        continue
      }
      answers[a] = say.answer
      const cluster = idFor(say.answer)
      const previous = lastCluster.get(a) ?? null
      const changed = previous !== null && previous !== cluster
      lastCluster.set(a, cluster)
      events.push({
        type: 'agent_response',
        data: {
          round: r,
          agent: a,
          payload: {
            reasoning:
              say.reasoning ?? `${a}'s reasoning in round ${r}.\n  Indented line kept as written.`,
            critiques: (say.critiques ?? []).map((c, k) => ({
              target: `Response ${k + 1}`,
              target_agent: c.to,
              issue: c.issue,
              severity: c.severity,
            })),
            changed_mind: changed,
            changed_mind_claimed: false,
            changed_mind_because: null,
            previous_cluster_id: previous,
            final_answer: say.answer,
            confidence: say.confidence ?? 80,
            valid: true,
            cluster_id: cluster,
            fallback_used: say.fallback === true,
          },
        },
      })
      for (const c of say.critiques ?? []) {
        events.push({
          type: 'critique_edge',
          data: { round: r, from_agent: a, to_agent: c.to, severity: c.severity, issue: c.issue },
        })
        received[c.to]?.push({ from_agent: a, issue: c.issue, severity: c.severity, round: r })
      }
    }

    const groups = new Map<string, string[]>()
    for (const [agent, ans] of Object.entries(answers)) {
      if (ans !== null) groups.set(ans, [...(groups.get(ans) ?? []), agent])
    }
    const largest = Math.max(0, ...[...groups.values()].map((g) => g.length))
    events.push({
      type: 'round_complete',
      data: {
        round: r,
        consensus_score: largest / spec.agents.length,
        agreed: groups.size === 1 && largest >= 2,
        clusters: [...groups].map(([ans, agents]) => ({
          cluster_id: idFor(ans),
          normalized_answer: ans,
          agents,
        })),
        received_critiques: r === 0 ? {} : received,
      },
    })
  })

  for (const e of spec.errors ?? []) events.push({ type: 'error', data: e })

  if (spec.verdict) {
    events.push({ type: 'agent_thinking', data: { round: spec.rounds.length, agent: 'Judge' } })
    events.push({
      type: 'judge_verdict',
      data: {
        payload: {
          final_answer: spec.verdict.answer,
          confidence: spec.verdict.confidence,
          summary: spec.verdict.summary,
          mistakes_caught: spec.verdict.mistakes ?? [],
          dissent: spec.verdict.dissent ?? null,
          consensus_reached: true,
        },
      },
    })
    events.push({
      type: 'done',
      data: {
        stats: {
          total_tokens: 4200,
          latency_ms: 9000,
          calls: 12,
          api_calls: 12,
          cache_hits: 0,
          fallbacks: 0,
        },
      },
    })
  }
  return events.map((e, seq) => ({ ...e, seq }))
}

const [D1, D2, D3, D4, D5] = agentLabels(5) as [string, string, string, string, string]

// --- 1. one right debater, two wrong, merge by round 2 ---

const MUTABLE_QUESTION =
  'What does this print?\n\ndef f(x, acc=[]):\n    acc.append(x)\n    return acc\n\nprint(f(1))\nprint(f(2))'
const RIGHT = '[1]\n[1, 2]'
const SPACING = '[1]\n[1,2]'
const FRESH = '[1]\n[2]'

const SHARED =
  "The default list is created once and shared, so the second call sees the first call's 1."
const SPACE = 'Python prints [1, 2] with a space after the comma, not [1,2].'

export const mergeWrongCluster = {
  question: MUTABLE_QUESTION,
  events: buildEvents({
    id: 'fixture-merge',
    agents: [D1, D2, D3],
    rounds: [
      {
        [D1]: { answer: RIGHT, confidence: 92 },
        [D2]: { answer: SPACING, confidence: 70 },
        [D3]: { answer: FRESH, confidence: 58 },
      },
      {
        [D1]: {
          answer: RIGHT,
          confidence: 95,
          critiques: [
            { to: D2, severity: 'medium', issue: SPACE },
            { to: D3, severity: 'high', issue: SHARED },
          ],
        },
        [D2]: { answer: SPACING, confidence: 66 },
        [D3]: { answer: FRESH, confidence: 52 },
      },
      {
        [D1]: { answer: RIGHT, confidence: 96 },
        [D2]: { answer: RIGHT, confidence: 88 },
        [D3]: { answer: RIGHT, confidence: 84 },
      },
    ],
    verdict: {
      answer: RIGHT,
      confidence: 93,
      summary: 'All three settled on the output with the shared default list.',
      mistakes: [
        { description: SPACE, caught_by: D1, round: 1 },
        { description: SHARED, caught_by: D1, round: 1 },
      ],
    },
  }),
}

// --- 2. an invalid turn and a fallback ---

export const invalidAndFallback = {
  question: 'Is 91 a prime number?',
  events: buildEvents({
    id: 'fixture-invalid',
    agents: [D1, D2, D3],
    rounds: [
      {
        [D1]: { answer: 'No', confidence: 90 },
        [D2]: { answer: 'Yes', confidence: 61 },
        [D3]: { answer: 'No', confidence: 84, fallback: true },
      },
      {
        [D1]: {
          answer: 'No',
          confidence: 94,
          critiques: [{ to: D2, severity: 'high', issue: '91 = 7 x 13.' }],
        },
        [D2]: {
          answer: null,
          error: 'The reply could not be read as an answer, even after one repair attempt.',
        },
        [D3]: {
          answer: 'No',
          confidence: 88,
          fallback: true,
          critiques: [{ to: D2, severity: 'low', issue: 'No factors were shown.' }],
        },
      },
    ],
    errors: [
      { agent: D2, message: 'This debater gave no usable answer in round 1.', recoverable: true },
    ],
    verdict: {
      answer: 'No',
      confidence: 90,
      summary: '91 is 7 times 13.',
      mistakes: [{ description: '91 = 7 x 13.', caught_by: D1, round: 1 }],
    },
  }),
}

// --- 3. five debaters (five different first answers, so the fifth cluster is neutral) ---

export const five = {
  question: 'How many days are there in 17 weeks and 3 days?',
  events: buildEvents({
    id: 'fixture-five',
    agents: [D1, D2, D3, D4, D5],
    rounds: [
      {
        [D1]: { answer: '122', confidence: 90 },
        [D2]: { answer: '119', confidence: 75 },
        [D3]: { answer: '120', confidence: 60 },
        [D4]: { answer: '124', confidence: 55 },
        [D5]: { answer: '1223', confidence: 40 },
      },
      {
        [D1]: {
          answer: '122',
          confidence: 93,
          critiques: [
            { to: D2, severity: 'high', issue: '17 x 7 = 119, then add the 3 extra days.' },
            { to: D5, severity: 'low', issue: 'The digits were joined, not added.' },
          ],
        },
        [D2]: {
          answer: '122',
          confidence: 70,
          critiques: [{ to: D3, severity: 'medium', issue: 'Forgot to add 3.' }],
        },
        [D3]: { answer: '122', confidence: 66 },
        [D4]: {
          answer: '124',
          confidence: 58,
          critiques: [{ to: D1, severity: 'low', issue: 'Check whether a week is seven days.' }],
        },
        [D5]: { answer: '120', confidence: 45 },
      },
      {
        [D1]: { answer: '122', confidence: 96 },
        [D2]: { answer: '122', confidence: 90 },
        [D3]: { answer: '122', confidence: 88 },
        [D4]: {
          answer: '122',
          confidence: 80,
          critiques: [{ to: D5, severity: 'medium', issue: '120 leaves out the extra 3 days.' }],
        },
        [D5]: { answer: '120', confidence: 50 },
      },
    ],
    verdict: {
      answer: '122',
      confidence: 91,
      summary: '17 x 7 + 3 = 122.',
      dissent: 'Debater 5 kept 120.',
    },
  }),
}

// --- 4. two debaters ---

export const two = {
  question: 'Which is larger, 9.11 or 9.9?',
  events: buildEvents({
    id: 'fixture-two',
    agents: [D1, D2],
    rounds: [
      { [D1]: { answer: '9.9', confidence: 88 }, [D2]: { answer: '9.11', confidence: 64 } },
      {
        [D1]: {
          answer: '9.9',
          confidence: 92,
          critiques: [{ to: D2, severity: 'high', issue: '9.90 is greater than 9.11.' }],
        },
        [D2]: { answer: '9.9', confidence: 80 },
      },
    ],
    verdict: {
      answer: '9.9',
      confidence: 95,
      summary: 'Compare 9.90 with 9.11.',
      mistakes: [{ description: '9.90 is greater than 9.11.', caught_by: D1, round: 1 }],
    },
  }),
}

// --- 5. seven debaters x three critique rounds (layout and performance stress) ---

function sevenSpec(): DebateSpec {
  const agents = agentLabels(7)
  const wrongs = ['40', '41', '42', '44', '45', '46']
  const round = (r: number): RoundSpec =>
    Object.fromEntries(
      agents.map((a, i) => {
        const settled = r >= 2 + (i % 2)
        const answer = i === 0 || settled ? '43' : wrongs[(i + r) % wrongs.length]!
        const critiques =
          r > 0 && i < 3
            ? [
                {
                  to: agents[(i + 3) % 7]!,
                  severity: (['low', 'medium', 'high'] as const)[(i + r) % 3]!,
                  issue: `Check step ${r + i}.`,
                },
              ]
            : []
        return [a, { answer, confidence: 55 + ((i * 11 + r * 9) % 40), critiques }]
      }),
    )
  return {
    id: 'fixture-seven',
    agents,
    rounds: [0, 1, 2, 3].map(round),
    verdict: { answer: '43', confidence: 88, summary: 'Seven debaters, four rounds.' },
  }
}
export const seven = {
  question: 'A seven-debater stress test question.',
  events: buildEvents(sevenSpec()),
}

// --- 6. very long reasoning (inspector layout tests) ---

const LONG_LINES = Array.from(
  { length: 120 },
  (_, i) => `Step ${i + 1}: a long line of reasoning, kept as written.\n    indented`,
)
// About 20,000 characters, ending in one long unbroken token.
export const LONG_REASONING = (LONG_LINES.join('\n') + '\n').padEnd(20000, 'x')
export const SHORT_REASONING = 'Short and sweet.'

export const longReasoning = {
  question: 'A debate whose first debater wrote a very long explanation.',
  events: buildEvents({
    id: 'fixture-long',
    agents: [D1, D2, D3],
    rounds: [
      {
        [D1]: { answer: 'Yes', confidence: 80, reasoning: LONG_REASONING },
        [D2]: { answer: 'No', confidence: 70, reasoning: SHORT_REASONING },
        [D3]: { answer: 'Yes', confidence: 60 },
      },
    ],
    verdict: { answer: 'Yes', confidence: 80, summary: 'Two of three said yes.' },
  }),
}

// --- 7. a stored log from before the server-derived fields existed ---

/** Strips what older servers did not send: cluster ids, changed_mind derivation and received_critiques. */
export const legacy = {
  question: mergeWrongCluster.question,
  events: mergeWrongCluster.events.map((e) => {
    const data = { ...(e.data as Record<string, unknown>) }
    if (e.type === 'agent_response' && typeof data.payload === 'object' && data.payload !== null) {
      const p = { ...(data.payload as Record<string, unknown>) }
      delete p.cluster_id
      delete p.previous_cluster_id
      delete p.changed_mind_claimed
      p.changed_mind = false
      data.payload = p
    }
    if (e.type === 'round_complete') {
      delete data.received_critiques
      delete data.clusters
    }
    return { ...e, data }
  }),
}

export type FixtureName =
  'mergeWrongCluster' | 'invalidAndFallback' | 'five' | 'two' | 'seven' | 'legacy' | 'longReasoning'
export const FIXTURES: Record<FixtureName, { question: string; events: RawEvent[] }> = {
  mergeWrongCluster,
  invalidAndFallback,
  five,
  two,
  seven,
  legacy,
  longReasoning,
}
