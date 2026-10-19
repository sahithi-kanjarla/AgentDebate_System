import { act, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useReplay } from '../../hooks/useReplay'
import { initialState, reduceAll, streamEnded } from '../../lib/debateState'
import { SPEEDS, buildSchedule, delayAt } from '../../lib/replay'
import { FIXTURES } from '../../test/graphFixtures'
import { Insights } from '../insights/Insights'
import { ReplayBar } from './ReplayBar'

const events = FIXTURES.mergeWrongCluster.events
const finalState = streamEnded(reduceAll(events, initialState()))
const prefix = (k: number) => reduceAll(events.slice(0, k), initialState())

describe('useReplay: position k is reduceAll of the first k events', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('starts at the end showing the finished state, with no motion', () => {
    const { result } = renderHook(() => useReplay(events, finalState))
    expect(result.current.position).toBe(events.length)
    expect(result.current.state).toBe(finalState)
    expect(result.current.motion).toBe(false)
    expect(result.current.touched).toBe(false)
  })

  it('matches the reducer at every position, scrubbing forwards and backwards', () => {
    const { result } = renderHook(() => useReplay(events, finalState))
    const check = (k: number) => {
      act(() => result.current.seek(k))
      expect(result.current.position).toBe(k)
      expect(result.current.motion).toBe(false)
      const expected = k === events.length ? finalState : prefix(k)
      expect(JSON.stringify(result.current.state)).toBe(JSON.stringify(expected))
    }
    for (let k = 0; k <= events.length; k++) check(k)
    for (let k = events.length; k >= 0; k--) check(k)
    for (const k of [7, 2, 15, 0, 11]) check(k)
  })

  it('matches the reducer at every tick of playback, at every speed', () => {
    for (const speed of SPEEDS) {
      const { result, unmount } = renderHook(() => useReplay(events, finalState))
      const schedule = buildSchedule(events)
      act(() => result.current.setSpeed(speed))
      act(() => result.current.seek(0))
      act(() => result.current.play())
      expect(result.current.playing).toBe(true)
      let guard = 0
      while (result.current.playing && guard++ < 500) {
        const k = result.current.position
        act(() => {
          vi.advanceTimersByTime(Math.max(1, delayAt(schedule, k, speed)))
        })
        const now = result.current.position
        expect(now).toBeGreaterThanOrEqual(k)
        const expected = now === events.length ? finalState : prefix(now)
        expect(JSON.stringify(result.current.state)).toBe(JSON.stringify(expected))
      }
      expect(result.current.position).toBe(events.length)
      expect(result.current.playing).toBe(false)
      unmount()
    }
  })

  it('animates ticks only, and every seek, step and jump is static', () => {
    const { result } = renderHook(() => useReplay(events, finalState))
    act(() => result.current.seek(0))
    act(() => result.current.play())
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(result.current.playing).toBe(true)
    expect(result.current.motion).toBe(true)
    act(() => result.current.seek(10))
    expect(result.current.playing).toBe(false)
    expect(result.current.motion).toBe(false)
    act(() => result.current.step(1))
    expect(result.current.position).toBe(11)
    expect(result.current.motion).toBe(false)
    act(() => result.current.jumpRound(1))
    expect(result.current.motion).toBe(false)
    expect(result.current.marks).toContain(result.current.position)
  })

  it('jumps between rounds and restarts from the end', () => {
    const { result } = renderHook(() => useReplay(events, finalState))
    const marks = result.current.marks
    act(() => result.current.jumpRound(-1))
    expect(result.current.position).toBe(marks[marks.length - 2])
    act(() => result.current.seek(0))
    act(() => result.current.jumpRound(1))
    expect(result.current.position).toBe(marks[1])
    act(() => result.current.seek(events.length))
    act(() => result.current.play())
    expect(result.current.position).toBe(0)
    expect(result.current.playing).toBe(true)
  })
})

function Harness({ onReplay }: { onReplay?: (r: ReturnType<typeof useReplay>) => void }) {
  const replay = useReplay(events, finalState)
  onReplay?.(replay)
  return <ReplayBar replay={replay} />
}

