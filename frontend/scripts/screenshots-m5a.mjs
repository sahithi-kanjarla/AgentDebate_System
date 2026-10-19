// Dev tool: screenshots of the M5a debate screen (replay bar, graph, Insights, linked verdict) from
// the TEST-ONLY fixtures, using the installed Microsoft Edge (no browser download). Needs
// `npm run dev` running. Usage: node scripts/screenshots-m5a.mjs <outDir> [baseUrl]
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const out = process.argv[2]
const base = process.argv[3] ?? 'http://localhost:5173'
if (!out) throw new Error('usage: node scripts/screenshots-m5a.mjs <outDir> [baseUrl]')
mkdirSync(out, { recursive: true })

const browser = await chromium.launch({ channel: 'msedge' })
const problems = []
const facts = []

async function open(page, fixture) {
  await page.goto(`${base}/dev/debate/${fixture}`)
  await page.waitForSelector('[data-testid="debate-graph"]')
  await page.waitForSelector('[data-testid="insights"]')
  await page.waitForTimeout(400)
}

async function overflow(page, label) {
  const o = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))
  facts.push(`${label}: scrollWidth ${o.scrollWidth} / innerWidth ${o.innerWidth}`)
  if (o.scrollWidth > o.innerWidth) problems.push(`${label}: horizontal page scroll`)
}

async function tab(page, name) {
  await page.getByRole('tab', { name }).click()
  await page.waitForTimeout(150)
}

const desktop = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const d = await desktop.newPage()
d.on('console', (m) => m.type() === 'error' && problems.push(`desktop: ${m.text()}`))
d.on('pageerror', (e) => problems.push(`desktop: ${e.message}`))

for (const f of ['mergeWrongCluster', 'invalidAndFallback', 'five']) {
  await open(d, f)
  await overflow(d, `desktop ${f}`)
  await d.screenshot({ path: join(out, `m5a-${f}-desktop.png`), fullPage: true })
}

// Insights tabs on the main fixture.
await open(d, 'mergeWrongCluster')
for (const [name, file] of [
  ['Agreement', 'agreement'],
  ['Answer flow', 'flow'],
  ['Confidence', 'confidence'],
]) {
  await tab(d, name)
  await d.getByTestId('insights').screenshot({ path: join(out, `m5a-insights-${file}.png`) })
}

// Replay mid-playback.
await open(d, 'mergeWrongCluster')
await d.getByRole('button', { name: /^Replay$/ }).click()
await d.waitForTimeout(4500)
await d.screenshot({ path: join(out, 'm5a-replay-mid-playback.png') })

// Linked verdict: hover the first Mistakes caught item.
await open(d, 'mergeWrongCluster')
await d.getByTestId('mistake-item').first().hover()
await d.waitForTimeout(250)
await d.locator('[data-testid="mistake-item"]').first().scrollIntoViewIfNeeded()
await d.screenshot({ path: join(out, 'm5a-linked-verdict.png'), fullPage: true })

// Narrow width.
const phone = await browser.newContext({
  viewport: { width: 360, height: 780 },
  deviceScaleFactor: 2,
  hasTouch: true,
  isMobile: true,
})
const p = await phone.newPage()
p.on('console', (m) => m.type() === 'error' && problems.push(`360: ${m.text()}`))
p.on('pageerror', (e) => problems.push(`360: ${e.message}`))
await open(p, 'mergeWrongCluster')
await overflow(p, '360 mergeWrongCluster')
await p.screenshot({ path: join(out, 'm5a-mergeWrongCluster-360.png'), fullPage: true })
await tab(p, 'Answer flow')
await overflow(p, '360 answer flow')
await p.getByTestId('insights').screenshot({ path: join(out, 'm5a-flow-360.png') })

await browser.close()
console.log(facts.join('\n'))
if (problems.length) {
  console.error('PROBLEMS:\n' + problems.join('\n'))
  process.exitCode = 1
} else console.log('no console errors, no horizontal page scroll')
