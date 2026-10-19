import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { DebateScreen } from '../components/DebateScreen'
import { useFetch } from '../hooks/useFetch'
import { getDebate } from '../lib/api'
import { initialState, reduceAll, streamEnded } from '../lib/debateState'
import {
  SLUG_RE,
  extractBannedTerms,
  forbiddenKeyPaths,
  indexItemFor,
  sanitizeShowcase,
  scanBannedTerms,
} from '../lib/showcase'

// The provider and model names to look for come from the backend config files, never from this code.
const CONFIGS = import.meta.glob('../../../backend/config/agents*.yaml', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>
const BANNED = extractBannedTerms(Object.values(CONFIGS))

/**
 * Development-only page (compiled out of production builds): turns a debate stored by the local
 * backend into a sanitised showcase file. It reads GET /api/debates/{id}; it calls no model and
 * needs no key. Nothing is written for you: download the file into frontend/public/showcase/, read
 * the warnings, and run `npm run showcase:index`.
 */
export default function DevExport() {
  const { debateId = '' } = useParams()
  const loaded = useFetch(() => getDebate(debateId), debateId)
  const [slug, setSlug] = useState('')
  const [title, setTitle] = useState('')
  const [testOnly, setTestOnly] = useState(false)

  const detail = loaded.status === 'ready' ? loaded.data : null
  const slugOk = SLUG_RE.test(slug)

  const file = useMemo(
    () =>
      detail && slugOk && title.trim() !== ''
        ? sanitizeShowcase({
            slug,
            title: title.trim(),
            testOnly,
            question: detail.question,
            recorded_on: detail.created_at.slice(0, 10),
            events: detail.events,
          })
        : null,
    [detail, slug, slugOk, title, testOnly],
  )
  const warnings = useMemo(() => (file ? scanBannedTerms(file, BANNED) : []), [file])
  const leaks = useMemo(() => (file ? forbiddenKeyPaths(file) : []), [file])
  const state = useMemo(
    () => (file ? streamEnded(reduceAll(file.events, initialState())) : initialState()),
    [file],
  )

  if (loaded.status === 'loading') return <p role="status">Loading debate…</p>
  if (loaded.status === 'error' || !detail) {
    return <p role="alert">{loaded.status === 'error' ? loaded.message : 'Debate not found.'}</p>
  }

  const download = () => {
    if (!file) return
    const blob = new Blob([JSON.stringify(file, null, 2) + '\n'], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${file.slug}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="space-y-5">
      <h1 className="text-3xl">Export a showcase file</h1>
      <p className="max-w-[68ch] text-ink-soft">
        Dev-only. Reads debate <code>{debateId}</code> from the local backend and keeps only the
        fields the screen needs: no <code>label_map</code>, provider or model. Read the preview and
        the warnings before you put the file in <code>frontend/public/showcase/</code>.
      </p>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm font-semibold text-ink">
          Slug (lowercase letters, digits, dashes)
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            aria-invalid={slug !== '' && !slugOk}
            className="mt-1 block w-full rounded-card border border-rule-strong bg-paper p-2 font-normal"
          />
        </label>
        <label className="block text-sm font-semibold text-ink">
          Title
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1 block w-full rounded-card border border-rule-strong bg-paper p-2 font-normal"
          />
        </label>
      </div>
      <label className="flex items-center gap-2 text-sm text-ink">
        <input type="checkbox" checked={testOnly} onChange={(e) => setTestOnly(e.target.checked)} />
        Mark as a test-only placeholder
      </label>

      {file && (
        <section
          aria-label="Checks"
          className="space-y-2 rounded-card border border-rule-strong bg-vellum p-4"
        >
          <p className="text-sm text-ink">
            {leaks.length === 0
              ? 'No label_map, provider or model keys in the output.'
              : `Forbidden keys found: ${leaks.join(', ')}`}
          </p>
          {warnings.length === 0 ? (
            <p className="text-sm text-ink">
              No provider or model names found in the text ({BANNED.length} terms checked).
            </p>
          ) : (
            <ul role="alert" className="list-disc pl-5 text-sm text-severity-high">
              {warnings.map((w) => (
                <li key={w}>{w}. Edit or drop this debate; the text is not rewritten for you.</li>
              ))}
            </ul>
          )}
          <p className="text-sm text-ink-soft">
            Index entry: <code>{JSON.stringify(indexItemFor(file))}</code>
          </p>
          <button
            type="button"
            className="graph-btn"
            onClick={download}
            disabled={leaks.length > 0}
          >
            Download {file.slug}.json
          </button>
          <p className="text-sm text-ink-soft">
            Then run <code>npm run showcase:index</code> to list it on the Home page.
          </p>
        </section>
      )}

      {file && (
        <DebateScreen
          header={{
            id: file.slug,
            question: file.question,
            mode: 'answer',
            status: 'completed',
            created_at: file.recorded_on ?? '',
          }}
          state={state}
          connection="closed"
          events={file.events}
          recorded
        />
      )}
    </div>
  )
}
