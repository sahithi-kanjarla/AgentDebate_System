import { useLayoutEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { DemoBanner } from '../components/DemoNotice'
import { GITHUB_URL, SiteFooter, SiteHeader } from '../components/SiteChrome'
import { HeroAnimation } from '../components/landing/HeroAnimation'
import { Reveal } from '../components/landing/Reveal'
import { ServerNotice } from '../components/landing/ServerNotice'
import { useFetch } from '../hooks/useFetch'
import {
  labCount,
  loadExamples,
  loadPanel,
  numberWord,
  type ExampleSet,
  type Panel,
} from '../lib/landing'

const FEATURES = [
  { title: 'Answer alone first', text: 'No debater sees another’s answer until round 1.' },
  { title: 'Anonymous critiques', text: 'Debaters see “Response 1”, never who wrote it.' },
  { title: 'Every step visible', text: 'Watch it live, or replay it later.' },
  { title: 'Mistakes, counted', text: 'The list is built from the debate transcript.' },
  { title: 'Free, no account', text: 'Type a question and start.' },
  { title: 'Your history is yours', text: 'The history list stays in your browser.' },
] as const

const WORTH_IT = [
  'A wrong answer would cost you: a calculation, a code question, a fact you will rely on.',
  'You want to see how an answer was reached.',
  'You want second and third opinions from different models.',
] as const

const NOT_WORTH_IT = [
  'You need an instant answer. A debate makes many model calls.',
  'It is a matter of taste, with nothing to check.',
  'The text is private. On this demo, questions go to model providers.',
] as const

const UNDER_THE_HOOD = [
  'Multi-agent debate: independent answers, rounds of anonymous critique, then a judge.',
  'One provider interface, with retries, rate limits and a fallback chain.',
  'Structured JSON from every debater, repaired once if malformed.',
  'Live updates over server-sent events; the same event log replays a finished debate.',
] as const

function Heading({ id, eyebrow, children }: { id: string; eyebrow?: string; children: string }) {
  return (
    <div>
      {eyebrow && <p className="mb-2 text-sm font-medium text-ink-soft">{eyebrow}</p>}
      <h2 id={id} className="text-[1.75rem] leading-9 text-ink">
        {children}
      </h2>
    </div>
  )
}

function Hero() {
  return (
    <section
      aria-labelledby="hero-title"
      className="hero-fit flex items-center border-b border-rule"
    >
      <div className="mx-auto grid w-full max-w-6xl items-center gap-8 px-4 py-6 sm:px-6 sm:py-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-12">
        <div>
          <h1
            id="hero-title"
            className="text-4xl leading-[1.08] text-ink sm:text-5xl lg:text-[3.5rem]"
          >
            Three AIs argue. One verdict.
          </h1>
          <p className="mt-4 max-w-[34ch] text-base leading-7 text-ink-soft sm:mt-5 sm:text-lg">
            Ask a question. Three AI models answer, challenge each other, and a judge decides. Watch
            every step.
          </p>
          <div className="mt-6 flex flex-wrap gap-3 sm:mt-8">
            <Link to="/app" className="btn btn-primary">
              Try it
            </Link>
            <Link to="/app?tab=demo" className="btn btn-secondary">
              Watch a demo
            </Link>
          </div>
          <p className="mt-3 text-sm text-ink-soft">Free. No account.</p>
          <div className="mt-2">
            <ServerNotice />
          </div>
        </div>
        <HeroAnimation />
      </div>
    </section>
  )
}

function Examples({ set }: { set: ExampleSet | null }) {
  if (set === null) return null
  return (
    <section id="examples" aria-labelledby="examples-title" className="scroll-mt-16">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <Reveal>
          <Heading id="examples-title" eyebrow="Real runs">
            See it run on four real questions
          </Heading>
          <p className="mt-3 max-w-[60ch] text-ink-soft">
            In each of these, most of the panel started out wrong. Open one and step through it: who
            answered what, who changed their mind, and when the judge ruled.
          </p>
          <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {set.examples.map((e) => (
              <li key={e.id}>
                <Link
                  to={`/app?tab=demo&q=${e.id}`}
                  className="card card-link flex h-full flex-col"
                >
                  <span className="text-xs font-medium text-ink-soft">{e.category}</span>
                  <span className="mt-1 line-clamp-4 text-[0.9375rem] leading-6 text-ink">
                    {e.stem}
                  </span>
                  <span className="mt-auto pt-4 text-sm font-medium text-brass">Watch it run</span>
                </Link>
              </li>
            ))}
          </ul>
          <p className="mt-4 max-w-[70ch] text-sm text-ink-soft">
            Tested honestly.{' '}
            <a
              href={`${GITHUB_URL}#results`}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-brass underline underline-offset-2"
            >
              See the results.
            </a>
          </p>
        </Reveal>
      </div>
    </section>
  )
}

function PanelSection({ panel }: { panel: Panel | null }) {
  if (panel === null) return null
  const n = panel.debaters.length
  const labs = labCount(panel)
  const heading = `${numberWord(n)} models from ${numberWord(labs)} ${labs === 1 ? 'lab' : 'labs'}`
  return (
    <section aria-labelledby="panel-title" className="border-t border-rule bg-vellum">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <Reveal>
          <Heading id="panel-title" eyebrow="Meet the panel">
            {heading.charAt(0).toUpperCase() + heading.slice(1)}
          </Heading>
          <p className="mt-3 max-w-[60ch] text-ink-soft">
            Models from different labs are less likely to make the same mistake, so they can check
            each other.
          </p>
          <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {panel.debaters.map((d) => (
              <li key={d.model} className="card" data-testid="panel-model">
                <p className="text-xs font-medium text-ink-soft">Debater</p>
                <p className="mt-1 font-mono text-[0.9375rem] font-medium text-ink [overflow-wrap:anywhere]">
                  {d.model}
                </p>
                <p className="mt-1 text-sm text-ink-soft">{d.lab}</p>
              </li>
            ))}
            <li className="card border-ink" data-testid="panel-judge">
              <p className="text-xs font-medium text-ink-soft">Judge</p>
              <p className="mt-1 font-mono text-[0.9375rem] font-medium text-ink [overflow-wrap:anywhere]">
                {panel.judge.model}
              </p>
              <p className="mt-1 text-sm text-ink-soft">{panel.judge.lab}</p>
            </li>
          </ul>
          <p className="mt-5 max-w-[64ch] text-sm text-ink-soft">
            Roles: {panel.personas.join(', ')}. Who plays which stays hidden until you ask after a
            debate.
            {panel.judgeSharesModel && ' The judge runs on the same model as one of the debaters.'}
          </p>
        </Reveal>
      </div>
    </section>
  )
}

function Features() {
  return (
    <section aria-labelledby="features-title" className="border-t border-rule bg-paper">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <Reveal>
          <Heading id="features-title">What you get</Heading>
          <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <li key={f.title} className="card">
                <h3 className="text-lg text-ink">{f.title}</h3>
                <p className="mt-1 text-ink-soft">{f.text}</p>
              </li>
            ))}
          </ul>
        </Reveal>
      </div>
    </section>
  )
}

