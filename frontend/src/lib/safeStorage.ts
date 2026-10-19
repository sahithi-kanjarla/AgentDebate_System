/**
 * localStorage that never throws. Storage can be blocked (private windows, site settings, quota), and
 * then reads return null and writes fall back to memory for the rest of this page load, so a choice
 * made once is not asked again until the next visit.
 */
const memory = new Map<string, string>()

export function readStored(key: string): string | null {
  try {
    const v = window.localStorage.getItem(key)
    if (v !== null) return v
  } catch {
    /* fall through to memory */
  }
  return memory.get(key) ?? null
}

export function writeStored(key: string, value: string): void {
  memory.set(key, value)
  try {
    window.localStorage.setItem(key, value)
  } catch {
    /* kept in memory above */
  }
}

export function removeStored(key: string): void {
  memory.delete(key)
  try {
    window.localStorage.removeItem(key)
  } catch {
    /* nothing to remove */
  }
}

/** Test helper: forget the in-memory fallback. */
export function resetStoredMemory(): void {
  memory.clear()
}
