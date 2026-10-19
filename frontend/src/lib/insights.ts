/**
 * Data for the Insights charts, derived from the same DebateState as everything else. Pure: the
 * charts, their data tables and their text summaries all read these series, so they cannot disagree.
 */
import { agreement, orderedRounds, type DebateState } from './debateState'

export interface AgreementPoint {
  round: number
  /** Debaters holding the most common answer. */
  agree: number
  /** Debaters in the debate; the chart's ceiling. */
  debaters: number
  /** Debaters that gave a valid answer this round. */
  answered: number
}

/** One point per finished round (rounds whose summary has arrived). */
export function agreementSeries(state: DebateState): AgreementPoint[] {
  const out: AgreementPoint[] = []
  for (const r of orderedRounds(state)) {
    const a = agreement(r)
    if (!a) continue
    out.push({
      round: r.round,
      agree: a.agree,
      debaters: Math.max(state.agents.length, a.total),
      answered: a.total,
    })
  }
  return out
}

export function agreementSummary(series: AgreementPoint[]): string {
  const first = series[0]
  const last = series[series.length - 1]
  if (!first || !last) return 'No round has finished yet, so there is no agreement to chart.'
  const of = (p: AgreementPoint) => `${p.agree} of ${p.debaters}`
  if (series.length === 1) return `In round ${first.round}, ${of(first)} debaters agreed.`
  const trend =
    last.agree > first.agree ? 'rose' : last.agree < first.agree ? 'fell' : 'stayed level'
  const tail = trend === 'stayed level' ? `at ${of(first)}` : `from ${of(first)} to ${of(last)}`
  return `Agreement ${trend} ${tail}, from round ${first.round} to round ${last.round}.`
}

export interface ConfidencePoint {
  round: number
  /** The confidence the debater reported, or null when it gave no valid answer. */
  value: number | null
  status: 'answered' | 'invalid' | 'missing'
}

export interface ConfidenceSeries {
  label: string
  persona: string
  index: number
  points: ConfidencePoint[]
}

/** Rounds that have at least one turn, in order, shared by every debater's series. */
export function chartRounds(state: DebateState): number[] {
  return orderedRounds(state)
    .filter((r) => Object.keys(r.turns).length > 0)
    .map((r) => r.round)
}

export function confidenceSeries(state: DebateState): ConfidenceSeries[] {
  const rounds = orderedRounds(state).filter((r) => Object.keys(r.turns).length > 0)
  return state.agents.map((a, index) => ({
    label: a.label,
    persona: a.persona,
    index,
    points: rounds.map((r): ConfidencePoint => {
      const t = r.turns[a.label]
      if (!t) return { round: r.round, value: null, status: 'missing' }
      if (t.status === 'answered' && typeof t.confidence === 'number')
        return { round: r.round, value: t.confidence, status: 'answered' }
      return { round: r.round, value: null, status: t.status === 'invalid' ? 'invalid' : 'missing' }
    }),
  }))
}

export function confidenceSummary(series: ConfidenceSeries[]): string {
  const parts = series.map((s) => {
    const known = s.points.filter((p) => p.value !== null)
    const first = known[0]
    const last = known[known.length - 1]
    if (!first || !last) return `${s.label} reported no confidence.`
    if (first === last) return `${s.label} reported ${first.value}% in round ${first.round}.`
    return `${s.label} went from ${first.value}% in round ${first.round} to ${last.value}% in round ${last.round}.`
  })
  return parts.length ? parts.join(' ') : 'No confidence has been reported yet.'
}
