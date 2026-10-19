import { Link } from 'react-router-dom'
import { useFetch } from '../hooks/useFetch'
import { validateIndex, type ShowcaseIndexItem } from '../lib/showcase'
import { showcaseUrl } from '../pages/Showcase'

async function loadIndex(): Promise<ShowcaseIndexItem[]> {
  const res = await fetch(showcaseUrl('index'))
  if (!res.ok) throw new Error('no index')
  const items = validateIndex(await res.json())
  if (!items) throw new Error('bad index')
  return items
}

/** "Watch a real debate": recorded examples from /showcase/index.json. Hides itself if there are none. */
export function ShowcaseList() {
  const loaded = useFetch(loadIndex, 'index')
  if (loaded.status !== 'ready' || loaded.data.length === 0) return null

  return (
    <section aria-labelledby="showcase-heading" className="mt-12" data-testid="showcase-list">
      <h2 id="showcase-heading" className="mb-1 font-sans text-base font-semibold text-ink">
        Watch a real debate
      </h2>
      <p className="mb-3 text-sm text-ink-soft">
        Saved examples that replay on their own. Nothing is sent to a model.
      </p>
      <ul className="grid gap-3 sm:grid-cols-3">
        {loaded.data.map((it) => (
          <li key={it.slug}>
            <Link
              to={`/showcase/${it.slug}`}
              className="block h-full rounded-card border border-rule-strong bg-vellum p-3 hover:bg-paper"
            >
              <span className="flex flex-wrap gap-1.5 text-xs">
                <span className="rounded-chip border border-ink bg-brass-tint px-1.5 py-0.5 font-semibold text-ink">
                  Recorded example
                </span>
                {it.testOnly && (
                  <span className="rounded-chip border border-dashed border-ink px-1.5 py-0.5 font-semibold text-ink">
                    Test-only placeholder
                  </span>
                )}
              </span>
              <span className="mt-1.5 block font-medium text-ink">{it.title}</span>
              <span className="mt-0.5 block text-xs text-ink-soft">
                {it.debaters} debaters, {it.rounds} {it.rounds === 1 ? 'round' : 'rounds'}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
