/**
 * The deployment notices (banner, footer note, line under the Start button, History note) belong to
 * the public demo, so they appear only in production builds. `import.meta.env.PROD` is read when
 * called, not when the module loads, so tests can switch it with `vi.stubEnv`.
 */
export function demoNoticeEnabled(): boolean {
  return import.meta.env.PROD === true
}

/** The services that receive a visitor's question. Named in the privacy note on purpose. */
export const PROVIDER_NAMES = ['Google Gemini', 'Groq', 'OpenRouter', 'Mistral'] as const

export const PROVIDER_LIST = `${PROVIDER_NAMES.slice(0, -1).join(', ')} and ${PROVIDER_NAMES.at(-1)}`

export const BANNER_KEY = 'tribunal.banner.v1'
export const PRIVACY_ANCHOR = 'privacy'
