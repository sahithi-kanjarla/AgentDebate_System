import { fireEvent, render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reduceAll } from '../../lib/debateState'
import { LONG_REASONING, longReasoning, SHORT_REASONING } from '../../test/graphFixtures'
import { DebateGraph } from './DebateGraph'

beforeEach(() => {
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: false,
    media: q,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
  window.localStorage.clear()
})

const css = readFileSync(resolve(process.cwd(), 'src/styles/index.css'), 'utf-8')

function setup() {
  const view = render(
    <DebateGraph
      state={reduceAll(longReasoning.events)}
      question={longReasoning.question}
      animate={false}
    />,
  )
  const stage = view.container.querySelector('.graph-stage') as HTMLElement
  const svg = view.container.querySelector('svg.graph-svg') as SVGSVGElement
  const viewport = svg.querySelector(':scope > g:last-of-type') as SVGGElement
  const snapshot = () => ({
    stage: stage.outerHTML.slice(0, stage.outerHTML.indexOf('<svg')),
    svgOpen: svg.outerHTML.slice(0, svg.outerHTML.indexOf('>')),
    transform: viewport.getAttribute('transform'),
    layoutStyle: view.container.querySelector('.graph-layout')!.getAttribute('style'),
  })
  const open = (id: string) =>
    fireEvent.click(view.container.querySelector(`[data-node-id="${id}"]`)!)
  return { ...view, stage, svg, snapshot, open }
}

describe('the inspector never changes the graph', () => {
  it('leaves the graph container identical with nothing, a short and a 20,000-character reasoning selected', () => {
    expect(LONG_REASONING.length).toBeGreaterThanOrEqual(20000)
    const { snapshot, open } = setup()
    const none = snapshot()

    open('n:0:Debater 2') // short reasoning
    expect(screen.getByTestId('inspector')).toHaveTextContent(SHORT_REASONING)
    const short = snapshot()

    open('n:0:Debater 1') // very long reasoning
    expect(screen.getByTestId('inspector').textContent).toContain('Step 120')
    const long = snapshot()

    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    const closed = snapshot()

    expect(short).toEqual(none)
    expect(long).toEqual(none)
    expect(closed).toEqual(none)
  })

  it('keeps the graph out of the panel and reserves the panel before anything is selected', () => {
    const { stage } = setup()
    const slot = screen.getByTestId('inspector-slot')
    expect(slot).toHaveAttribute('data-open', 'false')
    expect(slot).toHaveTextContent('Select a node to read its reasoning.')
    expect(slot.contains(stage)).toBe(false)
    expect(stage.contains(slot)).toBe(false)
    expect(slot.parentElement).toBe(stage.parentElement) // two cells of one grid
    expect(stage.parentElement).toHaveClass('graph-layout')
  })

  it('renders the same slot element before, during and after a selection', () => {
    const { open } = setup()
    const slot = screen.getByTestId('inspector-slot')
    open('n:0:Debater 1')
    expect(screen.getByTestId('inspector-slot')).toBe(slot)
    expect(slot).toHaveAttribute('data-open', 'true')
    expect(slot).toContainElement(screen.getByTestId('inspector'))
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.getByTestId('inspector-slot')).toBe(slot)
    expect(slot).toHaveAttribute('data-open', 'false')
  })

  it('shows the full long reasoning with its whitespace, inside the panel', () => {
    const { open } = setup()
    open('n:0:Debater 1')
    const reasoning = Array.from(screen.getByTestId('inspector').querySelectorAll('p')).find((p) =>
      p.textContent?.startsWith('Step 1:'),
    )!
    expect(reasoning.textContent).toBe(LONG_REASONING)
    expect(reasoning.className).toContain('whitespace-pre-wrap')
  })

  it('moves focus into the panel on open without scrolling, and Escape returns it to the node', async () => {
    const { container } = setup()
    const node = container.querySelector<HTMLElement>('[data-node-id="n:0:Debater 1"]')!
    node.focus()
    fireEvent.keyDown(node, { key: 'Enter' })
    const panel = screen.getByTestId('inspector')
    expect(panel).toHaveFocus()
    fireEvent.keyDown(panel, { key: 'Escape' })
    expect(screen.queryByTestId('inspector')).not.toBeInTheDocument()
    await vi.waitFor(() => expect(node).toHaveFocus())
  })
})

describe('the stylesheet makes the panel the thing that scrolls', () => {
  const rule = (selector: string) => {
    const at = css.indexOf(selector)
    expect(at, selector).toBeGreaterThan(-1)
    return css.slice(at, css.indexOf('}', at))
  }

  it('gives the panel its own vertical scroll, contained, with a styled scrollbar', () => {
    const r = rule('.graph-inspector-slot {')
    expect(r).toContain('overflow-y: auto')
    expect(r).toContain('overflow-x: hidden')
    expect(r).toContain('overscroll-behavior: contain')
    expect(css).toContain('.graph-inspector-slot::-webkit-scrollbar')
  })

  it('reserves a fixed 400px column beside a shrinkable graph from 1100px up', () => {
    const wide = css.slice(css.indexOf('@media (min-width: 1100px)'))
    expect(wide).toContain('grid-template-columns: minmax(0, 1fr) 400px')
    expect(wide).toContain('position: sticky')
    expect(wide).toMatch(/height: min\(calc\(100vh - 2rem\), var\(--stage-h, 560px\)\)/)
    expect(rule('.graph-layout > * {')).toContain('min-width: 0')
  })

  it('turns the panel into a bottom sheet of at most half the screen below 1100px', () => {
    const narrow = css.slice(
      css.indexOf('@media (max-width: 1099px)'),
      css.indexOf('@media (min-width: 1100px)'),
    )
    expect(narrow).toContain('position: fixed')
    expect(narrow).toContain('max-height: 50vh')
    expect(narrow).toContain("[data-open='false']")
  })

  it('wraps long words inside the panel', () => {
    expect(rule('.graph-inspector-slot * {')).toContain('overflow-wrap: anywhere')
  })
})
