import { useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { buildAnswerFlow } from '../../lib/answerFlow'
import type { DebateState } from '../../lib/debateState'
import { buildGraphModel } from '../../lib/graphModel'
import { agreementSeries, chartRounds, confidenceSeries } from '../../lib/insights'
import { AgreementChart } from './AgreementChart'
import { AnswerFlow } from './AnswerFlow'
import { ConfidenceSparklines } from './ConfidenceSparklines'

type TabId = 'agreement' | 'flow' | 'confidence'
const TABS: { id: TabId; label: string }[] = [
  { id: 'agreement', label: 'Agreement' },
  { id: 'flow', label: 'Answer flow' },
  { id: 'confidence', label: 'Confidence' },
]

interface Props {
  state: DebateState
  question: string | null
}

/**
 * The panel under the graph: agreement per round, how supporters of each answer move, and each
 * debater's confidence. Everything is derived from the same DebateState as the graph, so during a
 * replay it follows the replay position. Dark stage surface, like the graph above it.
 */
export function Insights({ state, question }: Props) {
  const uid = useId()
  const [tab, setTab] = useState<TabId>('agreement')
  const [open, setOpen] = useState(true)
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({})

  const model = useMemo(() => buildGraphModel(state, question), [state, question])
  const agreement = useMemo(() => agreementSeries(state), [state])
  const confidence = useMemo(() => confidenceSeries(state), [state])
  const rounds = useMemo(() => chartRounds(state), [state])
  const flow = useMemo(
    () => buildAnswerFlow(state, model, state.verdict ? state.verdict.final_answer : null),
    [state, model],
  )

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    const i = TABS.findIndex((t) => t.id === tab)
    let next: number
    if (e.key === 'ArrowRight') next = (i + 1) % TABS.length
    else if (e.key === 'ArrowLeft') next = (i - 1 + TABS.length) % TABS.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = TABS.length - 1
    else return
    e.preventDefault()
    const id = TABS[next]!.id
    setTab(id)
    tabRefs.current[id]?.focus()
  }

  return (
    <section className="insights" aria-labelledby={`${uid}-h`} data-testid="insights">
      <div className="insights-head">
        <h2 id={`${uid}-h`} className="insights-title">
          Insights
        </h2>
        <button
          type="button"
          className="insights-btn"
          aria-expanded={open}
          aria-controls={`${uid}-body`}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? 'Hide insights' : 'Show insights'}
        </button>
      </div>

      <div id={`${uid}-body`} hidden={!open}>
        <div role="tablist" aria-label="Insights" className="insights-tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              ref={(el) => {
                tabRefs.current[t.id] = el
              }}
              type="button"
              role="tab"
              id={`${uid}-tab-${t.id}`}
              aria-selected={tab === t.id}
              aria-controls={`${uid}-panel-${t.id}`}
              tabIndex={tab === t.id ? 0 : -1}
              className="insights-tab"
              onClick={() => setTab(t.id)}
              onKeyDown={onKeyDown}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div
          role="tabpanel"
          id={`${uid}-panel-${tab}`}
          aria-labelledby={`${uid}-tab-${tab}`}
          className="insights-panel"
        >
          {tab === 'agreement' && <AgreementChart series={agreement} />}
          {tab === 'flow' && <AnswerFlow flow={flow} />}
          {tab === 'confidence' && <ConfidenceSparklines series={confidence} rounds={rounds} />}
        </div>
      </div>
    </section>
  )
}
