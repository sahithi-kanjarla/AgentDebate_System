import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initialState, reduce, reduceAll } from '../../lib/debateState'
import { FIXTURES, legacy, mergeWrongCluster, type FixtureName } from '../../test/graphFixtures'
import { DebateGraph } from './DebateGraph'

function stubMatchMedia(reduce: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduce && query.includes('reduce'),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
}

beforeEach(() => {
  stubMatchMedia(false)
  window.localStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

function renderFixture(name: FixtureName, animate = false) {
  const f = FIXTURES[name]
  const state = reduceAll(f.events)
  return render(<DebateGraph state={state} question={f.question} animate={animate} />)
}

const nodes = (c: HTMLElement) => c.querySelectorAll('[data-node-id]')
const critiques = (c: HTMLElement) => c.querySelectorAll('[data-edge-kind="critique"]')

describe('node and edge counts', () => {
  it.each([
    ['mergeWrongCluster', 3 * 3 + 2, 2],
    ['invalidAndFallback', 3 * 2 + 2, 2],
    ['five', 5 * 3 + 2, 5],
    ['two', 2 * 2 + 2, 1],
    ['seven', 7 * 4 + 2, 9],
  ] as const)('%s', (name, nodeCount, critiqueCount) => {
    const { container } = renderFixture(name)
    expect(nodes(container)).toHaveLength(nodeCount)
    expect(critiques(container)).toHaveLength(critiqueCount)
  })

  it('batches the faint reading edges into one path per round', () => {
    const { container } = renderFixture('seven')
    const batches = container.querySelectorAll('[data-edge-kind="read-batch"]')
    expect(batches).toHaveLength(3)
    expect(Number(batches[0]!.getAttribute('data-count'))).toBe(7 * 6)
  })

  it('reports counts, and hides reading edges on request', () => {
    const { container } = renderFixture('two')
    expect(screen.getByTestId('debate-graph')).toHaveAttribute('data-nodes', '6')
    fireEvent.click(screen.getByRole('button', { name: 'Reading edges' }))
    expect(container.querySelectorAll('[data-edge-kind="read-batch"]')).toHaveLength(0)
  })

  it('draws halos only where two or more debaters agree', () => {
    const { container } = renderFixture('mergeWrongCluster')
    expect(container.querySelectorAll('[data-halo]')).toHaveLength(1) // round 2: all three agree
  })
})

describe('accessibility', () => {
  it('gives every node a focusable button with a descriptive label', () => {
    const { container } = renderFixture('mergeWrongCluster')
    const d2 = container.querySelector('[data-node-id="n:2:Debater 2"]')!
    expect(d2).toHaveAttribute('tabindex', '0')
    expect(d2).toHaveAttribute('role', 'button')
    expect(d2.getAttribute('aria-label')).toBe(
      'Debater 2, Round 2, Answer A, confidence 88 percent, changed its answer',
    )
    expect(d2).toHaveAttribute('data-changed', 'true')
  })

  it('makes critique edges focusable with who flagged whom in the label', () => {
    const { container } = renderFixture('mergeWrongCluster')
    const edge = critiques(container)[1]!
    expect(edge).toHaveAttribute('tabindex', '0')
    expect(edge.getAttribute('aria-label')).toMatch(
      /^Debater 1 flagged a high-severity problem with Debater 3's Round 0 answer: /,
    )
  })

  it('marks invalid turns without relying on colour', () => {
    const { container } = renderFixture('invalidAndFallback')
    const bad = container.querySelector('[data-node-id="n:1:Debater 2"]')!
    expect(bad).toHaveAttribute('data-status', 'invalid')
    expect(bad.getAttribute('aria-label')).toContain('no usable answer')
    expect(within(bad as HTMLElement).getByText('no answer')).toBeInTheDocument()
  })

  it('shows the honesty note and a legend that can be dismissed and stays dismissed', () => {
    const { unmount } = renderFixture('two')
    expect(screen.getByTestId('honesty-note')).toHaveTextContent('does not show the models')
    expect(screen.getByTestId('legend')).toBeInTheDocument()
    expect(screen.getByTestId('legend')).toHaveTextContent("marker sits at the accuser's end")
    fireEvent.click(screen.getByRole('button', { name: 'Hide legend' }))
    expect(screen.queryByTestId('legend')).not.toBeInTheDocument()
    unmount()
    renderFixture('two')
    expect(screen.queryByTestId('legend')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Legend' }))
    expect(screen.getByTestId('legend')).toBeInTheDocument()
  })

  it('renders the legend below the canvas, not over it', () => {
    renderFixture('two')
    const graph = screen.getByTestId('debate-graph')
    const legend = screen.getByTestId('legend')
    const stage = graph.querySelector('.graph-stage')!
    expect(stage.contains(legend)).toBe(false)
    expect(stage.compareDocumentPosition(legend) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe('inspector', () => {
  function open(id: string, container: HTMLElement) {
    fireEvent.click(container.querySelector(`[data-node-id="${id}"]`)!)
    return screen.getByTestId('inspector')
  }

  it('shows the answer before and after, the reasoning and the received critiques', () => {
    const { container } = renderFixture('mergeWrongCluster')
    const panel = open('n:1:Debater 2', container)
    expect(panel).toHaveTextContent('Critiques of the answer it revised')
    expect(panel).toHaveTextContent('From Debater 1')
    expect(panel).toHaveTextContent('Python prints [1, 2] with a space')
    expect(panel).toHaveTextContent("Debater 2's reasoning in round 1")
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    const after = open('n:2:Debater 2', container)
    expect(after).toHaveTextContent('Changed its answer')
    expect(after).toHaveTextContent('Previously')
    expect(after).toHaveTextContent('Answer after')
    expect(after).toHaveTextContent('None were raised.')
  })

  it('never claims a critique caused a change', () => {
    const { container } = renderFixture('mergeWrongCluster')
    for (const id of ['n:1:Debater 2', 'n:2:Debater 2', 'n:2:Debater 3']) {
      const text = open(id, container).textContent ?? ''
      expect(text).not.toMatch(/because|caused|convinced|why did/i)
      fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    }
  })

  it('preserves whitespace in answers exactly', () => {
    const { container } = renderFixture('mergeWrongCluster')
    const panel = open('n:0:Debater 1', container)
    const answer = panel.querySelector('.answer-text')!
    expect(answer.textContent).toBe('[1]\n[1, 2]')
    expect(getComputedStyleSafe(answer)).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(
      open('q', container).querySelector('[data-testid="inspector-question"]')!.textContent,
    ).toBe(mergeWrongCluster.question)
  })

  it('explains an invalid turn with its reason', () => {
    const { container } = renderFixture('invalidAndFallback')
    const panel = open('n:1:Debater 2', container)
    expect(panel).toHaveTextContent('No usable answer this round')
    expect(panel).toHaveTextContent('could not be read as an answer')
  })

  it('notes a backup answer without naming anything', () => {
    const { container } = renderFixture('invalidAndFallback')
    expect(open('n:0:Debater 3', container)).toHaveTextContent('A backup answered this turn.')
  })

  it('moves focus into the drawer, closes on Escape and returns focus to the node', async () => {
    const { container } = renderFixture('two')
    const node = container.querySelector<HTMLElement>('[data-node-id="n:0:Debater 1"]')!
    node.focus()
    fireEvent.keyDown(node, { key: 'Enter' })
    const panel = screen.getByTestId('inspector')
    expect(panel).toHaveFocus()
    fireEvent.keyDown(panel, { key: 'Escape' })
    expect(screen.queryByTestId('inspector')).not.toBeInTheDocument()
    await vi.waitFor(() => expect(node).toHaveFocus())
  })

  it('opens from the keyboard with Space as well', () => {
    const { container } = renderFixture('two')
    fireEvent.keyDown(container.querySelector('[data-node-id="n:0:Debater 2"]')!, { key: ' ' })
    expect(screen.getByTestId('inspector')).toHaveTextContent('Debater 2, Round 0')
  })

  it('shows the judge ruling', () => {
    const { container } = renderFixture('mergeWrongCluster')
    expect(open('j', container)).toHaveTextContent('Confidence 93%')
  })
})

describe('hover and focus highlighting', () => {
  it('dims everything unrelated and lights the connected marks', () => {
    const { container } = renderFixture('mergeWrongCluster')
    const svg = container.querySelector('svg.graph-svg')!
    expect(svg).toHaveAttribute('data-dim', 'false')
    const node = container.querySelector('[data-node-id="n:1:Debater 1"]')!
    fireEvent.pointerEnter(node)
    expect(svg).toHaveAttribute('data-dim', 'true')
    expect(container.querySelector('[data-node-id="n:0:Debater 2"]')).toHaveAttribute(
      'data-related',
      'true',
    )
    expect(container.querySelector('[data-node-id="n:1:Debater 2"]')).not.toHaveAttribute(
      'data-related',
    )
    expect(critiques(container)[0]).toHaveAttribute('data-related', 'true')
    fireEvent.pointerLeave(node)
    expect(svg).toHaveAttribute('data-dim', 'false')
  })

  it('highlights from keyboard focus too', () => {
    const { container } = renderFixture('mergeWrongCluster')
    fireEvent.focus(container.querySelector('[data-node-id="n:2:Debater 3"]')!)
    expect(container.querySelector('svg.graph-svg')).toHaveAttribute('data-dim', 'true')
  })

  it('shows the critique text and who flagged whom on a critique edge', () => {
    const { container } = renderFixture('mergeWrongCluster')
    fireEvent.pointerEnter(critiques(container)[1]!, { clientX: 10, clientY: 10 })
    const tip = screen.getByTestId('edge-tip')
    expect(tip).toHaveTextContent(
      "Debater 1 flagged a high-severity problem with Debater 3's answer",
    )
    expect(tip).toHaveTextContent('The default list is created once and shared')
    fireEvent.pointerLeave(critiques(container)[1]!)
    expect(screen.queryByTestId('edge-tip')).not.toBeInTheDocument()
  })
})

describe('motion', () => {
  it('is static for a finished debate', () => {
    const { container } = renderFixture('mergeWrongCluster', false)
    expect(container.querySelector('svg.graph-svg')).toHaveAttribute('data-motion', 'off')
    expect(container.querySelectorAll('.pulse, .is-fresh, .flash-ring')).toHaveLength(0)
  })

  it('is static with reduced motion, even for a live debate', () => {
    stubMatchMedia(true)
    const { container } = renderFixture('mergeWrongCluster', true)
    expect(container.querySelector('svg.graph-svg')).toHaveAttribute('data-motion', 'off')
    expect(container.querySelectorAll('.pulse, .is-fresh, .flash-ring')).toHaveLength(0)
  })

  it('animates only what arrives after the first render of a live debate', () => {
    const events = mergeWrongCluster.events
    const split = events.findIndex((e) => e.type === 'critique_edge')
    const before = reduceAll(events.slice(0, split))
    const { container, rerender } = render(<DebateGraph state={before} question={null} animate />)
    expect(container.querySelector('svg.graph-svg')).toHaveAttribute('data-motion', 'on')
    expect(container.querySelectorAll('.pulse')).toHaveLength(0)
    expect(container.querySelectorAll('.is-fresh')).toHaveLength(0)

    const after = reduce(before, events[split]!)
    rerender(<DebateGraph state={after} question={null} animate />)
    expect(container.querySelectorAll('.pulse')).toHaveLength(1)
    expect(critiques(container)).toHaveLength(1)
  })

  it('flashes a node that has just changed its answer', () => {
    const events = mergeWrongCluster.events
    const i = events.findIndex(
      (e) =>
        e.type === 'agent_response' &&
        (e.data as { round: number; agent: string }).round === 2 &&
        (e.data as { agent: string }).agent === 'Debater 2',
    )
    const before = reduceAll(events.slice(0, i))
    const { container, rerender } = render(<DebateGraph state={before} question={null} animate />)
    rerender(<DebateGraph state={reduceAll(events.slice(0, i + 1))} question={null} animate />)
    expect(container.querySelectorAll('.flash-ring')).toHaveLength(1)
  })
})

describe('live and stored debates', () => {
  it('render the same graph', () => {
    const events = FIXTURES.invalidAndFallback.events
    const stored = render(<DebateGraph state={reduceAll(events)} question="q" animate={false} />)
    const storedHtml = stored.container.innerHTML
    stored.unmount()
    let live = initialState()
    for (const e of events) live = reduce(live, e)
    const streamed = render(<DebateGraph state={live} question="q" animate={false} />)
    expect(streamed.container.innerHTML).toBe(storedHtml)
  })
})

describe('older stored debate', () => {
  it('renders without crashing and still shows the changes and received critiques', () => {
    const state = reduceAll(legacy.events)
    const { container } = render(
      <DebateGraph state={state} question={legacy.question} animate={false} />,
    )
    expect(nodes(container)).toHaveLength(11)
    expect(critiques(container)).toHaveLength(2)
    expect(container.querySelector('[data-node-id="n:2:Debater 2"]')).toHaveAttribute(
      'data-changed',
      'true',
    )
    fireEvent.click(container.querySelector('[data-node-id="n:1:Debater 2"]')!)
    expect(screen.getByTestId('inspector')).toHaveTextContent('From Debater 1')
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    fireEvent.click(container.querySelector('[data-node-id="n:2:Debater 2"]')!)
    expect(screen.getByTestId('inspector')).toHaveTextContent('worked out by comparing answers')
  })
})

describe('anonymity', () => {
  it('shows no provider or model names or the label map anywhere', () => {
    const forbidden =
      /openai|groq|gemini|mistral|openrouter|ollama|nemotron|gpt-oss|llama|label_map|mock-/i
    for (const name of Object.keys(FIXTURES) as FixtureName[]) {
      const f = FIXTURES[name]
      const events = f.events.map((e) =>
        e.type === 'agent_response'
          ? {
              ...e,
              data: {
                ...(e.data as object),
                payload: {
                  ...(e.data as { payload: object }).payload,
                  label_map: { 'Response 1': 'groq', 'Response 2': 'secret-model' },
                  provider: 'groq',
                  model: 'secret-model',
                },
              },
            }
          : e,
      )
      const { container, unmount } = render(
        <DebateGraph state={reduceAll(events)} question={f.question} animate={false} />,
      )
      // Open a sample (first, a middle one, last two) so the largest fixture stays quick.
      const ids = Array.from(container.querySelectorAll('[data-node-id]')).map((n) =>
        n.getAttribute('data-node-id')!,
      )
      const sample = [ids[0]!, ids[Math.floor(ids.length / 2)]!, ...ids.slice(-2)]
      for (const id of sample) {
        fireEvent.click(container.querySelector(`[data-node-id="${id}"]`)!)
        expect(screen.getByTestId('inspector').textContent).not.toMatch(forbidden)
        fireEvent.click(screen.getByRole('button', { name: 'Close' }))
      }
      expect(container.textContent).not.toMatch(forbidden)
      expect(container.innerHTML).not.toContain('secret-model')
      unmount()
    }
    // Renders every fixture, including the 7 x 4 one, and opens four inspectors on each: slow on a
    // busy machine, so it gets more time than the default.
  }, 90_000)
})

function getComputedStyleSafe(el: Element): boolean {
  return el.classList.contains('answer-text') // CSS gives .answer-text white-space: pre-wrap
}
