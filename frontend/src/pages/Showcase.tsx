import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { DebateScreen } from '../components/DebateScreen'
import { useFetch } from '../hooks/useFetch'
import { initialState, reduceAll, streamEnded } from '../lib/debateState'
import { SLUG_RE, validateShowcase, type ShowcaseFile } from '../lib/showcase'

export const showcaseUrl = (name: string) => `${import.meta.env.BASE_URL}showcase/${name}.json`

async function loadShowcase(slug: string): Promise<ShowcaseFile> {
  if (!SLUG_RE.test(slug)) throw new Error('This example does not exist.')
  let res: Response
  try {
    res = await fetch(showcaseUrl(slug))
  } catch {
    throw new Error('Could not load this example. Check your connection and try again.')
  }
  if (!res.ok) throw new Error('This example does not exist.')
  let body: unknown
  try {
    body = await res.json()
  } catch {
    throw new Error('This example could not be read.')
  }
  const checked = validateShowcase(body)
  if (!checked.ok) throw new Error('This example could not be read.')
  return checked.file
}

function Recorded({ file }: { file: ShowcaseFile }) {
  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-card border border-rule-strong bg-vellum p-3 text-sm text-ink"
      data-testid="recorded-banner"
    >
      <span className="rounded-chip border border-ink bg-brass-tint px-1.5 py-0.5 font-semibold">
        Recorded example
      </span>
      {file.testOnly && (
        <span
          className="rounded-chip border border-dashed border-ink px-1.5 py-0.5 font-semibold"
          data-testid="test-only-chip"
        >
          Test-only placeholder
        </span>
      )}
      <span className="text-ink-soft">
        Replayed from a saved log. No models are being called.
        {file.testOnly && ' This one is invented to show the screen; it is not a real debate.'}
      </span>
    </div>
  )
}

export function Showcase() {
  const { slug = '' } = useParams()
  const loaded = useFetch(() => loadShowcase(slug), slug)

  const file = loaded.status === 'ready' ? loaded.data : null
  const state = useMemo(
    () => (file ? streamEnded(reduceAll(file.events, initialState())) : initialState()),
    [file],
  )

  if (loaded.status === 'loading') return <p role="status">Loading example…</p>
  if (loaded.status === 'error' || !file) {
    return (
      <div className="max-w-xl">
        <h1 className="text-3xl">Example not available</h1>
        <p role="alert" className="mt-2 text-ink-soft">
          {loaded.status === 'error' ? loaded.message : 'This example does not exist.'}
        </p>
        <p className="mt-4">
          <Link to="/" className="font-medium text-brass underline">
            Back to the start
          </Link>
        </p>
      </div>
    )
  }

  return (
    <DebateScreen
      header={{
        id: file.slug,
        question: file.question,
        mode: file.mode,
        status: 'completed',
        created_at: file.recorded_on ?? '',
      }}
      state={state}
      connection="closed"
      events={file.events}
      recorded
      banner={<Recorded file={file} />}
    />
  )
}