function Worth() {
  const list = (items: readonly string[]) => (
    <ul className="mt-3 space-y-2 text-ink-soft">
      {items.map((t) => (
        <li key={t} className="flex gap-3">
          <span
            aria-hidden="true"
            className="mt-[0.6rem] h-1.5 w-1.5 shrink-0 rounded-pill bg-ink-soft"
          />
          {t}
        </li>
      ))}
    </ul>
  )
  return (
    <section aria-labelledby="worth-title" className="border-t border-rule bg-vellum">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <Reveal>
          <Heading id="worth-title">When it is worth it, and when not</Heading>
          <div className="mt-8 grid gap-4 md:grid-cols-2">
            <div className="card">
              <h3 className="text-lg text-ink">Worth trying</h3>
              {list(WORTH_IT)}
            </div>
            <div className="card">
              <h3 className="text-lg text-ink">Not worth it</h3>
              {list(NOT_WORTH_IT)}
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  )
}

function Cta() {
  return (
    <section aria-labelledby="try-title" className="band-ink">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-6 px-4 py-14 sm:px-6">
        <div>
          <h2 id="try-title" className="text-[1.75rem] leading-9 text-paper">
            Ask your own question
          </h2>
          <p className="mt-2 max-w-[52ch] text-[#c9d3dc]">
            Short, checkable questions work best: a calculation, or what a piece of code prints. Do
            not enter personal or confidential text.
          </p>
        </div>
        <Link to="/app" className="btn btn-on-ink">
          Try it
        </Link>
      </div>
    </section>
  )
}

function Hood() {
  return (
    <section aria-labelledby="hood-title" className="border-b border-rule bg-paper">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
        <h2 id="hood-title" className="text-xl text-ink">
          Under the hood
        </h2>
        <ul className="mt-4 grid gap-x-10 gap-y-2 text-sm text-ink-soft md:grid-cols-2">
          {UNDER_THE_HOOD.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
        <p className="mt-4 text-sm text-ink-soft">
          The graph in the app shows who criticised whom and who changed their answer. It does not
          show anything inside the models.
        </p>
      </div>
    </section>
  )
}

export function Landing() {
  const examples = useFetch(loadExamples, 'examples')
  const panel = useFetch(loadPanel, 'panel')
  const root = useRef<HTMLDivElement>(null)
  const banner = useRef<HTMLDivElement>(null)
  const header = useRef<HTMLElement>(null)

  // The hero fills what is left of the first screen once the banner and header are counted.
  useLayoutEffect(() => {
    const measure = () => {
      const h = (banner.current?.offsetHeight ?? 0) + (header.current?.offsetHeight ?? 0)
      root.current?.style.setProperty('--chrome', `${h}px`)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    if (banner.current) ro.observe(banner.current)
    if (header.current) ro.observe(header.current)
    return () => ro.disconnect()
  }, [])

  return (
    <div ref={root} className="bg-paper">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-30 focus:bg-paper focus:p-2"
      >
        Skip to content
      </a>
      <div ref={banner}>
        <DemoBanner />
      </div>
      <SiteHeader headerRef={header} />
      <main id="main">
        <Hero />
        <Examples set={examples.status === 'ready' ? examples.data : null} />
        <PanelSection panel={panel.status === 'ready' ? panel.data : null} />
        <Features />
        <Worth />
        <Cta />
        <Hood />
      </main>
      <SiteFooter />
    </div>
  )
}
