import { forwardRef } from 'react'
import { answerBefore, type DebateState } from '../../lib/debateState'
import { nodeById, receivedFor, type GraphModel, type GraphNode } from '../../lib/graphModel'
import { clusterColor, clusterLetter, clusterPattern } from '../../lib/palette'
import { ChangedMindBadge } from '../ChangedMindBadge'
import { CritiqueList, ReceivedCritiques } from '../CritiqueList'

function Swatch({ clusterId }: { clusterId: number }) {
  return (
    <span
      className="swatch"
      data-pattern={clusterPattern(clusterId)}
      style={{ ['--c' as string]: clusterColor(clusterId) }}
      aria-hidden="true"
    />
  )
}

function AnswerBlock({
  title,
  answer,
  clusterId,
}: {
  title: string
  answer: string
  clusterId: number | null
}) {
  return (
    <section aria-label={title}>
      <h3 className="mb-1 flex items-center gap-2 font-sans text-sm font-semibold text-ink">
        {clusterId !== null && <Swatch clusterId={clusterId} />}
        {title}
        {clusterId !== null && (
          <span className="text-xs font-normal text-ink-soft">
            Answer {clusterLetter(clusterId)}
          </span>
        )}
      </h3>
      <p className="answer-text max-h-48 overflow-auto rounded-card border border-rule bg-paper p-2.5 text-ink">
        {answer}
      </p>
    </section>
  )
}

function Body({ state, model, node }: { state: DebateState; model: GraphModel; node: GraphNode }) {
  if (node.kind === 'question') {
    return (
      <p
        className="answer-text rounded-card border border-rule bg-paper p-2.5 text-ink"
        data-testid="inspector-question"
      >
        {node.answer || 'The question is not available.'}
      </p>
    )
  }
  if (node.kind === 'judge') {
    const v = state.verdict
    if (!v) {
      return (
        <p className="text-sm text-ink-soft">
          {node.status === 'judging'
            ? 'The judge is reviewing the whole debate.'
            : 'The judge rules once the debate is finished.'}
        </p>
      )
    }
    const cluster = model.clusters.find((c) => c.answer === v.final_answer)
    return (
      <div className="space-y-4">
        <AnswerBlock
          title="Ruling"
          answer={v.final_answer}
          clusterId={cluster?.clusterId ?? null}
        />
        <p className="text-sm text-ink-soft">Confidence {v.confidence}%</p>
        {v.summary && (
          <p className="whitespace-pre-wrap break-words text-sm text-ink">{v.summary}</p>
        )}
        {v.dissent && (
          <p className="whitespace-pre-wrap break-words text-sm text-ink">
            <span className="font-medium">Dissent: </span>
            {v.dissent}
          </p>
        )}
      </div>
    )
  }

  const turn =
    node.round === null || node.agent === null
      ? undefined
      : state.rounds[node.round]?.turns[node.agent]
  if (!turn || turn.status === 'thinking') {
    return <p className="text-sm text-ink-soft">{node.agent} is still working on this round.</p>
  }
  if (turn.status === 'invalid') {
    return (
      <div
        role="note"
        className="rounded-card border border-severity-high bg-severity-high-tint p-3 text-sm text-ink"
      >
        <p className="font-medium">No usable answer this round</p>
        <p className="mt-1 whitespace-pre-wrap break-words text-ink-soft">{turn.error}</p>
      </div>
    )
  }

  const before =
    node.round === null || node.agent === null
      ? undefined
      : answerBefore(state, node.round, node.agent)
  const received = receivedFor(state, node)
  return (
    <div className="space-y-4">
      {node.changedMind ? (
        <>
          <ChangedMindBadge before={before} />
          {node.changedMindDerived && (
            <p className="text-xs text-ink-soft">
              This older debate has no server record of changes, so this was worked out by comparing
              answers.
            </p>
          )}
        </>
      ) : null}
      <AnswerBlock
        title={
          node.changedMind ? 'Answer after' : node.round === 0 ? 'Independent answer' : 'Answer'
        }
        answer={turn.finalAnswer ?? ''}
        clusterId={node.clusterId}
      />
      {turn.confidence !== undefined && (
        <p className="text-sm text-ink-soft">Confidence {turn.confidence}%</p>
      )}
      {turn.fallbackUsed && <p className="text-sm text-ink-soft">A backup answered this turn.</p>}
      {turn.reasoning ? (
        <details open>
          <summary className="cursor-pointer text-sm font-semibold text-ink">Reasoning</summary>
          <p className="mt-2 whitespace-pre-wrap break-words text-sm text-ink">{turn.reasoning}</p>
        </details>
      ) : null}
      {node.round !== null && node.round > 0 && node.agent && (
        <>
          <section aria-label="Critiques it raised">
            <h3 className="mb-1.5 font-sans text-sm font-semibold text-ink">Critiques it raised</h3>
            <CritiqueList from={node.agent} critiques={turn.critiques} />
          </section>
          <ReceivedCritiques critiques={received} />
        </>
      )}
    </div>
  )
}

interface Props {
  state: DebateState
  model: GraphModel
  nodeId: string
  onClose: () => void
}

/**
 * The panel's content. Its scroll container is the slot around it (`.graph-inspector-slot`), a fixed
 * column beside the graph on wide screens and a bottom sheet on narrow ones, so no amount of text
 * here can change the graph's size. Focus moves here on open.
 */
export const NodeInspector = forwardRef<HTMLElement, Props>(function NodeInspector(
  { state, model, nodeId, onClose },
  ref,
) {
  const node = nodeById(model, nodeId)
  if (!node) return null
  const column = model.columns[node.column]
  const title =
    node.kind === 'question'
      ? 'Question'
      : node.kind === 'judge'
        ? 'Judge'
        : `${node.agent}, ${column?.label}`
  return (
    <aside
      ref={ref}
      tabIndex={-1}
      role="dialog"
      aria-modal="false"
      aria-label={`Details: ${title}`}
      data-testid="inspector"
      className="graph-drawer p-4"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.stopPropagation()
          onClose()
        }
      }}
    >
      <header className="graph-drawer-head mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-xl">{title}</h2>
          {node.persona && node.kind === 'answer' && (
            <p className="text-sm text-ink-soft">
              {node.persona}
              {column ? `, ${column.sublabel}` : ''}
            </p>
          )}
        </div>
        <button type="button" className="graph-btn" onClick={onClose}>
          Close
        </button>
      </header>
      <Body state={state} model={model} node={node} />
    </aside>
  )
})
