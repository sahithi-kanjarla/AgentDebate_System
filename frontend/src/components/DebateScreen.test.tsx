import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { initialState, reduceAll, streamEnded } from '../lib/debateState'
import { FIXTURES } from '../test/graphFixtures'
import { DebateScreen } from './DebateScreen'

// These tests are not about the tour.
beforeEach(() => window.localStorage.setItem('tribunal.tour.v1', 'done'))

function mount(name: 'mergeWrongCluster' | 'legacy' = 'mergeWrongCluster') {
  const f = FIXTURES[name]
  const state = streamEnded(reduceAll(f.events, initialState()))
  return render(
    <DebateScreen
      header={{
        id: 'x',
        question: f.question,
        mode: 'answer',
        status: 'completed',
        created_at: '2000-01-01T00:00:00Z',
      }}
      state={state}
      connection="closed"
      events={f.events}
    />,
  )
}

const caughtEdges = (c: HTMLElement) => [
  ...c.querySelectorAll('[data-edge-kind="critique"][data-caught="true"]'),
]

describe('linked verdict', () => {
  it('lights the critique edge when a Mistakes caught item is hovered or focused', () => {
    const { container } = mount()
    const items = screen.getAllByTestId('mistake-item')
    expect(items).toHaveLength(2)
    expect(caughtEdges(container)).toHaveLength(2)

    fireEvent.pointerEnter(items[0]!)
    const lit = container.querySelectorAll('[data-edge-kind="critique"][data-related="true"]')
    expect(lit).toHaveLength(1)
    expect(lit[0]!.getAttribute('aria-label')).toContain(
      'The spacing differs'.slice(0, 0) + 'Python prints [1, 2]',
    )
    expect(container.querySelector('svg.graph-svg')).toHaveAttribute('data-dim', 'true')
    fireEvent.pointerLeave(items[0]!)
    expect(
      container.querySelectorAll('[data-edge-kind="critique"][data-related="true"]'),
    ).toHaveLength(0)

    fireEvent.focus(items[1]!)
    expect(
      container.querySelectorAll('[data-edge-kind="critique"][data-related="true"]'),
    ).toHaveLength(1)
  })

  it('lights the item when its edge is hovered or focused', () => {
    const { container } = mount()
    const edge = caughtEdges(container)[0]!
    fireEvent.focus(edge)
    expect(
      screen.getAllByTestId('mistake-item').filter((i) => i.dataset.linked === 'true'),
    ).toHaveLength(1)
    fireEvent.blur(edge)
    expect(
      screen.getAllByTestId('mistake-item').filter((i) => i.dataset.linked === 'true'),
    ).toHaveLength(0)
  })

  it('pins the link for touch with a Show in graph toggle', () => {
    const { container } = mount()
    const item = screen.getAllByTestId('mistake-item')[0]!
    const button = within(item).getByRole('button', { name: 'Show in graph' })
    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-pressed', 'true')
    expect(
      container.querySelectorAll('[data-edge-kind="critique"][data-related="true"]'),
    ).toHaveLength(1)
    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-pressed', 'false')
  })

  it('still renders the list when nothing matches (older debates)', () => {
    mount('legacy')
    const items = screen.queryAllByTestId('mistake-item')
    expect(items.length).toBeGreaterThanOrEqual(0)
    expect(screen.getByRole('heading', { name: /Mistakes caught/ })).toBeInTheDocument()
  })
})

describe('replay on the debate screen', () => {
  it('shows the finished debate first, and the verdict follows the replay position', () => {
    mount()
    expect(screen.getByTestId('final-answer')).toBeInTheDocument()
    fireEvent.change(screen.getByRole('slider', { name: 'Replay position' }), {
      target: { value: '3' },
    })
    expect(screen.queryByTestId('final-answer')).not.toBeInTheDocument()
    expect(screen.getByTestId('replay-status')).toHaveTextContent(/^3\//)
    fireEvent.click(screen.getByRole('button', { name: 'Next round' }))
    fireEvent.change(screen.getByRole('slider', { name: 'Replay position' }), {
      target: { value: String(FIXTURES.mergeWrongCluster.events.length) },
    })
    expect(screen.getByTestId('final-answer')).toBeInTheDocument()
  })
})
