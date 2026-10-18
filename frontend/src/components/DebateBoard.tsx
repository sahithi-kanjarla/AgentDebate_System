import { answerBefore, orderedRounds, type DebateState } from '../lib/debateState'
import { ConsensusBand } from './ConsensusBand'
import { PersonaBadge } from './PersonaBadge'
import { RoundCard } from './RoundCard'
import { debaterColor } from '../lib/palette'

/**
 * One column per debater, one row per round, with the consensus band between rounds. Rows are
 * grid rows, so cards in the same round line up across columns; on narrow screens everything
 * stacks, round by round.
 */
export function DebateBoard({ state }: { state: DebateState }) {
  const agents = state.agents
  const rounds = orderedRounds(state)
  if (agents.length === 0) return null
  const cols = { ['--cols' as string]: agents.length }
  const columns = 'md:[grid-template-columns:repeat(var(--cols),minmax(0,1fr))]'
  const grid = `grid grid-cols-1 gap-4 ${columns}`
  // Column headings only exist on wide screens; stacked cards carry their own badge.
  const headerGrid = `hidden gap-4 md:grid ${columns}`

  return (
    <div className="space-y-4" style={cols}>
      <div className={headerGrid}>
        {agents.map((a, i) => (
          <div
            key={a.label}
            className="rounded-card border-b-4 bg-vellum px-1 pb-2"
            style={{ borderBottomColor: debaterColor(i) }}
          >
            <PersonaBadge label={a.label} persona={a.persona} index={i} />
          </div>
        ))}
      </div>

      {rounds.map((r) => (
        <div key={r.round} className="space-y-4">
          <h2 className="font-serif text-xl text-ink">
            {r.round === 0
              ? 'Round 0: independent answers'
              : `Round ${r.round}: critique and revise`}
          </h2>
          <div className={grid}>
            {agents.map((a, i) => (
              <RoundCard
                key={a.label}
                round={r.round}
                label={a.label}
                persona={a.persona}
                index={i}
                turn={r.turns[a.label]}
                previousAnswer={answerBefore(state, r.round, a.label)}
              />
            ))}
          </div>
          <ConsensusBand round={r} />
        </div>
      ))}
    </div>
  )
}
