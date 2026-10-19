import { useEffect, useId, useRef, useState } from 'react'
import { usePrefersReducedMotion } from '../../hooks/usePrefersReducedMotion'
import { readStored, writeStored } from '../../lib/safeStorage'

export const TOUR_KEY = 'tribunal.tour.v1'

export interface TourStep {
  id: string
  title: string
  body: string
  /** The real thing on the page this step is about; it gets an outline while the step is showing. */
  selector: string
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: 'nodes',
    title: 'Each node is one answer',
    body: 'A node is one debater’s answer in one round. Debaters that gave the same answer share a colour and a letter, so you can see who agrees without reading anything.',
    selector: '[data-node-kind="answer"]',
  },
  {
    id: 'edges',
    title: 'Lines are critiques',
    body: 'A line runs from the debater who raised a problem to the debater whose answer it targets. Hover or focus one to read the issue and its severity.',
    selector: '[data-edge-kind="critique"]',
  },
  {
    id: 'legend',
    title: 'The legend explains every mark',
    body: 'Colours, letters, patterns and line styles are all listed there. Open it any time with the Legend button above the graph.',
    selector: '[data-testid="legend"], [role="toolbar"]',
  },
  {
    id: 'judge',
    title: 'The judge rules at the end',
    body: 'The judge is not one of the debaters. It reads the whole anonymised exchange, then gives one ruling.',
    selector: '[data-node-kind="judge"]',
  },
  {
    id: 'verdict',
    title: 'Reading the verdict',
    body: 'You get the final answer, how sure the judge is, and the mistakes it says were caught. Point at a mistake to light up the critique it came from.',
    selector: 'section[aria-labelledby="verdict-heading"]',
  },
]

export function tourDone(): boolean {
  return readStored(TOUR_KEY) === 'done'
}

interface Props {
  /** Called with the step being shown (or null on close) so the page can outline the right thing. */
  onStep: (id: string | null) => void
  onClose: () => void
}

/**
 * A short, non-modal tour of a finished debate. It never blocks the page: no focus trap, Esc skips,
 * and focus returns to where it was. Finishing or skipping is remembered (tribunal.tour.v1).
 */
export function Tour({ onStep, onClose }: Props) {
  const uid = useId()
  const [index, setIndex] = useState(0)
  const reduced = usePrefersReducedMotion()
  const nextRef = useRef<HTMLButtonElement>(null)
  const step = TOUR_STEPS[index]!
  const last = index === TOUR_STEPS.length - 1

  const finish = () => {
    writeStored(TOUR_KEY, 'done')
    onStep(null)
    onClose()
  }
  const finishRef = useRef(finish)
  finishRef.current = finish

  // Move focus in on open, and give it back on close.
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null
    nextRef.current?.focus()
    return () => {
      if (before && document.contains(before)) before.focus()
    }
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') finishRef.current()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    onStep(step.id)
    const target = document.querySelector<HTMLElement | SVGElement>(step.selector)
    target?.scrollIntoView?.({ block: 'center', behavior: reduced ? 'auto' : 'smooth' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step.id, reduced])

  return (
    <section
      role="dialog"
      aria-labelledby={`${uid}-t`}
      aria-describedby={`${uid}-b`}
      className="tour-card"
      data-testid="tour"
    >
      <p className="tour-count">
        Step {index + 1} of {TOUR_STEPS.length}
      </p>
      <h2 id={`${uid}-t`} className="tour-title">
        {step.title}
      </h2>
      <p id={`${uid}-b`} className="tour-body">
        {step.body}
      </p>
      <div className="tour-actions">
        <button type="button" className="graph-btn" onClick={finish}>
          Skip tour
        </button>
        <span className="tour-spacer" />
        <button
          type="button"
          className="graph-btn"
          disabled={index === 0}
          onClick={() => setIndex(index - 1)}
        >
          Back
        </button>
        <button
          type="button"
          ref={nextRef}
          className="tour-next"
          onClick={() => (last ? finish() : setIndex(index + 1))}
        >
          {last ? 'Done' : 'Next'}
        </button>
      </div>
    </section>
  )
}
