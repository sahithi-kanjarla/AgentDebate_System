import { vi } from 'vitest'

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown }

/** Stubs global fetch with a handler; returns the mock so tests can inspect calls. */
export function stubFetch(handler: Handler) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const { status = 200, body = {} } = handler(String(input), init)
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', mock)
  return mock
}
