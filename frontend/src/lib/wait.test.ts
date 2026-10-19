import { describe, expect, it } from 'vitest'
import { clockAfter, formatWait } from './wait'

describe('formatWait', () => {
  it('speaks seconds, minutes and hours, rounding up', () => {
    expect(formatWait(1)).toBe('1 second')
    expect(formatWait(30)).toBe('30 seconds')
    expect(formatWait(60)).toBe('about 1 minute')
    expect(formatWait(61)).toBe('about 2 minutes')
    expect(formatWait(3580)).toBe('about 60 minutes')
    expect(formatWait(5399)).toBe('about 90 minutes')
    expect(formatWait(5401)).toBe('about 2 hours')
    expect(formatWait(9 * 3600 - 5)).toBe('about 9 hours')
  })

  it('never says zero', () => {
    expect(formatWait(0)).toBe('1 second')
  })
})

describe('clockAfter', () => {
  it('is the local time the wait ends', () => {
    const now = new Date(2026, 9, 19, 14, 9, 30).getTime()
    const expected = new Date(2026, 9, 19, 14, 32, 30).toLocaleTimeString([], {
      hour: 'numeric',
      minute: '2-digit',
    })
    expect(clockAfter(23 * 60, now)).toBe(expected)
  })
})
