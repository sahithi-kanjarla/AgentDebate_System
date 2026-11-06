import { afterEach, describe, expect, it } from 'vitest'
import { clientIdHeaders, getClientId } from './clientId'
import { resetStoredMemory } from './safeStorage'

afterEach(() => {
  window.localStorage.clear()
  resetStoredMemory()
})

describe('client id', () => {
  it('is created once, stored and reused', () => {
    const first = getClientId()
    expect(first).toMatch(/^[A-Za-z0-9_-]{16,128}$/)
    expect(window.localStorage.getItem('tribunal.clientId')).toBe(first)
    expect(getClientId()).toBe(first)
  })

  it('replaces a stored value the server would reject', () => {
    window.localStorage.setItem('tribunal.clientId', 'short')
    expect(getClientId()).not.toBe('short')
  })

  it('goes out as the X-Client-Id header', () => {
    expect(clientIdHeaders()).toEqual({ 'X-Client-Id': getClientId() })
  })
})
