import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initialState, reduceAll, streamEnded } from '../../lib/debateState'
import { removeStored, resetStoredMemory } from '../../lib/safeStorage'
import { FIXTURES } from '../../test/graphFixtures'
import { DebateScreen } from '../DebateScreen'
import { TOUR_KEY, TOUR_STEPS } from './Tour'

const f = FIXTURES.mergeWrongCluster
const events = f.events
const header = {
  id: 'x',
  question: f.question,
  mode: 'answer' as const,
  status: 'completed',
  created_at: '2000-01-01T00:00:00Z',
}
const finalState = streamEnded(reduceAll(events, initialState()))

function mount(state = finalState, evs = events) {
  return render(<DebateScreen header={header} state={state} connection="closed" events={evs} />)
}

beforeEach(() => {
  window.localStorage.clear()
  resetStoredMemory()
})
afterEach(() => vi.restoreAllMocks())

describe('Tour', () => {
  it('opens on a finished debate, as a non-modal dialog with five steps', () => {
    mount()
    const dialog = screen.getByRole('dialog')
    expect(dialog).not.toHaveAttribute('aria-modal')
    expect(dialog).toHaveAccessibleName(TOUR_STEPS[0]!.title)
    expect(screen.getByText('Step 1 of 5')).toBeInTheDocument()
    expect(TOUR_STEPS).toHaveLength(5)
  })

  it('does not open while the debate is still running', () => {
    const running = reduceAll(events.slice(0, 8), initialState())
    mount(running, [])
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Replay the tour' })).toBeNull()
  })

  it('moves through the steps, outlines the real thing, and remembers it is done', () => {
    const { container } = mount()
    const root = container.firstElementChild as HTMLElement
    expect(root.getAttribute('data-tour')).toBe('nodes')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(root.getAttribute('data-tour')).toBe('edges')
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(root.getAttribute('data-tour')).toBe('nodes')
    for (let i = 0; i < TOUR_STEPS.length - 1; i++) {
      fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    }
    expect(root.getAttribute('data-tour')).toBe('verdict')
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(root.hasAttribute('data-tour')).toBe(false)
    expect(window.localStorage.getItem(TOUR_KEY)).toBe('done')
  })

  it('skips with the button or Escape, and stays away afterwards', () => {
    const first = mount()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    first.unmount()
    mount()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('replays on request even after it was finished', () => {
    window.localStorage.setItem(TOUR_KEY, 'done')
    mount()
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Replay the tour' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Step 1 of 5')).toBeInTheDocument()
  })

  it('returns focus to where it was when it closes', () => {
    window.localStorage.setItem(TOUR_KEY, 'done')
    mount()
    const replay = screen.getByRole('button', { name: 'Replay the tour' })
    replay.focus()
    fireEvent.click(replay)
    expect(screen.getByRole('button', { name: 'Next' })).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(replay).toHaveFocus()
  })

  it('works when storage throws on both read and write, and is not shown twice in one visit', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const first = mount()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    first.unmount()
    // The in-memory fallback remembers it for the rest of this page load.
    mount()
    expect(screen.queryByRole('dialog')).toBeNull()
    removeStored(TOUR_KEY)
  })
})
