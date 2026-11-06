import { useState } from 'react'
import { BANNER_KEY, PRIVACY_ANCHOR, PROVIDER_LIST, demoNoticeEnabled } from '../lib/demoNotice'
import { readStored, writeStored } from '../lib/safeStorage'

/** Slim bar above the header. Dismissible; the footer note below stays on every page. */
export function DemoBanner() {
  const [dismissed, setDismissed] = useState(() => readStored(BANNER_KEY) === 'dismissed')
  if (!demoNoticeEnabled() || dismissed) return null
  return (
    <div
      role="region"
      aria-label="About this demo"
      className="border-b border-rule-strong bg-brass-tint text-ink"
    >
      <div className="mx-auto flex max-w-6xl items-start gap-3 px-4 py-2 text-sm sm:px-6">
        <p className="flex-1">
          <strong className="font-semibold">Free-tier demo.</strong> Models may be slow or
          unavailable. Do not enter personal or confidential information: your question is sent to
          third-party model providers ({PROVIDER_LIST}).{' '}
          <a href={`#${PRIVACY_ANCHOR}`} className="font-medium underline">
            Details
          </a>
        </p>
        <button
          type="button"
          onClick={() => {
            writeStored(BANNER_KEY, 'dismissed')
            setDismissed(true)
          }}
          className="shrink-0 rounded-chip border border-rule-strong px-2 py-0.5 text-xs font-medium hover:bg-paper"
        >
          Dismiss
        </button>
      </div>
    </div>
  )
}

/** The full note. Always present in production builds, so dismissing the banner hides nothing. */
export function DemoFooter() {
  if (!demoNoticeEnabled()) return null
  return (
    <footer
      id={PRIVACY_ANCHOR}
      aria-labelledby="privacy-heading"
      className="mt-12 border-t border-rule-strong bg-vellum"
    >
      <div className="mx-auto max-w-6xl space-y-2 px-4 py-6 text-sm text-ink-soft sm:px-6">
        <h2 id="privacy-heading" className="font-sans text-sm font-semibold text-ink">
          About this demo and your data
        </h2>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            This is a free-tier demo. The models can be slow, rate-limited or unavailable, and the
            lineup may change.
          </li>
          <li>
            Do not enter personal or confidential information. Your question, and the debaters'
            answers to each other, are sent to third-party model providers: {PROVIDER_LIST}. They
            may keep or use free-tier inputs under their own terms; check their policies.
          </li>
          <li>
            History is stored per browser: it lists only the debates started from this browser.
            Anyone with a debate link can read that debate. The question and answers are stored on
            the demo's server and may be deleted when the host restarts, which can happen at any
            time.
          </li>
          <li>
            Your network address is used in memory to apply usage limits and is not saved with your
            debate.
          </li>
        </ul>
      </div>
    </footer>
  )
}

/** One line next to the Start button, where the data is actually entered. */
export function StartNotice() {
  if (!demoNoticeEnabled()) return null
  return (
    <p className="text-sm text-ink-soft">
      Free-tier demo: do not enter personal or confidential data.{' '}
      <a href={`#${PRIVACY_ANCHOR}`} className="underline">
        Where it goes
      </a>
    </p>
  )
}

/** Shown on the History page. */
export function HistoryNotice() {
  if (!demoNoticeEnabled()) return null
  return (
    <p role="note" className="mb-4 rounded-card border border-rule-strong bg-vellum p-3 text-sm">
      History is stored per browser: it shows only debates started from this browser. Anyone with a
      debate link can read that debate. The question and answers are stored on the server and may be
      deleted when the host restarts. The recorded examples on the home page are not affected.
    </p>
  )
}
