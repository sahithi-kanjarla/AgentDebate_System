import { readStored, writeStored } from './safeStorage'

const KEY = 'tribunal.clientId'

function generate(): string {
  const c = globalThis.crypto
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  const bytes = new Uint8Array(16)
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(bytes)
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

/**
 * A random per-browser ID that keeps History private to this browser. It is not a login: the
 * server stores only a hash of it. Kept in localStorage (memory fallback when storage is blocked).
 */
export function getClientId(): string {
  const existing = readStored(KEY)
  if (existing && /^[A-Za-z0-9_-]{16,128}$/.test(existing)) return existing
  const id = generate()
  writeStored(KEY, id)
  return id
}

export function clientIdHeaders(): Record<string, string> {
  return { 'X-Client-Id': getClientId() }
}