describe('ReplayBar', () => {
  it('has labelled controls, a scrubber with readable value text, and a speed radiogroup', () => {
    render(<Harness />)
    for (const name of ['Previous round', 'Previous event', 'Next event', 'Next round']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: /replay/i })).toBeInTheDocument()
    const range = screen.getByRole('slider', { name: 'Replay position' })
    expect(range).toHaveAttribute('max', String(events.length))
    expect(range).toHaveAttribute('aria-valuetext', expect.stringMatching(/^Event \d+ of \d+: /))
    const speeds = screen.getAllByRole('radio')
    expect(speeds.map((r) => r.textContent)).toEqual(['0.5×', '1×', '2×', '4×'])
    expect(screen.getByRole('radio', { name: '1×' })).toBeChecked()
  })

  it('steps, jumps and scrubs from the keyboard-reachable controls', () => {
    let latest: ReturnType<typeof useReplay> | undefined
    render(<Harness onReplay={(r) => (latest = r)} />)
    fireEvent.click(screen.getByRole('button', { name: 'Previous event' }))
    expect(latest?.position).toBe(events.length - 1)
    fireEvent.change(screen.getByRole('slider'), { target: { value: '5' } })
    expect(latest?.position).toBe(5)
    expect(screen.getByTestId('replay-status')).toHaveTextContent('5/' + events.length)
    fireEvent.click(screen.getByRole('radio', { name: '4×' }))
    expect(screen.getByRole('radio', { name: '4×' })).toBeChecked()
    fireEvent.keyDown(screen.getByRole('radio', { name: '4×' }), { key: 'ArrowLeft' })
    expect(latest?.speed).toBe(2)
  })

  it('does not speak a position before anyone has used the replay', () => {
    render(<Harness />)
    expect(screen.getByTestId('replay-announce')).toHaveTextContent('')
  })
})

describe('Insights text alternatives', () => {
  it('gives every chart an accessible name, a one-sentence summary and a data table', () => {
    render(<Insights state={finalState} question="q" />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual(['Agreement', 'Answer flow', 'Confidence'])

    const check = (svgOrRegion: HTMLElement, summary: RegExp, tableCaption: RegExp) => {
      expect(svgOrRegion).toHaveAttribute('role', 'img')
      expect(svgOrRegion).toHaveAccessibleName()
      expect(screen.getByTestId('chart-summary')).toHaveTextContent(summary)
      const table = screen.getByRole('table', { name: tableCaption, hidden: true })
      expect(table.querySelectorAll('tbody tr').length).toBeGreaterThan(0)
    }

    check(
      screen.getByTestId('agreement-chart'),
      /Agreement rose from 1 of 3 to 3 of 3/,
      /agreement/i,
    )
    fireEvent.click(tabs[1]!)
    check(
      screen.getByTestId('answer-flow') as unknown as HTMLElement,
      /Round 0: answer .*Round 2: answer A 3/,
      /supporting each answer/i,
    )
    fireEvent.click(tabs[2]!)
    check(
      screen.getByTestId('confidence-chart'),
      /Debater 1 went from 92% in round 0/,
      /Confidence/i,
    )
  })

  it('reveals the table on request and never hides data behind colour alone', () => {
    render(<Insights state={finalState} question="q" />)
    const wrap = screen.getByTestId('chart-table')
    expect(wrap).toHaveClass('sr-only')
    fireEvent.click(screen.getByRole('button', { name: 'Show as table' }))
    expect(wrap).not.toHaveClass('sr-only')
    expect(screen.getByRole('button', { name: 'Hide table' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    // Values are printed on the marks as text.
    expect(screen.getByTestId('agreement-chart').textContent).toContain('3/3')
  })

  it('moves between tabs with the arrow keys and collapses', () => {
    render(<Insights state={finalState} question="q" />)
    const first = screen.getAllByRole('tab')[0]!
    first.focus()
    fireEvent.keyDown(first, { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: 'Answer flow' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Answer flow' }), { key: 'End' })
    expect(screen.getByRole('tab', { name: 'Confidence' })).toHaveAttribute('aria-selected', 'true')
    const toggle = screen.getByRole('button', { name: 'Hide insights' })
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('shows plain empty states before the first round finishes', () => {
    render(<Insights state={initialState()} question={null} />)
    expect(screen.getByText(/Agreement appears once the first round/)).toBeInTheDocument()
  })
})
