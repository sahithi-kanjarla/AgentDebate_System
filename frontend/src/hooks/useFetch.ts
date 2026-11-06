import { useEffect, useState } from 'react'
import { friendlyMessage } from '../lib/friendly'

export type Fetched<T> =
  { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: T }

/** Minimal fetch-on-mount hook; re-runs when `key` changes. */
export function useFetch<T>(load: () => Promise<T>, key: string): Fetched<T> {
  const [result, setResult] = useState<{ key: string; value: Fetched<T> }>({
    key,
    value: { status: 'loading' },
  })

  useEffect(() => {
    let cancelled = false
    load().then(
      (data) => {
        if (!cancelled) setResult({ key, value: { status: 'ready', data } })
      },
      (err: unknown) => {
        if (!cancelled) {
          const message = friendlyMessage(err, 'Something went wrong. Try again in a moment.')
          setResult({ key, value: { status: 'error', message } })
        }
      },
    )
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `load` is recreated each render; `key` identifies it
  }, [key])

  return result.key === key ? result.value : { status: 'loading' }
}
