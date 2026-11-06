import type { Ref } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { DemoFooter } from './DemoNotice'

export const GITHUB_URL = 'https://github.com/sahithi-kanjarla/AgentDebate_System'

const linkClass = ({ isActive }: { isActive: boolean }) => `nav-link ${isActive ? 'is-active' : ''}`

/** The one header, on every page: brand, three links, and the Try it button. */
export function SiteHeader({ headerRef }: { headerRef?: Ref<HTMLElement> }) {
  return (
    <header ref={headerRef} className="sticky top-0 z-20 border-b border-rule bg-paper">
      <nav
        aria-label="Main"
        className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6"
      >
        <Link to="/" className="text-xl font-semibold text-ink">
          Tribunal
        </Link>
        <div className="flex items-center gap-1 sm:gap-2">
          <NavLink to="/app?tab=demo" className="nav-link hidden sm:inline-block">
            Demo
          </NavLink>
          <NavLink to="/history" className={linkClass}>
            History
          </NavLink>
          <Link to="/app" className="btn btn-primary btn-sm ml-1">
            Try it
          </Link>
        </div>
      </nav>
    </header>
  )
}

/** The one footer: links, then the data notice that production builds always carry. */
export function SiteFooter() {
  return (
    <>
      <div className="border-t border-rule bg-paper">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-6 text-sm text-ink-soft sm:px-6">
          <p>Tribunal</p>
          <nav aria-label="Footer" className="flex flex-wrap gap-4">
            <Link to="/app" className="underline underline-offset-2">
              Try it
            </Link>
            <Link to="/history" className="underline underline-offset-2">
              History
            </Link>
            <a href={GITHUB_URL} className="underline underline-offset-2">
              GitHub
            </a>
          </nav>
        </div>
      </div>
      <DemoFooter />
    </>
  )
}

/** Page title block used by every working page, so they all start the same way. */
export function PageTitle({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="mb-8">
      <h1 className="text-[2rem] leading-10 text-ink">{title}</h1>
      {children && <p className="mt-2 max-w-[60ch] text-ink-soft">{children}</p>}
    </div>
  )
}
