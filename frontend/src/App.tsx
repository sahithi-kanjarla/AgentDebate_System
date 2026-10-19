import { lazy, Suspense } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { Debate } from './pages/Debate'
import { History } from './pages/History'
import { Home } from './pages/Home'
import { NotFound } from './pages/NotFound'

// Fixtures are test-only: the route and its import are compiled out of production builds.
const DevGraph = import.meta.env.DEV ? lazy(() => import('./pages/DevGraph')) : null
const DevDebate = import.meta.env.DEV ? lazy(() => import('./pages/DevDebate')) : null

const navClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-chip px-2 py-1 text-sm font-medium ${isActive ? 'text-ink underline decoration-brass-fill decoration-2 underline-offset-4' : 'text-ink-soft hover:text-ink'}`

export function App() {
  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:bg-paper focus:p-2"
      >
        Skip to content
      </a>
      <header className="border-b border-rule-strong bg-vellum">
        <nav
          aria-label="Main"
          className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6"
        >
          <NavLink to="/" end className="font-serif text-xl font-semibold text-ink">
            Tribunal
          </NavLink>
          <div className="flex gap-2">
            <NavLink to="/" end className={navClass}>
              New debate
            </NavLink>
            <NavLink to="/history" className={navClass}>
              History
            </NavLink>
          </div>
        </nav>
      </header>
      <main id="main" className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/debate/:id" element={<Debate />} />
          <Route path="/history" element={<History />} />
          {DevGraph && (
            <Route
              path="/dev/graph/:fixture"
              element={
                <Suspense fallback={<p role="status">Loading…</p>}>
                  <DevGraph />
                </Suspense>
              }
            />
          )}
          {DevDebate && (
            <Route
              path="/dev/debate/:fixture"
              element={
                <Suspense fallback={<p role="status">Loading…</p>}>
                  <DevDebate />
                </Suspense>
              }
            />
          )}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </div>
  )
}
