import { useEffect, useState } from 'react'

export type ServerStatus = 'checking' | 'waking' | 'ready'

const WAKING_AFTER_MS = 2500
const RETRY_MS = 3000

/**
 * Pings /api/health. A free host sleeps when idle, so the first request can take a minute: after
 * 2.5 s without an answer the status becomes "waking" (the page says so) and the ping repeats until
 * the server answers. Any HTTP answer means the server is up.
 */
export function useServerStatus(): ServerStatus {
  const [status, setStatus] = useState<ServerStatus>('checking')
  useEffect(() => {
    if (typeof fetch !== 'function') return
    let cancelled = false
    let retry: ReturnType<typeof setTimeout> | undefined
    const waking = setTimeout(() => {
      if (!cancelled) setStatus((s) => (s === 'checking' ? 'waking' : s))
    }, WAKING_AFTER_MS)

    const ping = () => {
      fetch('/api/health').then(
        () => {
          if (cancelled) return
          clearTimeout(waking)
          setStatus('ready')
        },
        () => {
          if (!cancelled) retry = setTimeout(ping, RETRY_MS)
        },
      )
    }
    ping()
    return () => {
      cancelled = true
      clearTimeout(waking)
      clearTimeout(retry)
    }
  }, [])
  return status
}
