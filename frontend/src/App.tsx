import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { DemoBanner } from './components/DemoNotice'
import { SiteFooter, SiteHeader } from './components/SiteChrome'
import { Debate } from './pages/Debate'
import { History } from './pages/History'
import { Home } from './pages/Home'
import { Landing } from './pages/Landing'
import { NotFound } from './pages/NotFound'

// Fixtures are test-only: the route and its import are compiled out of production builds.
const DevGraph = import.meta.env.DEV ? lazy(() => import('./pages/DevGraph')) : null
const DevDebate = import.meta.env.DEV ? lazy(() => import('./pages/DevDebate')) : null

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="*" element={<AppShell />} />
    </Routes>
  )
}

/** Every page except the landing page: the working app, under the same header and footer. */
function AppShell() {
  return (
    <div className="min-h-screen bg-paper">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-30 focus:bg-paper focus:p-2"
      >
        Skip to content
      </a>
      <DemoBanner />
      <SiteHeader />
      <main id="main" className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <Routes>
          <Route path="/app" element={<Home />} />
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
      <SiteFooter />
    </div>
  )
}
