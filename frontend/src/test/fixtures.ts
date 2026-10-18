import type { RawEvent } from '../lib/types'

export const D1 = 'Debater 1'
export const D2 = 'Debater 2'
export const D3 = 'Debater 3'
export const AGENTS = [
  { label: D1, persona: 'Solver' },
  { label: D2, persona: 'Skeptic' },
  { label: D3, persona: 'Fact-Checker' },
]

export function response(
  round: number,
  agent: string,
  answer: string,
  clusterId: number,
  extra: Record<string, unknown> = {},
): RawEvent['data'] {
  return {
    round,
    agent,
    payload: {
      reasoning: `${agent} reasoning, round ${round}`,
      critiques: [],
      changed_mind: false,
      changed_mind_claimed: false,
      changed_mind_because: null,
      previous_cluster_id: null,
      final_answer: answer,
      confidence: 80,
      valid: true,
      cluster_id: clusterId,
      fallback_used: false,
      label_map: { 'Response 1': D2, 'Response 2': D3 },
      ...extra,
    },
  }
}

const CORRECT = '[1, 2, 3]'
const SPACED_WRONG = '[1,2,3]'

/**
 * A complete mock debate, in server order. Round 0: D2 differs only by spacing (a different
 * answer under exact comparison). Round 1: D1 critiques D2, D2 changes its answer, all agree.
 */
export function fullRun(): RawEvent[] {
  const events: Omit<RawEvent, 'seq'>[] = [
    { type: 'debate_started', data: { id: 'd1', agents: AGENTS } },
    ...[D1, D2, D3].map((a) => ({ type: 'agent_thinking', data: { round: 0, agent: a } })),
    { type: 'agent_response', data: response(0, D1, CORRECT, 0) },
    { type: 'agent_response', data: response(0, D2, SPACED_WRONG, 1) },
    { type: 'agent_response', data: response(0, D3, CORRECT, 0) },
    {
      type: 'round_complete',
      data: {
        round: 0,
        consensus_score: 0.67,
        agreed: false,
        clusters: [
          { cluster_id: 0, normalized_answer: CORRECT, agents: [D1, D3] },
          { cluster_id: 1, normalized_answer: SPACED_WRONG, agents: [D2] },
        ],
        received_critiques: {},
      },
    },
    ...[D1, D2, D3].map((a) => ({ type: 'agent_thinking', data: { round: 1, agent: a } })),
    {
      type: 'agent_response',
      data: response(1, D1, CORRECT, 0, {
        critiques: [
          {
            target: 'Response 1',
            target_agent: D2,
            issue: 'The spacing differs: [1,2,3] is not [1, 2, 3].',
            severity: 'medium',
          },
        ],
      }),
    },
    {
      type: 'agent_response',
      // changed_mind_claimed is false on purpose: the server-derived value must win.
      data: response(1, D2, CORRECT, 0, { changed_mind: true, previous_cluster_id: 1 }),
    },
    { type: 'agent_response', data: response(1, D3, CORRECT, 0) },
    {
      type: 'critique_edge',
      data: {
        round: 1,
        from_agent: D1,
        to_agent: D2,
        severity: 'medium',
        issue: 'The spacing differs: [1,2,3] is not [1, 2, 3].',
      },
    },
    {
      type: 'round_complete',
      data: {
        round: 1,
        consensus_score: 1,
        agreed: true,
        clusters: [{ cluster_id: 0, normalized_answer: CORRECT, agents: [D1, D2, D3] }],
        received_critiques: {
          [D1]: [],
          [D2]: [
            {
              from_agent: D1,
              issue: 'The spacing differs: [1,2,3] is not [1, 2, 3].',
              severity: 'medium',
              round: 1,
            },
          ],
          [D3]: [],
        },
      },
    },
    // The judge announces itself like a debater, with a round one past the last debate round.
    { type: 'agent_thinking', data: { round: 2, agent: 'Judge' } },
    {
      type: 'judge_verdict',
      data: {
        payload: {
          final_answer: CORRECT,
          confidence: 90,
          summary: 'All three settled on the same list.',
          mistakes_caught: [
            {
              description: 'The spacing differs: [1,2,3] is not [1, 2, 3].',
              caught_by: D1,
              round: 1,
            },
          ],
          dissent: null,
          consensus_reached: true,
        },
      },
    },
    {
      type: 'done',
      data: {
        stats: {
          total_tokens: 1234,
          latency_ms: 5000,
          calls: 7,
          api_calls: 7,
          cache_hits: 0,
          fallbacks: 0,
        },
      },
    },
  ]
  return events.map((e, seq) => ({ ...e, seq }))
}
