import { useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { RateLimitNotice } from '../components/RateLimitNotice'
import { ShowcaseList } from '../components/ShowcaseList'
import { RateLimitedError, createDebate } from '../lib/api'
import { EXAMPLES } from '../lib/examples'
import { readStored, removeStored, writeStored } from '../lib/safeStorage'
import type { Mode } from '../lib/types'

const MAX_CHARS = 4000
// A question the server refused, kept so a reload after waiting does not lose it.
const DRAFT_KEY = 'tribunal.draft.v1'

export function Home() {
  const navigate = useNavigate()
  const [question, setQuestion] = useState(() => readStored(DRAFT_KEY) ?? '')
  const [mode, setMode] = useState<Mode>('answer')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [limited, setLimited] = useState<RateLimitedError | null>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)

  const blank = question.trim().length === 0
  const tooLong = question.length > MAX_CHARS

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (blank || tooLong || busy) return
    setBusy(true)
    setError(null)
    setLimited(null)
    try {
      // Sent exactly as typed: whitespace and newlines matter for code questions.
      const id = await createDebate(question, mode)
      removeStored(DRAFT_KEY)
      navigate(`/debate/${id}`)
    } catch (err) {
      if (err instanceof RateLimitedError) {
        writeStored(DRAFT_KEY, question)
        setLimited(err)
      } else {
        setError(err instanceof Error ? err.message : 'Could not start the debate.')
      }
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-4xl text-ink sm:text-5xl">Three debaters. One ruling.</h1>
      <p className="mt-3 max-w-[60ch] font-serif text-lg text-ink-soft">
        Three AI debaters answer your question on their own, then critique each other without
        knowing who is who. A judge reads the exchange and rules.
      </p>

      <form onSubmit={submit} className="mt-8 space-y-5">
        <div>
          <label htmlFor="question" className="mb-1.5 block text-sm font-semibold text-ink">
            Your question or text
          </label>
          <textarea
            id="question"
            ref={textarea}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={9}
            spellCheck={false}
            aria-describedby="question-count"
            className="answer-text block w-full resize-y rounded-card border border-rule-strong bg-paper p-3 text-ink"
            placeholder="Ask anything. Code and line breaks are kept exactly as you type them."
          />
          <p
            id="question-count"
            className={`mt-1 text-right text-xs ${tooLong ? 'font-semibold text-severity-high' : 'text-ink-soft'}`}
          >
            {question.length} / {MAX_CHARS}
            {tooLong && ' (too long)'}
          </p>
        </div>

        <fieldset>
          <legend className="mb-1.5 text-sm font-semibold text-ink">Mode</legend>
          <div className="flex flex-wrap gap-3">
            <label
              className={`flex items-center gap-2 rounded-card border-2 px-3 py-2 ${
                mode === 'answer' ? 'border-ink bg-paper' : 'border-rule bg-vellum'
              }`}
            >
              <input
                type="radio"
                name="mode"
                value="answer"
                checked={mode === 'answer'}
                onChange={() => setMode('answer')}
              />
              <span>
                <span className="font-medium text-ink">Answer</span>
                <span className="block text-xs text-ink-soft">Find the best answer</span>
              </span>
            </label>
            <label className="flex items-center gap-2 rounded-card border-2 border-rule bg-vellum px-3 py-2 opacity-80">
              <input
                type="radio"
                name="mode"
                value="review"
                disabled
                onChange={() => setMode('review')}
              />
              <span>
                <span className="font-medium text-ink">Review</span>
                <span className="block text-xs text-ink-soft">Coming in a later milestone</span>
              </span>
            </label>
          </div>
        </fieldset>

        {limited && <RateLimitNotice scope={limited.scope} retryAfterS={limited.retryAfterS} />}

        {error && (
          <p
            role="alert"
            className="rounded-card border border-severity-high bg-severity-high-tint p-3 text-sm text-ink"
          >
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={blank || tooLong || busy}
          className="rounded-card bg-ink px-5 py-2.5 font-semibold text-paper hover:bg-ink-soft disabled:bg-rule-strong disabled:text-paper"
        >
          {busy ? 'Starting…' : 'Start debate'}
        </button>
      </form>

      <section aria-labelledby="examples-heading" className="mt-12">
        <h2 id="examples-heading" className="mb-3 font-sans text-base font-semibold text-ink">
          Try an example
        </h2>
        <ul className="grid gap-3 sm:grid-cols-3">
          {EXAMPLES.map((ex) => (
            <li key={ex.id}>
              <button
                type="button"
                onClick={() => {
                  setQuestion(ex.question)
                  textarea.current?.focus()
                }}
                className="h-full w-full rounded-card border border-rule-strong bg-vellum p-3 text-left hover:bg-paper"
              >
                <span className="block text-xs text-ink-soft">{ex.hint}</span>
                <span className="mt-0.5 block font-medium text-ink">{ex.title}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <ShowcaseList />
    </div>
  )
}
