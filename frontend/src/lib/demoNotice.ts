import { useEffect, useState } from 'react'
import { loadPanel } from './landing'

/**
 * The deployment notices (banner, footer note, line under the Start button, History note) belong to
 * the public demo, so they appear only in production builds. `import.meta.env.PROD` is read when
 * called, not when the module loads, so tests can switch it with `vi.stubEnv`.
 */
export function demoNoticeEnabled(): boolean {
  return import.meta.env.PROD === true
}

/** "A, B and C". Empty input gives an empty string. */
export function joinNames(names: readonly string[]): string {
  if (names.length < 2) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`
}

/**
 * The services that receive a visitor's question, read from public/panel.json (generated from the
 * agents config) so the copy cannot drift. Returns [] until loaded or if the file is unavailable;
 * the notices then say "third-party model providers" without names.
 */
export function useProviderNames(): string[] {
  const [names, setNames] = useState<string[]>([])
  useEffect(() => {
    let live = true
    void loadPanel().then((p) => {
      if (live && p) setNames(p.providers)
    })
    return () => {
      live = false
    }
  }, [])
  return names
}

/** " (Google Gemini, Groq and Mistral)" or "" when the names are not known. */
export const providerParen = (names: readonly string[]) =>
  names.length > 0 ? ` (${joinNames(names)})` : ''

export const BANNER_KEY = 'tribunal.banner.v1'
export const PRIVACY_ANCHOR = 'privacy'
