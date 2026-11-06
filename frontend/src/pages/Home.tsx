import { useRef, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ExampleDemo } from '../components/demo/ExampleDemo'
import { StartNotice } from '../components/DemoNotice'
import { ServerNotice } from '../components/landing/ServerNotice'
import { RateLimitNotice } from '../components/RateLimitNotice'
import { PageTitle } from '../components/SiteChrome'
import { useFetch } from '../hooks/useFetch'
import { RateLimitedError, createDebate } from '../lib/api'
import { friendlyMessage } from '../lib/friendly'
import { EXAMPLES } from '../lib/examples'
import { loadExamples } from '../lib/landing'
import { readStored, removeStored, writeStored } from '../lib/safeStorage'

const MAX_CHARS = 4000
// A question the server refused, kept so a reload after waiting does not lose it.
const DRAFT_KEY = 'tribunal.draft.v1'

type Tab = 'own' | 'demo'

function Demo({ initialId }: { initialId: string | null }) {
  const loaded = useFetch(loadExamples, 'examples')
  if (loaded.status === 'loading') return <p role="status">Loading the demo…</p>
  if (loaded.status === 'error' || loaded.data === null) {
    return (
      <p className="text-ink-soft">
        The demo is not available right now. You can still ask your own question.
      </p>
    )
  }
  return <ExampleDemo set={loaded.data} initialId={initialId} />
}

export function Home() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const tab: Tab = params.get('tab') === 'demo' ? 'demo' : 'own'
  const [question, setQuestion] = useState(() => readStored(DRAFT_KEY) ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [limited, setLimited] = useState<RateLimitedError | null>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)

  const blank = question.trim().length === 0
  const tooLong = question.length > MAX_CHARS

  const chooseTab = (next: Tab) => {
    const p = new URLSearchParams(params)
    if (next === 'demo') p.set('tab', 'demo')
    else {
      p.delete('tab')
      p.delete('q')
    }
    setParams(p, { replace: true })
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (blank || tooLong || busy) return
    setBusy(true)
    setError(null)
    setLimited(null)
    try {
      // Sent exactly as typed: whitespace and newlines matter for code questions.
      const id = await createDebate(question, 'answer')
      removeStored(DRAFT_KEY)
      navigate(`/debate/${id}`)
    } catch (err) {
      if (err instanceof RateLimitedError) {
        writeStored(DRAFT_KEY, question)
        setLimited(err)
      } else {
        setError(friendlyMessage(err, 'Could not start the debate. Try again in a moment.'))
      }
      setBusy(false)
    }
  }

  const tabButton = (id: Tab, text: string) => (
    <button
      type="button"
      role="tab"
      id={`tab-${id}`}
      aria-selected={tab === id}
      aria-controls={`panel-${id}`}
      onClick={() => chooseTab(id)}
      className={`seg ${tab === id ? 'is-active' : ''}`}
    >
      {text}
    </button>
  )

  return (
    <div className="mx-auto max-w-5xl">
      <PageTitle title="Try Tribunal">
        Ask your own question, or watch the panel work through a real one first.
      </PageTitle>

      <div role="tablist" aria-label="How to try it" className="seg-group">
        {tabButton('own', 'Ask your own')}
        {tabButton('demo', 'Watch a demo')}
      </div>

      {tab === 'own' ? (
        <div
          role="tabpanel"
          id="panel-own"
          aria-labelledby="tab-own"
          className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]"
        >
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label htmlFor="question" className="mb-2 block text-sm font-semibold text-ink">
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
                placeholder="Ask anything with a short, checkable answer. Code and line breaks are kept exactly as you type them."
              />
              <p
                id="question-count"
                className={`mt-1 text-right text-xs ${tooLong ? 'font-semibold text-severity-high' : 'text-ink-soft'}`}
              >
                {question.length} / {MAX_CHARS}
                {tooLong && ' (too long)'}
              </p>
            </div>

            {limited && <RateLimitNotice scope={limited.scope} retryAfterS={limited.retryAfterS} />}

            {error && (
              <p
                role="alert"
                className="rounded-card border border-severity-high bg-severity-high-tint p-3 text-sm text-ink"
              >
                {error}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-4">
              <button type="submit" disabled={blank || tooLong || busy} className="btn btn-primary">
                {busy ? 'Starting…' : 'Start debate'}
              </button>
              <p className="text-sm text-ink-soft">
                Three debaters, up to three rounds, one ruling.
              </p>
            </div>
            <StartNotice />
            <ServerNotice />
          </form>

          <aside aria-labelledby="examples-heading">
            <h2 id="examples-heading" className="text-base font-semibold text-ink">
              Not sure what to ask?
            </h2>
            <ul className="mt-3 space-y-2">
              {EXAMPLES.map((ex) => (
                <li key={ex.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setQuestion(ex.question)
                      textarea.current?.focus()
                    }}
                    className="pick block w-full"
                  >
                    <span className="block text-xs text-ink-soft">{ex.hint}</span>
                    <span className="mt-0.5 block font-medium text-ink">{ex.title}</span>
                  </button>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-sm text-ink-soft">
              Short questions with one checkable answer work best.{' '}
              <button
                type="button"
                onClick={() => chooseTab('demo')}
                className="font-medium text-brass underline underline-offset-2"
              >
                Or watch a demo first.
              </button>
            </p>
          </aside>
        </div>
      ) : (
        <div role="tabpanel" id="panel-demo" aria-labelledby="tab-demo" className="mt-8">
          <p className="mb-5 max-w-[64ch] text-ink-soft">
            Pick one of four real questions. Step through it to see what each debater answered, who
            changed their mind, and when the judge ruled.
          </p>
          <Demo initialId={params.get('q')} />
        </div>
      )}
    </div>
  )
}
