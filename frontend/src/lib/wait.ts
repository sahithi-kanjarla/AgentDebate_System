/** "30 seconds", "about 23 minutes", "about 9 hours": how long until a retry can work. Rounds up, never early. */
export function formatWait(seconds: number): string {
  const s = Math.max(1, Math.ceil(seconds))
  if (s < 60) return `${s} ${s === 1 ? 'second' : 'seconds'}`
  if (s < 90 * 60) {
    const m = Math.ceil(s / 60)
    return `about ${m} ${m === 1 ? 'minute' : 'minutes'}`
  }
  const h = Math.ceil(s / 3600)
  return `about ${h} ${h === 1 ? 'hour' : 'hours'}`
}

/** The local clock time a wait ends at, e.g. "2:32 PM". */
export function clockAfter(seconds: number, now: number = Date.now()): string {
  return new Date(now + seconds * 1000).toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
  })
}
