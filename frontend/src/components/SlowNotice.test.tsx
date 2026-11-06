import { act, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SLOW_AFTER_MS, SlowNotice } from './SlowNotice'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

const mount = () =>
  render(
    <MemoryRouter>
      <SlowNotice />
    </MemoryRouter>,
  )

describe('SlowNotice', () => {
  it('stays hidden for the first minute, then shows one line with a demo link in a new tab', () => {
    mount()
    act(() => void vi.advanceTimersByTime(SLOW_AFTER_MS - 1))
    expect(screen.queryByTestId('slow-notice')).toBeNull()
    act(() => void vi.advanceTimersByTime(1))
    const note = screen.getByTestId('slow-notice')
    expect(note).toHaveTextContent(
      'Free models can be slow. Keep this page open, or watch a demo while you wait.',
    )
    const link = screen.getByRole('link', { name: 'watch a demo' })
    expect(link).toHaveAttribute('href', '/app?tab=demo')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('never shows if it unmounts first (the debate finished)', () => {
    const { unmount } = mount()
    unmount()
    act(() => void vi.advanceTimersByTime(SLOW_AFTER_MS * 2))
    expect(screen.queryByTestId('slow-notice')).toBeNull()
  })
})
