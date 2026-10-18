import type { DebateHeader } from '../lib/types'
import type { Status } from '../lib/debateState'

const STATUS_WORD: Record<Status, string> = {
  connecting: 'Connecting',
  running: 'In progress',
  done: 'Finished',
  failed: 'Stopped early',
}

/** The question, exactly as submitted (whitespace preserved; multi-line text reads as code). */
export function QuestionPlate({ header, status }: { header: DebateHeader; status: Status }) {
  const multiline = header.question.includes('\n')
  return (
    <header className="rounded-card border border-rule-strong bg-paper p-5">
      <p className="mb-2 flex flex-wrap items-center gap-2 text-sm text-ink-soft">
        <span className="rounded-chip border border-rule-strong px-1.5 py-0.5 text-ink">
          {header.mode === 'review' ? 'Review' : 'Answer'}
        </span>
        <span>{STATUS_WORD[status]}</span>
      </p>
      <h1
        data-testid="question"
        className={
          multiline
            ? 'answer-text max-h-72 overflow-auto font-normal text-ink'
            : 'whitespace-pre-wrap break-words text-2xl text-ink'
        }
      >
        {header.question}
      </h1>
    </header>
  )
}
